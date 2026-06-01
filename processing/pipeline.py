"""
Processing Pipeline – orchestrates stabilization → detection → tracking.
"""

import os
import time
from typing import Callable, Optional

import config
from loguru import logger

from processing.csv_postprocess import process_trajectory_file
from processing.detect_obb_only import run_detection_to_file
from processing.stabilize import stabilize_video
from processing.tracking_only import track_from_detections

# from processing.track import track_and_output_csv


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []

    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}min")

    parts.append(f"{seconds}sec")
    return " ".join(parts)


def run_pipeline(
    input_path: str,
    output_dir: str,
    job_id: str,
    on_progress: Optional[Callable[[str, int], None]] = None,
) -> str:
    """
    Run the full 3-stage video processing pipeline.

    Args:
        input_path: Path to the uploaded video.
        output_dir: Directory to store intermediate and final output files.
        job_id: Unique job identifier.
        on_progress: Optional callback(stage_name, percent) for progress updates.

    Returns:
        Path to the final processed video.
    """

    def log(stage: str, pct: int = 0):
        if on_progress:
            on_progress(stage, pct)
        logger.info(f"[PIPELINE] {job_id} | {stage} ({pct}%)")

    ext = os.path.splitext(input_path)[1] or ".mp4"

    start = time.perf_counter()

    # ── Stage 1: Video Stabilization ──
    stabilized_path = os.path.join(
        output_dir, f"{input_path.split('/')[-1].split('.')[0]}_stabilized{ext}"
    )
    log("stabilizing", 0)
    stabilize_video(
        input_path,
        stabilized_path,
        (1920, 1080),
        0.5,
        on_progress=lambda pct: log("stabilizing", pct),
    )
    log("stabilizing", 100)

    base = input_path.split("/")[-1].split(".")[0]
    tracked_path = os.path.join(output_dir, f"{base}_tracked{ext}")
    raw_csv = os.path.join(output_dir, "raw.csv")
    detections_path = os.path.join(output_dir, "detections.jsonl")
    background_path = os.path.join(output_dir, "background.png")

    # ── Stage 2 (legacy): Object Detect & Tracking ──
    # log("tracking", 0)
    # track_and_output_csv(
    #     stabilized_path,
    #     tracked_path,
    #     config.MODEL_PATH,
    #     raw_csv,
    #     on_progress=lambda pct: log("tracking", pct),
    # )
    # log("tracking", 100)

    # ── Stage 2: OBB Detection ──
    log("detect_obb_only", 0)
    run_detection_to_file(
        stabilized_path,
        config.MODEL_PATH,
        detections_path,
        background_path,
        on_progress=lambda pct: log("detect_obb_only", pct),
    )
    log("detect_obb_only", 100)

    # ── Stage 3: Tracking ──
    log("tracking_only", 0)
    track_from_detections(
        stabilized_path,
        detections_path,
        tracked_path,
        raw_csv,
        on_progress=lambda pct: log("tracking_only", pct),
    )
    log("tracking_only", 100)

    # ── Stage 4: CSV file fixing ──
    processed_csv = os.path.join(output_dir, "processed.csv")
    log("csv_postprocess", 0)
    process_trajectory_file(raw_csv, processed_csv)
    log("csv_postprocess", 100)

    elapsed = time.perf_counter() - start
    logger.info(f"Processing time: {format_duration(elapsed)}")

    # Clean up input and intermediate files (keep only the final output)
    for intermediate in [input_path, stabilized_path, detections_path, raw_csv]:
        try:
            os.remove(intermediate)
        except OSError:
            pass

    return tracked_path
