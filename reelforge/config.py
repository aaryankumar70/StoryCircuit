"""Central configuration for ReelForge."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv, set_key

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE_FILE = PROJECT_ROOT / ".env.example"


def reload_env() -> None:
    """Load `.env`, refreshing keys that are unset or empty in the current process."""
    if ENV_FILE.exists():
        from dotenv import dotenv_values

        load_dotenv(dotenv_path=ENV_FILE, override=False)
        for k, v in dotenv_values(ENV_FILE).items():
            if v is not None and not os.environ.get(k, "").strip() and str(v).strip():
                os.environ[k] = str(v)


reload_env()

DATA_DIR = Path(os.environ.get("REELFORGE_DATA_DIR") or (PROJECT_ROOT / "data")).resolve()
OUTPUT_DIR = Path(os.environ.get("REELFORGE_OUTPUT_DIR") or (PROJECT_ROOT / "output")).resolve()
ASSETS_DIR = Path(os.environ.get("REELFORGE_ASSETS_DIR") or (PROJECT_ROOT / "assets")).resolve()
MUSIC_DIR = ASSETS_DIR / "music"
DB_PATH = Path(os.environ.get("REELFORGE_DB_PATH") or (DATA_DIR / "reelforge.db")).resolve()

for _d in (DATA_DIR, OUTPUT_DIR, ASSETS_DIR, MUSIC_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Video specifications (9:16 Shorts <= 120s, auto 16:9 Landscape > 120s)
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
LANDSCAPE_WIDTH = 1920
LANDSCAPE_HEIGHT = 1080
VIDEO_FPS = 30
SHORT_MAX_DURATION_SEC = float(os.environ.get("SHORT_MAX_DURATION_SEC", "120.0"))

# Caption safe zone (below top overlay, above YouTube Shorts bottom UI)
CAPTION_MARGIN_V = 410
LANDSCAPE_CAPTION_MARGIN_V = 72
CAPTION_FONT_NAME = os.environ.get("CAPTION_FONT_NAME", "Noto Sans Black")

# LLM Brain
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b-instruct")
OLLAMA_TIMEOUT_SEC = int(os.environ.get("OLLAMA_TIMEOUT_SEC", "120"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")

# Visuals
VISUAL_MODE = os.environ.get("VISUAL_MODE", "auto").strip().lower()
POLLINATIONS_MODEL = os.environ.get("POLLINATIONS_MODEL", "flux").strip()
POLLINATIONS_TIMEOUT_SEC = int(os.environ.get("POLLINATIONS_TIMEOUT_SEC", "45"))

# TTS
TTS_ENGINE = os.environ.get("TTS_ENGINE", "edge").strip().lower()
TTS_VOICE_PRIMARY = os.environ.get("TTS_VOICE_PRIMARY", "en-US-AndrewNeural")
TTS_VOICE_SECONDARY = os.environ.get("TTS_VOICE_SECONDARY", "en-US-AvaNeural")
TTS_RATE = os.environ.get("TTS_RATE", "+4%")

# Schedule & Automation
SCHEDULER_TIMEZONE = os.environ.get("SCHEDULER_TIMEZONE", "Asia/Kolkata")
SLOT1_TIME = os.environ.get("SLOT1_TIME", "12:30")
SLOT2_TIME = os.environ.get("SLOT2_TIME", "20:30")
MAX_DAILY_VIDEOS = int(os.environ.get("MAX_DAILY_VIDEOS", "2"))
AUTO_SCHEDULER_ENABLED = os.environ.get("AUTO_SCHEDULER_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
AUTO_GARBAGE_CLEANUP = os.environ.get("AUTO_GARBAGE_CLEANUP", "1").strip().lower() not in {"0", "false", "no"}

# YouTube
YOUTUBE_PUBLISHING_MODE = os.environ.get("YOUTUBE_PUBLISHING_MODE", "live").strip().lower()
YOUTUBE_PRIVACY_STATUS = os.environ.get("YOUTUBE_PRIVACY_STATUS", "private").strip().lower()
YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "").strip()
YOUTUBE_CATEGORY_ID = os.environ.get("YOUTUBE_CATEGORY_ID", "27").strip()
CLIENT_SECRET_PATH = Path(os.environ.get("YOUTUBE_CLIENT_SECRET_PATH") or (DATA_DIR / "client_secret.json")).resolve()


def ensure_env_file() -> Path:
    """Create `.env` from `.env.example` if missing so runtime updates persist."""
    if not ENV_FILE.exists():
        if ENV_EXAMPLE_FILE.exists():
            ENV_FILE.write_text(ENV_EXAMPLE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            ENV_FILE.write_text("", encoding="utf-8")
    return ENV_FILE


def save_env_values(updates: Dict[str, str]) -> None:
    """Persist key=value settings to `.env` and refresh in-memory config attributes."""
    global YOUTUBE_PUBLISHING_MODE, YOUTUBE_PRIVACY_STATUS
    global YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
    global GEMINI_API_KEY, GEMINI_MODEL
    env_path = ensure_env_file()
    for key, val in updates.items():
        clean_val = str(val)
        set_key(str(env_path), key, clean_val)
        os.environ[key] = clean_val
    YOUTUBE_PUBLISHING_MODE = os.environ.get("YOUTUBE_PUBLISHING_MODE", YOUTUBE_PUBLISHING_MODE).strip().lower()
    YOUTUBE_PRIVACY_STATUS = os.environ.get("YOUTUBE_PRIVACY_STATUS", YOUTUBE_PRIVACY_STATUS).strip().lower()
    YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", YOUTUBE_CLIENT_ID).strip()
    YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", YOUTUBE_CLIENT_SECRET).strip()
    YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", YOUTUBE_REFRESH_TOKEN).strip()
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", GEMINI_API_KEY).strip()
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", GEMINI_MODEL).strip() or "gemini-3-flash-preview"


def parse_client_secret_payload(data: Any) -> Dict[str, Any]:
    """Validate and normalize a Google OAuth `client_secret.json` payload."""
    if not isinstance(data, dict):
        raise ValueError("Client secret JSON must be an object.")
    client_type: Optional[str] = None
    section: Optional[Dict[str, Any]] = None
    for candidate in ("installed", "web"):
        if isinstance(data.get(candidate), dict):
            client_type = candidate
            section = data[candidate]
            break
    if not client_type or section is None:
        raise ValueError("JSON must contain an 'installed' (Desktop App) or 'web' OAuth client block.")

    client_id = str(section.get("client_id") or "").strip()
    client_secret = str(section.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise ValueError("Client JSON is missing 'client_id' or 'client_secret'.")

    redirect_uris = [str(u) for u in (section.get("redirect_uris") or []) if str(u).strip()]
    return {
        "client_type": client_type,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uris": redirect_uris,
        "raw": data,
    }


def load_client_secret_info() -> Optional[Dict[str, Any]]:
    """Load saved Google OAuth client_secret.json from data dir or project root."""
    candidates: List[Path] = [CLIENT_SECRET_PATH, PROJECT_ROOT / "client_secret.json"]
    for path in candidates:
        if path.exists() and path.is_file():
            try:
                parsed = parse_client_secret_payload(json.loads(path.read_text(encoding="utf-8")))
                parsed["path"] = str(path)
                return parsed
            except Exception:
                continue
    return None

# Dashboard (dedicated port 8090 to avoid conflicts with ClipSnip:8000 and GiggleBeats:8080)
DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8090"))

# Quality Control
MIN_DURATION_SEC = float(os.environ.get("MIN_DURATION_SEC", "18.0"))
MAX_DURATION_SEC = float(os.environ.get("MAX_DURATION_SEC", "120.0"))
LONG_MAX_DURATION_SEC = float(os.environ.get("LONG_MAX_DURATION_SEC", "3600.0"))
TARGET_LUFS = float(os.environ.get("TARGET_LUFS", "-16.0"))
MAX_TRUE_PEAK_DB = float(os.environ.get("MAX_TRUE_PEAK_DB", "-1.0"))
