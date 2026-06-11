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


def _gaussian_smooth_homographies(H_seq: torch.Tensor, sigma: float) -> torch.Tensor:
    """Gaussian-smooth a [N, 3, 3] homography sequence along the time axis.
    Endpoints are replicated so the trajectory isn't pulled toward zero at the edges.
    """
    if sigma <= 0 or H_seq.shape[0] < 3:
        return H_seq.clone()
    N = H_seq.shape[0]
    half = max(1, int(3 * sigma))
    half = min(half, N - 1)
    x = torch.arange(-half, half + 1, device=H_seq.device, dtype=H_seq.dtype)
    kernel = torch.exp(-x.pow(2) / (2.0 * sigma * sigma))
    kernel = kernel / kernel.sum()
    pad_lo = H_seq[0:1].expand(half, 3, 3)
    pad_hi = H_seq[-1:].expand(half, 3, 3)
    padded = torch.cat([pad_lo, H_seq, pad_hi], dim=0)
    out = torch.zeros_like(H_seq)
    for k in range(kernel.shape[0]):
        out = out + kernel[k] * padded[k : k + N]
    return out


def stabilize_video(
    input_path: str,
    output_path: str,
    output_size: tuple[int, int] = (1920, 1080),
    reg_scale: float = 1.0,
    smoothing_sigma: float = 15.0,
    on_progress=None,
):
    """
    Stabilize video using Kornia's GPU-accelerated homography registration
    with two-pass motion-trajectory smoothing.

    Pass 1 estimates a per-frame homography against the first frame using
    multi-scale ECC + LBFGS. The resulting H sequence is Gaussian-smoothed in
    time; pass 2 re-reads the video and warps each frame with its smoothed H.
    Smoothing eliminates the frame-to-frame wobble caused by the optimizer
    landing at slightly different minima each frame while preserving any
    intentional slow camera drift. Set smoothing_sigma=0 to disable.
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

    ret, first_frame = cap.read()
    if not ret:
        raise RuntimeError("Could not read the first frame.")
    first_resized = cv2.resize(first_frame, output_size, interpolation=cv2.INTER_CUBIC)

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

    # 3 pyramid levels (was 2) handles larger inter-frame motion before the
    # fine level snaps to the wrong basin. Model parameters persist across
    # frames as a warm start; LBFGS optimizer is recreated per level to avoid
    # stale curvature history across scales.
    pyramid_levels = 3
    registrator = KG.ImageRegistrator(
        model_type="homography",
        loss_fn=_ecc_loss,
        pyramid_levels=pyramid_levels,
    ).to(device)
    target_pyr = build_pyramid(target_gray, pyramid_levels)[::-1]

    # ===== Pass 1: estimate per-frame H against frame 0 =====
    H_list: list[torch.Tensor] = [torch.eye(3, device=device, dtype=torch.float32)]
    frame_idx = 1
    last_pct = -1

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        curr_resized = cv2.resize(frame, output_size, interpolation=cv2.INTER_CUBIC)
        curr_gray = to_gray_tensor(curr_resized)

        try:
            curr_pyr = build_pyramid(curr_gray, pyramid_levels)[::-1]

            for src_level, dst_level in zip(curr_pyr, target_pyr):
                # max_iter=20 (was 5) — 5 was below the reliable convergence
                # floor for LBFGS on an 8-DOF homography from a noisy warm
                # start, which is the primary source of the wobble.
                opt = torch.optim.LBFGS(
                    registrator.model.parameters(),
                    lr=0.1,
                    max_iter=20,
                    line_search_fn="strong_wolfe",
                    tolerance_grad=1e-7,
                    tolerance_change=1e-9,
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

            with torch.no_grad():
                H_list.append(registrator.model().detach().clone().squeeze(0))
        except Exception as e:
            logger.warning(
                f"Frame {frame_idx}: GPU ECC failed ({e}). Reusing previous H."
            )
            H_list.append(H_list[-1].clone())

        frame_idx += 1
        if on_progress and total_frames > 0:
            # Pass 1 occupies 0–50% of progress; pass 2 takes 50–99%.
            pct = min(49, int(frame_idx / total_frames * 50))
            if pct != last_pct:
                on_progress(pct)
                last_pct = pct
        if frame_idx % 100 == 0:
            logger.info(f"ECC GPU pass 1: estimated {frame_idx}/{total_frames}")

    cap.release()

    # ===== Smooth the H trajectory in time =====
    H_stack = torch.stack(H_list, dim=0)
    H_smoothed = _gaussian_smooth_homographies(H_stack, sigma=smoothing_sigma)

    # ===== Pass 2: re-read source and warp each frame with smoothed H =====
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, fps, output_size)

    cap = cv2.VideoCapture(input_path)
    frame_idx = 0
    last_pct = 49
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        curr_resized = cv2.resize(frame, output_size, interpolation=cv2.INTER_CUBIC)

        if frame_idx >= H_smoothed.shape[0]:
            out.write(curr_resized)
            frame_idx += 1
            continue

        try:
            curr_tensor = to_color_tensor(curr_resized)
            with torch.no_grad():
                registrator.model.model.data.copy_(H_smoothed[frame_idx].unsqueeze(0))
                stabilized = registrator.warp_src_into_dst(curr_tensor)
            out.write(to_bgr(stabilized))
        except Exception as e:
            logger.warning(
                f"Frame {frame_idx}: warp failed ({e}). Using unmodified frame."
            )
            out.write(curr_resized)

        frame_idx += 1
        if on_progress and total_frames > 0:
            pct = min(99, 50 + int(frame_idx / total_frames * 50))
            if pct != last_pct:
                on_progress(pct)
                last_pct = pct
        if frame_idx % 100 == 0:
            logger.info(f"ECC GPU pass 2: warped {frame_idx}/{total_frames}")

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
