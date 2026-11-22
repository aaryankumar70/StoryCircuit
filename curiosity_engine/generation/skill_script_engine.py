"""Autonomous Skill-Driven Script Generation Engine for CurioLoop.

Implements ScriptGenerationEngine using the viral-shorts-scriptwriter skill,
evidence dossiers, narrative structure (hook <14 words, 40-58s duration, loop ending),
and deterministic scene direction without relying on external Ollama or qwen models.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from curiosity_engine.generation.contracts import (
    GenerationEngineError,
    ScriptGenerationEngine,
)

logger = logging.getLogger("curiosity_engine.generation.skill_script_engine")


class SkillScriptEngine(ScriptGenerationEngine):
    """Production Script Engine driven by the viral-shorts-scriptwriter skill."""

    def __init__(self):
        logger.info("Initialized SkillScriptEngine (autonomous skill-driven).")

    def is_configured(self) -> bool:
        """Always configured and ready to generate verified narrative scripts."""
        return True

    def not_configured_reason(self) -> Optional[str]:
        return None

    def generate_script(self, topic_info: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a structured video script adhering to viral-shorts-scriptwriter rules."""
        from curiosity_engine.content.scriptwriter import _generate_viral_short_script

        if topic_info is None or not isinstance(topic_info, dict):
            raise GenerationEngineError("topic_info must be a dictionary.")

        return _generate_viral_short_script(topic_info)

    def assign_scenes(self, script_data: Dict[str, Any]) -> Dict[str, Any]:
        """Assign scene directives following cinematic story visual conventions."""
        from curiosity_engine.content.scriptwriter import assign_line_scenes

        return assign_line_scenes(script_data)

    def revise_duration(
        self, script_data: Dict[str, Any], target_sec: float
    ) -> Dict[str, Any]:
        """Revise script duration to target duration cleanly."""
        from curiosity_engine.content.scriptwriter import _revise_script_for_duration_internal

        current_dur = float(script_data.get("duration", 65.0))
        revised, _note = _revise_script_for_duration_internal(
            script_data, current_duration_sec=current_dur, target_max_sec=target_sec
        )
        return revised
