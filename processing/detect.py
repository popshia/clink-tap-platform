"""
Object Detection using Ultralytics YOLOv8.

Runs YOLOv8 nano model on each frame, draws bounding boxes and class labels
on detected objects, and writes the annotated video.
"""

import cv2
from ultralytics import YOLO


def detect_objects(
    input_path: str,
    output_path: str,
    model_name: str = "yolov8n.pt",
    conf: float = 0.35,
):
    """
    Run object detection on a video and write annotated output.

    Args:
        input_path: Path to the input video file.
        output_path: Path to write the annotated video.
        model_name: YOLOv8 model to use (auto-downloads if needed).
        conf: Confidence threshold for detections.
    """
    model = YOLO(model_name)

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {input_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, fps, (w, h))

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Run detection
        results = model(frame, conf=conf, verbose=False)

        # Draw detections on frame
        annotated = results[0].plot()
        out.write(annotated)
        frame_idx += 1

    cap.release()
    out.release()
    print(f"[DETECT] Processed {frame_idx} frames → {output_path}")
