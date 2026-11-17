"""Curiosity Engine - Local Persistent Database Client.
Stores video production records, publishing status, topic history,
and execution logs in a durable local JSON store.

Strict ₹0 / Local-First: Zero cloud deployment, zero ADC warnings.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from curiosity_engine.config import DATA_DIR

logger = logging.getLogger("curiosity_engine.db")

_TOPIC_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "from", "with", "and", "or",
    "why", "how", "what", "when", "who", "did", "your", "you", "this", "that", "into",
    "city", "story", "stories", "real", "secret", "inside", "shorts", "could", "would",
}


def normalize_topic_tokens(topic: str) -> Set[str]:
    """Extract normalized stem-like keyword tokens from a topic for near-duplicate detection."""
    tokens = set()
    for raw in re.findall(r"[a-z0-9]+", str(topic or "").lower()):
        if raw in _TOPIC_STOPWORDS or len(raw) < 3:
            continue
        stem = raw.rstrip("s") if len(raw) > 4 else raw
        tokens.add(stem)
    return tokens


def compute_topic_similarity(topic_a: str, topic_b: str) -> float:
    """Return Jaccard/overlap similarity in [0, 1] between two topic strings."""
    ta = normalize_topic_tokens(topic_a)
    tb = normalize_topic_tokens(topic_b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    if inter == 0:
        return 0.0
    union = len(ta | tb)
    containment = inter / min(len(ta), len(tb))
    return max(inter / union, containment * 0.85)


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

    def record_topic(
        self,
        topic: str,
        category: str,
        date_str: str,
        fallback_id: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        script_hash: Optional[str] = None,
    ) -> None:
        """Record used topic, category, date, and optional fallback ID to prevent duplicates within 90 days."""
        self._load_local_data()
        rec = {
            "topic": topic,
            "category": category,
            "used_date": date_str,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "fallback_id": fallback_id,
            "aliases": aliases or [],
            "script_hash": script_hash,
        }
        self._local_data.setdefault("topics", {})
        self._local_data["topics"][topic] = rec
        if fallback_id:
            self._local_data.setdefault("used_fallback_ids", {})
            self._local_data["used_fallback_ids"][fallback_id] = {
                "used_date": date_str,
                "topic": topic,
            }
        self._save_local_data()

    def record_fallback_used(self, fallback_id: str, date_str: str, topic: str = "") -> None:
        """Mark a curated fallback story ID as consumed to prevent repetitive selection."""
        if not fallback_id:
            return
        self._load_local_data()
        self._local_data.setdefault("used_fallback_ids", {})
        self._local_data["used_fallback_ids"][fallback_id] = {
            "used_date": date_str,
            "topic": topic,
        }
        self._save_local_data()

    def get_used_fallback_ids(self) -> Set[str]:
        """Return set of all curated fallback IDs consumed across past runs and videos."""
        self._load_local_data()
        used = set(self._local_data.get("used_fallback_ids", {}).keys())
        for v in self._local_data.get("videos", {}).values():
            if isinstance(v, dict):
                fid = v.get("fallback_id") or (v.get("script") or {}).get("id")
                if fid:
                    used.add(str(fid))
        for t in self._local_data.get("topics", {}).values():
            if isinstance(t, dict) and t.get("fallback_id"):
                used.add(str(t["fallback_id"]))
        return used

    def is_fallback_used(self, fallback_id: str) -> bool:
        """Check if a curated fallback ID has already been published/used."""
        if not fallback_id:
            return False
        return fallback_id in self.get_used_fallback_ids()

    def is_topic_recent(
        self,
        topic: str,
        days_threshold: int = 90,
        similarity_threshold: float = 0.45,
    ) -> bool:
        """Check if topic was already produced or closely matches a past topic within cooldown window."""
        self._load_local_data()
        if not topic:
            return False

        now = datetime.now(timezone.utc)
        topic_clean = str(topic).strip()

        # 1. Exact key match in topics
        rec = self._local_data.get("topics", {}).get(topic_clean)
        if rec and "used_date" in rec:
            try:
                dt = datetime.strptime(rec["used_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if (now - dt).days < days_threshold:
                    return True
            except Exception:
                pass

        # 2. Check used fallback IDs
        if topic_clean in self.get_used_fallback_ids():
            return True

        # 3. Near-duplicate and alias scan against all past topics and videos
        all_past_topics: List[Tuple[str, str]] = []  # (topic_str, date_str)
        for t_name, t_rec in self._local_data.get("topics", {}).items():
            u_date = t_rec.get("used_date") or t_rec.get("created_at", "")[:10]
            all_past_topics.append((t_name, u_date))
            for alias in t_rec.get("aliases", []):
                all_past_topics.append((alias, u_date))

        for v_rec in self._local_data.get("videos", {}).values():
            if isinstance(v_rec, dict) and v_rec.get("topic"):
                v_date = v_rec.get("target_date") or v_rec.get("created_at", "")[:10]
                all_past_topics.append((str(v_rec["topic"]), v_date))

        for prev_topic, prev_date in all_past_topics:
            if not prev_topic:
                continue
            is_recent_date = True
            if prev_date:
                try:
                    p_dt = datetime.strptime(prev_date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    is_recent_date = (now - p_dt).days < days_threshold
                except Exception:
                    pass
            if not is_recent_date:
                continue

            if prev_topic.strip().lower() == topic_clean.lower():
                return True

            sim = compute_topic_similarity(topic_clean, prev_topic)
            if sim >= similarity_threshold:
                return True

        return False

    def is_topic_novel(
        self,
        topic: str,
        days_threshold: int = 90,
        similarity_threshold: float = 0.45,
    ) -> Tuple[bool, Optional[str]]:
        """Return (True, None) if topic is genuinely novel, or (False, reason) if it matches recent content."""
        if self.is_topic_recent(topic, days_threshold=days_threshold, similarity_threshold=similarity_threshold):
            return False, f"Matches or closely overlaps a topic produced within {days_threshold} days"
        return True, None

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
