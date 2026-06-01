# TTGUI Web — Traffic Video Analysis Platform

A web application for analyzing traffic videos from aerial (drone) footage. Upload a video, and the system automatically stabilizes it, detects and tracks vehicles using a YOLOv11 OBB model, post-processes the raw trajectories into clean CSVs, and emails you a download link when the job is done.

---

## Features

- **Video Stabilization** — ECC or Lucas-Kanade optical flow to remove camera shake from drone footage
- **Object Detection & Tracking** — YOLOv11 Oriented Bounding Box (OBB) model with BotSORT, patched to bypass Kalman filter smoothing so bounding boxes stay accurate through 90° turns
- **Class-Aware Tracking** — Prevents track ID swaps between different vehicle classes (car, truck, bus, motorcycle, etc.)
- **Trajectory CSV Export** — Per-vehicle frame-by-frame OBB corner coordinates, cleaned and smoothed with configurable parameters
- **Email Notification** — Gmail SMTP delivers an HTML email with a direct download link once processing is complete
- **Job Queue** — Single-worker background queue ensures jobs run sequentially and the server stays responsive
- **Contact Us Widget** — A floating button opens an in-app contact form (name, email, phone, subject, message) that is forwarded to the support inbox via Gmail SMTP, with the sender set as `Reply-To`

## Tracked Vehicle Classes

| Code | Class         |
|------|---------------|
| `c`  | Car           |
| `t`  | Truck         |
| `b`  | Bus           |
| `h`  | Truck Head   |
| `g`  | Truck Tail|
| `p`  | pedestrian      |
| `u`  | bike      |
| `m`  | Motorcycle    |

---

## Architecture

```
Browser (Vue 3 SPA)
    │  POST /api/upload/init   (filename, email, total_chunks → job_id)
    │  POST /api/upload/chunk  (job_id, chunk_index, chunk)
    │  GET  /api/status/<job_id>
    │  GET  /api/download/<job_id>[/csv|/zip]
    │  POST /api/contact       (name, email, message, …)
    ▼
Flask backend (app.py)
    │
    ├── In-memory job store (dict)
    ├── Background thread (queue.Queue, single worker)
    │
    └── Processing Pipeline
            ├── Stage 1 — stabilize.py      (ECC / LK optical flow)
            ├── Stage 2 — track.py          (YOLOv11 OBB + BotSORT)
            └── Stage 3 — csv_postprocess.py (trajectory smoothing)
```

In production, Flask serves the pre-built Vue SPA from `frontend/dist/` and falls back to `index.html` for client-side routing.

---

## Prerequisites

- Python 3.10
- [uv](https://docs.astral.sh/uv/) (package manager)
- Node.js + npm (for frontend development)
- A GPU with MPS (Apple Silicon) or CUDA support (falls back to device index `1`)
- Gmail account with an [App Password](https://support.google.com/accounts/answer/185833) for email delivery

---

## Setup

### 1. Clone and install Python dependencies

```bash
git clone <repo-url>
cd TTGUI_Web
uv sync
```

### 2. Configure environment variables

```bash
export SECRET_KEY="your-secret-key"
export SERVER_URL="http://your-server-address:5000"
export SMTP_USER="your-email@gmail.com"
export SMTP_PASSWORD="your-gmail-app-password"
export CONTACT_RECIPIENT="support@your-domain.com"  # optional
```

| Variable        | Default                      | Description                              |
|-----------------|------------------------------|------------------------------------------|
| `SECRET_KEY`    | `dev-secret-key-change-me`   | Flask session secret                     |
| `SERVER_HOST`   | `127.0.0.1`                  | Host to bind Flask                       |
| `SERVER_PORT`   | `5000`                       | Port to bind Flask                       |
| `SERVER_URL`    | `http://127.0.0.1:5000`      | Public URL used in email download links  |
| `SMTP_USER`     | *(empty)*                    | Gmail address for sending result emails  |
| `SMTP_PASSWORD` | *(empty)*                    | Gmail App Password                       |
| `CONTACT_RECIPIENT` | *(falls back to `SMTP_USER`)* | Inbox that receives "Contact Us" submissions |

If `SMTP_USER` / `SMTP_PASSWORD` are not set, the email step is skipped and the download link (or contact submission) is logged to stdout instead.

### 3. Place the model

Put your YOLOv11 OBB model at:

```
processing/models/yolov11_obb.pt
```

### 4. Build the frontend (production)

```bash
cd frontend
npm install
npm run build
cd ..
```

### 5. Run the server

```bash
uv run app.py
```

The app will be available at `http://127.0.0.1:5000`.

---

## Development

Run the backend and frontend dev servers separately:

```bash
# Terminal 1 — Flask backend
uv run app.py

# Terminal 2 — Vite dev server (proxies /api to Flask)
cd frontend
npm run dev
```

---

## API Reference

| Method | Endpoint                  | Description                              |
|--------|---------------------------|------------------------------------------|
| `POST` | `/api/upload/init`        | Start a chunked upload. Body: `application/json` with `filename`, `email`, `total_chunks`. Allocates a staging dir and returns `{ job_id }`. |
| `POST` | `/api/upload/chunk`       | Upload one chunk. Body: `multipart/form-data` with `job_id`, `chunk_index`, `chunk` (blob). The job is assembled and queued once the final chunk arrives. |
| `GET`  | `/api/status/<job_id>`    | Poll job status. Returns `{ status, stage, progress, error }`. |
| `GET`  | `/api/download/<job_id>`      | Download the processed video once `status == "done"`. |
| `GET`  | `/api/download/<job_id>/csv`  | Download the processed trajectory CSV. |
| `GET`  | `/api/download/<job_id>/zip`  | Download a ZIP bundling the processed video and CSV. |
| `POST` | `/api/contact`            | Submit a "Contact Us" message. Body: `application/json` with `name`, `email`, `message` (required) and optional `phone`, `subject`. Returns `{ ok: true }`. |

**Processing stages (in order):** `queued` → `stabilizing` → `tracking` → `csv_postprocess` → `emailing` → `done`

**Accepted video formats:** `mp4`, `avi`, `mov`, `mkv`, `webm` (max 10 GB)

---

## Project Structure

```
TTGUI_Web/
├── app.py                  # Flask app, routes, job queue
├── config.py               # All configuration constants
├── processing/
│   ├── pipeline.py         # Orchestrates the 3-stage pipeline
│   ├── stabilize.py        # ECC / Lucas-Kanade video stabilization
│   ├── track.py            # YOLOv11 OBB detection + BotSORT tracking
│   ├── csv_postprocess.py  # Trajectory smoothing and CSV cleanup
│   ├── detect.py           # Standalone YOLOv8 detection utility (not used by the pipeline)
│   ├── models/
│   │   └── yolov11_obb.pt  # YOLOv11 OBB model weights
│   └── tools/              # Helper scripts (e.g. CSV row-length checks)
├── services/
│   └── email_service.py    # Gmail SMTP: result + "Contact Us" emails
├── frontend/               # Vue 3 + Vite SPA
│   ├── src/
│   │   ├── App.vue
│   │   └── components/
│   │       ├── UploadForm.vue
│   │       ├── JobStatus.vue
│   │       └── ContactWidget.vue  # Floating "Contact Us" button + form
│   └── dist/               # Production build output
├── docs/                   # Trajectory format spec + tracking-param notes
├── processed/              # Per-job staging + output: video + CSVs (auto-created)
├── requirements.txt
└── uv.lock
```
