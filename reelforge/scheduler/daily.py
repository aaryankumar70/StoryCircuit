"""Daily 2-video scheduler (Slot 1 & Slot 2), custom-plan executor, and midnight garbage cleanup."""
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
from reelforge.storage.cleanup import cleanup_ended_day_videos
from reelforge.storage.db import ReelDatabase
from reelforge.youtube.uploader import YouTubeUploader

logger = logging.getLogger("reelforge.scheduler.daily")


def _slot_datetime_local(date_str: str, hhmm: str, tz_name: str) -> datetime:
    clean_hhmm = (hhmm or "").strip() or "12:30"
    hh, mm = (int(x) for x in clean_hhmm.split(":")[:2])
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=ZoneInfo(tz_name))


def compute_smart_publish_at(
    target_date: str,
    target_hhmm: str,
    slot_num: int,
    tz_name: str,
    now_local: Optional[datetime] = None,
) -> datetime:
    """Return a guaranteed future UTC datetime for YouTube scheduled publishing."""
    tz = ZoneInfo(tz_name)
    now = now_local or datetime.now(tz)
    slot_dt = _slot_datetime_local(target_date, target_hhmm, tz_name)
    if slot_dt > now + timedelta(minutes=16):
        return slot_dt.astimezone(timezone.utc)
    # If the target slot time already passed today, schedule cleanly shortly ahead so it still publishes
    offset_min = 20 + max(0, slot_num - 1) * 45
    return (now + timedelta(minutes=offset_min)).astimezone(timezone.utc)


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
        raise ValueError(f"Job '{job['status']}' cannot be uploaded before passing QC.")

    if not job.get("video_path"):
        raise ValueError(f"Job '{job_id}' has no video file on disk (already cleaned up or missing).")

    vpath = Path(job["video_path"])
    sb = job.get("storyboard") or {}
    is_long = (job.get("video_format") == "long") or (sb.get("video_format") == "long")
    uploader = YouTubeUploader(mode=force_mode)

    if (force_mode or uploader.mode) == "live" and job.get("scheduled_date"):
        if db.count_live_uploads_for_date(job["scheduled_date"]) >= config.MAX_DAILY_VIDEOS:
            raise RuntimeError(f"Daily live upload cap ({config.MAX_DAILY_VIDEOS}) reached for {job['scheduled_date']}.")

    # Auto-determine future publish_at if scheduled_date/slot_num is set and caller omitted publish_at
    effective_publish_at = publish_at
    if effective_publish_at is None and job.get("scheduled_date"):
        slot_num = int(job.get("slot_num") or 1)
        slot_hhmm = config.SLOT2_TIME if slot_num == 2 else config.SLOT1_TIME
        effective_publish_at = compute_smart_publish_at(
            str(job["scheduled_date"]),
            slot_hhmm,
            slot_num,
            config.SCHEDULER_TIMEZONE,
        )

    prev_prog = job.get("progress") or {}
    started_at = prev_prog.get("started_at") or job.get("created_at")
    prod_done = [k for k, _ in PRODUCTION_STAGES]
    db.update_job(
        job_id,
        status="uploading",
        progress_json=build_progress_payload(
            stage="uploading",
            stage_label="Uploading & scheduling on YouTube",
            percent=98,
            detail="Transferring video & SEO metadata",
            started_at=started_at,
            completed_stages=prod_done,
        ),
    )

    try:
        res = uploader.upload_short(
            video_path=vpath,
            title=job["title"],
            description=str(sb.get("description") or job["title"]),
            tags=list(sb.get("tags") or [job["category"], "story"]),
            publish_at=effective_publish_at,
            force_mode=force_mode,
            exclude_youtube_ids=db.claimed_youtube_ids(),
            is_long=is_long,
        )
    except Exception:
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
        error="",
        progress_json=build_progress_payload(
            stage=new_status,
            stage_label="Scheduled on YouTube" if new_status == "scheduled" else "Uploaded to YouTube",
            percent=100,
            detail=str(res.get("video_id") or ""),
            started_at=started_at,
            completed_stages=done_stages,
        ),
    )
    return res


def run_plan_item_now(
    db: ReelDatabase,
    plan_id: str,
    *,
    auto_upload: bool = True,
    visual_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a specific Custom Plan item immediately and schedule it for its planned date/time."""
    planned = db.get_plan_item(plan_id)
    if not planned:
        raise ValueError(f"Plan item '{plan_id}' not found.")

    tz = ZoneInfo(config.SCHEDULER_TIMEZONE)
    now_local = datetime.now(tz)
    target_date = str(planned["planned_date"])
    slot_num = int(planned.get("slot_num") or 1)
    target_hhmm = str(planned.get("publish_time") or "").strip() or (
        config.SLOT2_TIME if slot_num == 2 else config.SLOT1_TIME
    )
    mode = SourceMode.CUSTOM_SCRIPT if planned.get("custom_script") else SourceMode.PLAN

    job = run_generation_job(
        db,
        mode=mode,
        topic=planned["topic"],
        category=planned.get("category") or "story",
        style=planned.get("style") or "auto",
        custom_script=planned.get("custom_script") or "",
        scheduled_date=target_date,
        slot_num=slot_num,
        visual_mode=visual_mode,
    )
    db.update_plan_item(
        planned["id"],
        status="completed" if job["status"] == "qc_passed" else "failed",
        job_id=job["id"],
    )

    if auto_upload and job.get("status") == "qc_passed":
        pub_at = compute_smart_publish_at(target_date, target_hhmm, slot_num, config.SCHEDULER_TIMEZONE, now_local)
        try:
            publish_job_to_youtube(db, job["id"], publish_at=pub_at)
            job = db.get_job(job["id"]) or job
        except Exception as exc:
            logger.error("Upload failed for %s: %s", job["id"], exc)
            db.update_job(job["id"], error=f"Upload skipped/failed: {exc}")
            job = db.get_job(job["id"]) or job
    return job


def run_daily_slots(
    db: ReelDatabase,
    *,
    date_str: Optional[str] = None,
    auto_upload: bool = True,
    visual_mode: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Run garbage cleanup for ended days, then produce & auto-schedule today's 2 videos."""
    tz = ZoneInfo(config.SCHEDULER_TIMEZONE)
    now_local = datetime.now(tz)
    target_date = date_str or now_local.strftime("%Y-%m-%d")

    if config.AUTO_GARBAGE_CLEANUP:
        try:
            cleanup_ended_day_videos(db, current_date=target_date)
        except Exception:
            logger.exception("Garbage cleanup failed before daily cycle")

    existing = db.get_jobs_for_date(target_date)
    by_slot: Dict[int, Dict[str, Any]] = {}
    for j in existing:
        snum = j.get("slot_num")
        if snum in (1, 2):
            by_slot[int(snum)] = j

    slot_times = {1: config.SLOT1_TIME, 2: config.SLOT2_TIME}
    results: List[Dict[str, Any]] = []

    for slot_num in (1, 2):
        prev_job = by_slot.get(slot_num)
        if prev_job and prev_job["status"] in {"uploaded", "scheduled"}:
            logger.info("Date %s slot %s already uploaded/scheduled.", target_date, slot_num)
            continue

        # If a video already passed QC for this slot today, finish uploading/scheduling instead of re-rendering
        if prev_job and prev_job["status"] == "qc_passed" and prev_job.get("video_path"):
            job = prev_job
            target_hhmm = slot_times[slot_num]
        else:
            planned = db.get_due_plan_item(target_date, slot_num)
            if planned:
                mode = SourceMode.CUSTOM_SCRIPT if planned["custom_script"] else SourceMode.PLAN
                target_hhmm = str(planned.get("publish_time") or "").strip() or slot_times[slot_num]
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
                target_hhmm = slot_times[slot_num]
                job = run_generation_job(
                    db,
                    mode=SourceMode.RANDOM,
                    scheduled_date=target_date,
                    slot_num=slot_num,
                    visual_mode=visual_mode,
                )

        if auto_upload and job.get("status") == "qc_passed":
            pub_at = compute_smart_publish_at(
                target_date,
                target_hhmm,
                slot_num,
                config.SCHEDULER_TIMEZONE,
                now_local,
            )
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
    """Continuous 2-video/day scheduler & end-of-day garbage cleanup loop."""
    db = ReelDatabase()
    db.recover_interrupted_jobs()
    logger.info(
        "ReelForge daily scheduler started (tz=%s, slots=%s, %s).",
        config.SCHEDULER_TIMEZONE, config.SLOT1_TIME, config.SLOT2_TIME,
    )
    while True:
        try:
            run_daily_slots(db, auto_upload=True)
        except Exception:
            logger.exception("Scheduler cycle error")
        time.sleep(poll_seconds)
