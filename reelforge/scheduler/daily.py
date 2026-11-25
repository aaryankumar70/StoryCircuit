"""Daily 2-video scheduler (Slot 1 & Slot 2) with custom-plan priority and YouTube upload."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from reelforge import config
from reelforge.models import SourceMode
from reelforge.pipeline import run_generation_job
from reelforge.progress import PRODUCTION_STAGES, build_progress_payload
from reelforge.storage.db import ReelDatabase
from reelforge.youtube.uploader import YouTubeUploader

logger = logging.getLogger("reelforge.scheduler.daily")


def _slot_datetime_local(date_str: str, hhmm: str, tz_name: str) -> datetime:
    hh, mm = (int(x) for x in hhmm.split(":"))
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=ZoneInfo(tz_name))


def publish_job_to_youtube(
    db: ReelDatabase,
    job_id: str,
    *,
    publish_at: Optional[datetime] = None,
    force_mode: Optional[str] = None,
) -> Dict[str, Any]:
    job = db.get_job(job_id)
    if not job:
        raise ValueError(f"Job '{job_id}' not found.")
    if job["status"] not in {"qc_passed", "uploaded", "scheduled"}:
        raise ValueError(f"Job '{job_id}' has status '{job['status']}' and cannot be uploaded before passing QC.")

    vpath = Path(job["video_path"])
    sb = job.get("storyboard") or {}
    uploader = YouTubeUploader(mode=force_mode)

    if (force_mode or uploader.mode) == "live" and job.get("scheduled_date"):
        if db.count_live_uploads_for_date(job["scheduled_date"]) >= config.MAX_DAILY_VIDEOS:
            raise RuntimeError(f"Daily live upload cap ({config.MAX_DAILY_VIDEOS}) reached for {job['scheduled_date']}.")

    prev_prog = job.get("progress") or {}
    started_at = prev_prog.get("started_at") or job.get("created_at")
    prod_done = [k for k, _ in PRODUCTION_STAGES]
    db.update_job(
        job_id,
        status="uploading",
        progress_json=build_progress_payload(
            stage="uploading",
            stage_label="Uploading to YouTube" if (force_mode or uploader.mode) == "live" else "Simulating YouTube upload",
            percent=98,
            detail="Transferring video & metadata",
            started_at=started_at,
            completed_stages=prod_done,
        ),
    )

    try:
        res = uploader.upload_short(
            video_path=vpath,
            title=job["title"],
            description=str(sb.get("description") or job["title"]),
            tags=list(sb.get("tags") or [job["category"], "shorts"]),
            publish_at=publish_at,
            force_mode=force_mode,
            exclude_youtube_ids=db.claimed_youtube_ids(),
        )
    except Exception:
        # Restore qc_passed so user can retry upload after fixing OAuth/settings
        db.update_job(
            job_id,
            status="qc_passed",
            progress_json=build_progress_payload(
                stage="qc_passed",
                stage_label="QC Passed • Upload retry needed",
                percent=95,
                started_at=started_at,
                completed_stages=prod_done,
            ),
        )
        raise

    new_status = "scheduled" if res.get("publish_at") else "uploaded"
    done_stages = prod_done + ["uploading"] + (["scheduled"] if new_status == "scheduled" else [])
    db.update_job(
        job_id,
        status=new_status,
        youtube_id=res.get("video_id"),
        youtube_url=res.get("url"),
        publish_at=res.get("publish_at"),
        simulated=1 if res.get("simulated") else 0,
        progress_json=build_progress_payload(
            stage=new_status,
            stage_label="Scheduled on YouTube" if new_status == "scheduled" else ("Uploaded (Simulated)" if res.get("simulated") else "Uploaded to YouTube"),
            percent=100,
            detail=str(res.get("video_id") or ""),
            started_at=started_at,
            completed_stages=done_stages,
        ),
    )
    return res


def run_daily_slots(
    db: ReelDatabase,
    *,
    date_str: Optional[str] = None,
    auto_upload: bool = True,
    visual_mode: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Ensure both daily slots (Slot 1 & Slot 2) are generated and optionally uploaded/scheduled."""
    tz = ZoneInfo(config.SCHEDULER_TIMEZONE)
    now_local = datetime.now(tz)
    target_date = date_str or now_local.strftime("%Y-%m-%d")

    existing = db.get_jobs_for_date(target_date)
    done_slots = {
        int(j["slot_num"])
        for j in existing
        if j.get("slot_num") in (1, 2) and j["status"] in {"qc_passed", "uploaded", "scheduled"}
    }

    slot_times = {1: config.SLOT1_TIME, 2: config.SLOT2_TIME}
    results: List[Dict[str, Any]] = []

    for slot_num in (1, 2):
        if slot_num in done_slots:
            logger.info("Date %s slot %s already completed.", target_date, slot_num)
            continue

        planned = db.get_due_plan_item(target_date, slot_num)
        if planned:
            if planned["custom_script"]:
                mode = SourceMode.CUSTOM_SCRIPT
            else:
                mode = SourceMode.PLAN
            job = run_generation_job(
                db,
                mode=mode,
                topic=planned["topic"],
                category=planned["category"] or "story",
                style=planned["style"] or "auto",
                custom_script=planned["custom_script"],
                scheduled_date=target_date,
                slot_num=slot_num,
                visual_mode=visual_mode,
            )
            db.update_plan_item(
                planned["id"],
                status="completed" if job["status"] == "qc_passed" else "failed",
                job_id=job["id"],
            )
        else:
            job = run_generation_job(
                db,
                mode=SourceMode.RANDOM,
                scheduled_date=target_date,
                slot_num=slot_num,
                visual_mode=visual_mode,
            )

        if auto_upload and job.get("status") == "qc_passed":
            slot_dt = _slot_datetime_local(target_date, slot_times[slot_num], config.SCHEDULER_TIMEZONE)
            pub_at = slot_dt.astimezone(timezone.utc) if slot_dt > now_local + timedelta(minutes=15) else None
            try:
                publish_job_to_youtube(db, job["id"], publish_at=pub_at)
                job = db.get_job(job["id"]) or job
            except Exception as exc:
                logger.error("Upload failed for %s: %s", job["id"], exc)
                db.update_job(job["id"], error=f"Upload skipped/failed: {exc}")
                job = db.get_job(job["id"]) or job

        results.append(job)

    return results


def serve_scheduler_loop(poll_seconds: int = 300) -> None:
    """Simple foreground loop checking daily slots every `poll_seconds`."""
    db = ReelDatabase()
    logger.info("ReelForge daily scheduler started (tz=%s, slots=%s, %s).", config.SCHEDULER_TIMEZONE, config.SLOT1_TIME, config.SLOT2_TIME)
    while True:
        try:
            run_daily_slots(db, auto_upload=True)
        except Exception:
            logger.exception("Scheduler cycle error")
        time.sleep(poll_seconds)
