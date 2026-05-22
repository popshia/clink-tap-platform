import io
import os
import queue
import threading
import uuid
import zipfile

from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

import config
from processing.pipeline import run_pipeline
from services.email_service import send_result_email

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="frontend/dist", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
app.secret_key = config.SECRET_KEY
CORS(app)

os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(config.PROCESSED_FOLDER, exist_ok=True)

# ---------------------------------------------------------------------------
# In-memory job store & Queue
# ---------------------------------------------------------------------------
jobs: dict = {}
job_queue = queue.Queue()

STAGES = ["queued", "stabilizing", "tracking", "csv_postprocess", "emailing", "done"]


def allowed_file(filename: str) -> bool:
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS
    )


# ---------------------------------------------------------------------------
# Background worker queue
# ---------------------------------------------------------------------------
def worker():
    """Continuously processes jobs from the queue."""
    while True:
        job_id = job_queue.get()
        if job_id is None:
            break
        try:
            process_job(job_id)
        except Exception as e:
            print(f"Error processing job {job_id}: {e}")
        finally:
            job_queue.task_done()


# Start a single background worker thread (limits concurrency to 1)
threading.Thread(target=worker, daemon=True).start()


def process_job(job_id: str):
    """Run the full pipeline in a background thread."""
    job = jobs[job_id]
    input_path = os.path.join(config.UPLOAD_FOLDER, job["filename"])
    # output_dir = config.PROCESSED_FOLDER + "/" + job_id
    output_dir = os.path.join(config.PROCESSED_FOLDER, job_id)
    os.makedirs(output_dir, exist_ok=True)

    def on_progress(stage: str, progress: int = 0):
        job["stage"] = stage
        job["progress"] = progress

    try:
        output_path = run_pipeline(input_path, output_dir, job_id, on_progress)

        # Send email
        on_progress("emailing", 0)
        download_url = f"{config.SERVER_URL}/api/download/{job_id}/zip"
        send_result_email(job["email"], download_url, job_id)

        job["status"] = "done"
        job["stage"] = "done"
        job["progress"] = 100
        job["output_filename"] = os.path.basename(output_path)

    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------
@app.route("/api/upload", methods=["POST"])
def upload_video():
    """Accept a video file + email and kick off processing."""
    if "video" not in request.files:
        return jsonify({"error": "No video file provided"}), 400

    file = request.files["video"]
    email = request.form.get("email", "").strip()

    if not email:
        return jsonify({"error": "Email address is required"}), 400
    if file.filename == "" or not allowed_file(file.filename):
        return jsonify({"error": "Invalid or unsupported video file"}), 400

    # Save uploaded file
    job_id = uuid.uuid4().hex[:4]
    filename = file.filename.rsplit(".", 1)[0]
    ext = file.filename.rsplit(".", 1)[1].lower()
    safe_name = f"{job_id}_{filename}.{ext}"
    file.save(os.path.join(config.UPLOAD_FOLDER, safe_name))

    # Create job record
    jobs[job_id] = {
        "status": "processing",
        "stage": "queued",
        "progress": 0,
        "error": None,
        "email": email,
        "filename": safe_name,
        "output_filename": None,
    }

    # Add job to the queue
    job_queue.put(job_id)

    return jsonify({"job_id": job_id}), 202


@app.route("/api/status/<job_id>")
def job_status(job_id):
    """Return current processing status for a job."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(
        {
            "job_id": job_id,
            "status": job["status"],
            "stage": job["stage"],
            "progress": job["progress"],
            "error": job["error"],
        }
    )


@app.route("/api/download/<job_id>")
def download_video(job_id):
    """Serve the processed video file."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job["status"] != "done" or not job["output_filename"]:
        return jsonify({"error": "Video not ready yet"}), 400
    output_dir = os.path.join(config.PROCESSED_FOLDER, job_id)
    return send_from_directory(
        output_dir,
        job["output_filename"],
        as_attachment=True,
    )


@app.route("/api/download/<job_id>/csv")
def download_csv(job_id):
    """Serve the processed CSV file."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job["status"] != "done":
        return jsonify({"error": "CSV not ready yet"}), 400
    output_dir = os.path.join(config.PROCESSED_FOLDER, job_id)
    return send_from_directory(
        output_dir,
        "processed.csv",
        as_attachment=True,
    )


@app.route("/api/download/<job_id>/zip")
def download_zip(job_id):
    """Stream a ZIP containing the processed video and CSV."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job["status"] != "done" or not job["output_filename"]:
        return jsonify({"error": "Results not ready yet"}), 400

    output_dir = os.path.join(config.PROCESSED_FOLDER, job_id)
    video_path = os.path.join(output_dir, job["output_filename"])
    csv_path = os.path.join(output_dir, "processed.csv")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.write(video_path, job["output_filename"])
        zf.write(csv_path, "processed.csv")
    buf.seek(0)

    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{job_id}.zip",
    )


# ---------------------------------------------------------------------------
# Serve Vue SPA (production)
# ---------------------------------------------------------------------------
@app.route("/")
def serve_spa():
    return send_from_directory(app.static_folder, "index.html")


@app.errorhandler(404)
def fallback(e):
    """SPA fallback – serve index.html for client-side routes."""
    if app.static_folder and os.path.exists(
        os.path.join(app.static_folder, "index.html")
    ):
        return send_from_directory(app.static_folder, "index.html")
    return jsonify({"error": "Not found"}), 404


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        debug=True,
    )
