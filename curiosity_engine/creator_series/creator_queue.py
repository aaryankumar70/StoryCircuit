"""Durable, due-time Creator production queue, isolated from Automatic Studio."""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from curiosity_engine.config import DATA_DIR
from curiosity_engine.creator_series.models import EpisodeStatus, RightsStatus, SeriesStatus
from curiosity_engine.creator_series.series_db import SeriesDatabase, series_db
from curiosity_engine.state.file_lock import interprocess_file_lock

logger = logging.getLogger("curiosity_engine.creator_queue")
CREATOR_QUEUE_FILE = DATA_DIR / "creator_series_queue.json"
MAX_JOB_ATTEMPTS = 5
RUNNING_LEASE = timedelta(minutes=90)
PRODUCTION_LEAD = timedelta(minutes=int(os.environ.get("CREATOR_PRODUCTION_LEAD_MINUTES", "60")))


def _parse_aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Creator schedule timestamps must include a timezone.")
    return parsed.astimezone(timezone.utc)


class CreatorProductionQueue:
    """A separate persisted queue for approved Creator episodes."""

    def __init__(self, state_file: Optional[Path] = None, s_db: Optional[SeriesDatabase] = None):
        self.state_file = Path(state_file or CREATOR_QUEUE_FILE)
        self._s_db = s_db or series_db
        self._thread_lock = threading.RLock()

    def _load(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {"version": 1, "jobs": {}}
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Creator queue state is unreadable; refusing to start empty: {exc}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("jobs", {}), dict):
            raise RuntimeError("Creator queue state has an invalid schema; refusing to start empty.")
        raw.setdefault("jobs", {})
        return raw

    def _save(self, state: Dict[str, Any]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_name(f".{self.state_file.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(state, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            tmp.replace(self.state_file)
        finally:
            tmp.unlink(missing_ok=True)

    def _transaction(self):
        class _Transaction:
            def __init__(inner, owner):
                inner.owner = owner
                inner.lock = None
                inner.state = None
                inner.original = None

            def __enter__(inner):
                inner.owner._thread_lock.acquire()
                try:
                    inner.lock = interprocess_file_lock(inner.owner.state_file.with_suffix(".json.lock"))
                    inner.lock.__enter__()
                    inner.state = inner.owner._load()
                    inner.original = json.dumps(inner.state, sort_keys=True, separators=(",", ":"))
                    return inner.state
                except Exception:
                    if inner.lock is not None:
                        inner.lock.__exit__(*__import__("sys").exc_info())
                    inner.owner._thread_lock.release()
                    raise

            def __exit__(inner, exc_type, exc, tb):
                try:
                    if exc_type is None and json.dumps(inner.state, sort_keys=True, separators=(",", ":")) != inner.original:
                        inner.owner._save(inner.state)
                finally:
                    inner.lock.__exit__(exc_type, exc, tb)
                    inner.owner._thread_lock.release()
                return False
        return _Transaction(self)

    def enqueue_series(self, series_id: str, episodes: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        series = self._s_db.get_series(series_id)
        if not series:
            raise ValueError(f"Series '{series_id}' not found.")
        episodes = episodes if episodes is not None else self._s_db.get_episodes_for_series(series_id)
        created: List[Dict[str, Any]] = []
        with self._transaction() as state:
            jobs = state["jobs"]
            for episode in episodes:
                if episode.status in (EpisodeStatus.PUBLISHED, EpisodeStatus.CANCELLED):
                    continue
                if not episode.is_approved:
                    raise ValueError(f"Episode {episode.episode_num} must be approved before scheduling.")
                if not episode.scheduled_publication_time:
                    raise ValueError(f"Episode {episode.episode_num} has no committed publication time.")
                scheduled_at = _parse_aware(episode.scheduled_publication_time).isoformat()
                job_id = f"creator_{episode.episode_id}"
                job = jobs.get(job_id)
                if job and job.get("status") in ("RUNNING", "COMPLETED"):
                    continue
                if job and job.get("status") == "BLOCKED_RIGHTS" and series.rights_status not in (
                    RightsStatus.OWNED, RightsStatus.LICENSED, RightsStatus.PUBLIC_DOMAIN
                ):
                    continue
                item = {
                    "job_id": job_id,
                    "job_type": "CREATOR_SERIES",
                    "series_id": series_id,
                    "episode_id": episode.episode_id,
                    "episode_num": episode.episode_num,
                    "scheduled_at": scheduled_at,
                    "not_before": ( _parse_aware(scheduled_at) - PRODUCTION_LEAD ).isoformat(),
                    "status": "QUEUED",
                    "attempts": 0,
                    "max_attempts": MAX_JOB_ATTEMPTS,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "last_error": None,
                    "cancel_requested": False,
                }
                jobs[job_id] = item
                created.append(dict(item))
        return created

    def claim_next_due(self, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        active_series = {s.series_id for s in self._s_db.get_all_series() if s.status == SeriesStatus.ACTIVE}
        with self._transaction() as state:
            jobs = state["jobs"]
            for job in jobs.values():
                if job.get("status") == "RUNNING":
                    try:
                        stale = now_utc - _parse_aware(job.get("started_at", "")) >= RUNNING_LEASE
                    except Exception:
                        stale = True
                    if stale:
                        job["status"] = "RETRY_WAIT" if job.get("attempts", 0) < job.get("max_attempts", MAX_JOB_ATTEMPTS) else "FAILED"
                        job["next_attempt_at"] = now_utc.isoformat()
                        job["last_error"] = "Recovered expired running job lease."
            due = []
            for job in jobs.values():
                if job.get("status") not in ("QUEUED", "RETRY_WAIT") or job.get("series_id") not in active_series:
                    continue
                due_at = job.get("next_attempt_at") if job.get("status") == "RETRY_WAIT" else job.get("not_before")
                try:
                    if _parse_aware(due_at) <= now_utc:
                        due.append(job)
                except Exception:
                    job["status"] = "FAILED"
                    job["last_error"] = "Invalid or missing timezone-aware due time."
            if not due:
                return None
            due.sort(key=lambda item: (_parse_aware(item["scheduled_at"]), item.get("episode_num", 999)))
            job = due[0]
            if job.get("cancel_requested"):
                job["status"] = "CANCELLED"
                return None
            job["status"] = "RUNNING"
            job["started_at"] = now_utc.isoformat()
            job["attempts"] = int(job.get("attempts", 0)) + 1
            return dict(job)

    def mark_completed(self, job_id: str, result: Optional[Dict[str, Any]] = None) -> None:
        with self._transaction() as state:
            job = state["jobs"].get(job_id)
            if not job:
                raise KeyError(job_id)
            job.update(status="COMPLETED", completed_at=datetime.now(timezone.utc).isoformat(), result=result or {})

    def mark_rights_hold(self, job_id: str, reason: str) -> None:
        with self._transaction() as state:
            job = state["jobs"].get(job_id)
            if job:
                job.update(status="BLOCKED_RIGHTS", last_error=reason, blocked_at=datetime.now(timezone.utc).isoformat())

    def mark_failed(self, job_id: str, reason: str, retry: bool = True) -> None:
        with self._transaction() as state:
            job = state["jobs"].get(job_id)
            if not job:
                return
            attempts = int(job.get("attempts", 1))
            if retry and attempts < int(job.get("max_attempts", MAX_JOB_ATTEMPTS)) and not job.get("cancel_requested"):
                delay = min(60, 2 ** max(0, attempts - 1))
                job.update(status="RETRY_WAIT", next_attempt_at=(datetime.now(timezone.utc) + timedelta(minutes=delay)).isoformat())
            else:
                job.update(status="CANCELLED" if job.get("cancel_requested") else "FAILED", completed_at=datetime.now(timezone.utc).isoformat())
            job["last_error"] = str(reason)

    def cancel_series(self, series_id: str) -> Dict[str, int]:
        counts = {"cancelled": 0, "running": 0}
        with self._transaction() as state:
            for job in state["jobs"].values():
                if job.get("series_id") != series_id:
                    continue
                if job.get("status") in ("QUEUED", "RETRY_WAIT"):
                    job["status"] = "CANCELLED"
                    counts["cancelled"] += 1
                elif job.get("status") == "RUNNING":
                    if not job.get("publish_started"):
                        job["cancel_requested"] = True
                    counts["running"] += 1
        return counts

    def set_series_paused(self, series_id: str, paused: bool) -> int:
        changed = 0
        with self._transaction() as state:
            for job in state["jobs"].values():
                if job.get("series_id") != series_id:
                    continue
                if paused and job.get("status") in ("QUEUED", "RETRY_WAIT"):
                    job["status"] = "PAUSED"
                    changed += 1
                elif paused and job.get("status") == "RUNNING" and not job.get("publish_started"):
                    job["pause_requested"] = True
                    changed += 1
                elif not paused and job.get("status") == "PAUSED":
                    job["status"] = "QUEUED"
                    job["pause_requested"] = False
                    changed += 1
                elif not paused and job.get("status") == "RUNNING" and job.get("pause_requested"):
                    job["pause_requested"] = False
                    changed += 1
        return changed

    def cancellation_requested(self, job_id: str) -> bool:
        with self._thread_lock, interprocess_file_lock(self.state_file.with_suffix(".json.lock")):
            job = self._load().get("jobs", {}).get(job_id, {})
            return bool(job.get("cancel_requested") or job.get("status") == "CANCELLED")

    def begin_publish(self, job_id: str) -> str:
        """Atomically establish the cancellation/pause boundary before publishing."""
        with self._transaction() as state:
            job = state.get("jobs", {}).get(job_id)
            if not job or job.get("status") != "RUNNING" or job.get("cancel_requested"):
                return "CANCELLED"
            if job.get("pause_requested"):
                job["status"] = "PAUSED"
                job["paused_at"] = datetime.now(timezone.utc).isoformat()
                return "PAUSED"
            job["publish_started"] = True
            job["publish_started_at"] = datetime.now(timezone.utc).isoformat()
            return "STARTED"

    def get_series_jobs(self, series_id: str) -> List[Dict[str, Any]]:
        with self._thread_lock, interprocess_file_lock(self.state_file.with_suffix(".json.lock")):
            jobs = self._load().get("jobs", {}).values()
            return sorted((dict(j) for j in jobs if j.get("series_id") == series_id), key=lambda j: j.get("episode_num", 999))


creator_queue_manager = CreatorProductionQueue()
