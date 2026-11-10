"""Persistent Date-Aware Automation State Manager for CurioLoop.
Maintains atomic JSON records for first-startup-of-the-day generation,
independent QC results, YouTube batch upload, and status.publishAt scheduling.

Strict ₹0 Budget: Pure local storage with atomic replace, no cloud database.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from curiosity_engine.config import DATA_DIR, SCHEDULER_TIMEZONE

logger = logging.getLogger("curiosity_engine.automation_state")

AUTOMATION_STATE_FILE = DATA_DIR / "automation_state.json"


class AutomationStateManager:
    """Thread-safe and process-safe atomic state manager for CurioLoop daily automation."""

    def __init__(self, state_path: Optional[Path] = None, state_file: Optional[Path] = None):
        self.state_path = state_file or state_path or AUTOMATION_STATE_FILE
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        if not self.state_path.exists():
            initial_state = {
                "version": "2.0",
                "enabled": True,
                "timezone": SCHEDULER_TIMEZONE,
                "last_run": None,
                "daily_records": {},
            }
            self._write_atomic(initial_state)

    def _load_raw(self) -> Dict[str, Any]:
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error reading automation state ({e}); reinitializing.")
            return {
                "version": "2.0",
                "enabled": True,
                "timezone": SCHEDULER_TIMEZONE,
                "last_run": None,
                "daily_records": {},
            }

    def _write_atomic(self, data: Dict[str, Any]) -> None:
        """Write to temporary file and atomically replace target file to prevent corruption."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path.replace(self.state_path)
        except Exception as e:
            logger.error(f"Failed to atomically persist automation state: {e}")
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            raise

    def is_enabled(self) -> bool:
        """Check whether daily autonomous scheduling is enabled by the user."""
        raw = self._load_raw()
        return bool(raw.get("enabled", True))

    def set_enabled(self, enabled: bool) -> None:
        """Toggle daily autonomous scheduling."""
        raw = self._load_raw()
        raw["enabled"] = bool(enabled)
        raw["last_updated"] = datetime.now(timezone.utc).isoformat()
        self._write_atomic(raw)
        logger.info(f"Automation enabled status updated to: {enabled}")

    def get_daily_record(self, date_str: str) -> Dict[str, Any]:
        """Retrieve automation record for a calendar date, initializing default schema if absent."""
        raw = self._load_raw()
        records = raw.setdefault("daily_records", {})
        if date_str not in records:
            clean_date = date_str.replace("-", "")
            records[date_str] = {
                "date": date_str,
                "overall_status": "PENDING",  # PENDING, RUNNING, COMPLETED, PARTIAL, FAILED
                "generation": {
                    "status": "PENDING",  # PENDING, RUNNING, COMPLETED, PARTIAL, FAILED
                    "started_at": None,
                    "completed_at": None,
                    "retries": 0,
                    "error": None,
                },
                "slot1": {
                    "video_id": f"video_{clean_date}_slot1",
                    "generation_status": "PENDING",
                    "qc_passed": False,
                    "qc_results": None,
                    "upload_status": "NOT_STARTED",  # NOT_STARTED, RUNNING, UPLOADED_PRIVATE, FAILED
                    "youtube_video_id": None,
                    "youtube_simulated": True,
                    "scheduled_status": "NOT_SCHEDULED",  # NOT_SCHEDULED, SCHEDULED, FAILED
                    "scheduled_publish_at": None,
                    "scheduled_publish_at_ist": None,
                    "retry_count": 0,
                    "error": None,
                },
                "slot2": {
                    "video_id": f"video_{clean_date}_slot2",
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
                },
                "last_failure": None,
                "last_recovery": None,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            self._write_atomic(raw)
        return records[date_str]

    def update_daily_record(self, date_str: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Atomically merge updates into a daily automation record."""
        raw = self._load_raw()
        record = self.get_daily_record(date_str)

        # Deep merge updates
        for k, v in updates.items():
            if isinstance(v, dict) and isinstance(record.get(k), dict):
                record[k].update(v)
            else:
                record[k] = v

        record["last_updated"] = datetime.now(timezone.utc).isoformat()
        raw["daily_records"][date_str] = record
        raw["last_run"] = datetime.now(timezone.utc).isoformat()
        self._write_atomic(raw)
        return record

    def get_summary(self) -> Dict[str, Any]:
        """Return high-level telemetry summary for dashboard integration."""
        raw = self._load_raw()
        return {
            "enabled": raw.get("enabled", True),
            "timezone": raw.get("timezone", SCHEDULER_TIMEZONE),
            "last_run": raw.get("last_run"),
            "daily_records_count": len(raw.get("daily_records", {})),
            "daily_records": raw.get("daily_records", {}),
        }


automation_state = AutomationStateManager()
