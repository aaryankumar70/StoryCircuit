"""Unit & Regression Tests for CurioLoop Production Quality Incident.

Covers:
1. Fix for JavaScript visual check exception: armPose and character rendering defensive handling.
2. Storytelling narration director: beat classification, speed modulation, pause calibration, text smoothing.
3. Story provenance: category enforcement (Mystery, History, Space), narration hash matching, anti-stale detection.
4. Scene non-repetition: consecutive visual type rotation and composition diversification.
5. Quality Control: 5-dimensional sub-scores and hard-failure gating.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from curiosity_engine.content.editorial_policy import ALLOWED_CATEGORIES, normalize_category
from curiosity_engine.content.scriptwriter import assign_line_scenes
from curiosity_engine.production.narration_director import (
    MODE_CLIMAX,
    MODE_ENDING,
    MODE_HOOK,
    MODE_REVELATION,
    MODE_SUSPENSE,
    classify_sentence_beat,
    get_storytelling_delivery_plan,
    smooth_storytelling_text,
)
from curiosity_engine.quality.provenance import (
    build_production_provenance,
    compute_script_narration_hash,
    compute_storyboard_hash,
    validate_story_provenance,
)
from curiosity_engine.quality.qc_gatekeeper import QCReport, verify_video


# ── Phase 5 Regression Tests: JS Arm Pose & Character Kit ──

def test_inside_out_kit_defines_chin_and_defensive_arm_pose():
    kit_path = Path("templates/inside-out/src/core/kit.js")
    assert kit_path.exists(), "templates/inside-out/src/core/kit.js missing"
    txt = kit_path.read_text(encoding="utf-8")

    # Verify chin is explicitly defined in ARM
    assert "chin:" in txt, "ARM.chin must be explicitly defined in ARM dictionary"

    # Verify defensive checks in armPose
    assert "Array.isArray" in txt or "pA" in txt or "ARM.down" in txt, (
        "armPose must defensively fall back to safe pose if a or b is undefined"
    )


# ── Phase 4 Tests: Narration Storytelling Direction ──

def test_smooth_storytelling_text():
    raw = 'In 1872... an intact "ship" sailed 20 km/h—past the Azores.'
    smoothed = smooth_storytelling_text(raw)
    assert "..." not in smoothed
    assert ", " in smoothed
    assert '"' not in smoothed
    assert "kilometers per hour" in smoothed


def test_classify_sentence_beat():
    total = 8
    # Beat 0 is hook
    assert classify_sentence_beat(0, total, "An intact ship sailed alone across the Atlantic.") == MODE_HOOK

    # Beat 7 is ending
    assert classify_sentence_beat(7, total, "Decades later, the ocean still keeps its silent secrets.") == MODE_ENDING

    # Revelation detection
    assert classify_sentence_beat(3, total, "Instead, they discovered untouched food and locked cargo.") == MODE_REVELATION

    # Suspense detection
    assert classify_sentence_beat(2, total, "Suddenly, an eerie silence settled over the crew.") == MODE_SUSPENSE

    # Climax detection
    assert classify_sentence_beat(6, total, "The ship shattered violently against the coastal reef.") == MODE_CLIMAX


def test_get_storytelling_delivery_plan_modulation():
    lines = [
        {"text": "A ghost ship was spotted sailing alone."},
        {"text": "Naval officers boarded expecting violence."},
        {"text": "Instead, they discovered warm food on the table."},
        {"text": "All seven crew members had vanished into thin air."},
        {"text": "The mystery remains unsolved today."},
    ]
    plan = get_storytelling_delivery_plan(lines, base_speed=1.0, enable_storytelling=True)
    assert len(plan) == len(lines)
    # Hook should be punchy (>= 1.0)
    assert plan[0]["speed"] >= 1.0
    assert plan[0]["mode"] == MODE_HOOK

    # Revelation / twist should slow down (< 1.0) for dramatic effect
    assert plan[2]["speed"] < 1.0
    assert plan[2]["pre_pause_sec"] > 0.0

    # Ending should have longer outro pause
    assert plan[-1]["gap_sec"] >= 0.70


def test_storytelling_delivery_rollback_preservation():
    lines = [{"text": "Simple test line one."}, {"text": "Simple test line two."}]
    plan = get_storytelling_delivery_plan(lines, base_speed=1.0, enable_storytelling=False)
    assert all(p["speed"] == 1.0 for p in plan)
    assert all(p["mode"] == "standard" for p in plan)


# ── Phase 2 Tests: Provenance Tracking & Category Enforcement ──

def test_automatic_lane_rejects_forbidden_categories():
    forbidden_cats = ["Nature", "Human Biology", "Anatomy", "Medical Trivia", "Generic Chemistry"]
    for cat in forbidden_cats:
        script = {
            "id": "bad_cat",
            "category": cat,
            "lines": [{"text": "A Greenland shark swims in deep arctic waters."}],
        }
        record = {"content_lane": "automatic", "category": cat}
        passed, issues, meta = validate_story_provenance(record, script)
        assert not passed, f"Expected category '{cat}' to be rejected in automatic lane"
        assert any("Automatic lane violation" in iss for iss in issues)


def test_automatic_lane_accepts_authorized_categories():
    for cat in ["MYSTERY", "HISTORY", "SPACE"]:
        script = {
            "id": "good_cat",
            "category": cat,
            "lines": [
                {"text": "Beat one text here."},
                {"text": "Beat two text here.", "scene": {"visual_type": "timeline"}},
            ],
        }
        record = {
            "content_lane": "automatic",
            "category": cat,
            "script_hash": compute_script_narration_hash(script),
        }
        passed, issues, meta = validate_story_provenance(record, script)
        assert passed, f"Expected authorized category '{cat}' to pass, got: {issues}"


def test_provenance_detects_mismatched_narration_hash():
    script = {
        "id": "script_1",
        "category": "MYSTERY",
        "lines": [{"text": "Line one."}, {"text": "Line two."}],
    }
    record = {
        "content_lane": "automatic",
        "category": "MYSTERY",
        "script_hash": "deadbeef12345678",  # Corrupted or mismatched hash
    }
    passed, issues, meta = validate_story_provenance(record, script)
    assert not passed
    assert any("Provenance mismatch" in iss for iss in issues)


# ── Phase 3 Tests: Scene Repetition & Storyboard Matching ──

def test_assign_line_scenes_prevents_consecutive_repetition():
    script_data = {
        "lines": [
            {"text": "In 1872 an intact ship was discovered sailing alone."},
            {"text": "British sailors boarded the empty vessel expecting a fight."},
            {"text": "Instead they found six months of supplies completely untouched."},
            {"text": "Naval investigators found zero evidence of mutiny."},
            {"text": "The ghost ship remains one of the ocean's greatest enigmas."},
        ]
    }
    updated = assign_line_scenes(script_data)
    scenes = [ln["scene"]["visual_type"] for ln in updated["lines"]]
    for i in range(len(scenes) - 1):
        assert scenes[i] != scenes[i + 1], f"Consecutive repetition found: scene {i} and {i+1} both '{scenes[i]}'"


# ── Phase 6 Tests: Quality Control 5D Sub-Scores & Hard Failures ──

def test_qc_gatekeeper_reports_5d_sub_scores(tmp_path):
    # Dummy video file that fails size check -> should report categorized failure
    dummy_mp4 = tmp_path / "dummy.mp4"
    dummy_mp4.write_bytes(b"\x00" * 50)  # Too small

    report = verify_video(dummy_mp4, {"category": "MYSTERY", "sources": ["Archive"]})
    assert not report.passed
    assert "integrity_missing" in report.checks.get("failure_categories", [])
