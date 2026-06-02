import io
import os
import queue
import shutil
import threading
import uuid
import zipfile

import config
from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS
from processing.pipeline import run_pipeline
from services.email_service import send_contact_email, send_result_email

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="frontend/dist", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
app.secret_key = config.SECRET_KEY
CORS(app)

os.makedirs(config.PROCESSED_FOLDER, exist_ok=True)

# ---------------------------------------------------------------------------
# In-memory job store & Queue
# ---------------------------------------------------------------------------
jobs: dict = {}
job_queue = queue.Queue()

# Tracks in-progress chunked uploads before they are enqueued as jobs
pending_uploads: dict = {}
_pending_lock = threading.Lock()

STAGES = [
    "queued",
    "stabilizing",
    "detecting",
    "tracking",
    "csv_postprocessing",
    "emailing",
    "done",
]


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
    output_dir = os.path.join(config.PROCESSED_FOLDER, job_id)
    input_path = os.path.join(output_dir, job["filename"])

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
@app.route("/api/upload/init", methods=["POST"])
def upload_init():
    """Allocate a job_id and chunk staging directory for a chunked upload."""
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "")
    email = data.get("email", "").strip()
    total_chunks = int(data.get("total_chunks", 1))

    if not email:
        return jsonify({"error": "Email address is required"}), 400
    if not filename or not allowed_file(filename):
        return jsonify({"error": "Invalid or unsupported video file"}), 400

    job_id = uuid.uuid4().hex[:4]
    ext = filename.rsplit(".", 1)[1].lower()
    base = filename.rsplit(".", 1)[0]
    safe_name = f"{job_id}_{base}.{ext}"
    output_dir = os.path.join(config.PROCESSED_FOLDER, job_id)
    chunk_dir = os.path.join(output_dir, "_chunks")
    os.makedirs(chunk_dir, exist_ok=True)

    pending_uploads[job_id] = {
        "email": email,
        "filename": safe_name,
        "total_chunks": total_chunks,
        "received_chunks": set(),
        "chunk_dir": chunk_dir,
        "output_dir": output_dir,
    }
    return jsonify({"job_id": job_id}), 200


@app.route("/api/upload/chunk", methods=["POST"])
def upload_chunk():
    """Receive one chunk and, when all chunks are in, assemble the file and queue the job."""
    job_id = request.form.get("job_id")
    chunk_index = request.form.get("chunk_index", type=int)
    chunk = request.files.get("chunk")

    upload = pending_uploads.get(job_id)

    if upload is None or chunk_index is None or not chunk:
        return jsonify({"error": "Invalid chunk request"}), 400
    if chunk_index < 0 or chunk_index >= upload["total_chunks"]:
        return jsonify({"error": "Chunk index out of bounds"}), 400

    chunk.save(os.path.join(upload["chunk_dir"], f"{chunk_index:06d}"))

    with _pending_lock:
        if job_id not in pending_uploads:
            return jsonify({"error": "Upload already finalized or invalid"}), 400
        upload["received_chunks"].add(chunk_index)
        received_count = len(upload["received_chunks"])
        should_finalize = received_count >= upload["total_chunks"]
        if should_finalize:
            pending_uploads.pop(job_id)

    if not should_finalize:
        return jsonify({"received": received_count}), 200

    # All chunks received — concatenate into the final file and create the job.
    final_path = os.path.join(upload["output_dir"], upload["filename"])
    try:
        with open(final_path, "wb") as out_f:
            for i in range(upload["total_chunks"]):
                with open(os.path.join(upload["chunk_dir"], f"{i:06d}"), "rb") as cf:
                    shutil.copyfileobj(cf, out_f)
    finally:
        shutil.rmtree(upload["chunk_dir"], ignore_errors=True)

    jobs[job_id] = {
        "status": "processing",
        "stage": "queued",
        "progress": 0,
        "error": None,
        "email": upload["email"],
        "filename": upload["filename"],
        "output_filename": None,
    }
    job_queue.put(job_id)
    return jsonify({"job_id": job_id, "done": True}), 202


@app.route("/api/contact", methods=["POST"])
def contact():
    """Receive a 'Contact Us' submission and forward it to the support inbox."""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()
    subject = (data.get("subject") or "").strip()
    message = (data.get("message") or "").strip()

    if not name or not email or not message:
        return jsonify({"error": "Name, email and message are required"}), 400

    try:
        send_contact_email(name, email, phone, subject, message)
    except Exception as exc:
        print(f"Error sending contact email: {exc}")
        return jsonify({"error": "Failed to send your message"}), 500

    return jsonify({"ok": True}), 200


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
