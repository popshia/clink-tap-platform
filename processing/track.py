import argparse
import csv

import cv2
import torch

# Monkey-patch ultralytics trackers to prevent Kalman filter from smoothing bounding boxes
# This fixes the issue where OBBs get misaligned (width and height swap but smoothed) during 90-degree turns.
import ultralytics.trackers.bot_sort as bot_sort
import ultralytics.trackers.byte_tracker as byte_tracker
from ultralytics import YOLO


def _patch_trackers():
    # Save a reference to the original, un-patched update function
    original_botrack_update = bot_sort.BOTrack.update

    # Define our custom, "patched" version of the update function
    def patched_botrack_update(self, new_track, frame_id):
        # 'new_track' contains the fresh, un-smoothed detection from YOLO.
        # '_tlwh' stands for Top-Left-Width-Height. We copy this exact raw
        # detection and store it in a new custom variable: '_latest_tlwh'.
        self._latest_tlwh = new_track._tlwh.copy()
        # Now that we've safely stored the raw detection, we pass the data
        # back to the original update function so the Kalman Filter can do its
        # math and keep the track alive.
        original_botrack_update(self, new_track, frame_id)

    # Overwrite the class's update method with our custom patched method.
    bot_sort.BOTrack.update = patched_botrack_update

    # Save a reference to the original re_activate function
    original_botrack_reactivate = bot_sort.BOTrack.re_activate

    # Define our custom patched re_activate function
    def patched_botrack_reactivate(self, new_track, frame_id, new_id=False):
        # Just like before, capture the raw detection box before the
        # Kalman Filter touches it.
        self._latest_tlwh = new_track._tlwh.copy()
        # Call the original re_activate function to handle the underlying math
        original_botrack_reactivate(self, new_track, frame_id, new_id)

    # Overwrite the class's re_activate method with our custom one.
    bot_sort.BOTrack.re_activate = patched_botrack_reactivate

    # Define a custom property function that will replace the original 'tlwh'
    def patched_botrack_tlwh(self):
        # Check if we saved a raw detection in '_latest_tlwh' (which we
        # did in our patched update/reactivate methods).
        if hasattr(self, "_latest_tlwh"):
            # If it exists, return the RAW detection box, completely
            # bypassing the Kalman Filter!
            return self._latest_tlwh.copy()
        # If it doesn't exist (like on the very first frame before an update),
        # just return the starting raw detection '_tlwh'.
        return self._tlwh.copy()

    # Overwrite the 'tlwh' property on the BOTrack class using our custom function.
    bot_sort.BOTrack.tlwh = property(patched_botrack_tlwh)

    # patch strack also
    original_strack_update = byte_tracker.STrack.update

    def patched_strack_update(self, new_track, frame_id):
        self._latest_tlwh = new_track._tlwh.copy()
        original_strack_update(self, new_track, frame_id)

    byte_tracker.STrack.update = patched_strack_update
    original_strack_reactivate = byte_tracker.STrack.re_activate

    def patched_strack_reactivate(self, new_track, frame_id, new_id=False):
        self._latest_tlwh = new_track._tlwh.copy()
        original_strack_reactivate(self, new_track, frame_id, new_id)

    byte_tracker.STrack.re_activate = patched_strack_reactivate

    def patched_strack_tlwh(self):
        if hasattr(self, "_latest_tlwh"):
            return self._latest_tlwh.copy()
        return self._tlwh.copy()

    byte_tracker.STrack.tlwh = property(patched_strack_tlwh)

    # Class-aware tracking patch for BOTSORT
    original_botsort_get_dists = bot_sort.BOTSORT.get_dists

    def patched_botsort_get_dists(self, tracks, detections):
        dists = original_botsort_get_dists(self, tracks, detections)
        # Apply class penalty: if classes don't match, set distance to 1.0 (max distance)
        for i, track in enumerate(tracks):
            for j, det in enumerate(detections):
                if track.cls != det.cls:
                    dists[i, j] = 1.0
        return dists

    bot_sort.BOTSORT.get_dists = patched_botsort_get_dists

    # Class-aware tracking patch for ByteTrack
    original_bytetrack_get_dists = byte_tracker.BYTETracker.get_dists

    def patched_bytetrack_get_dists(self, tracks, detections):
        dists = original_bytetrack_get_dists(self, tracks, detections)
        for i, track in enumerate(tracks):
            for j, det in enumerate(detections):
                if track.cls != det.cls:
                    dists[i, j] = 1.0
        return dists

    byte_tracker.BYTETracker.get_dists = patched_bytetrack_get_dists


_patch_trackers()


def track_and_output_csv(
    input_video_path,
    output_video_path,
    model_path,
    output_csv_path,
):
    # Load the YOLO26 model
    model = YOLO(model_path)

    # Open the video file
    cap = cv2.VideoCapture(input_video_path)

    # Get video properties for saving
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    # Set up the VideoWriter
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))

    # Store information for CSV export
    track_info = {}
    frame_index = 0
    # Loop through the video frames

    while cap.isOpened():
        # Read a frame from the video
        success, frame = cap.read()

        if success:
            frame_index += 1
            # Run YOLO26 tracking on the frame, persisting tracks between frames
            result = model.track(
                frame,
                persist=True,
                tracker="./botsort.yaml",
                device="cuda:1"
                if torch.cuda.is_available()
                else ("mps" if torch.backends.mps.is_available() else "cpu"),
            )[0]
            obb = result.obb if result.obb is not None else None

            # Collect tracking data for CSV export
            if obb is not None and getattr(obb, "id", None) is not None:
                track_ids = obb.id.int().cpu().tolist()
                class_map = {
                    0: "c",
                    1: "t",
                    2: "b",
                    3: "h",
                    4: "g",
                    5: "p",
                    6: "u",
                    7: "m",
                }
                cls_indices = [
                    class_map.get(c, str(c)) for c in obb.cls.int().cpu().tolist()
                ]

                # Get 4 corner coordinates (OBB or standard BBox)
                corners = obb.xyxyxyxy.cpu().numpy().astype(int)  # Shape (N, 4, 2)

                for t_id, corner, cls_idx in zip(track_ids, corners, cls_indices):
                    if t_id not in track_info:
                        track_info[t_id] = {
                            "enter_frame": frame_index,
                            "exit_frame": frame_index,
                            "cls_idx": cls_idx,
                            "coords": {},
                        }
                    track_info[t_id]["exit_frame"] = frame_index
                    track_info[t_id]["coords"][frame_index] = corner.flatten().tolist()

            # Visualize the result on the frame unconditionally
            frame = result.plot(line_width=2, font_size=2, conf=False)

            # Write the annotated frame to the output video
            out.write(frame)

        else:
            # Break the loop if the end of the video is reached
            break

    # Release the video capture and writer objects and close the display window
    cap.release()
    out.release()

    if output_csv_path:
        with open(output_csv_path, "w", newline="") as f:
            writer = csv.writer(f)

            for obj_id, info in track_info.items():
                row = [
                    obj_id,
                    info["enter_frame"],
                    info["exit_frame"],
                    "X",
                    "X",
                    info["cls_idx"],
                ]
                for frame_num in sorted(info["coords"].keys()):
                    row.extend(info["coords"][frame_num])
                writer.writerow(row)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file")
    parser.add_argument("output_file")
    parser.add_argument("model")
    parser.add_argument("csv")
    args = parser.parse_args()

    track_and_output_csv(args.input_file, args.output_file, args.model, args.csv)
