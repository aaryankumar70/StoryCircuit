"""Production and Publishing Pipelines for Curiosity Engine.
Coordinates content, production, QC, cloud storage, and social distribution.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from curiosity_engine.config import (
    INSTAGRAM_PUBLISHING_MODE,
    OUTPUT_DIR,
    YOUTUBE_PRIVACY_STATUS,
    YOUTUBE_PUBLISHING_MODE,
)
from curiosity_engine.content.scriptwriter import write_video_script
from curiosity_engine.content.topic_discovery import select_daily_topics
from curiosity_engine.distribution.instagram_publisher import instagram_publisher
from curiosity_engine.distribution.youtube_publisher import youtube_publisher
from curiosity_engine.production.director import prepare_project
from curiosity_engine.production.renderer import render_project_video, validate_rendered_mp4
from curiosity_engine.quality.qc_gatekeeper import verify_video
from curiosity_engine.state.db import db

logger = logging.getLogger("curiosity_engine.pipeline")


def _has_valid_project_assets(project_dir: Path) -> bool:
    """Verify whether prepared TTS/alignment project assets are intact for safe render resume."""
    required_files = [
        project_dir / "script.json",
        project_dir / "index.html",
        project_dir / "src" / "main.js",
        project_dir / "data" / "narration.wav",
        project_dir / "data" / "lines.json",
        project_dir / "data" / "words.json",
    ]
    if not all(p.exists() for p in required_files):
        return False
    if (project_dir / "data" / "narration.wav").stat().st_size < 10_000:
        return False
    try:
        lines = json.loads((project_dir / "data" / "lines.json").read_text(encoding="utf-8"))
        words = json.loads((project_dir / "data" / "words.json").read_text(encoding="utf-8"))
        return float(lines.get("duration", 0)) > 5.0 and len(words) > 0
    except Exception:
        return False


def is_slot_generation_complete(video_id: str) -> bool:
    """Return True only if record exists, passed QC, and local MP4 passes strict ffprobe validation."""
    rec = db.get_video_record(video_id)
    if not rec or rec.get("production_status") != "COMPLETED" or not rec.get("qc_passed"):
        return False
    mp4_path = Path(rec.get("local_video_path") or (OUTPUT_DIR / f"{video_id}.mp4"))
    try:
        validate_rendered_mp4(mp4_path)
        return True
    except Exception as e:
        logger.warning(f"Slot {video_id} DB says COMPLETED, but MP4 validation failed ({e}). Recovery needed.")
        return False


def produce_single_video(
    video_id: str,
    topic_info: Dict[str, Any],
    slot_index: int,
    target_date: str,
    force_rebuild: bool = False,
) -> Dict[str, Any]:
    """Execute or safely resume complete production lifecycle for a single video slot."""
    logger.info(f"=== Starting Production for Video {video_id} (Slot {slot_index}) ===")

    existing = db.get_video_record(video_id)
    output_mp4 = OUTPUT_DIR / f"{video_id}.mp4"
    project_dir = OUTPUT_DIR / video_id

    # 1. Check if already produced and MP4 verified
    if not force_rebuild and is_slot_generation_complete(video_id):
        logger.info(f"Video {video_id} already exists, passed QC, and MP4 verified; preserving existing assets.")
        return existing

    # Preserve existing metadata/uploads when resuming an interrupted or partial record
    base_record = dict(existing) if existing else {}
    record: Dict[str, Any] = {
        **base_record,
        "video_id": video_id,
        "slot_index": slot_index,
        "target_date": target_date,
        "topic": base_record.get("topic") or topic_info.get("topic"),
        "category": base_record.get("category") or topic_info.get("category"),
        "style": base_record.get("style") or topic_info.get("style"),
        "production_status": base_record.get("production_status") or "STARTING",
        "publishing_status": base_record.get("publishing_status") or "PENDING",
        "created_at": base_record.get("created_at") or datetime.now(timezone.utc).isoformat(),
    }
    db.save_video_record(video_id, record)

    try:
        # 2. Scriptwriting & Source Verification (reuse valid saved script when resuming)
        script_data = None
        if not force_rebuild and isinstance(record.get("script"), dict) and record["script"].get("lines"):
            script_data = record["script"]
            logger.info(f"[{video_id}] Reusing existing verified script for '{record.get('topic')}'.")
        else:
            logger.info(f"[{video_id}] Writing script and checking sources...")
            script_data = write_video_script(topic_info)
            record["script"] = script_data
            record["sources"] = script_data.get("sources", [])
            record["claims"] = script_data.get("claims", [])
            record["production_status"] = "SCRIPTED"

        # 2b. Intelligent Description Generation (preserve user-edited or already generated descriptions)
        if not force_rebuild and record.get("youtube_description"):
            logger.info(f"[{video_id}] Preserving existing YouTube description.")
        else:
            logger.info(f"[{video_id}] Generating intelligent YouTube Shorts description...")
            from curiosity_engine.content.description_generator import description_generator
            desc_data = description_generator.generate(
                topic=record.get("topic") or topic_info.get("topic", ""),
                category=record.get("category") or topic_info.get("category", ""),
                script_data=script_data,
                sources=record.get("sources", []),
                claims=record.get("claims", []),
            )
            record["youtube_description"] = desc_data["full_description"]
            record["description_data"] = desc_data
        db.save_video_record(video_id, record)

        # 3. Check if valid rendered MP4 already exists on disk (skip prep & render -> go straight to QC)
        rendered_valid = False
        if not force_rebuild and output_mp4.exists():
            try:
                validate_rendered_mp4(output_mp4)
                rendered_valid = True
                logger.info(f"[{video_id}] Valid rendered MP4 already present at {output_mp4}; resuming at QC.")
            except Exception as mp4_err:
                logger.warning(f"[{video_id}] Existing MP4 invalid ({mp4_err}); removing corrupt output.")
                try:
                    output_mp4.unlink()
                except Exception:
                    pass

        if not rendered_valid:
            # 3b. Preparation: TTS and Alignment (resume from valid project assets if intact)
            if not force_rebuild and _has_valid_project_assets(project_dir):
                logger.info(f"[{video_id}] Resuming from valid existing ASSETS_READY project at {project_dir}.")
                record["production_status"] = "ASSETS_READY"
                db.save_video_record(video_id, record)
            else:
                logger.info(f"[{video_id}] Preparing project assets, voice, and timing...")
                project_dir = prepare_project(video_id, script_data)
                record["production_status"] = "ASSETS_READY"
                db.save_video_record(video_id, record)

            # 4. Headless Chrome Frame Rendering & FFmpeg Assembly
            logger.info(f"[{video_id}] Rendering frames to {output_mp4}...")
            render_project_video(project_dir, output_mp4, resume=not force_rebuild, force_rebuild=force_rebuild)
            record["local_video_path"] = str(output_mp4)
            record["production_status"] = "RENDERED"
            db.save_video_record(video_id, record)
        else:
            record["local_video_path"] = str(output_mp4)
            record["production_status"] = "RENDERED"
            db.save_video_record(video_id, record)

        # 5. Programmatic Quality Control Gatekeeper
        logger.info(f"[{video_id}] Running Quality Control checks...")
        qc_report = verify_video(output_mp4, script_data)
        record["qc_passed"] = qc_report.passed
        record["qc_results"] = qc_report.to_dict()

        if not qc_report.passed:
            record["production_status"] = "REJECTED_QC"
            record["error"] = f"QC Failed: {'; '.join(qc_report.issues)}"
            db.save_video_record(video_id, record)
            db.log_error("QC_GATEKEEPER", f"Video {video_id} failed QC", {"issues": qc_report.issues})
            raise RuntimeError(f"Video {video_id} rejected by QC: {qc_report.issues}")

        record["production_status"] = "COMPLETED"
        record["error"] = None

        # 6. Record Local MP4 Storage URI
        record["storage_uri"] = str(output_mp4)
        db.save_video_record(video_id, record)
        logger.info(f"=== Video {video_id} Produced & Passed QC Successfully ===")
        return record

    except Exception as e:
        logger.error(f"Error during video {video_id} production: {e}")
        # Keep ASSETS_READY if assets remain valid so retry resumes cleanly instead of losing stage state
        if record.get("production_status") not in ("ASSETS_READY", "SCRIPTED"):
            record["production_status"] = "FAILED"
        else:
            record["production_status"] = "FAILED"
        record["qc_passed"] = False
        record["error"] = str(e)
        db.save_video_record(video_id, record)
        db.log_error("PRODUCTION_PIPELINE", f"Failed producing {video_id}: {e}", {"slot": slot_index})
        raise


def run_daily_generation(
    target_date: Optional[str] = None,
    force_rebuild: bool = False,
    slots: Optional[List[int]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Slot-independent daily video generation for requested slots (defaults to [1, 2])."""
    if not target_date:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    target_slots = slots if slots is not None else [1, 2]
    clean_date = target_date.replace("-", "")
    video_1_id = f"video_{clean_date}_slot1"
    video_2_id = f"video_{clean_date}_slot2"

    logger.info(f"==================================================")
    logger.info(
        f"Running Daily Generation for Date: {target_date} "
        f"(slots={target_slots}, force_rebuild={force_rebuild})"
    )
    logger.info(f"==================================================")

    v1_record = db.get_video_record(video_1_id)
    v2_record = db.get_video_record(video_2_id)

    s1_complete = (not force_rebuild) and is_slot_generation_complete(video_1_id)
    s2_complete = (not force_rebuild) and is_slot_generation_complete(video_2_id)

    need_s1 = (1 in target_slots) and not s1_complete
    need_s2 = (2 in target_slots) and not s2_complete

    if s1_complete and 1 in target_slots:
        logger.info(f"Slot 1 ({video_1_id}) already complete and QC-passed; preserving untouched.")
    if s2_complete and 2 in target_slots:
        logger.info(f"Slot 2 ({video_2_id}) already complete and QC-passed; preserving untouched.")

    if not need_s1 and not need_s2:
        logger.info("All requested slots are already generated and QC-passed. Zero work required.")
        return v1_record, v2_record

    # Build slot-specific topic_info only for slots needing generation, preserving saved topic if present
    def _topic_from_record(rec: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if rec and rec.get("topic"):
            return {
                "topic": rec.get("topic"),
                "category": rec.get("category", "Science"),
                "style": rec.get("style", "inside-out"),
                "sources": rec.get("sources", []),
                "claims": rec.get("claims", []),
                "scores": rec.get("scores", {}),
            }
        return None

    t1_info = _topic_from_record(v1_record) if (need_s1 and not force_rebuild) else None
    t2_info = _topic_from_record(v2_record) if (need_s2 and not force_rebuild) else None

    if (need_s1 and not t1_info) or (need_s2 and not t2_info):
        used_today = set()
        if v1_record and v1_record.get("topic"):
            used_today.add(v1_record["topic"])
        if v2_record and v2_record.get("topic"):
            used_today.add(v2_record["topic"])
        discovered_1, discovered_2 = select_daily_topics(target_date, exclude_topics=used_today)
        if need_s1 and not t1_info:
            t1_info = discovered_1
        if need_s2 and not t2_info:
            t2_info = discovered_2 if discovered_2["topic"] != (t1_info or {}).get("topic") else discovered_1

    # Produce Video 1 independently if needed
    if need_s1 and t1_info:
        try:
            v1_record = produce_single_video(
                video_1_id, t1_info, slot_index=1, target_date=target_date, force_rebuild=force_rebuild
            )
        except Exception as e:
            logger.error(f"Slot 1 production failed: {e}. Proceeding independently with remaining slots.")
            v1_record = db.get_video_record(video_1_id)

    # Produce Video 2 independently if needed
    if need_s2 and t2_info:
        try:
            v2_record = produce_single_video(
                video_2_id, t2_info, slot_index=2, target_date=target_date, force_rebuild=force_rebuild
            )
        except Exception as e:
            logger.error(f"Slot 2 production failed: {e}.")
            v2_record = db.get_video_record(video_2_id)

    logger.info(
        f"Daily generation finished. V1: {bool(v1_record and v1_record.get('qc_passed'))}, "
        f"V2: {bool(v2_record and v2_record.get('qc_passed'))}"
    )
    return v1_record, v2_record


def is_real_youtube_upload(record: Optional[Dict[str, Any]]) -> bool:
    """Return True only if record contains a verified real YouTube upload ID (not simulated)."""
    if not record:
        return False
    yt_id = record.get("youtube_upload_id")
    if not yt_id:
        return False
    if str(yt_id).startswith("yt_sim_"):
        return False
    if record.get("youtube_simulated") is True:
        return False
    return True


def run_slot_publishing(
    slot_index: int,
    target_date: Optional[str] = None,
    force_publish: bool = False,
    force_yt_mode: Optional[str] = None,
    force_ig_mode: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Job 2 (10:00 IST) or Job 3 (18:00 IST): Publish the specified video slot.
    Direct MP4 upload to YouTube; decoupled independent Instagram execution.
    Never duplicates real YouTube uploads, and does not block Slot 2 by historical simulation.
    """
    if not target_date:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    clean_date = target_date.replace("-", "")
    video_id = f"video_{clean_date}_slot{slot_index}"

    logger.info(f"==================================================")
    logger.info(f"Running Publishing Job for Slot {slot_index} (Video {video_id})")
    logger.info(f"==================================================")

    record = db.get_video_record(video_id)
    if not record:
        logger.error(f"Video record {video_id} not found in database! Did generation run?")
        db.log_error("PUBLISHER", f"Video {video_id} record not found")
        return None

    if not record.get("qc_passed"):
        logger.error(f"Video {video_id} has not passed QC. Refusing to publish rejected content.")
        db.log_error("PUBLISHER", f"Video {video_id} refused publishing: QC not passed")
        return None

    # Resolve platform modes
    effective_yt_mode = (force_yt_mode or YOUTUBE_PUBLISHING_MODE or "simulation").strip().lower()
    effective_ig_mode = (force_ig_mode or INSTAGRAM_PUBLISHING_MODE or "disabled").strip().lower()

    # Check YouTube duplicate status:
    # A video with a real YouTube ID must NEVER be uploaded again.
    has_real_yt = is_real_youtube_upload(record)

    if has_real_yt:
        logger.info(
            f"Video {video_id} already has verified real YouTube upload ID ({record.get('youtube_upload_id')}). "
            "Skipping YouTube upload to prevent duplicate publishing."
        )
    elif record.get("youtube_upload_id") and not force_publish and effective_yt_mode == "simulation":
        logger.info(
            f"Video {video_id} already has simulated YouTube upload ({record.get('youtube_upload_id')}). "
            "Skipping duplicate simulation (use force_publish=True to re-simulate)."
        )
    else:
        if record.get("youtube_upload_id") and str(record.get("youtube_upload_id", "")).startswith("yt_sim_"):
            logger.info(
                f"Video {video_id} has historical simulated status ({record.get('youtube_upload_id')}). "
                f"Proceeding with {effective_yt_mode.upper()} YouTube publishing."
            )

    # Resolve video path
    local_path = Path(record.get("local_video_path", ""))
    if not local_path.exists():
        fallback_path = OUTPUT_DIR / f"{video_id}.mp4"
        if fallback_path.exists():
            local_path = fallback_path
            record["local_video_path"] = str(fallback_path)
        else:
            raise FileNotFoundError(f"Video file {video_id}.mp4 not found on disk.")

    script = record.get("script", {})
    title = script.get("title", record.get("topic", "Fascinating Fact"))
    category = record.get("category", "Science")
    category_id = "27" if category in ["History", "Geography", "Interesting discoveries"] else "28"

    tags = [
        "Shorts",
        "Curiosity",
        category.replace(" ", ""),
        "Science",
        "DidYouKnow",
        "Education",
        "Interesting",
    ]

    record["publishing_status"] = "UPLOADING"
    db.save_video_record(video_id, record)

    yt_uploaded_now = False

    # 1. Independent YouTube Shorts Upload
    if not has_real_yt and (force_publish or not (record.get("youtube_upload_id") and effective_yt_mode == "simulation")):
        try:
            logger.info(f"Publishing {video_id} to YouTube Shorts (Mode: {effective_yt_mode})...")
            yt_description = record.get("youtube_description")
            if not yt_description:
                from curiosity_engine.content.description_generator import description_generator
                desc_data = description_generator.generate(
                    topic=record.get("topic", title),
                    category=category,
                    script_data=script,
                    sources=record.get("sources", []),
                    claims=record.get("claims", []),
                )
                yt_description = desc_data["full_description"]
                record["youtube_description"] = yt_description

            other_real_yt_ids = {
                str(r.get("youtube_upload_id"))
                for r in db.get_all_videos(limit=100)
                if r.get("video_id") != video_id and is_real_youtube_upload(r)
            }
            yt_res = youtube_publisher.upload_short(
                video_path=local_path,
                title=title,
                description=yt_description,
                tags=tags,
                category_id=category_id,
                privacy_status=YOUTUBE_PRIVACY_STATUS,
                force_mode=effective_yt_mode,
                exclude_youtube_ids=other_real_yt_ids,
            )
            record["youtube_upload_id"] = yt_res.get("video_id")
            record["youtube_url"] = yt_res.get("url")
            record["youtube_simulated"] = yt_res.get("simulated", False)
            record["youtube_privacy_status"] = yt_res.get("privacy_status", YOUTUBE_PRIVACY_STATUS)
            record["youtube_published_at"] = yt_res.get("published_at", datetime.now(timezone.utc).isoformat())
            record["schedule_confirmed"] = bool(yt_res.get("schedule_confirmed") and not yt_res.get("simulated"))
            if yt_res.get("publish_at") and record["schedule_confirmed"]:
                record["scheduled_publish_at"] = yt_res.get("publish_at")
            record["youtube_status"] = (
                "SIMULATED" if yt_res.get("simulated")
                else ("SCHEDULED" if record["schedule_confirmed"] else "PUBLISHED")
            )
            yt_uploaded_now = True
        except Exception as yt_err:
            record["youtube_status"] = "FAILED"
            record["youtube_error"] = str(yt_err)
            record["publishing_status"] = "PUBLISH_FAILED"
            db.save_video_record(video_id, record)
            db.log_error("YOUTUBE_PUBLISHER", f"Failed publishing {video_id}: {yt_err}", {"slot": slot_index})
            logger.error(f"YouTube publishing failed for {video_id}: {yt_err}")
            raise

    # 2. Independent Instagram Reels Upload (Never crashes YouTube success)
    try:
        logger.info(f"Publishing {video_id} to Instagram Reels (Mode: {effective_ig_mode})...")
        ig_res = instagram_publisher.publish_reel(
            video_path=local_path,
            caption=f"{title}\n\nDid you know this?",
            hashtags=tags,
            force_mode=effective_ig_mode,
        )
        if ig_res.get("disabled"):
            record["instagram_status"] = "DISABLED"
            # Preserve historical instagram media ID if already present
            if not record.get("instagram_media_id"):
                record["instagram_media_id"] = None
                record["instagram_url"] = None
                record["instagram_simulated"] = False
        else:
            record["instagram_media_id"] = ig_res.get("media_id")
            record["instagram_url"] = ig_res.get("url")
            record["instagram_simulated"] = ig_res.get("simulated", False)
            record["instagram_status"] = "PUBLISHED" if ig_res.get("success") else "FAILED"
            record["instagram_published_at"] = ig_res.get("published_at")
    except Exception as ig_err:
        logger.warning(f"Instagram publishing failed for {video_id} (non-fatal for YouTube): {ig_err}")
        record["instagram_status"] = "FAILED"
        record["instagram_error"] = str(ig_err)
        db.log_error("INSTAGRAM_PUBLISHER", f"Instagram failed for {video_id}: {ig_err}", {"slot": slot_index})

    # Overall publishing status determination
    if is_real_youtube_upload(record):
        record["publishing_status"] = (
            "SCHEDULED"
            if (record.get("schedule_confirmed") and record.get("scheduled_publish_at"))
            else "PUBLISHED"
        )
        record["published_at"] = record.get("youtube_published_at") or datetime.now(timezone.utc).isoformat()
    elif record.get("youtube_simulated") or record.get("youtube_status") == "SIMULATED":
        record["publishing_status"] = "SIMULATED"
        record["published_at"] = record.get("youtube_published_at") or datetime.now(timezone.utc).isoformat()
    elif yt_uploaded_now:
        record["publishing_status"] = "PUBLISHED"
        record["published_at"] = record.get("youtube_published_at") or datetime.now(timezone.utc).isoformat()
    else:
        record["publishing_status"] = "PUBLISHED" if record.get("publishing_status") == "PUBLISHED" else "PENDING"

    db.save_video_record(video_id, record)
    logger.info(
        f"Publishing flow complete for {video_id}. Status: {record.get('publishing_status')}, "
        f"YouTube: {record.get('youtube_status') or record.get('youtube_upload_id')}, "
        f"Instagram: {record.get('instagram_status')}"
    )
    return record
