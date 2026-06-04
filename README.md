# TTGUI Web — Traffic Video Analysis Platform

A web application for analyzing traffic videos from aerial (drone) footage. Upload a video, and the system automatically stabilizes it, detects and tracks vehicles using a YOLOv11 OBB model, post-processes the raw trajectories into clean CSVs, and emails you a secure download link when the job is done.

---

## Features

- **Video Stabilization** — ECC optical flow (GPU-accelerated via Kornia) to remove camera shake from drone footage
- **Object Detection** — YOLOv11 Oriented Bounding Box (OBB) model; detections exported as JSONL for streaming
- **Class-Aware Tracking** — OcSort tracker with per-class isolation to prevent track ID swaps between different vehicle types
- **Trajectory CSV Export** — Per-vehicle frame-by-frame OBB corner coordinates, cleaned and smoothed with configurable parameters
- **Email Notification** — Gmail SMTP delivers an HTML email with a secure (HMAC-signed) download link once processing is complete
- **Job Queue** — Single-worker background queue ensures jobs run sequentially and the server stays responsive
- **Contact Us Widget** — A floating button opens an in-app contact form (name, email, phone, subject, message) forwarded to the support inbox via Gmail SMTP

## Tracked Vehicle Classes

| Code | Class       |
|------|-------------|
| `c`  | Car         |
| `t`  | Truck       |
| `b`  | Bus         |
| `h`  | Truck Head  |
| `g`  | Truck Tail  |
| `p`  | Pedestrian  |
| `u`  | Bike        |
| `m`  | Motorcycle  |

---

## Architecture

```
Browser (Vue 3 SPA)
    │  POST /api/upload/init   (filename, email, total_chunks → job_id)
    │  POST /api/upload/chunk  (job_id, chunk_index, chunk)
    │  GET  /api/status/<job_id>
    │  GET  /api/dl/<token>    (HMAC-signed download token → ZIP)
    │  POST /api/contact       (name, email, message, …)
    ▼
Flask backend (app.py)
    │
    ├── In-memory job store (dict)
    ├── Background thread (queue.Queue, single worker)
    │
    └── Processing Pipeline (pipeline.py)
            ├── Stage 1 — stabilize.py      (ECC homography, Kornia GPU/MPS)
            ├── Stage 2 — detect.py         (YOLOv11 OBB inference → JSONL)
            ├── Stage 3 — tracking.py       (OcSort per-class tracking → raw.csv)
            └── Stage 4 — csv_postprocess.py (trajectory smoothing → processed.csv)
```

In production, Flask serves the pre-built Vue SPA from `frontend/dist/` and falls back to `index.html` for client-side routing.

---

## Prerequisites

- Python 3.10
- [uv](https://docs.astral.sh/uv/) (package manager)
- Node.js + npm (for frontend development)
- A GPU with CUDA or MPS (Apple Silicon) support recommended; falls back to CPU
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
cp .env.example .env
# Edit .env with your values
```

| Variable              | Default                         | Description                                          |
|-----------------------|---------------------------------|------------------------------------------------------|
| `SECRET_KEY`          | `dev-secret-key-change-me`      | Flask session secret (also used for HMAC tokens)     |
| `FLASK_DEBUG`         | `false`                         | Set to `true` in development to enable auto-reload and the interactive debugger |
| `SERVER_HOST`         | `127.0.0.1`                     | Host to bind Flask                                   |
| `SERVER_PORT`         | `5000`                          | Port to bind Flask                                   |
| `SERVER_URL`          | `http://127.0.0.1:5000`         | Public URL used in email download links              |
| `MAX_CONTENT_LENGTH`  | `10737418240` (10 GB)           | Maximum upload size in bytes                         |
| `SMTP_USER`           | *(empty)*                       | Gmail address for sending result emails              |
| `SMTP_PASSWORD`       | *(empty)*                       | Gmail App Password                                   |
| `CONTACT_RECIPIENT`   | *(falls back to `SMTP_USER`)*   | Inbox that receives "Contact Us" submissions         |

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
# App available at http://localhost:3000
```

---

## API Reference

| Method | Endpoint                   | Description                                                                                                                     |
|--------|----------------------------|---------------------------------------------------------------------------------------------------------------------------------|
| `POST` | `/api/upload/init`         | Start a chunked upload. Body: `application/json` with `filename`, `email`, `total_chunks`. Returns `{ job_id }`.               |
| `POST` | `/api/upload/chunk`        | Upload one chunk. Body: `multipart/form-data` with `job_id`, `chunk_index`, `chunk` (blob). Job queues on final chunk arrival. |
| `GET`  | `/api/status/<job_id>`     | Poll job status. Returns `{ status, stage, progress, error, download_token }`.                                                 |
| `GET`  | `/api/dl/<token>`          | Download ZIP (tracked video + processed CSV + background image) using the HMAC-signed token from the status response.          |
| `POST` | `/api/contact`             | Submit a "Contact Us" message. Body: `application/json` with `name`, `email`, `message` (required) and optional `phone`, `subject`. |

**Processing stages (in order):** `queued` → `stabilizing` → `detecting` → `tracking` → `csv_postprocessing` → `emailing` → `done`

**Accepted video formats:** `mp4`, `avi`, `mov`, `mkv`, `webm` (max 10 GB)

---

## Project Structure

```
TTGUI_Web/
├── app.py                  # Flask app, routes, job queue, chunked upload handling
├── config.py               # All configuration constants (paths, SMTP, limits)
├── pyproject.toml          # Project metadata, uv dependencies, Ruff linting config
├── .env.example            # Environment variable template
├── uv.lock                 # Lockfile for Python dependencies (managed via uv)
├── CONTRIBUTING.md         # Branching, PR, and code style guide
│
├── processing/
│   ├── pipeline.py         # Orchestrates the 4-stage pipeline
│   ├── stabilize.py        # ECC video stabilization (Kornia, GPU/MPS/CPU)
│   ├── detect.py           # YOLOv11 OBB inference, exports detections as JSONL
│   ├── tracking.py         # OcSort per-class tracking, writes raw.csv
│   ├── csv_postprocess.py  # Trajectory smoothing, validation, rotation handling
│   ├── models/
│   │   └── yolov11_obb.pt  # YOLOv11 OBB model weights (not in repo — user-provided)
│   └── tools/
│       └── check_row_length.py  # Helper script for CSV validation
│
├── services/
│   └── email_service.py    # Gmail SMTP: result emails + "Contact Us" forwarding
│
├── frontend/               # Vue 3 + Vite SPA
│   ├── src/
│   │   ├── App.vue
│   │   └── components/
│   │       ├── UploadForm.vue     # Drag-and-drop upload, chunked progress
│   │       ├── JobStatus.vue      # Polling status, stage progress, download button
│   │       └── ContactWidget.vue  # Floating "Contact Us" button + form modal
│   └── dist/               # Production build output (served by Flask)
│
├── docs/
│   ├── ocsort_tracking_params.md   # Tracking parameter tuning guide
│   └── su_軌跡檔格式定義.xlsx      # Trajectory CSV format specification
│
├── processed/              # Per-job staging and output directories (auto-created)
├── uploads/                # Temporary chunk upload directory (auto-created)
│
└── .github/
    ├── pull_request_template.md
    └── workflows/
        └── ci.yml          # Ruff lint + frontend build (runs on PRs)
```

---

## CI/CD

GitHub Actions runs on every pull request:

1. **Lint Python** — Ruff (`E`, `F`, `I` rules; `E501` line-length ignored)
2. **Build frontend** — `npm ci && npm run build`

No deployment automation. Build and run manually for production.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for branching conventions, PR guidelines, and code style.
