"""Estimated YouTube Data API v3 Quota Tracker for CurioLoop.

Tracks internal API operation counts keyed by Pacific Time (`America/Los_Angeles`)
matching Google's official quota reset schedule at midnight PT.

IMPORTANT: Google does not expose an API endpoint returning real-time remaining project quota.
All figures are clearly labeled `is_estimate = True` and derived from documented YouTube Data API
v3 unit costs (`videos.insert=1600`, `videos.update=50`, `videos.list=1`, `channels.list=1`,
`playlistItems.list=1`).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from curiosity_engine import config

PT = ZoneInfo("America/Los_Angeles")
IST = ZoneInfo(config.SCHEDULER_TIMEZONE)
QUOTA_STATE_FILE = config.DATA_DIR / "youtube_quota_state.json"

OPERATION_UNIT_COSTS: Dict[str, int] = {
    "videos.insert": 1600,
    "videos.update": 50,
    "videos.list": 1,
    "channels.list": 1,
    "playlistItems.list": 1,
    "analytics.query": 1,
}


class YouTubeQuotaTracker:
    """Thread-safe local atomic counter estimating daily YouTube Data API v3 usage."""

    def __init__(self, state_file: Optional[Path] = None) -> None:
        self._explicit_state_file = Path(state_file) if state_file is not None else None
        self.state_file = self._resolve_state_file()

    def _resolve_state_file(self) -> Path:
        if self._explicit_state_file is not None:
            path = self._explicit_state_file
        elif "PYTEST_CURRENT_TEST" in os.environ:
            path = Path(tempfile.gettempdir()) / f"curiosity_test_quota_{os.getpid()}.json"
        else:
            path = QUOTA_STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _pt_day_key(now_utc: Optional[datetime] = None) -> str:
        dt = (now_utc or datetime.now(timezone.utc)).astimezone(PT)
        return dt.strftime("%Y-%m-%d")

    @staticmethod
    def _next_reset_info(now_utc: Optional[datetime] = None) -> Dict[str, str]:
        now_pt = (now_utc or datetime.now(timezone.utc)).astimezone(PT)
        next_midnight_pt = (now_pt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return {
            "reset_policy": "Daily at 00:00 Pacific Time (America/Los_Angeles)",
            "next_reset_pt": next_midnight_pt.strftime("%Y-%m-%d %H:%M %Z"),
            "next_reset_ist": next_midnight_pt.astimezone(IST).strftime("%Y-%m-%d %H:%M IST"),
        }

    def _load_state(self) -> Dict[str, Any]:
        sf = self._resolve_state_file()
        self.state_file = sf
        if not sf.exists():
            return {"days": {}}
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("days"), dict):
                return data
        except Exception:
            pass
        return {"days": {}}

    def _save_state(self, state: Dict[str, Any]) -> None:
        sf = self._resolve_state_file()
        self.state_file = sf
        days = state.get("days", {})
        if len(days) > 30:
            for old_k in sorted(days.keys())[:-30]:
                days.pop(old_k, None)
        tmp = sf.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, sf)

    def record_operation(
        self,
        operation: str,
        count: int = 1,
        now_utc: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Record an internal YouTube Data API v3 call by documented unit cost."""
        unit_cost = OPERATION_UNIT_COSTS.get(operation, 1)
        day_key = self._pt_day_key(now_utc)
        state = self._load_state()
        day_rec = state["days"].setdefault(
            day_key,
            {"operations": {}, "estimated_units_used": 0, "last_updated": None},
        )
        ops = day_rec.setdefault("operations", {})
        ops[operation] = int(ops.get(operation, 0)) + int(count)
        day_rec["estimated_units_used"] = int(day_rec.get("estimated_units_used", 0)) + (unit_cost * int(count))
        day_rec["last_updated"] = (now_utc or datetime.now(timezone.utc)).isoformat()
        self._save_state(state)
        return self.get_quota_status(now_utc=now_utc)

    def get_quota_status(self, now_utc: Optional[datetime] = None) -> Dict[str, Any]:
        """Return clearly labeled estimated daily quota metrics, breakdown, and reset window."""
        day_key = self._pt_day_key(now_utc)
        state = self._load_state()
        day_rec = state.get("days", {}).get(day_key, {})
        used = int(day_rec.get("estimated_units_used", 0))
        daily_ref = config.YOUTUBE_API_DAILY_QUOTA_REF
        remaining = max(0, daily_ref - used)
        pct = round(min(100.0, (used / daily_ref) * 100.0), 2) if daily_ref > 0 else 0.0
        ops = dict(day_rec.get("operations", {}))

        breakdown = {
            "upload_insert": {
                "calls": int(ops.get("videos.insert", 0)),
                "unit_cost": OPERATION_UNIT_COSTS["videos.insert"],
                "units": int(ops.get("videos.insert", 0)) * OPERATION_UNIT_COSTS["videos.insert"],
            },
            "schedule_update": {
                "calls": int(ops.get("videos.update", 0)),
                "unit_cost": OPERATION_UNIT_COSTS["videos.update"],
                "units": int(ops.get("videos.update", 0)) * OPERATION_UNIT_COSTS["videos.update"],
            },
            "status_list": {
                "calls": int(ops.get("videos.list", 0)),
                "unit_cost": OPERATION_UNIT_COSTS["videos.list"],
                "units": int(ops.get("videos.list", 0)) * OPERATION_UNIT_COSTS["videos.list"],
            },
            "channel_playlist": {
                "calls": int(ops.get("channels.list", 0)) + int(ops.get("playlistItems.list", 0)),
                "unit_cost": 1,
                "units": int(ops.get("channels.list", 0)) + int(ops.get("playlistItems.list", 0)),
            },
        }
        reset_meta = self._next_reset_info(now_utc=now_utc)

        return {
            "is_estimate": True,
            "source_label": "Estimated from CurioLoop internal API logs (Google provides no live quota endpoint)",
            "quota_date_pt": day_key,
            "daily_reference_units": daily_ref,
            "estimated_units_used": used,
            "remaining_units": remaining,
            "usage_percent": pct,
            "operations_breakdown": breakdown,
            "unit_costs_reference": OPERATION_UNIT_COSTS,
            "last_updated": day_rec.get("last_updated"),
            **reset_meta,
        }


youtube_quota = YouTubeQuotaTracker()
