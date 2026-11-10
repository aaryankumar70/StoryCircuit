"""Curiosity Engine - Local Persistent Database Client.
Stores video production records, publishing status, topic history,
and execution logs in a durable local JSON store.

Strict ₹0 / Local-First: Zero cloud deployment, zero ADC warnings.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from curiosity_engine.config import DATA_DIR

logger = logging.getLogger("curiosity_engine.db")


class DatabaseClient:
    """Local JSON-backed persistent database interface for videos, topics, and logs."""

    def __init__(self, custom_file: Optional[Path] = None):
        self.local_file = custom_file or (DATA_DIR / "firestore_local.json")
        self._local_data: Dict[str, Dict[str, Any]] = {"videos": {}, "topics": {}, "logs": {}}
        self._last_mtime: float = 0.0
        self._load_local_data()

    def _load_local_data(self) -> None:
        """Load persistent records from local JSON store."""
        if self.local_file.exists():
            try:
                mtime = self.local_file.stat().st_mtime
                if mtime != self._last_mtime:
                    with open(self.local_file, "r", encoding="utf-8") as f:
                        self._local_data = json.load(f)
                    self._last_mtime = mtime
            except Exception as e:
                logger.error(f"Error loading local state from {self.local_file}: {e}")

    def _save_local_data(self) -> None:
        """Persist records atomically via temp file + replace."""
        try:
            self.local_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.local_file.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._local_data, f, indent=2, default=str)
            tmp_path.replace(self.local_file)
            self._last_mtime = self.local_file.stat().st_mtime
        except Exception as e:
            logger.error(f"Error saving local state to {self.local_file}: {e}")

    def save_video_record(self, video_id: str, data: Dict[str, Any]) -> None:
        """Create or update a video production & publishing record."""
        self._load_local_data()
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._local_data.setdefault("videos", {})
        self._local_data["videos"][video_id] = {
            **self._local_data["videos"].get(video_id, {}),
            **data,
        }
        self._save_local_data()

    def get_video_record(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve video record by ID (auto-reloading if modified on disk)."""
        self._load_local_data()
        return self._local_data.get("videos", {}).get(video_id)

    def get_todays_videos(self, date_str: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all video records for a given date (YYYY-MM-DD)."""
        self._load_local_data()
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        matched = [
            v for v in self._local_data.get("videos", {}).values()
            if v.get("target_date") == date_str
        ]
        return sorted(matched, key=lambda x: x.get("slot_index", 1))

    def get_all_videos(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch recent video records."""
        self._load_local_data()
        records = list(self._local_data.get("videos", {}).values())
        records.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return records[:limit]

    def record_topic(self, topic: str, category: str, date_str: str) -> None:
        """Record used topic to prevent duplicates within 90 days."""
        self._load_local_data()
        rec = {
            "topic": topic,
            "category": category,
            "used_date": date_str,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._local_data.setdefault("topics", {})
        self._local_data["topics"][topic] = rec
        self._save_local_data()

    def is_topic_recent(self, topic: str, days_threshold: int = 90) -> bool:
        """Check if topic was already produced within the cooldown window."""
        self._load_local_data()
        now = datetime.now(timezone.utc)
        rec = self._local_data.get("topics", {}).get(topic)
        if rec and "used_date" in rec:
            dt = datetime.strptime(rec["used_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return (now - dt).days < days_threshold
        return False

    def log_error(self, component: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Persist error log entry."""
        self._load_local_data()
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": component,
            "message": message,
            "context": context or {},
        }
        log_id = f"err_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
        self._local_data.setdefault("logs", {})
        self._local_data["logs"][log_id] = log_entry
        self._save_local_data()

    def get_recent_logs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieve recent error and operational logs."""
        self._load_local_data()
        logs = list(self._local_data.get("logs", {}).values())
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs[:limit]


# Global database instance
db = DatabaseClient()
