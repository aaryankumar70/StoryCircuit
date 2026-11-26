"""End-to-end single-job production pipeline with auto 16:9 long-format conversion (>2 min)."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from reelforge import config
from reelforge.audio.tts import synthesize_story_audio
from reelforge.audio.underscore import prepare_background_music
from reelforge.brain.director import StoryDirector
from reelforge.brain.metadata import enrich_story_metadata
from reelforge.models import SourceMode, VideoFormat
from reelforge.progress import build_progress_payload
from reelforge.qc.gatekeeper import verify_video
from reelforge.storage.db import ReelDatabase
from reelforge.video.renderer import render_short_video
from reelforge.visuals.resolver import resolve_all_visuals

logger = logging.getLogger("reelforge.pipeline")


def run_generation_job(
    db: ReelDatabase,
    *,
    mode: SourceMode = SourceMode.RANDOM,
    topic: str = "",
    category: str = "auto",
    style: str = "auto",
    custom_script: str = "",
    facts: str = "",
    scheduled_date: Optional[str] = None,
    slot_num: Optional[int] = None,
    visual_mode: Optional[str] = None,
    min_duration_sec: Optional[float] = None,
) -> Dict[str, Any]:
    """Generate storyboard, audio, per-beat visuals, rendered MP4 (9:16 or auto 16:9 >2m), and QC."""
    started_at = datetime.now(timezone.utc).isoformat()
    completed_stages: List[str] = []
    current_stage = "selecting_topic"

    init_title = topic.strip() or ("Custom Script" if mode == SourceMode.CUSTOM_SCRIPT else "Discovering fresh AI topic...")
    job_id = db.create_job(
        source_mode=mode.value,
        title=init_title,
        category=category if category != "auto" else "story",
        style=style if style != "auto" else "editorial_dark",
        script_text="",
        storyboard={"beats": []},
        scheduled_date=scheduled_date,
        slot_num=slot_num,
        status="rendering",
        video_format="short",
    )

    def _report(stage: str, label: str, pct: int, detail: str = "", failed: Optional[str] = None) -> None:
        db.update_job(
            job_id,
            progress_json=build_progress_payload(
                stage=stage,
                stage_label=label,
                percent=pct,
                detail=detail,
                started_at=started_at,
                completed_stages=completed_stages,
                failed_stage=failed,
            ),
        )

    work_dir = config.OUTPUT_DIR / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    output_mp4 = work_dir / "final.mp4"

    try:
        _report("selecting_topic", "Selecting fresh non-repeating topic", 6, f"Slot {slot_num}" if slot_num else mode.value)
        director = StoryDirector()
        plan = director.build_story(
            db,
            mode=mode,
            topic=topic,
            category=category,
            style=style,
            custom_script=custom_script,
            facts=facts,
        )
        completed_stages.extend(["selecting_topic", "writing_script"])
        db.update_job(
            job_id,
            title=plan.title,
            category=plan.category,
            style=plan.style.value,
            script_text=plan.full_script,
            storyboard_json=plan.model_dump(mode="json"),
        )
        current_stage = "generating_narration"
        _report("generating_narration", "Synthesizing voice & word timing", 22, f"{len(plan.beats)} beats")
        narration_wav, words, duration_sec = synthesize_story_audio(plan, work_dir)
        completed_stages.append("generating_narration")

        # Auto-convert to YouTube 16:9 Landscape Long Format whenever duration > 2 minutes (120s)
        is_long = duration_sec > config.SHORT_MAX_DURATION_SEC
        if is_long:
            plan.video_format = VideoFormat.LONG
            plan.target_width = config.LANDSCAPE_WIDTH
            plan.target_height = config.LANDSCAPE_HEIGHT
            logger.info(
                "Job %s duration %.1fs > %.0fs: auto-converting to 16:9 landscape long-format (%sx%s).",
                job_id, duration_sec, config.SHORT_MAX_DURATION_SEC, plan.target_width, plan.target_height,
            )
        else:
            plan.video_format = VideoFormat.SHORT
            plan.target_width = config.VIDEO_WIDTH
            plan.target_height = config.VIDEO_HEIGHT

        enrich_story_metadata(plan, is_long=is_long)
        db.update_job(
            job_id,
            video_format=plan.video_format.value,
            storyboard_json=plan.model_dump(mode="json"),
        )

        fmt_label = "16:9 Landscape" if is_long else "9:16 Short"
        current_stage = "preparing_music"
        _report("preparing_music", "Generating ambient underscore", 32, f"{duration_sec:.1f}s • {fmt_label}")
        seed = int(hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:8], 16)
        bgm_wav = prepare_background_music(duration_sec, work_dir / "audio" / "bgm.wav", seed=seed)
        completed_stages.append("preparing_music")

        current_stage = "resolving_visuals"
        _report("resolving_visuals", f"Resolving {fmt_label} visuals (0/{len(plan.beats)})", 36)

        def _on_visual(done: int, total: int, src: str) -> None:
            pct = 36 + int(round((done / max(1, total)) * 22))
            _report("resolving_visuals", f"Resolving visuals ({done}/{total})", pct, f"Beat {done}/{total} • {src}")

        resolve_all_visuals(plan, work_dir, visual_mode=visual_mode, on_progress=_on_visual)
        completed_stages.append("resolving_visuals")

        db.update_job(job_id, storyboard_json=plan.model_dump(mode="json"))

        current_stage = "rendering_video"
        _report("rendering_video", f"Rendering {fmt_label} clips (0/{len(plan.beats)})", 58)

        def _on_render(done: int, total: int, desc: str) -> None:
            pct = 58 + int(round((done / max(1, total)) * 32))
            label = "Burning captions & mixing audio" if done >= total else f"Rendering clips ({done}/{len(plan.beats)})"
            _report("rendering_video", label, pct, desc)

        render_short_video(
            plan=plan,
            narration_wav=narration_wav,
            bgm_wav=bgm_wav,
            words=words,
            work_dir=work_dir,
            output_mp4=output_mp4,
            on_progress=_on_render,
        )
        completed_stages.append("rendering_video")

        effective_min_dur = min_duration_sec
        if effective_min_dur is None and mode == SourceMode.CUSTOM_SCRIPT:
            effective_min_dur = 6.0

        current_stage = "running_qc"
        _report("running_qc", "Running FFprobe & loudness QC", 92)
        qc = verify_video(
            output_mp4,
            words_json_path=work_dir / "words.json",
            min_duration_sec=effective_min_dur,
            max_duration_sec=config.LONG_MAX_DURATION_SEC if is_long else config.SHORT_MAX_DURATION_SEC,
            expected_width=plan.target_width,
            expected_height=plan.target_height,
            video_format=plan.video_format.value,
        )
        qc_dict = qc.model_dump()
        (work_dir / "qc_report.json").write_text(json.dumps(qc_dict, indent=2), encoding="utf-8")

        if qc.passed:
            completed_stages.append("running_qc")

        new_status = "qc_passed" if qc.passed else "qc_failed"
        db.update_job(
            job_id,
            status=new_status,
            video_path=str(output_mp4),
            qc_json=qc_dict,
            progress_json=build_progress_payload(
                stage=new_status,
                stage_label=f"QC Passed ({fmt_label})" if qc.passed else "QC Failed",
                percent=95 if qc.passed else 92,
                detail=f"{qc.checks.get('duration_sec', '--')}s • {qc.checks.get('resolution', '--')} • {qc.checks.get('integrated_lufs', '--')} LUFS",
                started_at=started_at,
                completed_stages=completed_stages,
                failed_stage=None if qc.passed else "running_qc",
            ),
            error="" if qc.passed else "; ".join(qc.issues),
        )
        if qc.passed:
            db.record_topic_history(
                title=plan.title,
                body_text=plan.full_script,
                category=plan.category,
                job_id=job_id,
            )

        return db.get_job(job_id) or {"id": job_id, "status": new_status}
    except Exception as exc:
        logger.exception("Generation job %s failed", job_id)
        _report(current_stage, f"Failed at {current_stage.replace('_', ' ')}", 0, str(exc)[:180], failed=current_stage)
        db.update_job(job_id, status="failed", error=str(exc))
        return db.get_job(job_id) or {"id": job_id, "status": "failed", "error": str(exc)}
