import argparse
import json

import cv2
import numpy as np
import torch
from ultralytics import YOLO


def _result_to_dets(result):
    obb = result.obb if result.obb is not None else None

    if obb is not None and len(obb) > 0:
        # xywhr: [cx, cy, w, h, angle_rad] — shape (N, 5)
        xywhr = obb.xywhr.cpu().numpy()
        confs = obb.conf.cpu().numpy().reshape(-1, 1)
        clss = obb.cls.cpu().numpy().reshape(-1, 1)
        return np.hstack([xywhr, confs, clss]).astype(np.float32)

    return np.empty((0, 7), dtype=np.float32)


def _vehicle_mask_from_dets(dets, h, w):
    """True = 背景 pixel（未被 YOLO OBB 遮到），可納入底圖統計。"""
    fg = np.zeros((h, w), dtype=np.uint8)
    for det in dets:
        cx, cy, bw, bh, angle_rad = det[:5]
        corners = cv2.boxPoints(
            (
                (float(cx), float(cy)),
                (float(bw), float(bh)),
                float(np.degrees(angle_rad)),
            )
        ).astype(np.int32)
        cv2.fillConvexPoly(fg, corners, 255)
    return fg == 0


def _background_from_samples(samples):
    """以 YOLO mask 排除車輛後做 per-pixel median，避免紅燈停等造成鬼影。

    samples: [(frame, dets), ...]，dets 格式同 detections.jsonl。
    若某 pixel 在所有取樣影格都被車擋住，退回 naive median（極端情況降級）。
    """
    frames = np.stack([frame for frame, _ in samples], axis=0).astype(np.float32)
    h, w = frames.shape[1:3]
    masks = np.stack(
        [_vehicle_mask_from_dets(dets, h, w) for _, dets in samples], axis=0
    )

    masked = np.where(masks[..., np.newaxis], frames, np.nan)
    bg = np.nanmedian(masked, axis=0)

    # 永遠被擋的 pixel：nanmedian 無樣本，用未遮罩 median 填補
    holes = np.isnan(bg[..., 0])
    if holes.any():
        bg[holes] = np.median(frames, axis=0)[holes]
    return bg.astype(np.uint8)


def _bg_sampling_stride(total_frames, bg_max_frames):
    if bg_max_frames is None:
        return 1, None
    if bg_max_frames <= 0:
        raise ValueError("bg_max_frames must be a positive integer or None")
    if total_frames > 0:
        stride = max(1, (total_frames + bg_max_frames - 1) // bg_max_frames)
        return stride, bg_max_frames
    return 1, bg_max_frames


def export_background_and_detection_as_jsonl(
    input_video_path,
    model_path,
    detections_path,
    background_path,
    bg_max_frames=200,
    on_progress=None,
):
    model = YOLO(model_path)
    device = (
        "cuda"
        if torch.cuda.is_available()
        else ("mps" if torch.backends.mps.is_available() else "cpu")
    )

    cap = cv2.VideoCapture(input_video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    bg_stride, bg_cap = _bg_sampling_stride(total_frames, bg_max_frames)
    frame_index = 0
    last_pct = -1
    bg_samples = []

    with open(detections_path, "w") as f:
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                break

            result = model.predict(frame, device=device, verbose=False)[0]
            dets = _result_to_dets(result)

            # predict 後再取樣，才能用同幀 dets 遮掉車輛
            if frame_index % bg_stride == 0:
                if bg_cap is None or len(bg_samples) < bg_cap:
                    bg_samples.append((frame.copy(), dets))

            f.write(
                json.dumps(
                    {"frame_index": frame_index, "dets": dets.tolist()},
                    separators=(",", ":"),
                )
                + "\n"
            )

            frame_index += 1
            if on_progress and total_frames > 0:
                pct = min(99, int(frame_index / total_frames * 100))
                if pct != last_pct:
                    on_progress(pct)
                    last_pct = pct

    cap.release()

    if not bg_samples:
        raise ValueError(f"No frames read from video: {input_video_path}")
    background = _background_from_samples(bg_samples)
    if not cv2.imwrite(background_path, background):
        raise ValueError(f"Unable to write background image: {background_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file")
    parser.add_argument("model")
    parser.add_argument("detections")
    parser.add_argument("background")
    args = parser.parse_args()

    export_background_and_detection_as_jsonl(
        args.input_file, args.model, args.detections, args.background
    )
