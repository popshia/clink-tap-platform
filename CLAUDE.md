# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**TTGUI Web** is a traffic video analysis platform that processes aerial (drone) footage to detect and track vehicles. The system is a Flask + Vue 3 stack with a CPU/GPU-optimized Python backend for video processing.

### What It Does

1. Upload a video file (max 10 GB)
2. **Stabilize** the video using ECC optical flow (GPU-accelerated via Kornia)
3. **Detect** vehicles using YOLOv11 OBB (Oriented Bounding Box) model
4. **Track** vehicles across frames using OcSort (class-aware tracking to prevent ID swaps)
5. **Post-process** raw trajectory CSVs with smoothing and validation
6. Email the user a secure download link (HMAC-signed token) for the processed video + CSV + background image as a ZIP

### Tech Stack

**Backend:**
- Python 3.10, Flask 3.1.3
- PyTorch 2.3.1 (CUDA 12.1 / MPS support for Apple Silicon)
- Ultralytics YOLOv11 OBB model
- Kornia (GPU-accelerated image registration / video stabilization)
- Boxmot OcSort tracker (with custom IoU patches for OBB)
- OpenCV, NumPy, Pandas, Loguru, Flask-CORS

**Frontend:**
- Vue 3, Vite 7, JavaScript (no TypeScript)
- CSS with design tokens (light design system)
- Chunked file upload with progress tracking
- Polling-based job status updates

**Infrastructure:**
- Single-threaded background worker (queue.Queue) for sequential processing
- In-memory job store (dict) with HMAC-SHA256 download tokens
- Gmail SMTP for result emails and contact form submissions
- Environment variable configuration (no .env files)

---

## Directory Structure

```
TTGUI_Web/
├── app.py                      # Flask app, routes, job queue, chunked upload handling
├── config.py                   # Configuration constants (paths, SMTP, limits)
├── requirements.txt            # Python dependencies (managed via uv)
├── pyproject.toml             # Ruff linting config
│
├── processing/                # Video processing pipeline
│   ├── pipeline.py            # Orchestrates 4-stage pipeline (stabilize → detect → track → csv_postprocess)
│   ├── stabilize.py           # ECC-based video stabilization (Kornia, GPU/MPS)
│   ├── detect.py              # YOLOv11 OBB inference, exports detections as JSONL
│   ├── tracking.py            # OcSort tracking with per-class isolation
│   ├── csv_postprocess.py     # Trajectory smoothing, validation, rotation handling
│   ├── models/
│   │   └── yolov11_obb.pt     # YOLOv11 OBB model (not in repo, user-provided)
│   └── tools/
│
├── services/
│   └── email_service.py       # Gmail SMTP: result emails + contact form forwarding
│
├── frontend/                   # Vue 3 SPA (Vite)
│   ├── src/
│   │   ├── main.js            # Vue app entry
│   │   ├── App.vue            # Root component (UploadForm ↔ JobStatus routing)
│   │   ├── style.css          # Design system (colors, typography, animations)
│   │   └── components/
│   │       ├── UploadForm.vue  # File drop zone, email input, chunked upload logic
│   │       ├── JobStatus.vue   # Polling status updates, progress bar, download UI
│   │       └── ContactWidget.vue # Floating contact form button + submission modal
│   ├── vite.config.js         # Vite config with /api proxy to Flask
│   ├── package.json           # Node dependencies (Vue 3, Vite, @vitejs/plugin-vue)
│   ├── index.html
│   └── dist/                   # Production build output (served by Flask)
│
├── docs/
│   └── ocsort_tracking_params.md  # Detailed tracking tuning guide
│
├── .github/
│   └── workflows/
│       └── ci.yml             # Ruff linting + frontend build (PR only)
│
└── .claude/
    └── settings.local.json    # Permission allowlist for Bash + git commands
```

---

## Key Commands

### Setup

```bash
# Install Python dependencies (uses uv package manager)
uv sync

# Install frontend dependencies
cd frontend && npm install && cd ..

# Provide the YOLOv11 OBB model
cp /path/to/yolov11_obb.pt processing/models/
```

### Development

```bash
# Terminal 1 — Flask backend (debug mode, auto-reload)
uv run app.py

# Terminal 2 — Vite dev server (HMR, proxies /api to http://127.0.0.1:5000)
cd frontend && npm run dev

# App will be at http://localhost:3000 (frontend) → http://127.0.0.1:5000 (API)
```

### Production Build

```bash
# Build frontend SPA
cd frontend && npm run build

# Flask serves pre-built dist/ as static files (no separate server needed)
uv run app.py
```

### Linting

```bash
# Lint Python (Ruff, enforces E, F, I; ignores E501 line length)
# CI uses: github.com/astral-sh/ruff-action
ruff check .

# Lint + fix (sorts imports, auto-fixes some errors)
ruff check . --fix

# Check Python syntax without running
.venv/bin/python -c "import ast; ast.parse(open('app.py').read()); print('Syntax OK')"
```

### Testing

This codebase does not have automated tests. Test manually:

```bash
# Test local dev setup (upload a video file via UI)
# Check console logs in Flask terminal for processing pipeline output
# Verify email delivery (if SMTP configured) or check stdout for fallback message

# Test individual processing modules (standalone):
.venv/bin/python -c "from processing.stabilize import stabilize_video; help(stabilize_video)"
.venv/bin/python -c "from processing.detect import detect_and_export_as_jsonl; help(detect_and_export_as_jsonl)"
```

### Environment Variables (Optional)

```bash
# Set before running app.py
export SECRET_KEY="your-secret-key"
export SERVER_HOST="127.0.0.1"
export SERVER_PORT="5000"
export SERVER_URL="http://your-server-address:5000"  # Used in email download links

# Gmail SMTP (required for email delivery)
export SMTP_USER="your-email@gmail.com"
export SMTP_PASSWORD="your-gmail-app-password"  # Generate in Gmail account settings
export CONTACT_RECIPIENT="support@your-domain.com"  # Optional; defaults to SMTP_USER

# If SMTP credentials are not set, emails are logged to stdout instead
```

---

## Architecture & Design Patterns

### Backend: Flask Job Queue System

**Request Flow:**
1. Client calls `POST /api/upload/init` → server allocates `job_id`, staging dir, returns job ID
2. Client calls `POST /api/upload/chunk` repeatedly (chunked upload) → server writes chunks to disk
3. When final chunk arrives → all chunks are assembled into a single file and enqueued
4. Client calls `GET /api/status/<job_id>` (polling) → returns `{ status, stage, progress, error }`
5. Background worker processes job sequentially through the pipeline
6. When done → `POST /api/contact` or result email sent with HMAC-signed download token

**Key File:** `app.py` contains all routes, the in-memory job store, and the single background worker thread.

### Processing Pipeline (4 Stages)

**File:** `processing/pipeline.py`

```
Input Video
    ↓
[Stage 1] stabilize.py → ECC homography registration (Kornia GPU/MPS)
    ↓
[Stage 2] detect.py → YOLOv11 OBB inference, export as JSONL
    ↓
[Stage 3] tracking.py → OcSort with per-class isolation, write raw.csv
    ↓
[Stage 4] csv_postprocess.py → trajectory smoothing, rotation validation
    ↓
Output: processed.csv, processed video, background.png
```

Each stage calls `on_progress(stage_name, percent)` to update the job record in real-time. The pipeline logs are streamed to stdout with Loguru.

### Video Stabilization (`stabilize.py`)

- Uses Kornia's `ImageRegistrator` with **ECC loss** (Enhanced Correlation Coefficient)
- GPU-accelerated (CUDA / MPS fallback to CPU)
- Multi-scale pyramid for robustness
- Outputs a stabilized video at fixed 1920x1080 resolution

### Object Detection (`detect.py`)

- YOLOv11 OBB model (Oriented Bounding Boxes, not axis-aligned)
- Inference runs on every frame (no frame skipping for full trajectory coverage)
- Detections exported as JSONL (one JSON per frame): `{ "frame_index": N, "dets": [[cx, cy, w, h, angle_rad, conf, class], ...] }`
- Also computes a **background image** (median of sampled frames)

### Tracking (`tracking.py`)

- **OcSort tracker** (Occlusion-aware SORT from Boxmot library)
- **Per-class tracking** (`per_class=True`) → prevents ID swaps between different vehicle types (car, truck, bus, motorcycle, etc.)
- **Custom IoU patch** → uses rotated IoU for OBB (not axis-aligned bounding box IoU)
- Configuration tuned in the tracker init (det_thresh=0.3, max_age=30, min_hits=3)
- Output: tracked video + raw.csv with frame-by-frame detections and track IDs

**Tracked Vehicle Classes:**
```
c = Car, t = Truck, b = Bus, h = Truck Head, g = Truck Tail, p = Pedestrian, u = Bike, m = Motorcycle
```

### CSV Post-Processing (`csv_postprocess.py`)

**Heavy logic with Taiwan-specific tuning:**
- Trajectory smoothing (moving average window)
- Rotation handling (vehicle heading angle validation, force-long-axis for motorcycles)
- Turn angle limiting per vehicle class (prevent 180° flips from bounding box drift)
- Reverse detection (identify backward motion, apply distance limits)
- Escape radius check (ignore drift in parked vehicles)

**Key config class:** `TrajectoryConfig` — all smoothing/validation params centralized here. See `docs/ocsort_tracking_params.md` for detailed parameter tuning.

### Download Security

- Download URLs use **HMAC-SHA256 signed tokens** (not guessable job IDs)
- Token format: `base64url_payload.hex_signature`
- Payload: `{ "j": job_id }` (HMAC'd with Flask secret key)
- Generated on job completion, returned in status API and email link
- `GET /api/dl/<token>` → verifies signature, streams ZIP (video + CSV + background)

### Email Service (`services/email_service.py`)

- Uses Gmail SMTP (smtp.gmail.com:587 with STARTTLS)
- Two functions:
  1. **Result email** — HTML template with download button, sent after job completes
  2. **Contact form email** — forwards "Contact Us" widget submissions to support inbox with `Reply-To` header
- Falls back to stdout logging if SMTP not configured

### Frontend: Vue 3 SPA

**Three main components:**
1. **UploadForm.vue** — drag-and-drop file input, chunked upload with progress bar, email field
2. **JobStatus.vue** — polling-based status UI, stage-by-stage progress, download button (uses download token from API)
3. **ContactWidget.vue** — floating "Contact Us" button, form modal, AJAX submission

**App state flow:**
- `App.vue` routes between UploadForm (before upload) and JobStatus (during/after processing)
- Job ID stored in parent component, passed to JobStatus for polling
- No client-side routing (all server-rendered SPA)

**Styling:**
- Light design system (CSS custom properties) in `style.css`
- Color palette: light grays (#E9E9E9, #F6F6F6), accent teal (#7E99A3)
- Animations: fade-in-up, spinner, shimmer for progress bars

---

## Common Patterns & Conventions

### Progress Callbacks

Many processing functions accept an optional `on_progress(stage_name, percent)` callback. The pipeline uses this to update the job record in real-time without blocking:

```python
def stabilize_video(..., on_progress=None):
    ...
    if on_progress:
        on_progress("stabilizing", pct)
```

### JSONL Format for Detections

The detection output is a streaming JSON Lines format (one JSON object per line, one per frame):

```
{"frame_index": 0, "dets": [[cx, cy, w, h, angle_rad, conf, class], ...]}
{"frame_index": 1, "dets": [[cx, cy, w, h, angle_rad, conf, class], ...]}
...
```

This allows the tracker to read frame-by-frame without loading the entire file into memory.

### OBB Detection Format

Each detection is a 7-tuple: `[center_x, center_y, width, height, angle_rad, confidence, class_id]`

- `angle_rad` is the rotation of the bounding box in radians (0 = axis-aligned, π/4 = 45°)
- Classes are numeric: 0=car, 1=truck, ... (mapping defined in YOLOv11 model)

### Device Selection (GPU/MPS/CPU)

The codebase follows a consistent pattern for GPU fallback:

```python
device = (
    "cuda" if torch.cuda.is_available()
    else ("mps" if torch.backends.mps.is_available() else "cpu")
)
```

Used in both `stabilize.py` and `detect.py`. MPS is Apple Silicon support.

### Centralized Configuration

All config lives in `config.py` — paths, limits, SMTP server details, allowed extensions. No hardcoded values in code.

### Chunked Upload Deduplication

The upload system uses a lock + atomic swap to prevent race conditions:
- `_pending_lock` guards the `pending_uploads` dict
- Once the final chunk arrives, the upload is removed from `pending_uploads` before being enqueued as a job
- Prevents double-finalization if two chunk requests race

---

## Testing Notes

The project has **no automated test suite**. Manual testing workflow:

1. **Local dev**: Run both Flask backend and Vite frontend in separate terminals
2. **Upload a test video**: Use the UI to trigger the full pipeline
3. **Monitor logs**: Check Flask terminal for stage progress and errors
4. **Email delivery**: Set SMTP credentials to test email workflow, or check stdout fallback
5. **Processing validation**: Verify output CSV structure and video output visually

For isolated module testing, import and call functions directly in a Python REPL.

---

## CI/CD

**File:** `.github/workflows/ci.yml`

Runs on pull requests only:
1. **Lint Python** — Ruff (E, F, I rules; ignore E501)
2. **Build frontend** — `npm ci && npm run build`

No deployment automation. Manual build and run for production.

---

## Important Notes

### Model Setup
The YOLOv11 OBB model is **not** included in the repo. Users must provide:
```
processing/models/yolov11_obb.pt
```

### Video Codec
Output video uses **mp4v codec** (H.264 MPEG-4 Part 2). Ensure FFmpeg is installed on the system running Flask.

### Memory & Hardware
- Video processing is **single-threaded** (one job at a time)
- GPU strongly recommended for large videos (stabilization + detection are compute-intensive)
- Falls back to CPU gracefully but will be slow

### Email Fallback
If `SMTP_USER` or `SMTP_PASSWORD` are not set:
- Result emails are logged to stdout: `[EMAIL] Download link would be: ...`
- Contact form submissions are logged: `[CONTACT] Forwarded contact message from ...`
- This is useful for dev/testing without configuring Gmail

### CSV Output Format
The final `processed.csv` contains frame-by-frame bounding box corners and track IDs for each detected vehicle. Exact column structure defined in `csv_postprocess.py` (see `TrajectoryConfig` comments for field meanings).

