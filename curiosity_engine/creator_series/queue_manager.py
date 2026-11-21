"""Sequential Production Queue & Lifecycle Manager for CurioLoop Creator Series (Step 6).

Guarantees:
1. Production Lifecycle Statuses:
   - Planned
   - Script ready
   - Awaiting approval
   - In production
   - QC failed
   - Ready for publishing
   - Scheduled
   - Published
2. Lifecycle Controls:
   - Pause / Resume / Cancel controls for Creator Series.
3. CRITICAL Automatic Studio Preservation:
   - Automatic Studio's 2 daily autonomous videos (09:00 IST and 19:00 IST) must NEVER
     be disabled or displaced.
   - Sequential execution queue manages Creator Series and Automatic Studio jobs cleanly
     without database collisions or resource deadlocks.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from curiosity_engine.config import DATA_DIR
from curiosity_engine.creator_series.models import (
    EPISODE_STATUS_DISPLAY_MAP,
    EpisodeRecord,
    EpisodeStatus,
    SeriesRecord,
    SeriesStatus,
    normalize_episode_status,
)
from curiosity_engine.creator_series.series_db import SeriesDatabase, series_db

logger = logging.getLogger("curiosity_engine.queue_manager")

QUEUE_STATE_FILE = DATA_DIR / "production_queue.json"


class JobType(str, Enum):
    AUTOMATIC_STUDIO = "AUTOMATIC_STUDIO"
    CREATOR_SERIES = "CREATOR_SERIES"


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


@dataclass
class QueueJob:
    job_id: str
    job_type: JobType
    series_id: Optional[str] = None
    episode_id: Optional[str] = None
    episode_num: Optional[int] = None
    target_slot: Optional[str] = None
    target_date: Optional[str] = None
    scheduled_time: Optional[str] = None
    priority: int = 10  # Lower number = higher priority. Automatic Studio = 1, Creator Series = 10
    status: JobStatus = JobStatus.QUEUED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["job_type"] = self.job_type.value if isinstance(self.job_type, JobType) else str(self.job_type)
        d["status"] = self.status.value if isinstance(self.status, JobStatus) else str(self.status)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QueueJob":
        copied = dict(data)
        if "job_type" in copied and isinstance(copied["job_type"], str):
            copied["job_type"] = JobType(copied["job_type"])
        if "status" in copied and isinstance(copied["status"], str):
            copied["status"] = JobStatus(copied["status"])
        valid_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in copied.items() if k in valid_fields}
        return cls(**filtered)


class ProductionQueueManager:
    """Manages sequential execution and lifecycle control for Creator Series and Automatic Studio."""

    # Automatic Studio autonomous slots in IST (Preserved at all times)
    AUTOMATIC_STUDIO_SLOTS = ["09:00 IST", "19:00 IST"]

    def __init__(self, state_file: Optional[Path] = None, s_db: Optional[SeriesDatabase] = None):
        self.state_file = state_file or QUEUE_STATE_FILE
        self._custom_s_db = s_db
        self._lock = threading.RLock()
        self._execution_lock = threading.Lock()
        self._jobs: Dict[str, QueueJob] = {}
        self._load_state()

    def _get_s_db(self, s_db_override: Optional[SeriesDatabase] = None) -> SeriesDatabase:
        if s_db_override is not None:
            return s_db_override
        if self._custom_s_db is not None:
            return self._custom_s_db
        from curiosity_engine.creator_series.series_db import series_db
        return series_db

    @property
    def _s_db(self) -> SeriesDatabase:
        return self._get_s_db()

    # -------------------------------------------------------------------------
    # State Persistence (Atomic)
    # -------------------------------------------------------------------------
    def _load_state(self) -> None:
        with self._lock:
            if self.state_file.exists():
                try:
                    with open(self.state_file, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                        raw_jobs = raw.get("jobs", {})
                        self._jobs = {k: QueueJob.from_dict(v) for k, v in raw_jobs.items()}
                        return
                except Exception as e:
                    logger.warning(f"Failed to load production queue state ({e}); starting fresh.")
            self._jobs = {}

    def _save_state(self) -> None:
        with self._lock:
            try:
                self.state_file.parent.mkdir(parents=True, exist_ok=True)
                tmp_file = self.state_file.with_suffix(".tmp")
                data = {
                    "version": "1.0",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "automatic_studio_preserved": True,
                    "automatic_studio_slots": self.AUTOMATIC_STUDIO_SLOTS,
                    "jobs": {k: v.to_dict() for k, v in self._jobs.items()},
                }
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                tmp_file.replace(self.state_file)
            except Exception as e:
                logger.error(f"Failed to persist production queue state: {e}")

    # -------------------------------------------------------------------------
    # Automatic Studio Preservation
    # -------------------------------------------------------------------------
    def ensure_automatic_studio_reserved(self, target_date: str) -> None:
        """Guarantee Automatic Studio's 2 daily autonomous jobs exist with top priority."""
        with self._lock:
            clean_date = target_date.replace("-", "")
            slot1_job_id = f"auto_studio_{clean_date}_slot1"
            slot2_job_id = f"auto_studio_{clean_date}_slot2"

            if slot1_job_id not in self._jobs:
                self._jobs[slot1_job_id] = QueueJob(
                    job_id=slot1_job_id,
                    job_type=JobType.AUTOMATIC_STUDIO,
                    target_slot="09:00 IST",
                    target_date=target_date,
                    priority=1,  # Highest priority
                    status=JobStatus.QUEUED,
                )

            if slot2_job_id not in self._jobs:
                self._jobs[slot2_job_id] = QueueJob(
                    job_id=slot2_job_id,
                    job_type=JobType.AUTOMATIC_STUDIO,
                    target_slot="19:00 IST",
                    target_date=target_date,
                    priority=1,  # Highest priority
                    status=JobStatus.QUEUED,
                )

            self._save_state()
            logger.info(f"Verified Automatic Studio reservations for {target_date} (09:00 & 19:00 IST).")

    # -------------------------------------------------------------------------
    # Creator Series Queue Operations
    # -------------------------------------------------------------------------
    def enqueue_series(self, series_id: str, s_db: Optional[SeriesDatabase] = None) -> List[QueueJob]:
        """Enqueue uncompleted episodes of a series into the sequential queue."""
        db = self._get_s_db(s_db)
        with self._lock:
            series = db.get_series(series_id)
            if not series:
                raise ValueError(f"Series '{series_id}' not found.")

            episodes = db.get_episodes_for_series(series_id)
            enqueued_jobs = []

            for ep in episodes:
                if ep.status in (EpisodeStatus.PUBLISHED, EpisodeStatus.CANCELLED):
                    continue

                job_id = f"creator_{series_id}_{ep.episode_id}"
                if job_id not in self._jobs:
                    job = QueueJob(
                        job_id=job_id,
                        job_type=JobType.CREATOR_SERIES,
                        series_id=series_id,
                        episode_id=ep.episode_id,
                        episode_num=ep.episode_num,
                        scheduled_time=ep.scheduled_publication_time,
                        priority=10,  # Runs after Automatic Studio jobs
                        status=JobStatus.QUEUED,
                    )
                    self._jobs[job_id] = job
                    enqueued_jobs.append(job)

            self._save_state()
            logger.info(f"Enqueued {len(enqueued_jobs)} episodes for series '{series_id}'.")
            return enqueued_jobs

    def pause_series(self, series_id: str, s_db: Optional[SeriesDatabase] = None) -> Dict[str, Any]:
        """Pause series execution without disturbing Automatic Studio."""
        db = self._get_s_db(s_db)
        with self._lock:
            series = db.get_series(series_id)
            if not series:
                raise ValueError(f"Series '{series_id}' not found.")

            series.status = SeriesStatus.PAUSED
            db.save_series(series)

            paused_count = 0
            for job in self._jobs.values():
                if job.series_id == series_id and job.status == JobStatus.QUEUED:
                    job.status = JobStatus.PAUSED
                    paused_count += 1

            self._save_state()
            logger.info(f"Series '{series_id}' paused ({paused_count} queued jobs held).")
            return {
                "status": "success",
                "series_id": series_id,
                "series_status": SeriesStatus.PAUSED.value,
                "paused_jobs": paused_count,
            }

    def resume_series(self, series_id: str, s_db: Optional[SeriesDatabase] = None) -> Dict[str, Any]:
        """Resume execution of a paused series."""
        db = self._get_s_db(s_db)
        with self._lock:
            series = db.get_series(series_id)
            if not series:
                raise ValueError(f"Series '{series_id}' not found.")
            if series.status != SeriesStatus.PAUSED:
                raise ValueError(f"Series '{series_id}' is '{series.status.value}', not PAUSED.")

            series.status = SeriesStatus.ACTIVE
            db.save_series(series)

            resumed_count = 0
            for job in self._jobs.values():
                if job.series_id == series_id and job.status == JobStatus.PAUSED:
                    job.status = JobStatus.QUEUED
                    resumed_count += 1

            self._save_state()
            logger.info(f"Series '{series_id}' resumed ({resumed_count} jobs active).")
            return {
                "status": "success",
                "series_id": series_id,
                "series_status": SeriesStatus.ACTIVE.value,
                "resumed_jobs": resumed_count,
            }

    def cancel_series(self, series_id: str, s_db: Optional[SeriesDatabase] = None) -> Dict[str, Any]:
        """Cancel series execution and remove pending jobs from active queue."""
        db = self._get_s_db(s_db)
        with self._lock:
            series = db.get_series(series_id)
            if not series:
                raise ValueError(f"Series '{series_id}' not found.")

            series.status = SeriesStatus.CANCELLED
            db.save_series(series)

            cancelled_count = 0
            for job in self._jobs.values():
                if job.series_id == series_id and job.status in (JobStatus.QUEUED, JobStatus.PAUSED):
                    job.status = JobStatus.CANCELLED
                    cancelled_count += 1

            episodes = db.get_episodes_for_series(series_id)
            for ep in episodes:
                if ep.status not in (EpisodeStatus.PUBLISHED, EpisodeStatus.FAILED):
                    ep.status = EpisodeStatus.CANCELLED
                    db.save_episode(ep)

            self._save_state()
            logger.info(f"Series '{series_id}' cancelled ({cancelled_count} jobs cancelled).")
            return {
                "status": "success",
                "series_id": series_id,
                "series_status": SeriesStatus.CANCELLED.value,
                "cancelled_jobs": cancelled_count,
            }

    # -------------------------------------------------------------------------
    # Queue Status Inspection
    # -------------------------------------------------------------------------
    def get_series_queue_status(self, series_id: str, s_db: Optional[SeriesDatabase] = None) -> Dict[str, Any]:
        """Retrieve detailed production lifecycle statuses across all episodes."""
        db = self._get_s_db(s_db)
        with self._lock:
            series = db.get_series(series_id)
            if not series:
                raise ValueError(f"Series '{series_id}' not found.")

            episodes = db.get_episodes_for_series(series_id)
            ep_status_list = []
            completed = 0
            failed = 0
            pending = 0

            for ep in episodes:
                raw_enum = ep.status if isinstance(ep.status, EpisodeStatus) else normalize_episode_status(ep.status)
                lifecycle_label = EPISODE_STATUS_DISPLAY_MAP.get(raw_enum, raw_enum.value)

                if raw_enum == EpisodeStatus.PUBLISHED:
                    completed += 1
                elif raw_enum in (EpisodeStatus.QC_FAILED, EpisodeStatus.FAILED):
                    failed += 1
                elif raw_enum != EpisodeStatus.CANCELLED:
                    pending += 1

                ep_status_list.append({
                    "episode_id": ep.episode_id,
                    "episode_num": ep.episode_num,
                    "title": ep.title,
                    "status": lifecycle_label,
                    "raw_status": raw_enum.value,
                    "scheduled_publication_time": ep.scheduled_publication_time,
                    "actual_publication_time": ep.actual_publication_time,
                    "youtube_id": ep.youtube_id,
                    "duration": ep.actual_duration or ep.estimated_duration,
                    "is_approved": getattr(ep, "is_approved", False),
                    "approval_date": getattr(ep, "approval_date", None),
                    "qc_result": ep.qc_result,
                })

            return {
                "series_id": series.series_id,
                "series_title": series.title,
                "series_status": series.status.value,
                "automatic_studio_preserved": True,
                "automatic_studio_slots": self.AUTOMATIC_STUDIO_SLOTS,
                "publication_schedule": series.publication_schedule,
                "total_episodes": len(episodes),
                "completed_episodes": completed,
                "pending_episodes": pending,
                "failed_episodes": failed,
                "next_episode_num": series.next_episode_num,
                "episodes": ep_status_list,
            }

    # -------------------------------------------------------------------------
    # Sequential Execution & Concurrency Protection
    # -------------------------------------------------------------------------
    def get_next_job(self, s_db: Optional[SeriesDatabase] = None) -> Optional[QueueJob]:
        """Find the next eligible job, strictly prioritizing Automatic Studio."""
        db = self._get_s_db(s_db)
        with self._lock:
            # 1. Automatic Studio jobs first (priority 1)
            auto_jobs = [
                j for j in self._jobs.values()
                if j.job_type == JobType.AUTOMATIC_STUDIO and j.status == JobStatus.QUEUED
            ]
            if auto_jobs:
                auto_jobs.sort(key=lambda x: (x.priority, x.created_at))
                return auto_jobs[0]

            # 2. Creator Series jobs for ACTIVE series only
            creator_jobs = [
                j for j in self._jobs.values()
                if j.job_type == JobType.CREATOR_SERIES and j.status == JobStatus.QUEUED
            ]
            if creator_jobs:
                # filter to active series
                active_series_ids = {
                    s.series_id for s in db.get_all_series()
                    if s.status == SeriesStatus.ACTIVE
                }
                eligible = [j for j in creator_jobs if j.series_id in active_series_ids]
                if eligible:
                    eligible.sort(key=lambda x: (x.priority, x.episode_num or 999, x.created_at))
                    return eligible[0]

            return None

    def execute_job_locked(self, job_id: str, runner_fn) -> Any:
        """Execute a job sequentially with mutex locking to prevent resource deadlocks."""
        # Acquire global execution lock (prevents overlapping Chrome / Kokoro / Whisper renders)
        acquired = self._execution_lock.acquire(timeout=60.0)
        if not acquired:
            raise TimeoutError("Could not acquire sequential production lock; pipeline busy.")

        try:
            with self._lock:
                job = self._jobs.get(job_id)
                if not job:
                    raise ValueError(f"Job '{job_id}' not found.")
                job.status = JobStatus.RUNNING
                job.started_at = datetime.now(timezone.utc).isoformat()
                self._save_state()

            # Execute work outside state lock
            result = runner_fn(job)

            with self._lock:
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.now(timezone.utc).isoformat()
                self._save_state()

            return result

        except Exception as e:
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id].status = JobStatus.FAILED
                    self._jobs[job_id].error = str(e)
                    self._jobs[job_id].completed_at = datetime.now(timezone.utc).isoformat()
                    self._save_state()
            raise
        finally:
            self._execution_lock.release()


queue_manager = ProductionQueueManager()
