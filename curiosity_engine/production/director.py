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


def prepare_project(video_id: str, script_data: Dict[str, Any]) -> Path:
    """Set up working directory, copy style template, and generate voice + alignment."""
    project_dir = OUTPUT_DIR / video_id
    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    style = script_data.get("style", "inside-out")
    template_dir = TEMPLATES_DIR / style
    if not template_dir.exists():
        template_dir = TEMPLATES_DIR / "inside-out"

    # Copy template into project directory
    shutil.copytree(template_dir, project_dir, dirs_exist_ok=True)

    # Save script.json
    script_path = project_dir / "script.json"
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script_data, f, indent=2)

    logger.info(f"Project prepared at {project_dir} using style '{style}'.")

    # Step 1: Synthesize narration via Kokoro-82M ONNX
    logger.info(f"[{video_id}] Synthesizing narration...")
    synthesize_narration(project_dir)

    # Step 2: Align word timings
    logger.info(f"[{video_id}] Aligning word timestamps...")
    align_narration_words(project_dir)

    return project_dir
