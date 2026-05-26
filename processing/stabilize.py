import argparse

import cv2
import kornia.color as KC
import kornia.geometry as KG
import numpy as np
import torch
from kornia.geometry.transform import build_pyramid
from loguru import logger


def _ecc_loss(warped: torch.Tensor, template: torch.Tensor, **_) -> torch.Tensor:
    """Enhanced Correlation Coefficient loss — illumination-invariant, range [0, 2]."""
    t = template - template.mean()
    w = warped - warped.mean()
    return 1.0 - (t * w).sum() / (t.norm() * w.norm() + 1e-8)


def stabilize_video(
    input_path: str,
    output_path: str,
    output_size,
    reg_scale: float = 1.0,
):
    """
    Stabilize video using Kornia's GPU-accelerated ImageRegistrator (homography).
    Runs gradient-descent ECC on CUDA/MPS tensors via a multi-scale pyramid.
    Falls back to CPU Kornia if no GPU is available.
    """
    device = (
        "cuda"
        if torch.cuda.is_available()
        else ("mps" if torch.backends.mps.is_available() else "cpu")
    )

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {input_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    W, H = output_size
    reg_size = (max(1, int(W * reg_scale)), max(1, int(H * reg_scale)))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, fps, output_size)

    ret, first_frame = cap.read()
    if not ret:
        raise RuntimeError("Could not read the first frame.")

    first_resized = cv2.resize(first_frame, output_size, interpolation=cv2.INTER_CUBIC)
    out.write(first_resized)

    def to_gray_tensor(bgr):
        """BGR ndarray → [1, 1, reg_H, reg_W] float32 tensor on device."""
        small = cv2.resize(bgr, reg_size, interpolation=cv2.INTER_LINEAR)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        t = (
            torch.from_numpy(rgb)
            .permute(2, 0, 1)
            .float()
            .div(255.0)
            .unsqueeze(0)
            .to(device)
        )
        return KC.rgb_to_grayscale(t)

    def to_color_tensor(bgr):
        """BGR ndarray → [1, 3, H, W] float32 tensor on device."""
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        return (
            torch.from_numpy(rgb)
            .permute(2, 0, 1)
            .float()
            .div(255.0)
            .unsqueeze(0)
            .to(device)
        )

    def to_bgr(tensor):
        """[1, 3, H, W] float32 tensor → BGR ndarray."""
        np_rgb = (
            (tensor.detach().squeeze(0).permute(1, 2, 0).cpu().numpy() * 255)
            .clip(0, 255)
            .astype(np.uint8)
        )
        return cv2.cvtColor(np_rgb, cv2.COLOR_RGB2BGR)

    target_gray = to_gray_tensor(first_resized)

    # Use ECC loss (illumination-invariant, same criterion as OpenCV findTransformECC)
    # with LBFGS (quasi-Newton) instead of Adam — LBFGS converges in ~5-10 steps
    # vs 30+ for Adam, matching the speed of Gauss-Newton in OpenCV's ECC.
    # Model parameters persist across frames for a warm start; LBFGS optimizer is
    # recreated per pyramid level to avoid stale curvature history across scales.
    pyramid_levels = 2

    registrator = KG.ImageRegistrator(
        model_type="homography",
        loss_fn=_ecc_loss,
        pyramid_levels=pyramid_levels,
    ).to(device)

    # Pre-build the template pyramid once; it never changes.
    target_pyr = build_pyramid(target_gray, pyramid_levels)[::-1]

    frame_idx = 1
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        curr_resized = cv2.resize(frame, output_size, interpolation=cv2.INTER_CUBIC)
        curr_gray = to_gray_tensor(curr_resized)
        curr_tensor = to_color_tensor(curr_resized)

        try:
            curr_pyr = build_pyramid(curr_gray, pyramid_levels)[::-1]

            for src_level, dst_level in zip(curr_pyr, target_pyr):
                # New LBFGS per level — avoids stale curvature from previous scale.
                # Model params (homography) carry over as the warm start.
                opt = torch.optim.LBFGS(
                    registrator.model.parameters(),
                    lr=0.1,
                    max_iter=5,
                    line_search_fn="strong_wolfe",
                )

                def closure(sl=src_level, dl=dst_level):
                    opt.zero_grad()
                    loss = registrator.get_single_level_loss(
                        sl, dl, registrator.model()
                    )
                    loss += registrator.get_single_level_loss(
                        dl, sl, registrator.model.forward_inverse()
                    )
                    loss.backward()
                    return loss

                opt.step(closure)

            stabilized_tensor = registrator.warp_src_into_dst(curr_tensor)
            out.write(to_bgr(stabilized_tensor))
        except Exception as e:
            logger.warning(
                f"Frame {frame_idx}: GPU ECC failed ({e}). Using unmodified frame."
            )
            out.write(curr_resized)

        frame_idx += 1
        if frame_idx % 100 == 0:
            logger.info(f"ECC GPU: Stabilized {frame_idx}/{total_frames} frames")

    cap.release()
    out.release()
    logger.info(f"[STABILIZE] Output saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file")
    parser.add_argument("output_file")
    args = parser.parse_args()

    stabilize_video(
        args.input_file,
        args.output_file,
        (1920, 1080),
        0.5,
    )
