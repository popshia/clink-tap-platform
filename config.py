import os

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROCESSED_FOLDER = os.path.join(BASE_DIR, "processed")
MODEL_PATH = os.path.join(BASE_DIR, "processing", "models", "yolov11_obb.pt")

# --- Flask ---
MAX_CONTENT_LENGTH = 10 * 1024 * 1024 * 1024  # 10 GB upload limit
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

# --- Allowed extensions ---
ALLOWED_EXTENSIONS = {"mp4", "avi", "mov", "mkv", "webm"}
