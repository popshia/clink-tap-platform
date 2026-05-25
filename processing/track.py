import argparse
import csv

import cv2
import numpy as np
import torch
from boxmot.trackers.ocsort.ocsort import OcSort
from ultralytics import YOLO


def track_and_output_csv(
    input_video_path,
    output_video_path,
    model_path,
    output_csv_path,
):
    model = YOLO(model_path)

    device = (
        "cuda:1"
        if torch.cuda.is_available()
        else ("mps" if torch.backends.mps.is_available() else "cpu")
    )

    # is_obb=True  → input [cx,cy,w,h,angle_rad,conf,cls], uses rotated IoU automatically
    # per_class=True → class-aware tracking (objects of different classes never merge IDs)
    tracker = OcSort(
        per_class=True,
        det_thresh=0.3,
        max_age=30,
        min_hits=3,
        iou_threshold=0.3,
        asso_func="iou",
    )

    cap = cv2.VideoCapture(input_video_path)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))

    class_map = {0: "c", 1: "t", 2: "b", 3: "h", 4: "g", 5: "p", 6: "u", 7: "m"}
    class_colors = {
        0: (189, 114,   0),  # c — blue
        1: ( 25,  83, 217),  # t — orange
        2: ( 32, 177, 237),  # b — yellow
        3: (142,  47, 126),  # h — purple
        4: ( 48, 172, 119),  # g — green
        5: (238, 190,  77),  # p — cyan
        6: ( 47,  20, 162),  # u — red
        7: (128, 128,   0),  # m — teal
    }

    track_info = {}
    frame_index = 0

    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            break

        result = model.predict(frame, device=device)[0]
        obb = result.obb if result.obb is not None else None

        if obb is not None and len(obb) > 0:
            # xywhr: [cx, cy, w, h, angle_rad] — shape (N, 5)
            xywhr = obb.xywhr.cpu().numpy()
            confs = obb.conf.cpu().numpy().reshape(-1, 1)
            clss = obb.cls.cpu().numpy().reshape(-1, 1)
            dets = np.hstack([xywhr, confs, clss]).astype(np.float32)
        else:
            dets = np.empty((0, 7), dtype=np.float32)

        # tracks: [cx, cy, w, h, angle_rad, id, conf, cls, det_ind] — shape (M, 9)
        tracks = tracker.update(dets, frame)

        annotated = frame.copy()

        if len(tracks) > 0:
            for track in tracks:
                cx, cy, w, h, angle, t_id, conf, cls_raw, _ = track
                t_id = int(t_id)
                cls_idx = class_map.get(int(cls_raw), str(int(cls_raw)))

                # cv2.boxPoints expects angle in degrees
                corners = cv2.boxPoints(
                    ((cx, cy), (w, h), float(np.degrees(angle)))
                ).astype(int)

                if t_id not in track_info:
                    track_info[t_id] = {
                        "enter_frame": frame_index,
                        "exit_frame": frame_index,
                        "cls_idx": cls_idx,
                        "coords": {},
                    }
                track_info[t_id]["exit_frame"] = frame_index
                track_info[t_id]["coords"][frame_index] = corners.flatten().tolist()

                color = class_colors.get(int(cls_raw), (255, 255, 255))
                cv2.polylines(
                    annotated, [corners.reshape((-1, 1, 2))], True, color, 2
                )
                cv2.putText(
                    annotated,
                    f"{cls_idx} {t_id}",
                    tuple(corners[0]),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    color,
                    2,
                )

        out.write(annotated)
        frame_index += 1

    cap.release()
    out.release()

    if output_csv_path:
        with open(output_csv_path, "w", newline="") as f:
            writer = csv.writer(f)

            for obj_id, info in track_info.items():
                enter, exit_ = info["enter_frame"], info["exit_frame"]
                coords = info["coords"]
                frame_nums = sorted(coords.keys())

                row = [obj_id, enter, exit_, "X", "X", info["cls_idx"]]
                for frame_num in range(enter, exit_ + 1):
                    if frame_num in coords:
                        row.extend(coords[frame_num])
                    else:
                        # Interpolate between nearest known frames on each side
                        before = [f for f in frame_nums if f < frame_num]
                        after = [f for f in frame_nums if f > frame_num]
                        f0, f1 = before[-1], after[0]
                        t = (frame_num - f0) / (f1 - f0)
                        c0, c1 = coords[f0], coords[f1]
                        interpolated = [
                            round(c0[i] + t * (c1[i] - c0[i])) for i in range(len(c0))
                        ]
                        row.extend(interpolated)
                writer.writerow(row)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file")
    parser.add_argument("output_file")
    parser.add_argument("model")
    parser.add_argument("csv")
    args = parser.parse_args()

    track_and_output_csv(args.input_file, args.output_file, args.model, args.csv)
