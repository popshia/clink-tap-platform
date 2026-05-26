import argparse

import cv2
import kornia.color as KC
import kornia.geometry as KG
import numpy as np
import torch
from loguru import logger


def ecc_stabilize(input_path: str, output_path: str, output_size):
    """
    Stabilize video using ECC with 'Warm Start' (persistent warp matrix)
    and Homography mapping.
    """
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {input_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, fps, output_size)

    # 1. Initialize Target Template
    ret, first_frame = cap.read()
    if not ret:
        raise RuntimeError("Could not read the first frame.")

    # Resize and Grayscale for the ECC algorithm
    first_resized = cv2.resize(first_frame, output_size, interpolation=cv2.INTER_CUBIC)
    target_gray = cv2.cvtColor(first_resized, cv2.COLOR_BGR2GRAY)

    # Write the first frame as-is
    out.write(first_resized)

    # 2. ECC Configuration
    warp_mode = cv2.MOTION_HOMOGRAPHY
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 5 * 1e-4)

    # Persistent Warp Matrix (The "Warm Start")
    # Instead of resetting this every loop, we evolve it.
    warp_matrix = np.eye(3, 3, dtype=np.float32)

    frame_idx = 1
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        curr_resized = cv2.resize(frame, output_size, interpolation=cv2.INTER_CUBIC)
        curr_gray = cv2.cvtColor(curr_resized, cv2.COLOR_BGR2GRAY)

        try:
            # The Warm Start: We pass the 'warp_matrix' from the PREVIOUS frame
            # as the initial guess for the CURRENT frame.
            _, warp_matrix = cv2.findTransformECC(
                target_gray, curr_gray, warp_matrix, warp_mode, criteria
            )

            # Apply the calculated perspective transformation
            # WARP_INVERSE_MAP is used because ECC calculates the mapping
            # from template to input, but we want to pull input back to template.
            stabilized_frame = cv2.warpPerspective(
                curr_resized,
                warp_matrix,
                output_size,
                flags=cv2.INTER_CUBIC + cv2.WARP_INVERSE_MAP,
            )
            out.write(stabilized_frame)

        except cv2.error:
            logger.warning(
                f"Frame {frame_idx}: ECC failed to converge. Using previous matrix."
            )
            # If it fails, we apply the last successful matrix to maintain continuity
            fallback_frame = cv2.warpPerspective(
                curr_resized,
                warp_matrix,
                output_size,
                flags=cv2.INTER_CUBIC + cv2.WARP_INVERSE_MAP,
            )
            out.write(fallback_frame)

        frame_idx += 1
        if frame_idx % 10 == 0:
            logger.info(f"ECC: Stabilized {frame_idx}/{total_frames} frames")

    cap.release()
    out.release()


def ecc_stabilize_gpu(
    input_path: str, output_path: str, output_size, device: str | None = None
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

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, fps, output_size)

    ret, first_frame = cap.read()
    if not ret:
        raise RuntimeError("Could not read the first frame.")

    first_resized = cv2.resize(first_frame, output_size, interpolation=cv2.INTER_CUBIC)
    out.write(first_resized)

    def to_gray_tensor(bgr):
        """BGR ndarray → [1, 1, H, W] float32 tensor on device."""
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
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

    # ImageRegistrator wraps gradient-descent ECC over a Gaussian image pyramid.
    # model_type='homography' matches the OpenCV MOTION_HOMOGRAPHY mode.
    # The model is persistent — its parameters carry over between register() calls,
    # providing a warm start: each frame begins from the previous frame's solution.
    registrator = KG.ImageRegistrator(
        model_type="homography",
        optimizer=torch.optim.Adam,
        pyramid_levels=5,
        lr=1e-3,
        num_iterations=200,
        tolerance=1e-5,
    ).to(device)

    frame_idx = 1
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        curr_resized = cv2.resize(frame, output_size, interpolation=cv2.INTER_CUBIC)
        curr_gray = to_gray_tensor(curr_resized)
        curr_tensor = to_color_tensor(curr_resized)

        try:
            # register(src, dst) finds H s.t. warp(src, H) ≈ dst.
            # warp_src_into_dst then applies that H to the color frame.
            registrator.register(curr_gray, target_gray)
            stabilized_tensor = registrator.warp_src_into_dst(curr_tensor)
            out.write(to_bgr(stabilized_tensor))
        except Exception as e:
            logger.warning(
                f"Frame {frame_idx}: GPU ECC failed ({e}). Using unmodified frame."
            )
            out.write(curr_resized)

        frame_idx += 1
        if frame_idx % 10 == 0:
            logger.info(f"ECC GPU: Stabilized {frame_idx}/{total_frames} frames")

    cap.release()
    out.release()


def stabilize_video(input_path: str, output_path: str, method: str, output_size):
    match method:
        case "ecc":
            ecc_stabilize(input_path, output_path, output_size)
        case "ecc_gpu":
            ecc_stabilize_gpu(input_path, output_path, output_size)

    logger.info(f"[STABILIZE] Output saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file")
    parser.add_argument("output_file")
    args = parser.parse_args()

    stabilize_video(
        args.input_file,
        args.output_file,
        "ecc_gpu",
        (1920, 1080),
    )
