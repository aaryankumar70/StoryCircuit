"""Pipeline Integration for CurioLoop Creator Series & Dual-Lane Scheduler.

Handles Creator Series rendering and record creation in its own production lane.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from curiosity_engine.config import MAX_DURATION_SEC, MIN_DURATION_SEC, OUTPUT_DIR, YOUTUBE_PUBLISHING_MODE
from curiosity_engine.creator_series.creator_queue import creator_queue_manager
from curiosity_engine.creator_series.models import (
    EpisodeRecord,
    EpisodeStatus,
    RightsStatus,
    SeriesRecord,
    SeriesStatus,
)
from curiosity_engine.creator_series.series_db import series_db
from curiosity_engine.generation import GenerationEngineError, engine_registry
from curiosity_engine.production.aligner import align_narration_words
from curiosity_engine.production.renderer import current_render_matches, render_project_video, validate_rendered_mp4
from curiosity_engine.production.tts_engine import synthesize_narration
from curiosity_engine.distribution.youtube_publisher import youtube_publisher
from curiosity_engine.state.db import db

logger = logging.getLogger("curiosity_engine.creator_pipeline")


def _creator_audio_assets_match(project_dir: Path) -> bool:
    """Reuse narration/alignment only when the immutable project script still matches."""
    try:
        script = json.loads((project_dir / "script.json").read_text(encoding="utf-8"))
        lines_data = json.loads((project_dir / "data" / "lines.json").read_text(encoding="utf-8"))
        words = json.loads((project_dir / "data" / "words.json").read_text(encoding="utf-8"))
        lines = script.get("lines") or []
        aligned = lines_data.get("lines") or []
        if len(lines) != len(aligned) or not lines or not isinstance(words, list):
            return False
        if not (MIN_DURATION_SEC <= float(lines_data.get("duration") or 0) <= MAX_DURATION_SEC):
            return False
        if any(str(src.get("text") or "") != str(dst.get("text") or "") for src, dst in zip(lines, aligned)):
            return False
        expected_words = sum(len(str(line.get("text") or "").split()) for line in lines)
        if len(words) != expected_words or any(not all(key in word for key in ("w", "s", "e", "line")) for word in words):
            return False
        narration = project_dir / "data" / "narration.wav"
        return narration.is_file() and narration.stat().st_size > 10_000
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def get_slot2_content_choice() -> Tuple[str, Optional[Tuple[SeriesRecord, EpisodeRecord]]]:
    """Check if an active Creator Series has an eligible next episode for Slot 2.
    Returns:
        ("creator_series", (active_series, next_episode)) or ("automatic", None)
    """
    active_series = series_db.get_active_series()
    if not active_series:
        logger.info("No active Creator Series found. Slot 2 will use automatic Lane A content.")
        return "automatic", None

    next_ep = series_db.get_next_eligible_episode(active_series.series_id)
    if not next_ep:
        logger.info(
            f"Active series '{active_series.series_id}' has no eligible next episode "
            f"(next_num={active_series.next_episode_num}). Slot 2 will use automatic Lane A content."
        )
        return "automatic", None

    logger.info(
        f"Slot 2 prioritized for Creator Series '{active_series.series_id}' Ep {next_ep.episode_num} ('{next_ep.title}')."
    )
    return "creator_series", (active_series, next_ep)


def produce_creator_series_slot(
    video_id: str,
    series: SeriesRecord,
    episode: EpisodeRecord,
    target_date: str,
    force_rebuild: bool = False,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Render a Creator episode via the configured VisualRenderingEngine.
    If the visual engine is unconfigured, marks episode as ENGINE_NOT_CONFIGURED and safely returns.
    """
    if not episode.is_approved:
        raise ValueError("Creator episode must have an approved storyboard before rendering.")

    if not engine_registry.get_visual_engine().is_configured():
        visual_engine = engine_registry.get_visual_engine()
        reason = getattr(visual_engine, "not_configured_reason", None)
        msg = reason() if callable(reason) else "Visual rendering engine is not configured. Creator episode safely held in ENGINE_NOT_CONFIGURED state."
        logger.warning(f"[{video_id}] {msg}")
        episode.status = EpisodeStatus.ENGINE_NOT_CONFIGURED
        episode.error = msg
        series_db.save_episode(episode)
        return {
            "status": "ENGINE_NOT_CONFIGURED",
            "error": msg,
            "video_id": video_id,
            "series_id": series.series_id,
            "episode_id": episode.episode_id,
        }

    # Safety Check: Rights and permissions
    if series.rights_status == RightsStatus.UNVERIFIED_EVALUATION_ONLY:
        logger.info("Series '%s' has unverified rights; rendering remains local until verified.", series.series_id)

    # Delegate project preparation to active visual engine
    visual_engine = engine_registry.get_visual_engine()
    project_dir = visual_engine.prepare_project(
        video_id=video_id,
        script_data={"title": series.title, "episode": episode.to_dict()},
        output_dir=output_dir or OUTPUT_DIR,
    )

    output_mp4 = (Path(output_dir) if output_dir else OUTPUT_DIR) / f"{video_id}.mp4"
    rendered_meta = None
    if output_mp4.is_file() and current_render_matches(output_mp4, project_dir) and not force_rebuild:
        logger.info("[%s] Reusing the MP4 bound to this exact approved Creator script.", video_id)
        rendered_meta = validate_rendered_mp4(output_mp4)
    elif output_mp4.exists() and not force_rebuild:
        raise GenerationEngineError("A different existing MP4 occupies this Creator video ID; it was preserved. Choose a new video ID or explicitly request force_rebuild.")
    else:
        if _creator_audio_assets_match(project_dir):
            logger.info("[%s] Reusing matching Creator narration and word alignment.", video_id)
        else:
            logger.info(f"[{video_id}] Synthesizing creator series narration...")
            synthesize_narration(project_dir)
            logger.info(f"[{video_id}] Aligning creator series timestamps...")
            align_narration_words(project_dir)

        logger.info(f"[{video_id}] Rendering video to {output_mp4}...")
        render_project_video(project_dir, output_mp4, resume=not force_rebuild, force_rebuild=force_rebuild)
        rendered_meta = validate_rendered_mp4(output_mp4)

    # Validate Rendered MP4
    try:
        actual_dur = float(json.loads((project_dir / "data" / "lines.json").read_text(encoding="utf-8"))["duration"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        actual_dur = float(rendered_meta["duration"])
    meta = validate_rendered_mp4(output_mp4, expected_duration=actual_dur)
    render_script = json.loads((project_dir / "script.json").read_text(encoding="utf-8"))
    render_script.update({
        "id": episode.episode_id,
        "topic": f"{series.title} | Part {episode.episode_num}",
        "category": "CreatorSeries",
        "evidence_type": "creator_provided",
        "sources": (episode.source_segment or {}).get("sources", []),
    })
    from curiosity_engine.quality.provenance import build_production_provenance
    provenance = build_production_provenance(
        video_id=video_id,
        content_lane="creator_series",
        topic_id=series.series_id,
        script_data=render_script,
        original_source_id=series.series_id,
    )
    qc_metadata = {
        "video_id": video_id,
        "content_lane": "creator_series",
        "category": "CreatorSeries",
        "topic": render_script["topic"],
        "script": render_script,
        "script_hash": provenance["script_hash"],
        "provenance": provenance,
        "sources": render_script["sources"],
        "evidence_type": "creator_provided",
    }
    from curiosity_engine.quality.qc_gatekeeper import verify_video
    qc_report = verify_video(output_mp4, qc_metadata, project_dir=project_dir)
    qc_payload = qc_report.to_dict()

    # Persist Creator status from actual programmatic QC before the queue can publish.
    episode.status = EpisodeStatus.QC_PASSED if qc_report.passed else EpisodeStatus.QC_FAILED
    episode.actual_duration = meta["duration"]
    episode.audio_path = str(project_dir / "data" / "mix.wav")
    episode.visual_storyboard_path = str(project_dir / "storyboard.json")
    episode.rendered_video_path = str(output_mp4)
    episode.qc_result = qc_payload
    series_db.save_episode(episode)

    prior_record = db.get_video_record(video_id) or {}
    record_data = {
        **prior_record,
        "video_id": video_id,
        "slot_index": None,
        "target_date": target_date,
        "is_creator_series": True,
        "content_lane": "creator_series",
        "provenance": provenance,
        "series_id": series.series_id,
        "episode_id": episode.episode_id,
        "episode_num": episode.episode_num,
        "rights_status": series.rights_status.value if hasattr(series.rights_status, "value") else str(series.rights_status),
        "visual_profile": series.visual_profile,
        "topic": f"{series.title} | Part {episode.episode_num}",
        "category": "CreatorSeries",
        "style": "cartoon_3d",
        "visual_engine": visual_engine.__class__.__name__,
        "project_path": str(project_dir),
        "duration_sec": meta["duration"],
        "local_video_path": str(output_mp4),
        "qc_passed": bool(qc_report.passed),
        "production_status": "COMPLETED" if qc_report.passed else "QC_FAILED",
        "qc_results": qc_payload,
        "script": render_script,
        "script_hash": provenance["script_hash"],
        "sources": render_script["sources"],
        "evidence_type": "creator_provided",
        "visual_qc": qc_payload.get("checks", {}).get("sub_scores", {}),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.save_video_record(video_id, record_data)
    logger.info(f"Creator series episode {episode.episode_id} successfully produced ({meta['duration']:.2f}s).")
    return record_data


def process_creator_queue_once(now: Optional[datetime] = None) -> bool:
    """Claim and execute one due Creator job without entering either Automatic slot."""
    job = creator_queue_manager.claim_next_due(now=now)
    if not job:
        return False
    job_id = job["job_id"]
    episode = None
    try:
        series = series_db.get_series(job["series_id"])
        episode = series_db.get_episode(job["episode_id"])
        if not series or not episode:
            raise ValueError("Scheduled Creator series or episode no longer exists.")
        if series.status != SeriesStatus.ACTIVE:
            raise ValueError(f"Creator series is {series.status.value}; production is paused.")
        if not episode.is_approved:
            raise ValueError("Episode approval was removed after scheduling.")

        video_id = f"creator_{series.series_id}_ep{episode.episode_num:03d}"
        existing_upload = db.get_video_record(video_id) or {}
        if existing_upload.get("youtube_upload_id"):
            creator_queue_manager.mark_completed(job_id, {"video_id": video_id, "deduplicated": True})
            return True
        if existing_upload.get("publishing_status") in ("UPLOAD_IN_PROGRESS", "UPLOAD_OUTCOME_UNKNOWN"):
            db.save_video_record(video_id, {"publishing_status": "UPLOAD_OUTCOME_UNKNOWN"})
            creator_queue_manager.mark_failed(job_id, "A previous upload attempt has an unknown outcome; reconcile the YouTube record before retrying.", retry=False)
            return True
        record = produce_creator_series_slot(
            video_id=video_id,
            series=series,
            episode=episode,
            target_date=datetime.fromisoformat(job["scheduled_at"]).date().isoformat(),
        )
        if not record.get("qc_passed"):
            raise RuntimeError("Creator render did not pass visual quality control.")
        if creator_queue_manager.cancellation_requested(job_id):
            creator_queue_manager.mark_failed(job_id, "Cancelled before publishing.", retry=False)
            return True


        rights = series.rights_status.value if hasattr(series.rights_status, "value") else str(series.rights_status)
        permitted_rights = {RightsStatus.OWNED.value, RightsStatus.LICENSED.value, RightsStatus.PUBLIC_DOMAIN.value}
        if YOUTUBE_PUBLISHING_MODE == "live" and rights not in permitted_rights:
            reason = "Live publishing is blocked until ownership, license, or public-domain status is verified."
            db.save_video_record(video_id, {"publishing_status": "RIGHTS_HOLD", "rights_hold_reason": reason})
            episode.status = EpisodeStatus.READY_FOR_PUBLISHING
            episode.upload_status = "BLOCKED_RIGHTS"
            series_db.save_episode(episode)
            creator_queue_manager.mark_rights_hold(job_id, reason)
            return True

        publish_at = datetime.fromisoformat(job["scheduled_at"].replace("Z", "+00:00"))
        if publish_at.tzinfo is None:
            raise ValueError("Scheduled Creator publication time must be timezone-aware.")
        if YOUTUBE_PUBLISHING_MODE == "live" and publish_at.astimezone(timezone.utc) <= datetime.now(timezone.utc) + timedelta(minutes=5):
            db.save_video_record(video_id, {
                "publishing_status": "MISSED_CREATOR_WINDOW",
                "publication_recovery_required": True,
            })
            creator_queue_manager.mark_failed(job_id, "Render completed too late for the committed publication time. Commit a new schedule to retry.", retry=False)
            return True

        creator_info = series.creator_info or {}
        attribution = creator_info.get("attribution") or creator_info.get("name") or "Creator Series"
        source_url = creator_info.get("source") or ""
        description = f"{series.title} — Episode {episode.episode_num}.\n\nSource: {attribution}"
        if source_url:
            description += f"\nOriginal source: {source_url}"
        publish_decision = creator_queue_manager.begin_publish(job_id)
        if publish_decision == "PAUSED":
            return True
        if publish_decision != "STARTED":
            creator_queue_manager.mark_failed(job_id, "Cancelled before publishing began.", retry=False)
            return True
        db.save_video_record(video_id, {
            "publishing_status": "UPLOAD_IN_PROGRESS",
            "creator_series_id": series.series_id,
            "creator_episode_id": episode.episode_id,
            "source_url": source_url,
            "source_attribution": attribution,
            "rights_status": rights,
            "scheduled_publish_at": publish_at.isoformat(),
        })
        upload = youtube_publisher.upload_short(
            video_path=Path(record["local_video_path"]),
            title=f"{episode.title} | {series.title}",
            description=description,
            tags=["CurioLoop", "Story", series.visual_profile],
            privacy_status="private",
            publish_at=publish_at,
            force_mode=YOUTUBE_PUBLISHING_MODE,
        )
        db.save_video_record(video_id, {
            "youtube_upload_id": upload.get("video_id"),
            "youtube_simulated": bool(upload.get("simulated")),
            "youtube_privacy_status": upload.get("privacy_status", "private"),
            "scheduled_publish_at": upload.get("publish_at"),
            "schedule_confirmed": bool(upload.get("schedule_confirmed")),
            "publishing_status": "SIMULATED" if upload.get("simulated") else "SCHEDULED",
            "youtube_url": upload.get("url"),
        })
        episode.youtube_id = upload.get("video_id")
        episode.upload_status = "SIMULATED" if upload.get("simulated") else "SCHEDULED"
        if not upload.get("simulated"):
            episode.status = EpisodeStatus.SCHEDULED
        series_db.save_episode(episode)
        creator_queue_manager.mark_completed(job_id, {"video_id": video_id, "upload": upload})
        return True
    except Exception as exc:
        logger.exception("Creator queue job %s failed: %s", job_id, exc)
        if episode:
            episode.retry_count += 1
            series_db.save_episode(episode)
        creator_queue_manager.mark_failed(job_id, str(exc), retry=True)
        return True
