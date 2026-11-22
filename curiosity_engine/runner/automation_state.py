"""Persistent Date-Aware Automation State Manager for CurioLoop.
Maintains atomic JSON records for first-startup-of-the-day generation,
independent QC results, YouTube batch upload, and status.publishAt scheduling.

Strict ₹0 Budget: Pure local storage with atomic replace, no cloud database.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from curiosity_engine.config import DATA_DIR, SCHEDULER_TIMEZONE
from curiosity_engine.state.file_lock import interprocess_file_lock

logger = logging.getLogger("curiosity_engine.automation_state")
AUTOMATION_STATE_FILE = DATA_DIR / "automation_state.json"
STATE_LOCK_TIMEOUT_SEC = 30.0


class AutomationStateManager:
    """Thread-safe and process-safe atomic state manager for CurioLoop daily automation."""

    def __init__(self, state_path: Optional[Path] = None, state_file: Optional[Path] = None):
        self.state_path = Path(state_file or state_path or AUTOMATION_STATE_FILE)
        self._thread_lock = threading.RLock()
        self._lock_path = self.state_path.with_suffix(self.state_path.suffix + ".lock")
        self._ensure_file_exists()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock:
            with interprocess_file_lock(self._lock_path, timeout_sec=STATE_LOCK_TIMEOUT_SEC):
                yield

    @staticmethod
    def _default_state() -> Dict[str, Any]:
        return {
            "version": "2.0",
            "enabled": True,
            "timezone": SCHEDULER_TIMEZONE,
            "last_run": None,
            "daily_records": {},
        }

    @staticmethod
    def _new_daily_record(date_str: str) -> Dict[str, Any]:
        clean_date = date_str.replace("-", "")
        slot_template = {
            "generation_status": "PENDING",
            "qc_passed": False,
            "qc_results": None,
            "upload_status": "NOT_STARTED",
            "youtube_video_id": None,
            "youtube_simulated": True,
            "scheduled_status": "NOT_SCHEDULED",
            "scheduled_publish_at": None,
            "scheduled_publish_at_ist": None,
            "retry_count": 0,
            "error": None,
        }
        return {
            "date": date_str,
            "overall_status": "PENDING",
            "generation": {
                "status": "PENDING",
                "started_at": None,
                "completed_at": None,
                "retries": 0,
                "error": None,
            },
            "slot1": {"video_id": f"video_{clean_date}_slot1", **slot_template},
            "slot2": {"video_id": f"video_{clean_date}_slot2", **slot_template},
            "last_failure": None,
            "last_recovery": None,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    def _ensure_file_exists(self) -> None:
        with self._locked():
            if not self.state_path.exists():
                self._write_atomic(self._default_state())

    def _load_raw(self) -> Dict[str, Any]:
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                value = json.load(f)
            if not isinstance(value, dict):
                raise ValueError("automation state must be a JSON object")
            return value
        except Exception as e:
            logger.warning("Error reading automation state (%s); using an in-memory default.", e)
            return self._default_state()

    def _write_atomic(self, data: Dict[str, Any]) -> None:
        """Persist under the caller's process lock using a unique temp file and replace retries."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        unique = f"{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}"
        tmp_path = self.state_path.with_name(f".{self.state_path.name}.{unique}.tmp")
        try:
            with open(tmp_path, "x", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            for attempt in range(6):
                try:
                    os.replace(tmp_path, self.state_path)
                    return
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.05 * (2 ** attempt))
        except Exception as e:
            logger.error("Failed to atomically persist automation state: %s", e)
            raise
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not clean this writer's temporary state file: %s", tmp_path)

    def is_enabled(self) -> bool:
        """Check whether daily autonomous scheduling is enabled by the user."""
        raw = self._load_raw()
        return bool(raw.get("enabled", True))

    def set_enabled(self, enabled: bool) -> None:
        """Toggle daily autonomous scheduling without clobbering concurrent state updates."""
        with self._locked():
            raw = self._load_raw()
            raw["enabled"] = bool(enabled)
            if enabled:
                raw["oauth_paused"] = False
                raw["oauth_pause_reason"] = None
            raw["last_updated"] = datetime.now(timezone.utc).isoformat()
            self._write_atomic(raw)
        logger.info("Automation enabled status updated to: %s", enabled)

    def pause_for_oauth(self, reason: str) -> Dict[str, Any]:
        """Safely pause new automation due to OAuth expiration/rejection while preserving schedules."""
        with self._locked():
            raw = self._load_raw()
            prior_enabled = bool(raw.get("oauth_prior_enabled", raw.get("enabled", True))) if raw.get("oauth_paused") else bool(raw.get("enabled", True))
            raw["enabled"] = False
            raw["oauth_paused"] = True
            raw["oauth_pause_reason"] = str(reason)[:300]
            raw["oauth_paused_at"] = datetime.now(timezone.utc).isoformat()
            raw["oauth_prior_enabled"] = prior_enabled
            raw["last_updated"] = datetime.now(timezone.utc).isoformat()
            self._write_atomic(raw)
        logger.warning("Paused new automation due to OAuth error (prior_enabled=%s).", prior_enabled)
        return self.get_oauth_pause()

    def get_oauth_pause(self) -> Dict[str, Any]:
        """Return whether automation is currently paused specifically for OAuth recovery."""
        raw = self._load_raw()
        return {
            "paused": bool(raw.get("oauth_paused", False)),
            "reason": raw.get("oauth_pause_reason"),
            "paused_at": raw.get("oauth_paused_at"),
            "prior_enabled": bool(raw.get("oauth_prior_enabled", False)),
        }

    def resume_after_oauth(self) -> bool:
        """Resume automation after healthy OAuth reauthorization if it was paused for OAuth."""
        with self._locked():
            raw = self._load_raw()
            was_oauth_paused = bool(raw.get("oauth_paused", False))
            prior_enabled = bool(raw.get("oauth_prior_enabled", True))
            raw["oauth_paused"] = False
            raw["oauth_pause_reason"] = None
            raw["oauth_resumed_at"] = datetime.now(timezone.utc).isoformat()
            resumed = False
            if was_oauth_paused and prior_enabled:
                raw["enabled"] = True
                resumed = True
            raw["last_updated"] = datetime.now(timezone.utc).isoformat()
            self._write_atomic(raw)
        if resumed:
            logger.info("Resumed automation automatically after verified YouTube OAuth reauthorization.")
        return resumed

    def get_daily_record(self, date_str: str) -> Dict[str, Any]:
        """Retrieve a daily record, initializing only that missing date if necessary."""
        with self._locked():
            raw = self._load_raw()
            records = raw.get("daily_records")
            if not isinstance(records, dict):
                records = {}
                raw["daily_records"] = records
            if date_str not in records or not isinstance(records[date_str], dict):
                records[date_str] = self._new_daily_record(date_str)
                self._write_atomic(raw)
            return records[date_str]

    def update_daily_record(self, date_str: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Merge an update in one cross-process read-modify-write transaction."""
        with self._locked():
            raw = self._load_raw()
            records = raw.get("daily_records")
            if not isinstance(records, dict):
                records = {}
                raw["daily_records"] = records
            record = records.get(date_str)
            if not isinstance(record, dict):
                record = self._new_daily_record(date_str)

            for key, value in updates.items():
                if isinstance(value, dict) and isinstance(record.get(key), dict):
                    record[key].update(value)
                else:
                    record[key] = value

            now = datetime.now(timezone.utc).isoformat()
            record["last_updated"] = now
            records[date_str] = record
            raw["last_run"] = now
            self._write_atomic(raw)
            return record

    def get_summary(self) -> Dict[str, Any]:
        """Return high-level telemetry summary for dashboard integration."""
        raw = self._load_raw()
        daily_records = raw.get("daily_records")
        if not isinstance(daily_records, dict):
            daily_records = {}
        return {
            "enabled": raw.get("enabled", True),
            "oauth_paused": bool(raw.get("oauth_paused", False)),
            "oauth_pause_reason": raw.get("oauth_pause_reason"),
            "oauth_paused_at": raw.get("oauth_paused_at"),
            "timezone": raw.get("timezone", SCHEDULER_TIMEZONE),
            "last_run": raw.get("last_run"),
            "daily_records_count": len(daily_records),
            "daily_records": daily_records,
        }


automation_state = AutomationStateManager()
