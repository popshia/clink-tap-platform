import argparse
import csv

import cv2
import numpy as np

# Corner order from csv_postprocess: LF, RF, RB, LB
FRONT_LEFT, FRONT_RIGHT, REAR_RIGHT, REAR_LEFT = 0, 1, 2, 3

CLASS_COLORS = {
    "c": (220, 100, 30),   # car        — 藍
    "t": (30, 140, 240),   # truck      — 橘
    "b": (40, 200, 40),    # bus        — 綠
    "h": (200, 60, 180),   # truck head — 紫
    "g": (180, 120, 0),    # truck tail — 青
    "p": (220, 220, 0),    # pedestrian — 黃
    "u": (255, 180, 0),    # bike       — 青藍 (cyan)
    "m": (100, 80, 255),   # motorcycle — 粉橘
}

FRONT_HIGHLIGHT_COLOR = (0, 0, 255)  # BGR red
DEFAULT_COLOR = (255, 255, 255)


def _load_processed_csv(csv_path):
    """Build a frame-indexed lookup from processed trajectory CSV."""
    frame_tracks = {}

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            row = [item for item in row if item.strip() != ""]
            if len(row) < 6:
                continue

            obj_id = int(row[0])
            enter_frame = int(row[1])
            exit_frame = int(row[2])
            cls_idx = row[5]
            coords = [float(v) for v in row[6:]]
            num_frames = len(coords) // 8

            for i in range(num_frames):
                frame_num = enter_frame + i
                if frame_num > exit_frame:
                    break

                corners = np.array(coords[i * 8 : (i + 1) * 8], dtype=np.float32).reshape(
                    4, 2
                )
                frame_tracks.setdefault(frame_num, []).append(
                    {
                        "id": obj_id,
                        "cls": cls_idx,
                        "corners": corners.astype(int),
                    }
                )

    return frame_tracks


def _draw_centered_label(frame, text, center, color):
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.6
    thickness = 2
    (text_w, text_h), baseline = cv2.getTextSize(text, font, scale, thickness)
    cx, cy = int(center[0]), int(center[1])
    origin = (cx - text_w // 2, cy + text_h // 2)

    # 先畫粗黑字當描邊，再疊彩色字，避免標籤與背景混在一起
    cv2.putText(
        frame,
        text,
        origin,
        font,
        scale,
        (0, 0, 0),
        thickness + 2,
        cv2.LINE_AA,
    )
    cv2.putText(frame, text, origin, font, scale, color, thickness, cv2.LINE_AA)


def _draw_vehicle(frame, vehicle):
    corners = vehicle["corners"]
    cls_idx = vehicle["cls"]
    track_id = vehicle["id"]
    color = CLASS_COLORS.get(cls_idx, DEFAULT_COLOR)

    lf = tuple(corners[FRONT_LEFT])
    rf = tuple(corners[FRONT_RIGHT])
    rb = tuple(corners[REAR_RIGHT])
    lb = tuple(corners[REAR_LEFT])

    # Body edges (rear + sides) in class color
    cv2.line(frame, rb, lb, color, 2, cv2.LINE_AA)
    cv2.line(frame, lb, lf, color, 2, cv2.LINE_AA)
    cv2.line(frame, rf, rb, color, 2, cv2.LINE_AA)

    # Front edge highlighted in red
    cv2.line(frame, lf, rf, FRONT_HIGHLIGHT_COLOR, 4, cv2.LINE_AA)

    center = corners.mean(axis=0)
    _draw_centered_label(frame, f"{cls_idx} {track_id}", center, color)


def plot_trajectory_video(
    input_video_path,
    processed_csv_path,
    output_video_path,
    on_progress=None,
):
    frame_tracks = _load_processed_csv(processed_csv_path)

    cap = cv2.VideoCapture(input_video_path)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))
    if not out.isOpened():
        raise ValueError(f"Failed to open VideoWriter for path: {output_video_path}")

    frame_index = 0
    last_pct = -1

    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            break

        annotated = frame.copy()
        for vehicle in frame_tracks.get(frame_index, []):
            _draw_vehicle(annotated, vehicle)

        out.write(annotated)
        frame_index += 1

        if on_progress and total_frames > 0:
            pct = min(99, int(frame_index / total_frames * 100))
            if pct != last_pct:
                on_progress(pct)
                last_pct = pct

    cap.release()
    out.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_video")
    parser.add_argument("processed_csv")
    parser.add_argument("output_video")
    args = parser.parse_args()

    plot_trajectory_video(args.input_video, args.processed_csv, args.output_video)
