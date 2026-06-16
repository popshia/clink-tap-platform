import os

from dotenv import load_dotenv

load_dotenv()

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROCESSED_FOLDER = os.path.join(BASE_DIR, "processed")
MODEL_PATH = os.path.join(BASE_DIR, "processing", "models", "yolov11_obb.pt")

# --- Flask ---
MAX_CONTENT_LENGTH = int(
    os.environ.get("MAX_CONTENT_LENGTH", str(10 * 1024 * 1024 * 1024))
)
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

# --- Server ---
SERVER_HOST = os.environ.get("SERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "5000"))
SERVER_URL = os.environ.get("SERVER_URL", f"http://{SERVER_HOST}:{SERVER_PORT}")

# --- Gmail SMTP ---
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ.get("SMTP_USER", "")  # your-email@gmail.com
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")  # Gmail App Password

# Inbox that receives "Contact Us" submissions (defaults to the SMTP account).
CONTACT_RECIPIENT = os.environ.get("CONTACT_RECIPIENT", "") or SMTP_USER

# --- Allowed extensions ---
ALLOWED_EXTENSIONS = {"mp4", "avi", "mov", "mkv", "webm"}

# --- Processing limits ---
# Uploads from non-developer ("normal user") sessions are trimmed to the first
# N seconds of footage during stabilization. Developer-mode uploads bypass this
# and process the full video. Set to 0 to disable trimming for everyone.
FREE_TIER_MAX_DURATION_SECONDS = int(
    os.environ.get("FREE_TIER_MAX_DURATION_SECONDS", str(5 * 60))
)
