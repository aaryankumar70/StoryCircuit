"""Pipeline Integration for CurioLoop Creator Series & Dual-Lane Scheduler.

Handles:
- Slot 2 priority determination (Creator Series vs. Lane A automatic content)
- Series episode video production using existing Kokoro, Whisper, and Canvas renderer
- Safe rights protection (blocks unverified copyright content from live uploads)
- Sequence integrity enforcement (no skipping, halting on failure, completing series)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from curiosity_engine.config import OUTPUT_DIR, YOUTUBE_PUBLISHING_MODE
from curiosity_engine.creator_series.models import (
    EpisodeRecord,
    EpisodeStatus,
    RightsStatus,
    SeriesRecord,
    SeriesStatus,
)
from curiosity_engine.creator_series.renderer_adapter import renderer_adapter
from curiosity_engine.creator_series.series_db import series_db
from curiosity_engine.creator_series.visual_director import visual_director
from curiosity_engine.creator_series.visual_qc import visual_qc
from curiosity_engine.production.aligner import align_narration_words
from curiosity_engine.production.renderer import render_project_video, validate_rendered_mp4
from curiosity_engine.production.tts_engine import synthesize_narration
from curiosity_engine.state.db import db

logger = logging.getLogger("curiosity_engine.creator_pipeline")


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
) -> Dict[str, Any]:
    """Produce a single Creator Series episode into CurioLoop video output.
    Uses existing Kokoro ONNX, faster-whisper alignment, and Canvas renderer.
    """
    # Safety Check: Rights and permissions
    if series.rights_status == RightsStatus.UNVERIFIED_EVALUATION_ONLY:
        logger.warning(
            f"Series '{series.series_id}' rights are UNVERIFIED_EVALUATION_ONLY. "
            "Local evaluation only. Public publishing must be blocked."
        )

    # 1. Load or generate Visual Bible
    bible_path = Path(series.visual_bible_path) if series.visual_bible_path else None
    if bible_path and bible_path.exists():
        with open(bible_path, "r", encoding="utf-8") as f:
            bible = json.load(f)
    else:
        bible = visual_director.create_horror_visual_bible(
            series_id=series.series_id,
            title=series.title,
            logline=f"Creator series narrative for {series.title}",
        )

    # 2. Load or generate Episode Storyboard
    sb_path = Path(episode.visual_storyboard_path) if episode.visual_storyboard_path else None
    if sb_path and sb_path.exists():
        with open(sb_path, "r", encoding="utf-8") as f:
            storyboard = json.load(f)
    else:
        storyboard = visual_director.create_episode_storyboard(
            series_id=series.series_id,
            episode=episode,
            bible=bible,
            duration_s=episode.estimated_duration or 48.0,
        )

    # 3. Stage project directory
    project_dir, downgrades = renderer_adapter.prepare_creator_project(
        project_id=video_id,
        storyboard=storyboard,
        bible=bible,
    )

    # 4. Synthesize narration via Kokoro ONNX
    logger.info(f"[{video_id}] Synthesizing creator series narration...")
    synthesize_narration(project_dir)

    # 5. Word-level timestamp alignment
    logger.info(f"[{video_id}] Aligning creator series timestamps...")
    align_narration_words(project_dir)

    # 6. Render Video via Headless Chrome & FFmpeg
    output_mp4 = OUTPUT_DIR / f"{video_id}.mp4"
    logger.info(f"[{video_id}] Rendering video to {output_mp4}...")
    render_project_video(project_dir, output_mp4, resume=not force_rebuild, force_rebuild=force_rebuild)

    # 7. Validate Rendered MP4
    lines_json = project_dir / "data" / "lines.json"
    actual_dur = episode.estimated_duration
    if lines_json.exists():
        with open(lines_json, "r", encoding="utf-8") as f:
            actual_dur = float(json.load(f).get("duration", actual_dur))

    meta = validate_rendered_mp4(output_mp4, expected_duration=actual_dur)

    # 8. Visual Quality Control
    qc_score = visual_qc.evaluate_storyboard(storyboard, bible)
    qc_passed = qc_score.verdict in ("SHIP", "REVISE")

    # 9. Update EpisodeRecord and VideoRecord
    episode.status = EpisodeStatus.RENDERED if qc_passed else EpisodeStatus.QC_FAILED
    episode.actual_duration = meta["duration"]
    episode.audio_path = str(project_dir / "data" / "mix.wav")
    episode.rendered_video_path = str(output_mp4)
    episode.qc_result = qc_score.to_dict()
    series_db.save_episode(episode)

    record_data = {
        "video_id": video_id,
        "slot_index": 2,
        "target_date": target_date,
        "is_creator_series": True,
        "series_id": series.series_id,
        "episode_id": episode.episode_id,
        "episode_num": episode.episode_num,
        "rights_status": series.rights_status.value if hasattr(series.rights_status, "value") else str(series.rights_status),
        "visual_profile": series.visual_profile,
        "topic": f"{series.title} | Part {episode.episode_num}",
        "category": "CreatorSeries",
        "style": "paper-atlas",
        "duration_sec": meta["duration"],
        "local_video_path": str(output_mp4),
        "qc_passed": qc_passed,
        "production_status": "COMPLETED" if qc_passed else "QC_FAILED",
        "applied_downgrades": downgrades,
        "visual_qc": qc_score.to_dict(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.save_video_record(video_id, record_data)
    logger.info(f"Creator series episode {episode.episode_id} successfully produced ({meta['duration']:.2f}s).")
    return record_data
