"""Safe Automatic Daily Local Video & Render Cleanup Manager for CurioLoop.

Deletes obsolete generated MP4s, preview images, and temporary render folders strictly
under OUTPUT_DIR after the production IST day has ended and retention allows.

Strict Safety Guarantees:
- Never operates outside explicitly resolved OUTPUT_DIR paths.
- Never runs broad wildcard/recursive wipes on repository roots or system folders.
- Never touches models, source code, config, credentials, templates, docs, or DB/log JSONs.
- Protects current IST day files, active/recovering jobs, unuploaded or unscheduled live jobs.
- Fully idempotent; preserves database metadata and logs while tracking reclaimed storage.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from curiosity_engine import config
from curiosity_engine.distribution.youtube_publisher import NON_PRODUCTION_TEST_YOUTUBE_IDS
from curiosity_engine.state.db import db

logger = logging.getLogger("curiosity_engine.storage_cleanup")

IST = ZoneInfo(config.SCHEDULER_TIMEZONE)
CLEANUP_STATE_FILE = config.DATA_DIR / "storage_cleanup.json"
_VIDEO_DATE_RE = re.compile(r"^(video_(\d{4})(\d{2})(\d{2})_slot\d+)")


def _extract_job_id_and_date(name: str) -> Optional[tuple[str, str]]:
    """Extract canonical `(video_id, YYYY-MM-DD)` only for generated `video_YYYYMMDD_slotN` artifacts."""
    m = _VIDEO_DATE_RE.match(name)
    if not m:
        return None
    vid_id = m.group(1)
    date_iso = f"{m.group(2)}-{m.group(3)}-{m.group(4)}"
    return vid_id, date_iso


def _dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    for root, _, files in os.walk(path):
        for fname in files:
            try:
                total += (Path(root) / fname).stat().st_size
            except OSError:
                pass
    return total


def _is_within_output_dir(target: Path, output_root: Path) -> bool:
    try:
        resolved_root = output_root.resolve()
        resolved_target = target.resolve()
        return resolved_target != resolved_root and resolved_root in resolved_target.parents
    except Exception:
        return False


def _load_cleanup_state(state_file: Path) -> Dict[str, Any]:
    default = {
        "last_cleanup_date_ist": None,
        "last_cleanup_at_ist": None,
        "total_files_deleted": 0,
        "total_dirs_deleted": 0,
        "total_bytes_reclaimed": 0,
        "runs": [],
    }
    if not state_file.exists():
        return default
    try:
        loaded = json.loads(state_file.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            default.update(loaded)
        return default
    except Exception:
        return default


def _save_cleanup_state(state: Dict[str, Any], state_file: Path) -> None:
    if len(state.get("runs", [])) > 50:
        state["runs"] = state["runs"][-50:]
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, state_file)


def _is_job_protected(
    vid_id: str,
    job_date_iso: str,
    today_date_iso: str,
    retention_days: int,
    records_by_id: Dict[str, Dict[str, Any]],
    active_scheduled_yt_ids: set[str],
    now_ist: datetime,
) -> Optional[str]:
    """Return a non-empty protection reason if `vid_id`'s local files must NOT be deleted."""
    try:
        job_dt = datetime.strptime(job_date_iso, "%Y-%m-%d").date()
        today_dt = datetime.strptime(today_date_iso, "%Y-%m-%d").date()
    except ValueError:
        return "invalid_job_date"

    age_days = (today_dt - job_dt).days
    if age_days < max(1, int(retention_days)):
        return f"within_retention_window (age={age_days}d < retention={retention_days}d)"

    rec = records_by_id.get(vid_id)
    if rec is None:
        return "unowned_missing_db_record"

    prod_status = str(rec.get("production_status") or "").upper()
    if prod_status in ("STARTING", "SCRIPTED", "ASSETS_READY", "RENDERED", "RECOVERING", "RUNNING"):
        return f"active_production_status ({prod_status})"

    if prod_status == "REJECTED_QC" and int(rec.get("recovery_attempts") or 0) < config.MAX_QC_RECOVERY_ATTEMPTS:
        return "pending_qc_recovery"

    pub_status = str(rec.get("publishing_status") or "").upper()
    if pub_status in ("PENDING", "UPLOADING", "UPLOADED_PRIVATE"):
        return f"pending_publishing_operation ({pub_status})"

    yt_id = str(rec.get("youtube_upload_id") or "")
    is_sim = bool(rec.get("youtube_simulated")) or yt_id.startswith("yt_sim_")

    # In live mode, protect failed/unconfirmed/unscheduled local MP4s unless published or confirmed scheduled
    if config.YOUTUBE_PUBLISHING_MODE == "live" and not is_sim:
        if yt_id in NON_PRODUCTION_TEST_YOUTUBE_IDS:
            return "protected_test_reference"
        if not yt_id or (not rec.get("schedule_confirmed") and pub_status not in ("PUBLISHED", "SCHEDULED")):
            return f"live_upload_or_schedule_incomplete (pub_status={pub_status}, schedule_confirmed={rec.get('schedule_confirmed')})"

    # Extra guard: never delete if YouTube video ID has not yet passed scheduled publishAt and upload lacks confirmation
    if yt_id and yt_id in active_scheduled_yt_ids and not rec.get("schedule_confirmed"):
        return "scheduled_video_needs_confirmation"

    return None


def cleanup_old_generated_videos(
    retention_days: Optional[int] = None,
    output_dir: Optional[Path] = None,
    state_file: Optional[Path] = None,
    db_client: Any = None,
    now_ist: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Identify and safely remove eligible previous-day generated files inside OUTPUT_DIR."""
    out_root = Path(output_dir) if output_dir else config.OUTPUT_DIR
    st_file = Path(state_file) if state_file else CLEANUP_STATE_FILE
    store = db_client or db
    now = (now_ist or datetime.now(IST)).astimezone(IST)
    today_iso = now.strftime("%Y-%m-%d")
    retain = max(1, int(retention_days if retention_days is not None else config.VIDEO_RETENTION_DAYS))

    if not out_root.exists() or not out_root.is_dir():
        return {
            "success": True,
            "date_ist": today_iso,
            "files_deleted": 0,
            "dirs_deleted": 0,
            "bytes_reclaimed": 0,
            "protected": {},
            "deleted_paths": [],
        }

    all_records = store.get_all_videos(limit=500)
    if not isinstance(all_records, list):
        all_records = []
    records_by_id: Dict[str, Dict[str, Any]] = {
        str(r["video_id"]): r for r in all_records if isinstance(r, dict) and r.get("video_id")
    }
    active_scheduled_yt_ids = {
        str(r.get("youtube_upload_id"))
        for r in all_records
        if isinstance(r, dict) and r.get("youtube_upload_id") and r.get("scheduled_publish_at")
    }

    # Inspect immediate children inside OUTPUT_DIR grouped cleanly by owned job_id
    candidates_by_job: Dict[str, tuple[str, List[Path]]] = {}
    skipped_unowned: List[str] = []

    for child in sorted(out_root.iterdir()):
        parsed = _extract_job_id_and_date(child.name)
        if not parsed:
            skipped_unowned.append(child.name)
            continue
        vid_id, job_date_iso = parsed
        # Only allow exact MP4, preview JPGs, or the matching per-video build folder
        is_allowed_artifact = (
            (child.is_file() and (child.name == f"{vid_id}.mp4" or (child.name.startswith(f"{vid_id}_preview_") and child.suffix.lower() == ".jpg")))
            or (child.is_dir() and child.name == vid_id)
        )
        if not is_allowed_artifact:
            skipped_unowned.append(child.name)
            continue
        candidates_by_job.setdefault(vid_id, (job_date_iso, []))[1].append(child)

    files_deleted = 0
    dirs_deleted = 0
    bytes_reclaimed = 0
    protected_jobs: Dict[str, str] = {}
    deleted_paths: List[str] = []

    for vid_id, (job_date_iso, paths) in candidates_by_job.items():
        reason = _is_job_protected(
            vid_id=vid_id,
            job_date_iso=job_date_iso,
            today_date_iso=today_iso,
            retention_days=retain,
            records_by_id=records_by_id,
            active_scheduled_yt_ids=active_scheduled_yt_ids,
            now_ist=now,
        )
        if reason:
            protected_jobs[vid_id] = reason
            continue

        job_reclaimed = 0
        for target in paths:
            if not _is_within_output_dir(target, out_root):
                logger.warning("Refused cleanup target outside OUTPUT_DIR: %s", target)
                continue
            size = _dir_size_bytes(target)
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                    dirs_deleted += 1
                elif target.is_file():
                    target.unlink()
                    files_deleted += 1
                job_reclaimed += size
                deleted_paths.append(target.name)
            except Exception as exc:
                logger.warning("Failed deleting obsolete artifact %s: %s", target, exc)

        bytes_reclaimed += job_reclaimed
        if job_reclaimed > 0 and vid_id in records_by_id:
            rec = dict(records_by_id[vid_id])
            rec["local_file_cleaned"] = True
            rec["local_file_cleaned_at"] = now.isoformat()
            rec["local_bytes_reclaimed"] = job_reclaimed
            # Preserve all metadata, QC history, YouTube IDs & descriptions cleanly
            store.save_video_record(vid_id, rec)

    state = _load_cleanup_state(st_file)
    state["last_cleanup_date_ist"] = today_iso
    state["last_cleanup_at_ist"] = now.isoformat()
    state["total_files_deleted"] = int(state.get("total_files_deleted", 0)) + files_deleted
    state["total_dirs_deleted"] = int(state.get("total_dirs_deleted", 0)) + dirs_deleted
    state["total_bytes_reclaimed"] = int(state.get("total_bytes_reclaimed", 0)) + bytes_reclaimed
    run_entry = {
        "date_ist": today_iso,
        "timestamp_ist": now.isoformat(),
        "retention_days": retain,
        "files_deleted": files_deleted,
        "dirs_deleted": dirs_deleted,
        "bytes_reclaimed": bytes_reclaimed,
        "reclaimed_mb": round(bytes_reclaimed / (1024 * 1024), 2),
        "protected_count": len(protected_jobs),
        "deleted_artifacts": deleted_paths[:30],
    }
    state.setdefault("runs", []).append(run_entry)
    _save_cleanup_state(state, st_file)

    logger.info(
        "Storage cleanup (%s, retention=%dd): deleted %d file(s), %d folder(s), reclaimed %.2f MB; protected %d job(s).",
        today_iso,
        retain,
        files_deleted,
        dirs_deleted,
        bytes_reclaimed / (1024 * 1024),
        len(protected_jobs),
    )

    return {
        "success": True,
        "date_ist": today_iso,
        "retention_days": retain,
        "files_deleted": files_deleted,
        "dirs_deleted": dirs_deleted,
        "bytes_reclaimed": bytes_reclaimed,
        "reclaimed_mb": round(bytes_reclaimed / (1024 * 1024), 2),
        "protected": protected_jobs,
        "deleted_paths": deleted_paths,
        "skipped_unowned": skipped_unowned,
    }


def get_storage_summary(
    output_dir: Optional[Path] = None,
    state_file: Optional[Path] = None,
) -> Dict[str, Any]:
    """Return live storage consumption inside OUTPUT_DIR and recent cleanup telemetry."""
    out_root = Path(output_dir) if output_dir else config.OUTPUT_DIR
    st_file = Path(state_file) if state_file else CLEANUP_STATE_FILE
    state = _load_cleanup_state(st_file)

    mp4_count = 0
    total_output_bytes = 0
    job_dirs = 0
    if out_root.exists():
        for child in out_root.iterdir():
            if child.is_file() and child.suffix.lower() == ".mp4":
                mp4_count += 1
            elif child.is_dir():
                job_dirs += 1
            total_output_bytes += _dir_size_bytes(child)

    disk_free_gb = None
    try:
        usage = shutil.disk_usage(out_root if out_root.exists() else config.PROJECT_ROOT)
        disk_free_gb = round(usage.free / (1024 ** 3), 2)
    except Exception:
        pass

    runs = state.get("runs", [])
    latest_run = runs[-1] if runs else None
    return {
        "output_dir": str(out_root),
        "retention_days": config.VIDEO_RETENTION_DAYS,
        "output_size_mb": round(total_output_bytes / (1024 * 1024), 2),
        "mp4_files_on_disk": mp4_count,
        "project_dirs_on_disk": job_dirs,
        "disk_free_gb": disk_free_gb,
        "last_cleanup_date_ist": state.get("last_cleanup_date_ist"),
        "last_cleanup_at_ist": state.get("last_cleanup_at_ist"),
        "total_bytes_reclaimed_mb": round(int(state.get("total_bytes_reclaimed", 0)) / (1024 * 1024), 2),
        "latest_run": latest_run,
    }
