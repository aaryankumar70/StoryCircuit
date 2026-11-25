"""End-of-day garbage remover: cleans previous-day rendered media while preserving DB & anti-repeat history."""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from reelforge import config
from reelforge.storage.db import ReelDatabase

logger = logging.getLogger("reelforge.storage.cleanup")


def _dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return total


def _job_local_date(job: Dict[str, Any], tz: ZoneInfo) -> Optional[str]:
    if job.get("scheduled_date"):
        return str(job["scheduled_date"])[:10]
    created_raw = job.get("created_at")
    if not created_raw:
        return None
    try:
        dt = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz).strftime("%Y-%m-%d")
    except Exception:
        return None


def get_output_storage_stats() -> Dict[str, Any]:
    out_root = config.OUTPUT_DIR.resolve()
    total_bytes = _dir_size_bytes(out_root) if out_root.exists() else 0
    job_dirs = [p for p in out_root.iterdir() if p.is_dir()] if out_root.exists() else []
    return {
        "output_dir": str(out_root),
        "folder_count": len(job_dirs),
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / (1024 * 1024), 2),
    }


def cleanup_ended_day_videos(
    db: ReelDatabase,
    *,
    current_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Delete rendered video directories from ended days (`job_date < current_date`).

    Preserves SQLite job metadata and `topic_history` so anti-repeat never resets.
    Never removes active (`rendering` / `uploading`) jobs.
    """
    tz = ZoneInfo(config.SCHEDULER_TIMEZONE)
    today_str = current_date or datetime.now(tz).strftime("%Y-%m-%d")
    out_root = config.OUTPUT_DIR.resolve()

    deleted_jobs: List[str] = []
    freed_bytes = 0
    active_job_ids = set()

    for job in db.list_jobs(limit=500):
        jid = str(job["id"])
        status = str(job.get("status") or "")
        if status in {"rendering", "uploading"}:
            active_job_ids.add(jid)
            continue

        job_date = _job_local_date(job, tz)
        if not job_date or job_date >= today_str:
            continue

        removed_any = False
        job_dir = (out_root / jid).resolve()
        if job_dir.exists() and job_dir.is_dir() and job_dir.parent == out_root:
            freed_bytes += _dir_size_bytes(job_dir)
            shutil.rmtree(job_dir, ignore_errors=True)
            removed_any = True

        vpath_raw = job.get("video_path")
        if vpath_raw:
            vpath = Path(vpath_raw)
            if vpath.exists() and vpath.is_file():
                freed_bytes += _dir_size_bytes(vpath)
                try:
                    vpath.unlink()
                    removed_any = True
                except OSError:
                    pass

        if removed_any or vpath_raw or not job.get("cleaned_at"):
            db.mark_job_cleaned(jid)
            if removed_any:
                deleted_jobs.append(jid)

    # Also sweep orphan output directories from prior days not attached to active jobs
    orphan_dirs = 0
    if out_root.exists():
        for child in out_root.iterdir():
            if not child.is_dir() or child.name in active_job_ids:
                continue
            try:
                mtime_date = datetime.fromtimestamp(child.stat().st_mtime, tz=tz).strftime("%Y-%m-%d")
            except OSError:
                continue
            if mtime_date < today_str:
                job_row = db.get_job(child.name)
                if job_row and _job_local_date(job_row, tz) and _job_local_date(job_row, tz) >= today_str:
                    continue
                freed_bytes += _dir_size_bytes(child)
                shutil.rmtree(child, ignore_errors=True)
                if job_row:
                    db.mark_job_cleaned(child.name)
                orphan_dirs += 1

    if deleted_jobs or orphan_dirs:
        logger.info(
            "Garbage remover cleaned %d job folder(s) and %d orphan folder(s) prior to %s (%.2f MB freed).",
            len(deleted_jobs), orphan_dirs, today_str, freed_bytes / (1024 * 1024),
        )

    return {
        "current_date": today_str,
        "deleted_job_ids": deleted_jobs,
        "deleted_count": len(deleted_jobs) + orphan_dirs,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
