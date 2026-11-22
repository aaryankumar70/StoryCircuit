"""Explicit registration for CurioLoop's concrete local generation engines."""
from __future__ import annotations

from typing import Any, Dict

from curiosity_engine.generation.engine_registry import engine_registry
from curiosity_engine.generation.skill_script_engine import SkillScriptEngine
from curiosity_engine.generation.cartoon_visual_engine import Cartoon3DVisualEngine


def configure_generation_engines() -> Dict[str, Any]:
    """Register engines without starting services, downloading models, or touching state."""
    engine_registry.register_script_engine(SkillScriptEngine())
    engine_registry.register_visual_engine(Cartoon3DVisualEngine())
    return engine_registry.get_status()
