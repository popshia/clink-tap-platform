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


def _bg_sampling_stride(total_frames, bg_max_frames):
    if bg_max_frames is None:
        return 1, None
    if total_frames > 0:
        stride = max(1, (total_frames + bg_max_frames - 1) // bg_max_frames)
        return stride, bg_max_frames
    return 1, bg_max_frames


def export_background_and_detection_as_jsonl(
    input_video_path,
    model_path,
    detections_path,
    background_path,
    bg_max_frames=1000,
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
    bg_frames = []

    with open(detections_path, "w") as f:
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                break

            if frame_index % bg_stride == 0:
                if bg_cap is None or len(bg_frames) < bg_cap:
                    bg_frames.append(frame.copy())

            result = model.predict(frame, device=device, verbose=False)[0]
            dets = _result_to_dets(result)
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

    if not bg_frames:
        raise ValueError(f"No frames read from video: {input_video_path}")
    background = np.median(np.stack(bg_frames, axis=0), axis=0).astype(np.uint8)
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
