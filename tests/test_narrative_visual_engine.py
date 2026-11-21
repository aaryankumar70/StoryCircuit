"""Comprehensive unit and regression tests for CurioLoop Narrative Visual Engine.

Tests:
1. Cinematography: Shot types, motivated camera paths, quintic easing, keyframes.
2. Visual Diversity: Pairwise similarity checks, framing repetition penalty.
3. Visual Continuity: Entity persistence, era consistency, 180-degree screen direction.
4. Semantic Asset Selection: Grounded subject matching, era-appropriate assets, zero filler.
5. Narrative Visual Director: Beat-by-beat storyboard synthesis, rationale generation.
6. Storyboard Approval Manager: Dossier generation, manual and programmatic gates.
7. Semantic Visual QC: 10-criterion rubric evaluation and scoring.
"""

import json
import pytest
from pathlib import Path

from curiosity_engine.production.cinematography import (
    CameraShotType,
    CameraMotivation,
    CameraKeyframe,
    CameraShotSpec,
    quintic_in_out,
    create_motivated_camera_path,
)
from curiosity_engine.production.visual_diversity import (
    VisualDiversityChecker,
    SequenceDiversityReport,
    DiversityComparison,
)
from curiosity_engine.production.visual_continuity import (
    VisualContinuityTracker,
    ContinuityAuditReport,
    ContinuityViolation,
)
from curiosity_engine.production.semantic_asset_selector import (
    SemanticAssetSelector,
)
from curiosity_engine.production.visual_director import (
    NarrativeVisualDirector,
    NarrativeSceneSpecification,
)
from curiosity_engine.production.storyboard_approval import (
    StoryboardApprovalManager,
)
from curiosity_engine.quality.visual_semantic_qc import (
    SemanticVisualQC,
)


# ---------------------------------------------------------------------------
# 1. CINEMATOGRAPHY TESTS
# ---------------------------------------------------------------------------

def test_cinematography_easing_curves():
    # At t=0, value is 0.0
    assert quintic_in_out(0.0) == 0.0
    # At t=1, value is 1.0
    assert quintic_in_out(1.0) == 1.0
    # At t=0.5, symmetric inflection point is 0.5
    assert abs(quintic_in_out(0.5) - 0.5) < 1e-5


def test_cinematography_motivated_camera_path():
    spec = create_motivated_camera_path(
        shot_type=CameraShotType.ESTABLISHING,
        motivation=CameraMotivation.ISOLATION,
        duration_sec=6.0,
        target=(0.0, -20.0, 0.0),
        narrative_reason="Establishing lonely ship in vast ocean",
    )
    assert spec.shot_type == CameraShotType.ESTABLISHING
    assert spec.motivation == CameraMotivation.ISOLATION
    assert spec.duration_sec == 6.0
    assert len(spec.keyframes) == 2
    d = spec.to_dict()
    assert d["shot_type"] == "ESTABLISHING"
    assert d["motivation"] == "ISOLATION"


# ---------------------------------------------------------------------------
# 2. VISUAL DIVERSITY AUDITOR TESTS
# ---------------------------------------------------------------------------

def test_visual_diversity_detects_consecutive_identical_shots():
    scenes = [
        {"scene_id": "SCN_01", "composition_type": "TYPE_A", "rendering_method": "CINEMATIC_2_5D", "camera": {"shot_type": "WIDE"}, "primary_subject": {"name": "Ship"}, "environment": {"palette": ["#111111", "#222222"]}},
        {"scene_id": "SCN_02", "composition_type": "TYPE_A", "rendering_method": "CINEMATIC_2_5D", "camera": {"shot_type": "WIDE"}, "primary_subject": {"name": "Ship"}, "environment": {"palette": ["#111111", "#222222"]}},
        {"scene_id": "SCN_03", "composition_type": "TYPE_A", "rendering_method": "CINEMATIC_2_5D", "camera": {"shot_type": "WIDE"}, "primary_subject": {"name": "Ship"}, "environment": {"palette": ["#111111", "#222222"]}},
        {"scene_id": "SCN_04", "composition_type": "TYPE_A", "rendering_method": "CINEMATIC_2_5D", "camera": {"shot_type": "WIDE"}, "primary_subject": {"name": "Ship"}, "environment": {"palette": ["#111111", "#222222"]}},
    ]
    checker = VisualDiversityChecker()
    report = checker.audit_sequence(scenes)
    assert report.total_scenes == 4
    assert len(report.violations) > 0


def test_visual_diversity_passes_varied_scenes():
    scenes = [
        {"scene_id": "SCN_01", "composition_type": "HORIZON_WIDE", "rendering_method": "CINEMATIC_2_5D", "camera": {"shot_type": "ESTABLISHING"}, "primary_subject": {"name": "Ship"}, "environment": {"palette": ["#112233", "#445566"]}},
        {"scene_id": "SCN_02", "composition_type": "INTERIOR_MEDIUM", "rendering_method": "SELECTIVE_3D", "camera": {"shot_type": "MEDIUM"}, "primary_subject": {"name": "Deck"}, "environment": {"palette": ["#332211", "#665544"]}},
        {"scene_id": "SCN_03", "composition_type": "DOCUMENT_MACRO", "rendering_method": "ARCHIVAL_IMAGERY", "camera": {"shot_type": "MACRO_CLOSEUP"}, "primary_subject": {"name": "Logbook"}, "environment": {"palette": ["#f0e0d0", "#806040"]}},
        {"scene_id": "SCN_04", "composition_type": "ATMOSPHERE_WIDE", "rendering_method": "PROCEDURAL_ENV", "camera": {"shot_type": "DOLLY_OUT"}, "primary_subject": {"name": "Horizon"}, "environment": {"palette": ["#051020", "#102030"]}},
    ]
    checker = VisualDiversityChecker()
    report = checker.audit_sequence(scenes)
    assert report.passed is True
    assert report.diversity_score >= 7.0


# ---------------------------------------------------------------------------
# 3. VISUAL CONTINUITY TRACKER TESTS
# ---------------------------------------------------------------------------

def test_visual_continuity_detects_era_rupture():
    scenes = [
        {"scene_id": "SCN_01", "environment": {"era": "1872 Victorian"}},
        {"scene_id": "SCN_02", "environment": {"era": "2026 Modern Futuristic"}},
    ]
    tracker = VisualContinuityTracker()
    report = tracker.audit_sequence(scenes)
    assert len(report.violations) > 0
    assert any("era" in v.rule.lower() or "rupture" in v.description.lower() for v in report.violations)


def test_visual_continuity_tracks_entity_persistence():
    scenes = [
        {"scene_id": "SCN_01", "environment": {"era": "1872"}, "primary_subject": {"name": "Mary Celeste", "attributes": {"color": "wood", "masts": 2}}},
        {"scene_id": "SCN_02", "environment": {"era": "1872"}, "primary_subject": {"name": "Mary Celeste", "attributes": {"color": "wood", "masts": 2}}},
    ]
    tracker = VisualContinuityTracker()
    report = tracker.audit_sequence(scenes)
    assert report.passed is True


# ---------------------------------------------------------------------------
# 4. SEMANTIC ASSET SELECTOR TESTS
# ---------------------------------------------------------------------------

def test_semantic_asset_selector_resolves_ship():
    selector = SemanticAssetSelector()
    path, record, score = selector.select_asset_for_scene(
        primary_subject="The Mary Celeste Brigantine",
        narration_text="In December 1872, the brigantine was discovered abandoned in the Atlantic ocean.",
        era="1872",
        category="MYSTERY",
    )
    assert record is not None
    assert score > 0.4
    assert path.exists() or "mary_celeste" in str(path)
    assert "mary_celeste" in record.asset_id or "brigantine" in record.subject_name.lower()


def test_semantic_asset_selector_resolves_cabin_and_logbook():
    selector = SemanticAssetSelector()
    path, record, score = selector.select_asset_for_scene(
        primary_subject="Archival Captains Logbook",
        narration_text="Down in the cabin, an open logbook lay with its final entry.",
        era="1872",
        category="MYSTERY",
    )
    assert record is not None
    assert path is not None


# ---------------------------------------------------------------------------
# 5. NARRATIVE VISUAL DIRECTOR TESTS
# ---------------------------------------------------------------------------

def test_narrative_visual_director_generates_storyboard():
    director = NarrativeVisualDirector()
    script_data = {
        "title": "The Ghost Vessel of 1872",
        "category": "HISTORICAL_MYSTERY",
        "lead": 0.4,
        "lines": [
            {"text": "In 1872, a brigantine was found drifting alone in the North Atlantic.", "gap": 0.3},
            {"text": "Its sails were fully hoisted, but the helm was unmanned.", "gap": 0.3},
            {"text": "Down below, an open ledger was signed only ten days earlier.", "gap": 0.3},
        ]
    }
    storyboard = director.direct_script(script_data)
    assert storyboard["total_scenes"] == 3
    assert storyboard["title"] == "The Ghost Vessel of 1872"
    for s in storyboard["scenes"]:
        assert "visual_match_explanation" in s
        assert len(s["visual_match_explanation"]) > 20
        assert s["camera"]["shot_type"] in [st.value for st in CameraShotType]
        assert s["primary_subject"]["name"] != ""


# ---------------------------------------------------------------------------
# 6. STORYBOARD APPROVAL MANAGER TESTS
# ---------------------------------------------------------------------------

def test_storyboard_approval_workflow(tmp_path):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    storyboard = {
        "title": "Test Mystery",
        "total_scenes": 2,
        "total_duration_sec": 12.0,
        "historical_era": "1872",
        "primary_setting": "North Atlantic",
        "scenes": [
            {
                "scene_id": "SCN_01",
                "narration": {"text": "A ship drifting on the ocean.", "start_s": 0.0, "end_s": 6.0, "duration_sec": 6.0},
                "primary_subject": {"name": "Ghost Ship", "action": "drifting"},
                "environment": {"name": "Atlantic", "era": "1872", "lighting": "DUSK"},
                "rendering_method": "CINEMATIC_2_5D",
                "camera": {"shot_type": "ESTABLISHING", "motivation": "ISOLATION"},
                "visual_match_explanation": "Visual matches narration of ship drifting."
            },
            {
                "scene_id": "SCN_02",
                "narration": {"text": "The logbook lay open on the desk.", "start_s": 6.0, "end_s": 12.0, "duration_sec": 6.0},
                "primary_subject": {"name": "Logbook", "action": "resting open"},
                "environment": {"name": "Cabin", "era": "1872", "lighting": "CANDLELIGHT"},
                "rendering_method": "ARCHIVAL_IMAGERY",
                "camera": {"shot_type": "MACRO_CLOSEUP", "motivation": "EVIDENCE"},
                "visual_match_explanation": "Visual matches narration of open logbook."
            }
        ]
    }

    # Save without auto-approve
    sb_file = StoryboardApprovalManager.save_storyboard(project_dir, storyboard, auto_approve=False)
    assert sb_file.exists()
    approved, _ = StoryboardApprovalManager.is_approved(project_dir)
    assert not approved

    # Approve
    approval = StoryboardApprovalManager.approve_storyboard(project_dir, reviewer="TestAuditor")
    assert approval["approval_status"] == "APPROVED"
    approved_after, _ = StoryboardApprovalManager.is_approved(project_dir)
    assert approved_after


# ---------------------------------------------------------------------------
# 7. SEMANTIC VISUAL QC TESTS
# ---------------------------------------------------------------------------

def test_semantic_visual_qc_scores_valid_storyboard():
    storyboard = {
        "title": "The Mystery of the Mary Celeste",
        "total_scenes": 3,
        "total_duration_sec": 18.0,
        "historical_era": "1872",
        "primary_setting": "North Atlantic",
        "scenes": [
            {
                "scene_id": "SCN_01",
                "narration": {"text": "In 1872, the brigantine was discovered abandoned in the North Atlantic ocean."},
                "primary_subject": {"name": "Mary Celeste Brigantine"},
                "environment": {"name": "North Atlantic Ocean", "era": "1872", "palette": ["#1a2d42", "#243c58"]},
                "camera": {"shot_type": "ESTABLISHING", "motivation": "ISOLATION"},
                "rendering_method": "CINEMATIC_2_5D",
                "visual_match_explanation": "Directly presents the Mary Celeste in the Atlantic."
            },
            {
                "scene_id": "SCN_02",
                "narration": {"text": "The boarding crew walked the silent wooden deck with no souls aboard."},
                "primary_subject": {"name": "Unmanned Wooden Deck"},
                "environment": {"name": "North Atlantic Ocean", "era": "1872", "palette": ["#1a2d42", "#3a4c58"]},
                "camera": {"shot_type": "MEDIUM", "motivation": "INVESTIGATION"},
                "rendering_method": "CINEMATIC_2_5D",
                "visual_match_explanation": "Directly presents the silent wooden deck."
            },
            {
                "scene_id": "SCN_03",
                "narration": {"text": "Inside the cabin lay an open logbook with handwriting intact."},
                "primary_subject": {"name": "Archival Open Logbook"},
                "environment": {"name": "Cabin Interior", "era": "1872", "palette": ["#2e1f14", "#4a3520"]},
                "camera": {"shot_type": "MACRO_CLOSEUP", "motivation": "EVIDENCE"},
                "rendering_method": "ARCHIVAL_IMAGERY",
                "visual_match_explanation": "Directly presents the archival open logbook in close up."
            }
        ]
    }

    report = SemanticVisualQC.evaluate_storyboard(storyboard)
    assert report.passed is True
    assert report.overall_semantic_score >= 8.5
    assert len(report.rejection_reasons) == 0
    assert len(report.scene_results) == 3
    assert report.scene_results[0].criterion_scores["1_narration_correspondence"] >= 8.5
    assert report.scene_results[0].criterion_scores["2_subject_correctness"] >= 8.5
