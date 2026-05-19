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
    │  POST /api/upload (video + email)
    │  GET  /api/status/<job_id>
    │  GET  /api/download/<job_id>
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
```

| Variable        | Default                      | Description                              |
|-----------------|------------------------------|------------------------------------------|
| `SECRET_KEY`    | `dev-secret-key-change-me`   | Flask session secret                     |
| `SERVER_HOST`   | `127.0.0.1`                  | Host to bind Flask                       |
| `SERVER_PORT`   | `5000`                       | Port to bind Flask                       |
| `SERVER_URL`    | `http://127.0.0.1:5000`      | Public URL used in email download links  |
| `SMTP_USER`     | *(empty)*                    | Gmail address for sending result emails  |
| `SMTP_PASSWORD` | *(empty)*                    | Gmail App Password                       |

If `SMTP_USER` / `SMTP_PASSWORD` are not set, the email step is skipped and the download link is logged to stdout instead.

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
| `POST` | `/api/upload`             | Upload a video. Body: `multipart/form-data` with `video` (file) and `email` (string). Returns `{ job_id }`. |
| `GET`  | `/api/status/<job_id>`    | Poll job status. Returns `{ status, stage, progress, error }`. |
| `GET`  | `/api/download/<job_id>`  | Download the processed video once `status == "done"`. |

**Processing stages (in order):** `queued` → `stabilizing` → `tracking` → `csv_postprocess` → `emailing` → `done`

**Accepted video formats:** `mp4`, `avi`, `mov`, `mkv`, `webm` (max 500 MB)

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
│   ├── models/
│   │   └── yolov11_obb.pt  # YOLOv11 OBB model weights
│   └── botsort.yaml        # BotSORT tracker configuration
├── services/
│   └── email_service.py    # Gmail SMTP email delivery
├── frontend/               # Vue 3 + Vite SPA
│   ├── src/
│   │   ├── App.vue
│   │   └── components/
│   │       ├── UploadForm.vue
│   │       └── JobStatus.vue
│   └── dist/               # Production build output
├── uploads/                # Uploaded raw videos (auto-created)
├── processed/              # Per-job output: annotated video + CSVs (auto-created)
├── pyproject.toml
└── requirements.txt
```
