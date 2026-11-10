"""Curiosity Engine - Global Configuration & Constants.
Autonomous Short-Form Video Production Studio.
Strict ₹0 / $0 Free-Tier Local Target.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple
from dotenv import dotenv_values, load_dotenv

# Base Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
_LAST_ENV_STATE: Optional[Tuple[str, float]] = None
if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE, override=False)
    try:
        _LAST_ENV_STATE = (str(ENV_FILE), ENV_FILE.stat().st_mtime)
    except OSError:
        _LAST_ENV_STATE = None
MODELS_DIR = PROJECT_ROOT / "models"
KOKORO_DIR = MODELS_DIR / "kokoro"
WHISPER_DIR = MODELS_DIR / "whisper-small"
OUTPUT_DIR = PROJECT_ROOT / "output"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
DATA_DIR = PROJECT_ROOT / "data"

for directory in [OUTPUT_DIR, DATA_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# CurioLoop Studio Brand Identity
BRAND_NAME = "CurioLoop"
BRAND_WATERMARK_ENABLED = True
BRAND_WATERMARK_OPACITY = 0.55

# Audio Broadcast Standards (YouTube Shorts / Reels EBU R128)
TARGET_INTEGRATED_LUFS_MIN = -21.0
TARGET_INTEGRATED_LUFS_MAX = -13.0
MAX_TRUE_PEAK_DB = -0.5

# Video Geometry & Timing Constraints
MAX_DAILY_VIDEOS = 2
MIN_DURATION_SEC = 20.0
MAX_DURATION_SEC = 30.0
MIN_WORD_COUNT = 48
MAX_WORD_COUNT = 62
TARGET_FPS = 30
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920

# Safe Caption Zones (Pixels from top)
SAFE_ZONE_TOP = 250
SAFE_ZONE_BOTTOM = 1600
CAPTION_ZONE_Y = 1400

# Content Pillars
CONTENT_PILLARS = [
    "Science",
    "Space",
    "History",
    "Mysteries",
    "Technology",
    "AI",
    "Psychology",
    "Biology",
    "Geography",
    "Nature",
    "Interesting discoveries",
]

# Visual Style Mappings
STYLE_MAPPINGS = {
    "Biology": "inside-out",
    "Psychology": "inside-out",
    "Science": "inside-out",
    "History": "paper-atlas",
    "Geography": "paper-atlas",
    "Interesting discoveries": "paper-atlas",
    "Mysteries": "paper-atlas",
    "Technology": "stick-story",
    "AI": "stick-story",
    "Space": "stick-story",
    "Nature": "inside-out",
}

# Voice Configuration
VOICE_MAP = {
    "inside-out": "am_michael",   # US male, steady explainer
    "paper-atlas": "bm_george",   # UK male, documentary
    "stick-story": "am_puck",     # US male, lively & engaging
}

# Gemini API Settings (Free Tier: 15 RPM / 1M TPM)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Social Publishing Credentials & Controls
INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_ACCOUNT_ID = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")
INSTAGRAM_API_VERSION = os.environ.get("INSTAGRAM_API_VERSION", "v22.0")

YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
YOUTUBE_UPLOAD_DAILY_LIMIT = 100  # Dedicated YouTube Data API v3 upload bucket

# Telegram Operational Notifications (Bot API - free tier)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_DAILY_SUMMARY_HOUR_IST = int(os.environ.get("TELEGRAM_DAILY_SUMMARY_HOUR_IST", "21"))


_SYNCABLE_ENV_KEYS = (
    "GEMINI_API_KEY",
    "INSTAGRAM_ACCESS_TOKEN",
    "INSTAGRAM_ACCOUNT_ID",
    "INSTAGRAM_API_VERSION",
    "YOUTUBE_CLIENT_ID",
    "YOUTUBE_CLIENT_SECRET",
    "YOUTUBE_REFRESH_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_DAILY_SUMMARY_HOUR_IST",
)


def sync_env_if_updated(force: bool = False) -> bool:
    """Hot-reload `.env` values into process globals when `.env` changes on disk.

    Tracks `(path, mtime)` so normal in-memory `monkeypatch.setenv` tests are
    never overwritten unless the `.env` file was actually modified or `force=True`.
    """
    global _LAST_ENV_STATE
    global GEMINI_API_KEY, INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_ACCOUNT_ID, INSTAGRAM_API_VERSION
    global YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_DAILY_SUMMARY_HOUR_IST

    if not ENV_FILE.exists():
        return False

    try:
        current_state = (str(ENV_FILE), ENV_FILE.stat().st_mtime)
    except OSError:
        return False

    if not force and _LAST_ENV_STATE == current_state:
        return False

    parsed = dotenv_values(ENV_FILE)
    for key in _SYNCABLE_ENV_KEYS:
        if key in parsed and parsed[key] is not None:
            os.environ[key] = str(parsed[key])

    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
    INSTAGRAM_ACCOUNT_ID = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")
    INSTAGRAM_API_VERSION = os.environ.get("INSTAGRAM_API_VERSION", "v22.0")
    YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "")
    YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
    YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    try:
        TELEGRAM_DAILY_SUMMARY_HOUR_IST = int(os.environ.get("TELEGRAM_DAILY_SUMMARY_HOUR_IST", "21"))
    except ValueError:
        TELEGRAM_DAILY_SUMMARY_HOUR_IST = 21

    _LAST_ENV_STATE = current_state
    return True

# Publishing Mode & Provider Controls
# Global fallback mode
PUBLISHING_MODE = os.environ.get("PUBLISHING_MODE", "simulation").strip().lower()

# Platform-specific Publishing Modes
# YouTube Publishing Mode: "simulation" (default) or "live"
YOUTUBE_PUBLISHING_MODE = os.environ.get(
    "YOUTUBE_PUBLISHING_MODE",
    PUBLISHING_MODE if PUBLISHING_MODE in ["simulation", "live"] else "simulation",
).strip().lower()


def _resolve_youtube_privacy() -> str:
    """Resolve YouTube privacy status with strict 'private' default. Never default to public."""
    val = os.environ.get("YOUTUBE_PRIVACY_STATUS", "private").strip().lower()
    if val in ["private", "unlisted", "public"]:
        return val
    return "private"


YOUTUBE_PRIVACY_STATUS = _resolve_youtube_privacy()

# Instagram Publishing Mode: "disabled" (strict ₹0 default), "simulation", or "live"
INSTAGRAM_PUBLISHING_MODE = os.environ.get("INSTAGRAM_PUBLISHING_MODE", "disabled").strip().lower()

VIDEO_HOST_PROVIDER = os.environ.get("VIDEO_HOST_PROVIDER", "simulation").strip().lower()

# Autonomous Scheduler Configuration (Asia/Kolkata / IST)
SCHEDULER_TIMEZONE = os.environ.get("SCHEDULER_TIMEZONE", "Asia/Kolkata")
SCHEDULER_GENERATE_TIME = os.environ.get("SCHEDULER_GENERATE_TIME", "05:30")
SCHEDULER_PUBLISH_SLOT1_TIME = os.environ.get("SCHEDULER_PUBLISH_SLOT1_TIME", "12:30")
SCHEDULER_PUBLISH_SLOT2_TIME = os.environ.get("SCHEDULER_PUBLISH_SLOT2_TIME", "20:30")

# Local Dashboard Binding & Dynamic Secret Generation
DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8000"))


def get_dashboard_secret() -> str:
    """Retrieve or securely generate a local random dashboard secret stored outside VCS."""
    env_secret = os.environ.get("DASHBOARD_SECRET_KEY")
    if env_secret and len(env_secret.strip()) >= 16:
        return env_secret.strip()

    secret_file = DATA_DIR / ".dashboard_secret"
    if secret_file.exists():
        try:
            stored = secret_file.read_text(encoding="utf-8").strip()
            if len(stored) >= 16:
                return stored
        except Exception:
            pass

    import secrets
    new_secret = secrets.token_urlsafe(32)
    try:
        secret_file.write_text(new_secret, encoding="utf-8")
        # On POSIX, restrict permissions (no-op on Windows but good practice)
        if hasattr(os, "chmod"):
            os.chmod(secret_file, 0o600)
    except Exception:
        pass
    return new_secret


DASHBOARD_SECRET_KEY = get_dashboard_secret()

# Google Cloud Project Reference (Hosts YouTube Data API v3 & OAuth 2.0 Client)
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "curiosity-engine-prod")

# Chrome / Browser Binary Discovery
DEFAULT_CHROME_PATHS = [
    os.environ.get("CHROME"),
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def get_chrome_executable() -> str:
    """Find available Chrome/Chromium/Edge binary."""
    for path in DEFAULT_CHROME_PATHS:
        if path and Path(path).exists():
            return str(path)
    return "google-chrome"
