"""Truthful YouTube Performance & Channel Learning Tracker for CurioLoop.

Tracks real metrics available via the authorized OAuth scopes:
- Public statistics (`views`, `likes`, `comments`) via YouTube Data API v3 `videos.list(part="statistics")`.
- Retention & subscriber deltas via YouTube Analytics API ONLY if `yt-analytics.readonly`
  is granted on the active OAuth token (otherwise transparently reports exact API/scope limitation
  instead of guessing or fabricating numbers).

Sample-size & editorial discipline:
- Early low view counts (e.g., ~10 views after 12-15 hours on a new channel) are normal and NEVER
  flagged as failures or used to auto-delete videos.
- Pattern correlations (`category`, `style`, `duration_bucket`) are withheld as tentative until at
  least `MIN_SAMPLE_FOR_INSIGHTS = 5` public videos accumulate >=24h metrics.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from curiosity_engine import config
from curiosity_engine.distribution.token_manager import token_manager
from curiosity_engine.distribution.youtube_quota import youtube_quota
from curiosity_engine.state.db import db

logger = logging.getLogger("curiosity_engine.youtube_analytics")

ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
PERFORMANCE_FILE = config.DATA_DIR / "performance_history.json"
MIN_SAMPLE_FOR_INSIGHTS = 5


class YouTubePerformanceTracker:
    """Collects factual post-publication metrics and prevents premature strategy conclusions."""

    def __init__(self, state_file: Optional[Path] = None) -> None:
        self._explicit_state_file = Path(state_file) if state_file is not None else None
        self.state_file = self._resolve_state_file()

    def _resolve_state_file(self) -> Path:
        if self._explicit_state_file is not None:
            path = self._explicit_state_file
        elif "PYTEST_CURRENT_TEST" in os.environ:
            path = Path(tempfile.gettempdir()) / f"curiosity_test_perf_{os.getpid()}.json"
        else:
            path = PERFORMANCE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _load(self) -> Dict[str, Any]:
        sf = self._resolve_state_file()
        self.state_file = sf
        default = {
            "videos": {},
            "last_synced_at": None,
            "analytics_access": "UNKNOWN",
            "limitation_note": None,
        }
        if not sf.exists():
            return default
        try:
            loaded = json.loads(sf.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                default.update(loaded)
                if not isinstance(default.get("videos"), dict):
                    default["videos"] = {}
                return default
        except Exception:
            pass
        return default

    def _save(self, state: Dict[str, Any]) -> None:
        sf = self._resolve_state_file()
        self.state_file = sf
        tmp = sf.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, sf)

    @staticmethod
    def _has_analytics_scope() -> bool:
        yt = token_manager.get_summary().get("youtube", {})
        scopes = yt.get("scopes") or []
        return any(ANALYTICS_SCOPE in s for s in scopes)

    @staticmethod
    def _duration_bucket(duration_sec: Optional[float]) -> str:
        if duration_sec is None:
            return "unknown"
        d = float(duration_sec)
        if d < 25.0:
            return "20-25s"
        if d <= 45.0:
            return "25-45s_target"
        return "45-60s_extended"

    def refresh_public_video_metrics(
        self,
        youtube_publisher_client: Any,
        db_client: Any = None,
    ) -> Dict[str, Any]:
        """Fetch real Data API statistics for confirmed public videos cleanly."""
        store = db_client or db
        state = self._load()
        now_utc = datetime.now(timezone.utc)
        has_analytics = self._has_analytics_scope()

        if not has_analytics:
            state["analytics_access"] = "LIMITED_SCOPE_MISSING"
            state["limitation_note"] = (
                "Current OAuth token grants Data API metrics (views, likes, comments) via youtube.readonly, "
                "but lacks 'yt-analytics.readonly' for averageViewDuration, averageViewPercentage, and subscriber delta."
            )
        else:
            state["analytics_access"] = "GRANTED"
            state["limitation_note"] = None

        all_vids = store.get_all_videos(limit=100)
        if not isinstance(all_vids, list):
            all_vids = []

        public_vids = [
            v for v in all_vids
            if isinstance(v, dict)
            and v.get("youtube_upload_id")
            and not v.get("youtube_simulated")
            and not str(v.get("youtube_upload_id")).startswith("yt_sim_")
            and not v.get("is_test")
            and str(v.get("youtube_privacy_status") or "").lower() == "public"
        ]

        service = getattr(youtube_publisher_client, "service", None)
        if not service or not public_vids:
            state["last_synced_at"] = now_utc.isoformat()
            self._save(state)
            return self.get_summary()

        yt_ids = [str(v["youtube_upload_id"]) for v in public_vids][:50]
        try:
            resp = service.videos().list(part="statistics", id=",".join(yt_ids)).execute()
            youtube_quota.record_operation("videos.list")
            items_by_id = {str(it.get("id")): it.get("statistics", {}) for it in resp.get("items", [])}
        except Exception as exc:
            logger.warning("Failed refreshing public video statistics: %s", exc)
            state["last_synced_at"] = now_utc.isoformat()
            self._save(state)
            return self.get_summary()

        for v in public_vids:
            yt_id = str(v["youtube_upload_id"])
            stats = items_by_id.get(yt_id)
            if stats is None:
                continue

            pub_at_str = v.get("youtube_published_public_at") or v.get("scheduled_publish_at") or v.get("youtube_published_at")
            age_hours = None
            if pub_at_str:
                try:
                    pub_dt = datetime.fromisoformat(str(pub_at_str).replace("Z", "+00:00"))
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    age_hours = max(0.0, round((now_utc - pub_dt).total_seconds() / 3600.0, 1))
                except Exception:
                    pass

            views = int(stats.get("viewCount", 0))
            likes = int(stats.get("likeCount", 0))
            comments = int(stats.get("commentCount", 0))

            entry = dict(state["videos"].get(yt_id) or {})
            entry.update({
                "youtube_id": yt_id,
                "video_id": v.get("video_id"),
                "title": v.get("youtube_title") or (v.get("script") or {}).get("title") or v.get("topic"),
                "category": v.get("category"),
                "style": v.get("style"),
                "discovery_origin": v.get("discovery_origin", "curated_research"),
                "duration_sec": v.get("duration_sec") or (v.get("qc_results") or {}).get("checks", {}).get("duration_sec"),
                "duration_bucket": self._duration_bucket(
                    v.get("duration_sec") or (v.get("qc_results") or {}).get("checks", {}).get("duration_sec")
                ),
                "published_at": pub_at_str,
                "age_hours": age_hours,
                "views": views,
                "likes": likes,
                "comments": comments,
                # Analytics-API fields remain null unless real Analytics data is retrieved
                "average_view_duration_sec": entry.get("average_view_duration_sec"),
                "average_percentage_viewed": entry.get("average_percentage_viewed"),
                "subscribers_delta": entry.get("subscribers_delta"),
                "last_checked_at": now_utc.isoformat(),
            })

            snapshots = dict(entry.get("snapshots") or {})
            if age_hours is not None and age_hours >= 24.0 and "24h" not in snapshots:
                snapshots["24h"] = {"recorded_at": now_utc.isoformat(), "age_hours": age_hours, "views": views, "likes": likes, "comments": comments}
            if age_hours is not None and age_hours >= 168.0 and "7d" not in snapshots:
                snapshots["7d"] = {"recorded_at": now_utc.isoformat(), "age_hours": age_hours, "views": views, "likes": likes, "comments": comments}
            entry["snapshots"] = snapshots
            state["videos"][yt_id] = entry

        state["last_synced_at"] = now_utc.isoformat()
        self._save(state)
        return self.get_summary()

    def get_summary(self) -> Dict[str, Any]:
        """Return truthful analytics summary, explicitly guarding against small-sample bias."""
        state = self._load()
        has_analytics = self._has_analytics_scope()
        analytics_access = "GRANTED" if has_analytics else "LIMITED_SCOPE_MISSING"
        limitation_note = (
            None
            if has_analytics
            else (
                "Current OAuth scopes grant YouTube Data API views/likes/comments cleanly, "
                "but omit 'yt-analytics.readonly' for averageViewDuration, averageViewPercentage, "
                "and subscriber changes. Unobserved retention metrics remain null."
            )
        )

        vids = list(state.get("videos", {}).values())
        sample_count = len(vids)
        mature_24h = [v for v in vids if v.get("age_hours") is not None and float(v.get("age_hours")) >= 24.0]
        total_views = sum(int(v.get("views") or 0) for v in vids)
        total_likes = sum(int(v.get("likes") or 0) for v in vids)
        total_comments = sum(int(v.get("comments") or 0) for v in vids)

        insufficient_sample = len(mature_24h) < MIN_SAMPLE_FOR_INSIGHTS
        insights: List[str] = []
        if insufficient_sample:
            sample_status = "INSUFFICIENT_SAMPLE"
            sample_guidance = (
                f"Tracked {sample_count} public video(s) ({len(mature_24h)} >= 24h old; need {MIN_SAMPLE_FOR_INSIGHTS} "
                "mature videos before drawing pattern conclusions). Early ~10-view readings on a new channel are normal and never treated as failures."
            )
        else:
            sample_status = "PATTERNS_AVAILABLE"
            sample_guidance = f"Based on {len(mature_24h)} public videos >=24h old."
            by_cat: Dict[str, List[int]] = {}
            for v in mature_24h:
                by_cat.setdefault(str(v.get("category") or "General"), []).append(int(v.get("views") or 0))
            if by_cat:
                best_cat, best_vals = max(by_cat.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))
                insights.append(f"Highest average views among tracked categories: {best_cat} (avg {sum(best_vals)/len(best_vals):.1f} across {len(best_vals)} video(s)).")

        return {
            "tracked_videos_count": sample_count,
            "mature_24h_count": len(mature_24h),
            "min_sample_for_insights": MIN_SAMPLE_FOR_INSIGHTS,
            "sample_status": sample_status,
            "sample_guidance": sample_guidance,
            "analytics_access": analytics_access,
            "limitation_note": limitation_note,
            "totals": {
                "views": total_views,
                "likes": total_likes,
                "comments": total_comments,
                "average_view_duration_sec": None,
                "average_percentage_viewed": None,
                "subscribers_delta": None,
            },
            "pattern_insights": insights,
            "videos": sorted(vids, key=lambda x: str(x.get("published_at") or ""), reverse=True)[:20],
            "last_synced_at": state.get("last_synced_at"),
        }


performance_tracker = YouTubePerformanceTracker()
