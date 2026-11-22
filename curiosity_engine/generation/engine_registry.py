"""Singleton Engine Registry managing active generation and rendering engines."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from curiosity_engine.generation.contracts import (
    GenerationEngineNotConfiguredError,
    ScriptGenerationEngine,
    UnconfiguredScriptEngine,
    UnconfiguredVisualEngine,
    VisualRenderingEngine,
)

logger = logging.getLogger("curiosity_engine.generation.registry")


class EngineRegistry:
    """Registry coordinating active content generation and visual rendering engines."""

    def __init__(self):
        self._script_engine: ScriptGenerationEngine = UnconfiguredScriptEngine()
        self._visual_engine: VisualRenderingEngine = UnconfiguredVisualEngine()

    def get_script_engine(self) -> ScriptGenerationEngine:
        return self._script_engine

    def register_script_engine(self, engine: ScriptGenerationEngine) -> None:
        logger.info(f"Registering script generation engine: {engine.__class__.__name__}")
        self._script_engine = engine

    def reset_script_engine(self) -> None:
        self._script_engine = UnconfiguredScriptEngine()

    def get_visual_engine(self) -> VisualRenderingEngine:
        return self._visual_engine

    def register_visual_engine(self, engine: VisualRenderingEngine) -> None:
        logger.info(f"Registering visual rendering engine: {engine.__class__.__name__}")
        self._visual_engine = engine

    def reset_visual_engine(self) -> None:
        self._visual_engine = UnconfiguredVisualEngine()

    def get_status(self) -> Dict[str, Any]:
        """Return engine readiness status for health check and dashboard inspection."""
        script_configured = self._script_engine.is_configured()
        visual_configured = self._visual_engine.is_configured()
        script_reason = getattr(self._script_engine, "not_configured_reason", None)
        visual_reason = getattr(self._visual_engine, "not_configured_reason", None)
        return {
            "ready": script_configured and visual_configured,
            "script_engine": {
                "name": self._script_engine.__class__.__name__,
                "configured": script_configured,
                "reason": None if script_configured else script_reason() if callable(script_reason) else "Script engine is in safe standby.",
            },
            "visual_engine": {
                "name": self._visual_engine.__class__.__name__,
                "configured": visual_configured,
                "reason": None if visual_configured else visual_reason() if callable(visual_reason) else "Visual engine dependencies are in safe standby.",
            },
            "status_message": (
                "All generation engines configured."
                if (script_configured and visual_configured)
                else "Generation engines not configured. System is in safe standby mode."
            ),
        }


# Global singleton instance
engine_registry = EngineRegistry()
