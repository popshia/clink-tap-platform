"""
Processing Pipeline – orchestrates stabilization → detection → tracking.
"""

import os
import time
from typing import Callable, Optional

from loguru import logger

import config
from processing.csv_postprocess import process_trajectory_csv_file
from processing.detect import export_background_and_detection_as_jsonl
from processing.stabilize import stabilize_video
from processing.tracking import track_from_detection_jsonl

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
    upload_video: str,
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

    ext = os.path.splitext(upload_video)[1] or ".mp4"

    start = time.perf_counter()

    # ── Stage 1: Video Stabilization ──
    stabilized_video = os.path.join(
        output_dir, f"{upload_video.split('/')[-1].split('.')[0]}_stabilized{ext}"
    )
    log("stabilizing", 0)
    stabilize_video(
        upload_video,
        stabilized_video,
        on_progress=lambda pct: log("stabilizing", pct),
    )
    log("stabilizing", 100)

    # ── Stage 2: OBB Detection ──
    detections = os.path.join(output_dir, "detections.jsonl")
    background_image = os.path.join(output_dir, "background.png")
    log("detecting", 0)
    export_background_and_detection_as_jsonl(
        stabilized_video,
        config.MODEL_PATH,
        detections,
        background_image,
        on_progress=lambda pct: log("detecting", pct),
    )
    log("detecting", 100)

    # ── Stage 3: Tracking ──
    video_base_name = upload_video.split("/")[-1].split(".")[0]
    plotted_video = os.path.join(output_dir, f"{video_base_name}_tracked{ext}")
    raw_csv = os.path.join(output_dir, "raw.csv")
    log("tracking", 0)
    track_from_detection_jsonl(
        stabilized_video,
        detections,
        plotted_video,
        raw_csv,
        on_progress=lambda pct: log("tracking", pct),
    )
    log("tracking", 100)

    # ── Stage 4: CSV file fixing ──
    processed_csv = os.path.join(output_dir, "processed.csv")
    log("csv_postprocessing", 0)
    process_trajectory_csv_file(raw_csv, processed_csv)
    log("csv_postprocessing", 100)

    elapsed = time.perf_counter() - start
    logger.info(f"Processing time: {format_duration(elapsed)}")

    # Clean up input and intermediate files (keep only the final output)
    for intermediate in [
        upload_video,
        stabilized_video,
        detections,
        raw_csv,
    ]:
        try:
            os.remove(intermediate)
        except OSError:
            pass

    return plotted_video
