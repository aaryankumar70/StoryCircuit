"""Tests for CurioLoop Generation Engine Boundary & Unconfigured Engine Safety.

Verifies:
1. Engine registry provides unconfigured defaults.
2. Unconfigured engines raise GenerationEngineNotConfiguredError.
3. Automatic Studio pipeline safely pauses with ENGINE_NOT_CONFIGURED status.
4. Creator Studio pipeline safely holds episode with ENGINE_NOT_CONFIGURED status.
5. No fake video files, no fake successes, and no automatic publishing occurs when engines are unconfigured.
6. Clean pluggable registration of replacement engines via the engine boundary.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from curiosity_engine.creator_series.models import EpisodeRecord, EpisodeStatus, SeriesRecord, SeriesStatus
from curiosity_engine.creator_series.pipeline_integration import produce_creator_series_slot
from curiosity_engine.creator_series.series_db import SeriesDatabase
from curiosity_engine.generation import (
    GenerationEngineError,
    GenerationEngineNotConfiguredError,
    ScriptGenerationEngine,
    UnconfiguredScriptEngine,
    UnconfiguredVisualEngine,
    VisualRenderingEngine,
    engine_registry,
)
from curiosity_engine.content.scriptwriter import write_video_script
from curiosity_engine.production.director import _ensure_narration_assets, prepare_project
from curiosity_engine.production.renderer import render_project_video
from curiosity_engine.runner.pipeline import produce_single_video
from curiosity_engine.state.db import DatabaseClient


class DummyScriptEngine(ScriptGenerationEngine):
    """Test implementation of a replacement script engine."""

    def is_configured(self) -> bool:
        return True

    def generate_script(self, topic_info: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "topic": topic_info.get("topic", "Test Topic"),
            "category": "Science",
            "duration": 35.0,
            "lines": [
                {"text": "Line one opening hook.", "scene": "scene_1"},
                {"text": "Line two development.", "scene": "scene_2"},
                {"text": "Line three memorable ending.", "scene": "scene_3"},
            ],
        }


class DummyVisualEngine(VisualRenderingEngine):
    """Test implementation of a replacement visual engine."""

    def is_configured(self) -> bool:
        return True

    def prepare_project(self, video_id: str, script_data: Dict[str, Any], output_dir: Path) -> Path:
        proj_dir = output_dir / ".engine_projects" / video_id / "dummy-project"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "script.json").write_text(json.dumps(script_data), encoding="utf-8")
        (proj_dir / ".curioloop_project.json").write_text(json.dumps({
            "project_id": proj_dir.name, "renderer_version": "dummy-test-v1",
        }), encoding="utf-8")
        return proj_dir

    def render_video(self, project_dir: Path, output_mp4: Path, resume: bool = True, force_rebuild: bool = False) -> Path:
        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("FFmpeg is required for the strict boundary media fixture.")
        subprocess.run([
            ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4", "-shortest",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", str(output_mp4),
        ], check=True, capture_output=True, timeout=30)
        return output_mp4


@pytest.fixture(autouse=True)
def reset_engine_registry():
    """Ensure engine registry starts in clean unconfigured state for every test."""
    engine_registry.reset_script_engine()
    engine_registry.reset_visual_engine()
    yield
    engine_registry.reset_script_engine()
    engine_registry.reset_visual_engine()


class TestGenerationEngineBoundary:

    def test_narration_assets_are_created_in_order_and_reused_when_valid(self, tmp_path):
        project = tmp_path / "engine-project"
        data_dir = project / "data"
        data_dir.mkdir(parents=True)
        lines = [{"text": "First sentence."}, {"text": "Second sentence."}]
        (project / "script.json").write_text(json.dumps({"lines": lines}), encoding="utf-8")
        events = []

        def fake_tts(project_dir):
            events.append("tts")
            data = project_dir / "data"
            (data / "narration.wav").write_bytes(b"0" * 12_000)
            (data / "lines.json").write_text(json.dumps({"duration": 25.0, "lines": [
                {"text": lines[0]["text"], "start": 0.4, "end": 1.2},
                {"text": lines[1]["text"], "start": 1.5, "end": 2.3},
            ]}), encoding="utf-8")

        def fake_alignment(project_dir):
            events.append("alignment")
            words = [
                {"w": "First", "line": 0, "s": 0.4, "e": 0.7},
                {"w": "sentence.", "line": 0, "s": 0.7, "e": 1.2},
                {"w": "Second", "line": 1, "s": 1.5, "e": 1.9},
                {"w": "sentence.", "line": 1, "s": 1.9, "e": 2.3},
            ]
            (project_dir / "data" / "words.json").write_text(json.dumps(words), encoding="utf-8")

        with patch("curiosity_engine.production.tts_engine.synthesize_narration", side_effect=fake_tts), \
             patch("curiosity_engine.production.aligner.align_narration_words", side_effect=fake_alignment):
            _ensure_narration_assets(project)
            assert events == ["tts", "alignment"]
            events.clear()
            _ensure_narration_assets(project)
            assert events == []

    def test_default_unconfigured_status(self):
        status = engine_registry.get_status()
        assert status["ready"] is False
        assert status["script_engine"]["configured"] is False
        assert status["visual_engine"]["configured"] is False
        assert "not configured" in status["status_message"].lower()

    def test_unconfigured_script_engine_raises_error(self):
        engine = engine_registry.get_script_engine()
        assert isinstance(engine, UnconfiguredScriptEngine)
        assert engine.is_configured() is False

        with pytest.raises(GenerationEngineNotConfiguredError) as exc_info:
            write_video_script({"topic": "The Voynich Mystery"})
        assert "not configured" in str(exc_info.value).lower()

    def test_unconfigured_visual_engine_raises_error(self, tmp_path):
        engine = engine_registry.get_visual_engine()
        assert isinstance(engine, UnconfiguredVisualEngine)
        assert engine.is_configured() is False

        with pytest.raises(GenerationEngineNotConfiguredError) as exc_info:
            prepare_project("test_vid", {"lines": []}, output_dir=tmp_path)
        assert "not configured" in str(exc_info.value).lower()

        with pytest.raises(GenerationEngineNotConfiguredError) as exc_info:
            render_project_video(tmp_path / "proj", tmp_path / "test.mp4")
        assert "not configured" in str(exc_info.value).lower()

    def test_pluggable_engine_registration_and_execution(self, tmp_path):
        dummy_script = DummyScriptEngine()
        dummy_visual = DummyVisualEngine()

        engine_registry.register_script_engine(dummy_script)
        engine_registry.register_visual_engine(dummy_visual)

        status = engine_registry.get_status()
        assert status["ready"] is True
        assert status["script_engine"]["name"] == "DummyScriptEngine"
        assert status["visual_engine"]["name"] == "DummyVisualEngine"

        # Verify execution through boundary functions
        script = write_video_script({"topic": "Quantum Teleportation"})
        assert script["topic"] == "Quantum Teleportation"
        assert len(script["lines"]) == 3

        proj = prepare_project("quantum_ep", script, output_dir=tmp_path)
        assert proj.exists()

        rendered = render_project_video(proj, tmp_path / "quantum.mp4")
        assert rendered.exists()
        from curiosity_engine.production.renderer import current_render_matches, validate_rendered_mp4
        metadata = validate_rendered_mp4(rendered)
        assert metadata["width"] == 640
        assert metadata["height"] == 360
        assert current_render_matches(rendered, proj)


class TestPipelineSafetyWhenUnconfigured:

    def test_automatic_pipeline_pauses_safely_at_script_generation(self, tmp_path):
        """When script engine is unconfigured, production halts with ENGINE_NOT_CONFIGURED status."""
        db_file = tmp_path / "test_curiosity.db"
        test_db = DatabaseClient(db_file)

        with patch("curiosity_engine.runner.pipeline.db", test_db), \
             patch("curiosity_engine.runner.pipeline.acquire_slot_worker_lock"), \
             patch("curiosity_engine.runner.pipeline.release_slot_worker_lock"):

            record = produce_single_video(
                video_id="video_20261122_slot1",
                topic_info={"topic": "Black Hole Singularities", "category": "Space"},
                slot_index=1,
                target_date="2026-11-22",
            )

            assert record["production_status"] == "ENGINE_NOT_CONFIGURED"
            assert record.get("paused") is True
            assert "engine is not configured" in record.get("error", "").lower()
            assert not (tmp_path / "video_20261122_slot1.mp4").exists()

            # Verify persisted database record
            db_rec = test_db.get_video_record("video_20261122_slot1")
            assert db_rec["production_status"] == "ENGINE_NOT_CONFIGURED"
            assert db_rec.get("qc_passed") is not True

    def test_automatic_pipeline_pauses_safely_at_visual_rendering(self, tmp_path):
        """When script engine is configured but visual engine is unconfigured, halts at render."""
        db_file = tmp_path / "test_curiosity2.db"
        test_db = DatabaseClient(db_file)
        engine_registry.register_script_engine(DummyScriptEngine())

        with patch("curiosity_engine.runner.pipeline.db", test_db), \
             patch("curiosity_engine.runner.pipeline.OUTPUT_DIR", tmp_path), \
             patch("curiosity_engine.runner.pipeline.acquire_slot_worker_lock"), \
             patch("curiosity_engine.runner.pipeline.release_slot_worker_lock"):

            record = produce_single_video(
                video_id="video_20261122_slot2",
                topic_info={"topic": "Bermuda Mystery", "category": "Mysteries"},
                slot_index=2,
                target_date="2026-11-22",
            )

            assert record["production_status"] == "ENGINE_NOT_CONFIGURED"
            assert record.get("paused") is True
            assert "visual rendering engine is not configured" in record.get("error", "").lower()
            assert not (tmp_path / "video_20261122_slot2.mp4").exists()

    def test_creator_studio_slot_pauses_safely_when_visual_engine_unconfigured(self, tmp_path):
        """Creator Studio episode marks ENGINE_NOT_CONFIGURED without creating fake videos."""
        db_file = tmp_path / "test_creator.db"
        test_db = DatabaseClient(db_file)
        s_db = SeriesDatabase(test_db)

        series = SeriesRecord(
            series_id="ser_creepy_cabin",
            title="The Creepy Cabin",
            full_script="A spooky tale of a lost cabin in the woods.",
        )
        s_db.save_series(series)

        ep = EpisodeRecord(
            episode_id="ser_creepy_cabin_ep01",
            series_id="ser_creepy_cabin",
            episode_num=1,
            title="Episode 1: The Lantern",
            adapted_narration="The snow began falling fast.",
            is_approved=True,
            status=EpisodeStatus.AWAITING_APPROVAL,
        )
        s_db.save_episode(ep)

        with patch("curiosity_engine.creator_series.pipeline_integration.series_db", s_db):
            result = produce_creator_series_slot(
                video_id="creator_cabin_ep01",
                series=series,
                episode=ep,
                target_date="2026-11-22",
                output_dir=tmp_path,
            )

            assert result["status"] == "ENGINE_NOT_CONFIGURED"
            assert "not configured" in result["error"].lower()

            updated_ep = s_db.get_episode("ser_creepy_cabin_ep01")
            assert updated_ep.status == EpisodeStatus.ENGINE_NOT_CONFIGURED
            assert updated_ep.rendered_video_path is None
            assert not (tmp_path / "creator_cabin_ep01.mp4").exists()
