"""Director Engine Boundary for Curiosity Engine.

Orchestrates video project preparation by delegating to the active
VisualRenderingEngine registered in curiosity_engine.generation.
If no visual engine is configured, raises GenerationEngineNotConfiguredError.
"""
from __future__ import annotations

import logging
import json
import math
import re
from pathlib import Path
from typing import Any, Dict

from curiosity_engine.config import MAX_DURATION_SEC, MIN_DURATION_SEC, OUTPUT_DIR
from curiosity_engine.generation import (
    GenerationEngineError,
    GenerationEngineNotConfiguredError,
    engine_registry,
)

logger = logging.getLogger("curiosity_engine.director")


def _narration_assets_match(project_dir: Path) -> bool:
    """Return whether existing Kokoro audio and line timings match this project script."""
    try:
        script = json.loads((project_dir / "script.json").read_text(encoding="utf-8"))
        timing = json.loads((project_dir / "data" / "lines.json").read_text(encoding="utf-8"))
        wav_path = project_dir / "data" / "narration.wav"
        script_lines = script.get("lines") or []
        timed_lines = timing.get("lines") or []
        duration = float(timing.get("duration"))
        if (not wav_path.is_file() or wav_path.stat().st_size < 10_000
                or not math.isfinite(duration) or not MIN_DURATION_SEC <= duration <= MAX_DURATION_SEC
                or len(script_lines) != len(timed_lines) or not script_lines):
            return False
        previous_end = 0.0
        for source, timed in zip(script_lines, timed_lines):
            if not isinstance(source, dict) or not isinstance(timed, dict):
                return False
            if str(source.get("text") or "").strip() != str(timed.get("text") or "").strip():
                return False
            start, end = float(timed.get("start")), float(timed.get("end"))
            if (not math.isfinite(start) or not math.isfinite(end) or start < previous_end
                    or end < start or end > duration + 0.05):
                return False
            previous_end = start
        return True
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _word_alignment_matches(project_dir: Path) -> bool:
    """Check alignment count, token order, and bounded monotonic timestamps."""
    try:
        script = json.loads((project_dir / "script.json").read_text(encoding="utf-8"))
        timing = json.loads((project_dir / "data" / "lines.json").read_text(encoding="utf-8"))
        words = json.loads((project_dir / "data" / "words.json").read_text(encoding="utf-8"))
        if not isinstance(words, list):
            return False
        expected = [(token, index) for index, line in enumerate(script.get("lines") or [])
                    if isinstance(line, dict)
                    for token in str(line.get("text") or "").split()
                    if re.sub(r"[^a-z0-9]+", "", token.lower())]
        duration = float(timing.get("duration"))
        if len(words) != len(expected) or not expected:
            return False
        previous_start = 0.0
        for word, (token, line_index) in zip(words, expected):
            if not isinstance(word, dict):
                return False
            start, end = float(word.get("s")), float(word.get("e"))
            if (str(word.get("w") or "") != token or word.get("line") != line_index
                    or not math.isfinite(start) or not math.isfinite(end)
                    or start < previous_start or end < start or end > duration + 0.05):
                return False
            previous_start = start
        return True
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _ensure_narration_assets(project_dir: Path) -> None:
    """Create only missing or script-mismatched TTS/alignment artifacts, sequentially."""
    from curiosity_engine.production.aligner import align_narration_words
    from curiosity_engine.production.tts_engine import synthesize_narration

    if not _narration_assets_match(project_dir):
        logger.info("Generating Kokoro narration and sentence timings for %s.", project_dir.name)
        synthesize_narration(project_dir)
    if not _word_alignment_matches(project_dir):
        logger.info("Aligning narration words for %s.", project_dir.name)
        align_narration_words(project_dir)
    if not _narration_assets_match(project_dir) or not _word_alignment_matches(project_dir):
        raise GenerationEngineError("Narration or word-alignment assets did not validate against the prepared script.")


def prepare_project(
    video_id: str,
    script_data: Dict[str, Any],
    auto_approve_storyboard: bool = True,
    output_dir: Path = OUTPUT_DIR,
    prepare_narration_assets: bool = False,
) -> Path:
    """Set up working directory and prepare project via the active VisualRenderingEngine.

    Raises GenerationEngineNotConfiguredError if no visual rendering engine is registered.
    """
    engine = engine_registry.get_visual_engine()
    if not engine.is_configured():
        raise GenerationEngineNotConfiguredError(
            "Visual rendering engine is not configured. "
            "Please register a VisualRenderingEngine with engine_registry."
        )
    project_dir = Path(engine.prepare_project(video_id, script_data, output_dir=output_dir))
    if prepare_narration_assets:
        _ensure_narration_assets(project_dir)
    return project_dir
