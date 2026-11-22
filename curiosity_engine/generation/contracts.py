"""Generation Engine Boundary & Contract Interfaces for CurioLoop.

Defines the clean boundary between CurioLoop's production pipeline/workflows
and pluggable content/script generation and visual/video rendering engines.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional


class GenerationEngineError(RuntimeError):
    """Base exception for generation engine failures."""
    pass


class GenerationEngineNotConfiguredError(GenerationEngineError):
    """Raised when a production workflow requires a generation engine that is not configured."""
    pass


class ScriptGenerationEngine(ABC):
    """Abstract interface that any content/script generation engine must implement."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if the engine is ready to generate scripts, False otherwise."""
        pass

    @abstractmethod
    def generate_script(self, topic_info: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a structured video script from topic information.

        Returns a dictionary conforming to CurioLoop script schema:
        {
            "topic": str,
            "category": str,
            "duration": float,
            "lines": [{"text": str, "scene": str, ...}],
            ...
        }
        """
        pass

    def assign_scenes(self, script_data: Dict[str, Any]) -> Dict[str, Any]:
        """Assign scene directives; concrete engines must implement narrative direction."""
        raise GenerationEngineNotConfiguredError("Narrative scene assignment requires a configured script generation engine.")

    def revise_duration(self, script_data: Dict[str, Any], target_sec: float) -> Dict[str, Any]:
        """Revise narration for target spoken duration; never return an unchecked no-op."""
        raise GenerationEngineNotConfiguredError("Duration revision requires a configured script generation engine.")


class VisualRenderingEngine(ABC):
    """Abstract interface that any visual generation / video rendering engine must implement."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if the visual engine is ready to render video, False otherwise."""
        pass

    @abstractmethod
    def prepare_project(
        self,
        video_id: str,
        script_data: Dict[str, Any],
        output_dir: Path,
    ) -> Path:
        """Prepare project directory, visual assets, and staging data for rendering."""
        pass

    @abstractmethod
    def render_video(
        self,
        project_dir: Path,
        output_mp4: Path,
        resume: bool = True,
        force_rebuild: bool = False,
    ) -> Path:
        """Render the staged project into a verified MP4 video file."""
        pass


class UnconfiguredScriptEngine(ScriptGenerationEngine):
    """Default fallback when no script generation engine is configured."""

    def is_configured(self) -> bool:
        return False

    def generate_script(self, topic_info: Dict[str, Any]) -> Dict[str, Any]:
        raise GenerationEngineNotConfiguredError(
            "Content/script generation engine is not configured. "
            "Connect a new engine via curiosity_engine.generation.engine_registry."
        )


class UnconfiguredVisualEngine(VisualRenderingEngine):
    """Default fallback when no visual rendering engine is configured."""

    def is_configured(self) -> bool:
        return False

    def prepare_project(
        self,
        video_id: str,
        script_data: Dict[str, Any],
        output_dir: Path,
    ) -> Path:
        raise GenerationEngineNotConfiguredError(
            "Visual rendering engine is not configured. "
            "Connect a new visual engine via curiosity_engine.generation.engine_registry."
        )

    def render_video(
        self,
        project_dir: Path,
        output_mp4: Path,
        resume: bool = True,
        force_rebuild: bool = False,
    ) -> Path:
        raise GenerationEngineNotConfiguredError(
            "Visual rendering engine is not configured. "
            "Connect a new visual engine via curiosity_engine.generation.engine_registry."
        )
