"""Director Engine for Curiosity Engine.
Prepares video projects, orchestrates style kits, voice generation,
and word-level subtitle alignment.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict

from curiosity_engine.config import OUTPUT_DIR, TEMPLATES_DIR
from curiosity_engine.production.aligner import align_narration_words
from curiosity_engine.production.tts_engine import synthesize_narration

logger = logging.getLogger("curiosity_engine.director")


def _progress_call(fn_name: str, *args: Any, **kwargs: Any) -> None:
    """Invoke progress_tracker helper safely without interrupting direct unit calls."""
    try:
        from curiosity_engine.runner import progress_tracker
        getattr(progress_tracker, fn_name)(*args, **kwargs)
    except Exception:
        pass


def prepare_project(video_id: str, script_data: Dict[str, Any], auto_approve_storyboard: bool = True) -> Path:
    """Set up working directory, deploy narrative visual engine, generate voice,
    align subtitles, and direct narrative storyboard.
    """
    project_dir = OUTPUT_DIR / video_id
    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    # Primary production visual engine: Narrative Engine (legacy templates retired and deleted)
    template_dir = TEMPLATES_DIR / "narrative-engine"
    if not template_dir.exists():
        raise FileNotFoundError(f"Required narrative-engine template missing at {template_dir}")

    # Copy engine template into project directory
    shutil.copytree(template_dir, project_dir, dirs_exist_ok=True)

    # Save script.json
    script_path = project_dir / "script.json"
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script_data, f, indent=2)

    logger.info(f"Project prepared at {project_dir} using narrative visual engine.")

    # Step 1: Synthesize narration via Kokoro-82M ONNX
    _progress_call("record_stage_start", video_id, "generating_narration")
    logger.info(f"[{video_id}] Synthesizing narration...")
    synthesize_narration(project_dir)
    _progress_call("record_stage_complete", video_id, "generating_narration")

    # Step 2: Align word timings & visual script prep
    _progress_call("record_stage_start", video_id, "preparing_visuals")
    logger.info(f"[{video_id}] Aligning word timestamps...")
    align_narration_words(project_dir)
    _progress_call("record_stage_checkpoint", video_id, "preparing_visuals", 0.30, "Word timings aligned")

    # Step 3: Direct Narrative Visual Storyboard & Semantic Assets
    logger.info(f"[{video_id}] Directing narrative visual storyboard...")
    words_json_path = project_dir / "data" / "words.json"
    lines_json_path = project_dir / "data" / "lines.json"
    words_data = json.loads(words_json_path.read_text(encoding="utf-8")) if words_json_path.exists() else []
    lines_data = json.loads(lines_json_path.read_text(encoding="utf-8")) if lines_json_path.exists() else []

    from curiosity_engine.production.visual_director import NarrativeVisualDirector
    from curiosity_engine.production.storyboard_approval import StoryboardApprovalManager

    director = NarrativeVisualDirector()
    storyboard = director.direct_script(script_data, word_timings=words_data, line_timings=lines_data)
    StoryboardApprovalManager.save_storyboard(project_dir, storyboard, auto_approve=auto_approve_storyboard)
    _progress_call("record_stage_checkpoint", video_id, "preparing_visuals", 0.65, "Narrative storyboard directed & approved")

    return project_dir
