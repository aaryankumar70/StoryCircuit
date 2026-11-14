"""Curiosity Engine - Web Dashboard Server CLI Runner.
Runs FastAPI/Uvicorn server for the local dashboard.
Handles logging redirection, PID lock acquisition, and safe termination.

Usage:
    python scripts/run_dashboard.py
"""
from __future__ import annotations

import atexit
import io
import logging
import os
import signal
import sys
from pathlib import Path

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from curiosity_engine.config import DASHBOARD_HOST, DASHBOARD_PORT, DATA_DIR

DASHBOARD_LOCK_FILE = DATA_DIR / ".dashboard.lock"
DASHBOARD_LOG_FILE = DATA_DIR / "dashboard.log"


def _configure_logging():
    """Ensure sys.stdout / sys.stderr are valid under pythonw.exe and append to dashboard.log."""
    DASHBOARD_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(DASHBOARD_LOG_FILE, "a", encoding="utf-8", buffering=1)

    if sys.stdout is None or getattr(sys.stdout, "closed", False):
        sys.stdout = log_fh
    elif isinstance(sys.stdout, io.TextIOWrapper):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if sys.stderr is None or getattr(sys.stderr, "closed", False):
        sys.stderr = log_fh
    elif isinstance(sys.stderr, io.TextIOWrapper):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _acquire_lock():
    pid = os.getpid()
    try:
        DASHBOARD_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        DASHBOARD_LOCK_FILE.write_text(str(pid), encoding="utf-8")
    except Exception:
        pass

    def _release_lock():
        try:
            if DASHBOARD_LOCK_FILE.exists():
                curr = DASHBOARD_LOCK_FILE.read_text(encoding="utf-8").strip()
                if curr == str(pid):
                    DASHBOARD_LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    atexit.register(_release_lock)


def main():
    _configure_logging()
    _acquire_lock()

    import uvicorn
    from curiosity_engine.dashboard.app import app

    uvicorn.run(
        app,
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
