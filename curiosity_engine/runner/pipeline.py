"""Production and Publishing Pipelines for Curiosity Engine.
Coordinates content, production, QC, cloud storage, and social distribution.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from curiosity_engine.config import (
    INSTAGRAM_PUBLISHING_MODE,
    MAX_DAILY_VIDEOS,
    MAX_QC_RECOVERY_ATTEMPTS,
    OUTPUT_DIR,
    SCHEDULER_TIMEZONE,
    YOUTUBE_PRIVACY_STATUS,
    YOUTUBE_PUBLISHING_MODE,
    get_hidden_subprocess_kwargs,
)
from curiosity_engine.content.description_generator import (
    build_youtube_tags,
    description_generator,
    generate_youtube_title,
)
from curiosity_engine.content.scriptwriter import (
    assign_line_scenes,
    revise_script_for_duration,
    write_video_script,
)
from curiosity_engine.content.topic_discovery import select_daily_topics
from curiosity_engine.distribution.instagram_publisher import instagram_publisher
from curiosity_engine.distribution.youtube_publisher import (
    NON_PRODUCTION_TEST_YOUTUBE_IDS,
    DailyPublishingLimitError,
    YouTubePublisherError,
    youtube_publisher,
)
from curiosity_engine.production.director import prepare_project
from curiosity_engine.production.renderer import render_project_video, validate_rendered_mp4
from curiosity_engine.quality.qc_gatekeeper import verify_video
from curiosity_engine.runner.progress_tracker import (
    complete_qc_recovery,
    record_stage_checkpoint,
    record_stage_complete,
    record_stage_failed,
    record_stage_start,
)
from curiosity_engine.state.db import db

logger = logging.getLogger("curiosity_engine.pipeline")
IST = ZoneInfo(SCHEDULER_TIMEZONE)


def _compute_file_sha256(path: Path) -> Optional[str]:
    """Compute SHA-256 hex digest of a file if it exists, else None."""
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_ffmpeg_loudnorm_fix(source_mp4: Path, target_mp4: Path) -> bool:
    """Apply EBU R128 loudness normalization in-place via staging file (audio fix without altering visuals)."""
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(source_mp4),
            "-af", "loudnorm=I=-16.0:TP=-1.5:LRA=7.0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            str(target_mp4),
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            **get_hidden_subprocess_kwargs(),
        )
        return res.returncode == 0 and target_mp4.exists() and target_mp4.stat().st_size > 100_000
    except Exception as exc:
        logger.warning("Audio loudnorm recovery pass failed (%s); falling back to full rebuild.", exc)
        return False


def _choose_recovery_strategy(qc_report: Any) -> Tuple[str, str]:
    """Determine targeted recovery strategy cleanly from categorized QC issues."""
    checks = getattr(qc_report, "checks", {}) or {}
    cats = set(checks.get("failure_categories") or [])
    issues_txt = " ".join(getattr(qc_report, "issues", []) or []).lower()

    if "duration_exceeded" in cats or "duration_too_short" in cats or "duration" in issues_txt:
        if "exceed" in issues_txt or "duration_exceeded" in cats:
            return "revise_script_duration_down", "Revising script and re-rendering video within 20-60s."
        return "revise_script_duration_up", "Expanding story depth and re-rendering within 20-60s."
    if "sync_mismatch" in cats or "caption" in issues_txt or "drift" in issues_txt:
        return "resync_tts_alignment", "Re-aligning narration timings and regenerating fresh render."
    if ("audio_loudness" in cats or "audio_codec" in cats or "loudness" in issues_txt or "true peak" in issues_txt) and not (
        {"integrity_missing", "integrity_codec", "visual_black_frames", "visual_geometry"} & cats
    ):
        return "audio_normalization", "Normalizing audio loudness/codec and verifying broadcast standards."
    if "visual_black_frames" in cats or "visual_geometry" in cats or "black frame" in issues_txt:
        return "regenerate_visual_sequence", "Regenerating visual scene choreography and fresh render."
    return "full_fresh_render", "Rebuilding assets cleanly and rendering a fresh output MP4."


def _execute_recovery_attempt(
    attempt: int,
    video_id: str,
    project_dir: Path,
    output_mp4: Path,
    script_data: Dict[str, Any],
    qc_report: Any,
    prev_hash: Optional[str],
) -> Tuple[Dict[str, Any], Path, str, str]:
    """Execute one targeted recovery action, guaranteeing a fresh output artifact before re-QC."""
    attempt_id = f"{video_id}_rec{attempt}"
    strategy, action_desc = _choose_recovery_strategy(qc_report)
    checks = getattr(qc_report, "checks", {}) or {}
    curr_dur = float(checks.get("duration_sec") or 0.0)
    updated_script = dict(script_data)

    logger.info(
        "[%s] QC Recovery Attempt %d/2 (%s): strategy=%s",
        video_id,
        attempt,
        attempt_id,
        strategy,
    )

    if strategy in ("revise_script_duration_down", "revise_script_duration_up"):
        fallback_dur = 65.0 if strategy == "revise_script_duration_down" else 17.0
        revised_script, rev_note = revise_script_for_duration(
            updated_script,
            curr_dur if curr_dur > 0 else fallback_dur,
        )
        updated_script = revised_script
        action_desc = rev_note
        record_stage_checkpoint(
            video_id,
            "qc_recovery",
            0.25,
            rev_note,
            extra_detail={"substage": "revising_script", "next_action": rev_note},
            db_client=db,
        )
        prep_dir = prepare_project(video_id, updated_script)
        render_project_video(prep_dir, output_mp4, resume=False, force_rebuild=True)
        return updated_script, prep_dir, strategy, action_desc

    if strategy == "audio_normalization" and output_mp4.exists():
        record_stage_checkpoint(
            video_id,
            "qc_recovery",
            0.65,
            "Applying EBU R128 loudness normalization",
            extra_detail={"substage": "audio_normalization"},
            db_client=db,
        )
        staged = output_mp4.with_name(f".{attempt_id}_norm.mp4")
        if _run_ffmpeg_loudnorm_fix(output_mp4, staged):
            staged.replace(output_mp4)
            return updated_script, project_dir, strategy, "Applied FFmpeg EBU R128 loudness normalization"
        # Fallback if audio-only mux failed (e.g. corrupt stream): remove & run fresh render cleanly

    if strategy == "regenerate_visual_sequence":
        for idx, ln in enumerate(updated_script.get("lines") or []):
            if isinstance(ln, dict):
                sc = dict(ln.get("scene") or {})
                alt_moods = ("wonder", "calm", "tense")
                sc["mood"] = alt_moods[idx % len(alt_moods)]
                ln["scene"] = sc
        assign_line_scenes(updated_script)

    # Remove prior failed MP4 so render_project_video never reuses the failed artifact
    try:
        if output_mp4.exists():
            output_mp4.unlink()
    except Exception:
        pass

    prep_dir = project_dir
    if strategy in ("resync_tts_alignment", "regenerate_visual_sequence") or not _has_valid_project_assets(project_dir):
        prep_dir = prepare_project(video_id, updated_script)
    render_project_video(prep_dir, output_mp4, resume=False, force_rebuild=True)
    return updated_script, prep_dir, strategy, action_desc


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
        "evidence_type": base_record.get("evidence_type") or topic_info.get("evidence_type", "documented_fact"),
        "discovery_origin": base_record.get("discovery_origin") or topic_info.get("discovery_origin", "curated_research"),
        "production_status": "STARTING",
        "publishing_status": base_record.get("publishing_status") or "PENDING",
        "recovery_attempts": 0 if force_rebuild else int(base_record.get("recovery_attempts") or 0),
        "qc_recovery_history": [] if force_rebuild else list(base_record.get("qc_recovery_history") or []),
        "created_at": base_record.get("created_at") or datetime.now(timezone.utc).isoformat(),
    }
    if force_rebuild:
        record["failed_mp4_sha256"] = None
    db.save_video_record(video_id, record)
    if record.get("topic"):
        record_stage_start(video_id, "selecting_topic", db_client=db)
        record_stage_complete(video_id, "selecting_topic", db_client=db)

    # Notify Telegram immediately when production begins (never blocks execution)
    try:
        from curiosity_engine.notifications.telegram_notifier import get_telegram_notifier
        sched_window = "12:30 PM IST" if int(slot_index) == 1 else "8:30 PM IST"
        get_telegram_notifier().notify_production_started(
            video_id=video_id,
            date_str=target_date,
            slot_index=slot_index,
            scheduled_time_ist=sched_window,
            topic=str(record.get("topic") or topic_info.get("topic") or ""),
            dedup_tag="rebuild" if force_rebuild else "",
        )
    except Exception:
        pass

    try:
        # Respect prior exhausted QC recovery limit cleanly instead of re-testing the exact failed file
        current_disk_hash = _compute_file_sha256(output_mp4)
        prior_failed_hash = record.get("failed_mp4_sha256")
        prior_attempts = int(record.get("recovery_attempts") or 0)
        if (
            not force_rebuild
            and prior_attempts >= MAX_QC_RECOVERY_ATTEMPTS
            and current_disk_hash
            and current_disk_hash == prior_failed_hash
        ):
            raise RuntimeError(
                record.get("error")
                or f"Video {video_id} previously exhausted {MAX_QC_RECOVERY_ATTEMPTS} QC recovery attempts."
            )

        # 2. Scriptwriting & Source Verification (reuse valid saved script when resuming)
        script_data = None
        record_stage_start(video_id, "writing_script", db_client=db)
        if not force_rebuild and isinstance(record.get("script"), dict) and record["script"].get("lines"):
            script_data = record["script"]
            assign_line_scenes(script_data)
            logger.info(f"[{video_id}] Reusing existing verified script for '{record.get('topic')}'.")
        else:
            logger.info(f"[{video_id}] Writing storytelling script and verifying internal sources...")
            script_data = write_video_script(topic_info)
            record["script"] = script_data
            record["sources"] = script_data.get("sources", [])
            record["claims"] = script_data.get("claims", [])
            record["evidence_type"] = script_data.get("evidence_type", record.get("evidence_type"))
            record["discovery_origin"] = script_data.get("discovery_origin", record.get("discovery_origin"))
            record["production_status"] = "SCRIPTED"

        # 2b. Link-Free YouTube Title, Description & Separate API Tags Generation
        if not force_rebuild and record.get("youtube_description"):
            logger.info(f"[{video_id}] Preserving existing YouTube description.")
            if not record.get("youtube_title"):
                record["youtube_title"] = generate_youtube_title(
                    record.get("topic") or "", script_data
                )
            if not record.get("youtube_tags"):
                record["youtube_tags"] = build_youtube_tags(
                    record.get("topic") or "", record.get("category") or "Science", script_data
                )
        else:
            logger.info(f"[{video_id}] Generating link-free YouTube title, description & search tags...")
            desc_data = description_generator.generate(
                topic=record.get("topic") or topic_info.get("topic", ""),
                category=record.get("category") or topic_info.get("category", ""),
                script_data=script_data,
                sources=record.get("sources", []),
                claims=record.get("claims", []),
            )
            record["youtube_description"] = desc_data["full_description"]
            record["youtube_title"] = desc_data.get("recommended_title") or generate_youtube_title(
                record.get("topic") or "", script_data
            )
            record["youtube_tags"] = desc_data.get("youtube_tags") or build_youtube_tags(
                record.get("topic") or "", record.get("category") or "Science", script_data
            )
            record["description_data"] = desc_data
        db.save_video_record(video_id, record)
        record_stage_complete(video_id, "writing_script", db_client=db)

        # 3. Check if valid rendered MP4 already exists on disk (NEVER reuse an unchanged previously failed MP4!)
        rendered_valid = False
        is_same_failed_file = bool(prior_failed_hash and current_disk_hash and current_disk_hash == prior_failed_hash)
        if not force_rebuild and output_mp4.exists() and not is_same_failed_file:
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
        elif is_same_failed_file:
            logger.info(f"[{video_id}] Existing MP4 matches previously rejected failed hash; skipping redundant unchanged QC.")

        if not rendered_valid and not is_same_failed_file:
            # 3b. Preparation: TTS and Alignment (resume from valid project assets if intact)
            if not force_rebuild and _has_valid_project_assets(project_dir):
                logger.info(f"[{video_id}] Resuming from valid existing ASSETS_READY project at {project_dir}.")
                record_stage_complete(video_id, "generating_narration", db_client=db)
                record["production_status"] = "ASSETS_READY"
                db.save_video_record(video_id, record)
            else:
                logger.info(f"[{video_id}] Preparing project assets, voice, and timing...")
                project_dir = prepare_project(video_id, script_data)
                record = db.get_video_record(video_id) or record
                record["production_status"] = "ASSETS_READY"
                db.save_video_record(video_id, record)

            # 4. Headless Chrome Frame Rendering & FFmpeg Assembly
            logger.info(f"[{video_id}] Rendering frames to {output_mp4}...")
            render_project_video(project_dir, output_mp4, resume=not force_rebuild, force_rebuild=force_rebuild)
            record = db.get_video_record(video_id) or record
            record["local_video_path"] = str(output_mp4)
            record["production_status"] = "RENDERED"
            db.save_video_record(video_id, record)
        elif rendered_valid:
            record_stage_complete(video_id, "generating_narration", db_client=db)
            record_stage_complete(video_id, "preparing_visuals", db_client=db)
            record_stage_complete(video_id, "rendering_video", db_client=db)
            record = db.get_video_record(video_id) or record
            record["local_video_path"] = str(output_mp4)
            record["production_status"] = "RENDERED"
            db.save_video_record(video_id, record)

        # 5. Programmatic Quality Control Gatekeeper (+ Bounded Automatic Recovery up to 2 attempts)
        record["production_status"] = "QC_RUNNING"
        db.save_video_record(video_id, record)
        record_stage_start(video_id, "running_qc", db_client=db)

        if is_same_failed_file and record.get("qc_results"):
            # Reconstruct last failed QC report without running redundant QC on identical unchanged file
            prev_qc = record["qc_results"]
            from curiosity_engine.quality.qc_gatekeeper import QCReport
            qc_report = QCReport(
                passed=False,
                checks=prev_qc.get("checks", {}),
                issues=list(prev_qc.get("issues") or [record.get("error") or "Prior QC failure"]),
            )
            current_hash = current_disk_hash
        else:
            logger.info(f"[{video_id}] Running Quality Control checks...")
            qc_report = verify_video(output_mp4, script_data, project_dir=project_dir)
            current_hash = _compute_file_sha256(output_mp4)

        record["qc_passed"] = qc_report.passed
        record["qc_results"] = qc_report.to_dict()
        if qc_report.checks.get("duration_sec"):
            record["duration_sec"] = qc_report.checks["duration_sec"]

        if qc_report.passed:
            record_stage_complete(video_id, "running_qc", db_client=db)

        if not qc_report.passed:
            original_issues = list(qc_report.issues)
            record["original_qc_issues"] = record.get("original_qc_issues") or original_issues
            record["failed_mp4_sha256"] = current_hash
            record["production_status"] = "REJECTED_QC"
            record["error"] = f"QC Failed: {'; '.join(original_issues)}"
            db.save_video_record(video_id, {k: v for k, v in record.items() if k not in ("stage_progress", "lifecycle_stage")})
            db.log_error("QC_GATEKEEPER", f"Video {video_id} failed QC", {"issues": original_issues})

            attempts_done = int(record.get("recovery_attempts") or 0)
            while not qc_report.passed and attempts_done < MAX_QC_RECOVERY_ATTEMPTS:
                next_attempt = attempts_done + 1
                strategy, next_action_desc = _choose_recovery_strategy(qc_report)
                record["production_status"] = "RECOVERING"
                record["recovery_attempts"] = next_attempt
                db.save_video_record(video_id, {k: v for k, v in record.items() if k not in ("stage_progress", "lifecycle_stage")})
                record_stage_start(
                    video_id,
                    "qc_recovery",
                    detail={
                        "attempt": next_attempt,
                        "max_attempts": MAX_QC_RECOVERY_ATTEMPTS,
                        "reason": "; ".join(qc_report.issues)[:240],
                        "next_action": next_action_desc,
                        "strategy": strategy,
                        "substage": "starting_recovery",
                    },
                    db_client=db,
                )

                try:
                    from curiosity_engine.notifications.telegram_notifier import get_telegram_notifier
                    get_telegram_notifier().notify_qc_failed(
                        video_id=video_id,
                        topic=str(record.get("topic") or video_id),
                        slot_index=slot_index,
                        reason="; ".join(qc_report.issues),
                        attempt=next_attempt,
                        max_attempts=MAX_QC_RECOVERY_ATTEMPTS,
                        next_action=next_action_desc,
                    )
                except Exception:
                    pass

                rec_error = None
                try:
                    updated_script, project_dir, used_strategy, action_desc = _execute_recovery_attempt(
                        attempt=next_attempt,
                        video_id=video_id,
                        project_dir=project_dir,
                        output_mp4=output_mp4,
                        script_data=script_data,
                        qc_report=qc_report,
                        prev_hash=current_hash,
                    )
                    script_data = updated_script
                    record["script"] = script_data
                    record["local_video_path"] = str(output_mp4)
                except Exception as exc:
                    rec_error = str(exc)
                    used_strategy = strategy
                    action_desc = f"Recovery raised {rec_error}"

                new_hash = _compute_file_sha256(output_mp4)
                # NEVER pass QC against the exact same unchanged failed output artifact!
                if rec_error:
                    from curiosity_engine.quality.qc_gatekeeper import QCReport
                    qc_report = QCReport(False, {"failure_categories": ["recovery_error"]}, [rec_error])
                elif not new_hash or (current_hash and new_hash == current_hash):
                    from curiosity_engine.quality.qc_gatekeeper import QCReport
                    qc_report = QCReport(
                        False,
                        {"failure_categories": ["unchanged_failed_output"]},
                        [f"Recovery attempt {next_attempt} did not produce a new/changed output MP4."],
                    )
                else:
                    record_stage_checkpoint(
                        video_id,
                        "qc_recovery",
                        0.92,
                        "Re-running QC verification on recovered MP4",
                        extra_detail={"substage": "running_qc"},
                        db_client=db,
                    )
                    qc_report = verify_video(output_mp4, script_data, project_dir=project_dir)

                record["qc_recovery_history"].append({
                    "attempt": next_attempt,
                    "attempt_id": f"{video_id}_rec{next_attempt}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "original_issues": original_issues,
                    "strategy": used_strategy,
                    "action_taken": action_desc,
                    "sha256_before": current_hash,
                    "sha256_after": new_hash,
                    "passed": qc_report.passed,
                    "issues_after": list(qc_report.issues),
                    "duration_sec": qc_report.checks.get("duration_sec"),
                })
                record["qc_passed"] = qc_report.passed
                record["qc_results"] = qc_report.to_dict()
                if qc_report.checks.get("duration_sec"):
                    record["duration_sec"] = qc_report.checks["duration_sec"]
                current_hash = new_hash
                attempts_done = next_attempt

                if qc_report.passed:
                    record["failed_mp4_sha256"] = None
                    record["qc_recovered"] = True
                    record["production_status"] = "COMPLETED"
                    record["error"] = None
                    db.save_video_record(video_id, {k: v for k, v in record.items() if k not in ("stage_progress", "lifecycle_stage")})
                    complete_qc_recovery(video_id, db_client=db)
                    latest_rec = db.get_video_record(video_id)
                    if latest_rec and "stage_progress" in latest_rec:
                        record["stage_progress"] = latest_rec["stage_progress"]
                    logger.info(
                        "[%s] QC RECOVERED on attempt %d/%d (%s)!",
                        video_id,
                        next_attempt,
                        MAX_QC_RECOVERY_ATTEMPTS,
                        used_strategy,
                    )
                    try:
                        from curiosity_engine.notifications.telegram_notifier import get_telegram_notifier
                        get_telegram_notifier().notify_qc_recovered(
                            video_id=video_id,
                            topic=str(record.get("topic") or video_id),
                            slot_index=slot_index,
                            attempt=next_attempt,
                            duration_sec=qc_report.checks.get("duration_sec"),
                        )
                    except Exception:
                        pass
                    break
                else:
                    record["failed_mp4_sha256"] = new_hash
                    record["production_status"] = "REJECTED_QC"
                    record["error"] = (
                        f"QC Failed ({'; '.join(original_issues)}) | "
                        f"Recovery {next_attempt}/{MAX_QC_RECOVERY_ATTEMPTS} failed ({'; '.join(qc_report.issues)})"
                    )
                    db.save_video_record(video_id, {k: v for k, v in record.items() if k not in ("stage_progress", "lifecycle_stage")})

            if not qc_report.passed:
                try:
                    from curiosity_engine.notifications.telegram_notifier import get_telegram_notifier
                    get_telegram_notifier().notify_failure(
                        failure_type="PRODUCTION_FAILED",
                        title=f"QC recovery exhausted for {video_id}",
                        detail=f"Original: {'; '.join(original_issues)} | Latest: {'; '.join(qc_report.issues)}",
                        video_id=video_id,
                        dedup_key=f"prod_fail:{video_id}:{attempts_done}",
                    )
                except Exception:
                    pass
                raise RuntimeError(f"Video {video_id} rejected by QC: {original_issues} (exhausted {attempts_done}/{MAX_QC_RECOVERY_ATTEMPTS} recovery attempts)")

        record["production_status"] = "COMPLETED"
        record["failed_mp4_sha256"] = None
        record["error"] = None

        # 6. Record Local MP4 Storage URI
        record["storage_uri"] = str(output_mp4)
        db.save_video_record(video_id, {k: v for k, v in record.items() if k not in ("stage_progress", "lifecycle_stage")})
        latest_final = db.get_video_record(video_id)
        if isinstance(latest_final, dict):
            record["stage_progress"] = latest_final.get("stage_progress", record.get("stage_progress"))
        logger.info(f"=== Video {video_id} Produced & Passed QC Successfully ===")
        return record

    except Exception as e:
        logger.error(f"Error during video {video_id} production: {e}")
        # Keep ASSETS_READY if assets remain valid so retry resumes cleanly instead of losing stage state
        record["production_status"] = "FAILED"
        record["qc_passed"] = False
        record["error"] = str(e)
        db.save_video_record(video_id, {k: v for k, v in record.items() if k not in ("stage_progress", "lifecycle_stage")})
        err_lower = str(e).lower()
        cur_latest = db.get_video_record(video_id) or {}
        cur_active = (cur_latest.get("stage_progress") or {}).get("active_stage")
        fail_at = "running_qc" if ("rejected by qc" in err_lower or cur_active == "qc_recovery") else cur_active
        record_stage_failed(video_id, fail_at, str(e), db_client=db)
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

        for s_idx, v_id, needs_pick in ((1, video_1_id, need_s1 and not t1_info), (2, video_2_id, need_s2 and not t2_info)):
            if needs_pick:
                if not db.get_video_record(v_id):
                    db.save_video_record(v_id, {
                        "video_id": v_id,
                        "slot_index": s_idx,
                        "target_date": target_date,
                        "production_status": "SELECTING_TOPIC",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                record_stage_start(v_id, "selecting_topic", db_client=db)

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


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA-256 hex digest of a video file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_production_publication_record(record: Optional[Dict[str, Any]]) -> bool:
    """Return True only if record represents an active scheduled or public production publication.
    Never counts simulated uploads, private unscheduled staging/historical records,
    or disposable private test videos.
    """
    if not is_real_youtube_upload(record):
        return False
    if record.get("is_test") or record.get("video_type") == "test":
        return False
    yt_id = str(record.get("youtube_upload_id") or "")
    if yt_id in NON_PRODUCTION_TEST_YOUTUBE_IDS:
        return False
    if bool(record.get("schedule_confirmed") and record.get("scheduled_publish_at")):
        return True
    if record.get("youtube_privacy_status") == "public" and record.get("publishing_status") in ("PUBLISHED", "SCHEDULED"):
        return True
    return False


def get_production_publications_by_ist_date() -> Dict[str, List[Dict[str, Any]]]:
    """Group deduplicated production YouTube publications by their IST publication calendar date."""
    all_vids = db.get_all_videos(limit=500)
    if not isinstance(all_vids, list):
        all_vids = []

    by_date: Dict[str, List[Dict[str, Any]]] = {}
    seen_yt_ids: Set[str] = set()

    for rec in all_vids:
        if not isinstance(rec, dict) or not is_production_publication_record(rec):
            continue
        yt_id = str(rec.get("youtube_upload_id"))
        if yt_id in seen_yt_ids:
            continue

        ts_str = rec.get("scheduled_publish_at") or rec.get("youtube_published_at") or rec.get("published_at")
        if not ts_str:
            continue
        try:
            dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ist_dt = dt.astimezone(IST)
        except Exception:
            continue

        seen_yt_ids.add(yt_id)
        ist_date = ist_dt.strftime("%Y-%m-%d")
        by_date.setdefault(ist_date, []).append({
            "video_id": rec.get("video_id"),
            "youtube_upload_id": yt_id,
            "ist_datetime": ist_dt,
            "slot_time": ist_dt.strftime("%H:%M"),
        })

    return by_date


def get_occupied_publication_windows() -> Dict[str, Set[str]]:
    """Return mapping of IST calendar date -> occupied HH:MM publication slots."""
    by_date = get_production_publications_by_ist_date()
    return {
        date_str: {entry["slot_time"] for entry in entries}
        for date_str, entries in by_date.items()
    }


def assert_daily_publication_capacity(
    publish_at_dt: datetime,
    candidate_video_id: str,
    candidate_yt_id: Optional[str] = None,
) -> None:
    """Enforce maximum two production publications per IST calendar day and no slot double-booking."""
    if candidate_yt_id and str(candidate_yt_id) in NON_PRODUCTION_TEST_YOUTUBE_IDS:
        raise YouTubePublisherError(
            f"Refusing to publish/schedule protected disposable test video ID {candidate_yt_id}."
        )

    ist_dt = publish_at_dt.astimezone(IST)
    ist_date = ist_dt.strftime("%Y-%m-%d")
    slot_time = ist_dt.strftime("%H:%M")

    existing = [
        entry for entry in get_production_publications_by_ist_date().get(ist_date, [])
        if entry.get("video_id") != candidate_video_id
        and (not candidate_yt_id or entry.get("youtube_upload_id") != candidate_yt_id)
    ]

    if len(existing) >= MAX_DAILY_VIDEOS:
        raise DailyPublishingLimitError(
            f"Daily publishing limit reached for {ist_date} IST: "
            f"{len(existing)}/{MAX_DAILY_VIDEOS} production publications already scheduled "
            f"({[e.get('youtube_upload_id') for e in existing]})."
        )

    if any(entry.get("slot_time") == slot_time for entry in existing):
        raise DailyPublishingLimitError(
            f"Publication window {ist_date} {slot_time} IST is already occupied by another production video."
        )


def assert_no_duplicate_mp4_upload(video_path: Path, candidate_video_id: str) -> str:
    """Ensure the exact MP4 file bytes are never uploaded twice to YouTube across production records."""
    sha256 = compute_file_sha256(video_path)
    all_vids = db.get_all_videos(limit=500)
    if not isinstance(all_vids, list):
        all_vids = []

    for rec in all_vids:
        if not isinstance(rec, dict) or rec.get("video_id") == candidate_video_id:
            continue
        if is_real_youtube_upload(rec) and rec.get("mp4_sha256") == sha256:
            raise YouTubePublisherError(
                f"Duplicate MP4 upload blocked for {candidate_video_id}: "
                f"file matches already-uploaded {rec.get('video_id')} "
                f"(YouTube ID: {rec.get('youtube_upload_id')})."
            )
    return sha256


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
    title = record.get("youtube_title") or generate_youtube_title(
        record.get("topic", "Fascinating Fact"), script, duration_sec=record.get("duration_sec")
    )
    category = record.get("category", "Science")
    category_id = "27" if category in ["History", "Geography", "Interesting discoveries", "Mysteries", "Unexplained events"] else "28"

    tags = record.get("youtube_tags") or build_youtube_tags(
        record.get("topic", title), category, script
    )

    record["publishing_status"] = "UPLOADING"
    db.save_video_record(video_id, record)

    yt_uploaded_now = False

    # 1. Independent YouTube Shorts Upload
    if not has_real_yt and (force_publish or not (record.get("youtube_upload_id") and effective_yt_mode == "simulation")):
        record_stage_start(video_id, "uploading_privately", db_client=db)
        try:
            logger.info(f"Publishing {video_id} to YouTube Shorts (Mode: {effective_yt_mode})...")
            mp4_sha256: Optional[str] = None
            if effective_yt_mode == "live":
                mp4_sha256 = assert_no_duplicate_mp4_upload(local_path, video_id)
                target_cap_dt = datetime.now(IST)
                if record.get("scheduled_publish_at"):
                    try:
                        target_cap_dt = datetime.fromisoformat(
                            str(record["scheduled_publish_at"]).replace("Z", "+00:00")
                        ).astimezone(IST)
                    except Exception:
                        target_cap_dt = datetime.now(IST)
                assert_daily_publication_capacity(target_cap_dt, candidate_video_id=video_id)

            yt_description = record.get("youtube_description")
            if not yt_description:
                desc_data = description_generator.generate(
                    topic=record.get("topic", title),
                    category=category,
                    script_data=script,
                    sources=record.get("sources", []),
                    claims=record.get("claims", []),
                )
                yt_description = desc_data["full_description"]
                record["youtube_description"] = yt_description
                if not record.get("youtube_tags"):
                    tags = desc_data.get("youtube_tags") or tags
                    record["youtube_tags"] = tags

            all_vids_for_excl = db.get_all_videos(limit=100)
            if not isinstance(all_vids_for_excl, list):
                all_vids_for_excl = []
            other_real_yt_ids = set(NON_PRODUCTION_TEST_YOUTUBE_IDS) | {
                str(r.get("youtube_upload_id"))
                for r in all_vids_for_excl
                if isinstance(r, dict) and r.get("video_id") != video_id and is_real_youtube_upload(r)
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
            if mp4_sha256 and not yt_res.get("simulated"):
                record["mp4_sha256"] = mp4_sha256
            if yt_res.get("publish_at") and record["schedule_confirmed"]:
                record["scheduled_publish_at"] = yt_res.get("publish_at")
            record["youtube_status"] = (
                "SIMULATED" if yt_res.get("simulated")
                else ("SCHEDULED" if record["schedule_confirmed"] else "PUBLISHED")
            )
            record_stage_complete(video_id, "uploading_privately", db_client=db)
            if record["schedule_confirmed"]:
                record_stage_complete(video_id, "scheduling_publication", db_client=db)
            yt_uploaded_now = True
        except Exception as yt_err:
            record["youtube_status"] = "FAILED"
            record["youtube_error"] = str(yt_err)
            record["publishing_status"] = "PUBLISH_FAILED"
            db.save_video_record(video_id, {k: v for k, v in record.items() if k not in ("stage_progress", "lifecycle_stage")})
            record_stage_failed(video_id, "uploading_privately", str(yt_err), db_client=db)
            db.log_error("YOUTUBE_PUBLISHER", f"Failed publishing {video_id}: {yt_err}", {"slot": slot_index})
            logger.error(f"YouTube publishing failed for {video_id}: {yt_err}")
            try:
                from curiosity_engine.notifications.telegram_notifier import get_telegram_notifier
                err_str = str(yt_err)
                fail_kind = "AUTH_FAILURE" if ("invalid_grant" in err_str.lower() or "revoked" in err_str.lower()) else "UPLOAD_FAILURE"
                get_telegram_notifier().notify_failure(
                    failure_type=fail_kind,
                    title=f"YouTube publishing failed for {video_id}",
                    detail=err_str,
                    video_id=video_id,
                )
            except Exception:
                pass
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

    db.save_video_record(video_id, {k: v for k, v in record.items() if k not in ("stage_progress", "lifecycle_stage")})
    latest_pub = db.get_video_record(video_id)
    if isinstance(latest_pub, dict) and "stage_progress" in latest_pub:
        record["stage_progress"] = latest_pub["stage_progress"]
    logger.info(
        f"Publishing flow complete for {video_id}. Status: {record.get('publishing_status')}, "
        f"YouTube: {record.get('youtube_status') or record.get('youtube_upload_id')}, "
        f"Instagram: {record.get('instagram_status')}"
    )
    return record
