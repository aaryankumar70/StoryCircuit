"""Comprehensive test suite for CurioLoop Creator Series & Cinematic Visuals Integration."""
from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from curiosity_engine.creator_series.models import (
    EpisodeRecord,
    EpisodeStatus,
    RightsStatus,
    SeriesRecord,
    SeriesStatus,
    VisualQualityScore,
)
from curiosity_engine.creator_series.series_db import SeriesDatabase
from curiosity_engine.creator_series.story_adapter import (
    StoryAdapter,
    estimate_narration_duration,
    split_into_sentences,
)
from curiosity_engine.creator_series.continuity import (
    ContinuityEngine,
    ContinuityLedgerEntry,
    StoryContinuityBible,
)
from curiosity_engine.creator_series.visual_director import VisualDirector
from curiosity_engine.creator_series.renderer_adapter import RendererAdapter
from curiosity_engine.creator_series.visual_qc import VisualQCEvaluator
from curiosity_engine.creator_series.pipeline_integration import get_slot2_content_choice
from curiosity_engine.dashboard.app import app
from curiosity_engine.state.db import DatabaseClient

SAMPLE_HORROR_STORY = (
    "I was only nine when our school bus broke down on the mountain pass during the autumn excursion. "
    "The substitute driver had hollow eyes and spoke with a quiet, raspy voice. "
    "He gathered all the children around his seat, asking if we wanted to hear the most terrifying story in existence. "
    "I was sitting in the very back row with my headphones on, nursing a terrible fever, and I never heard a single word. "
    "When I finally opened my eyes, the bus was unnaturally silent, and every child stared ahead in paralyzed terror. "
    "A moment later, an oncoming timber truck slammed into our driver's side. "
    "Decades passed, but my childhood friend Isaiah refused to speak of what the driver told them. "
    "On his deathbed, Isaiah whispered that he would only tell me when I turned fifty-five, because the story demanded it. "
    "He died that night with the secret locked in his chest. "
    "Years later in a quiet café, I overheard Maria weeping to a stranger in the dim corner. "
    "She said the story was never a tale, but a curse that numbered every child on that bus. "
    "Shinji fell into a coma, Mitsuko perished on her wedding day, and Isaiah was promised fifty-five years. "
    "Then I heard Maria whisper the driver's final sentence: Joshua dies three days after he hears this story. "
    "The cold air left my lungs as the teacup shattered on the wooden floor."
)


@pytest.fixture
def temp_db(tmp_path: Path):
    db_file = tmp_path / "test_firestore.json"
    client = DatabaseClient(custom_file=db_file)
    s_db = SeriesDatabase(db_client=client)
    return s_db, client


# ── Story Engine Tests ──

def test_split_into_sentences():
    sentences = split_into_sentences(SAMPLE_HORROR_STORY)
    assert len(sentences) >= 12
    assert "headphones" in sentences[3].lower()
    assert "shattered" in sentences[-1].lower()


def test_estimate_narration_duration():
    # ~210 words; duration should be around 85-95s
    dur = estimate_narration_duration(SAMPLE_HORROR_STORY)
    assert 70.0 <= dur <= 110.0


def test_story_adapter_analysis():
    adapter = StoryAdapter()
    analysis = adapter.analyze_story("The Scariest Story Ever Told", SAMPLE_HORROR_STORY)
    assert analysis.perspective == "first_person"
    assert "shattered" in analysis.original_ending.lower()
    char_names = [c["name"] for c in analysis.characters]
    assert "Isaiah" in char_names or "Maria" in char_names


def test_story_adapter_segmentation_bounds():
    adapter = StoryAdapter()
    analysis = adapter.analyze_story("The Scariest Story Ever Told", SAMPLE_HORROR_STORY)
    outlines = adapter.create_narrative_outline(analysis, SAMPLE_HORROR_STORY, num_episodes=3)
    assert len(outlines) == 3

    for outline in outlines:
        # Check that duration is reasonably calibrated
        assert 15.0 <= outline.target_duration <= 60.0
        assert len(outline.hook) > 0
        assert len(outline.cliffhanger) > 0

    # Ensure last outline preserves the original ending
    assert "shattered" in outlines[-1].cliffhanger.lower()


def test_story_adapter_narration_adaptation():
    adapter = StoryAdapter()
    analysis = adapter.analyze_story("The Scariest Story", SAMPLE_HORROR_STORY)
    outlines = adapter.create_narrative_outline(analysis, SAMPLE_HORROR_STORY, num_episodes=2)
    ep1 = adapter.adapt_episode_narration("test_series", outlines[0], SAMPLE_HORROR_STORY, analysis)

    assert ep1.episode_id == "test_series_ep01"
    assert ep1.status == EpisodeStatus.ADAPTED
    assert len(ep1.adapted_narration) > 50
    assert ep1.estimated_duration >= 20.0


# ── Continuity Engine Tests ──

def test_continuity_validation():
    engine = ContinuityEngine()
    bible = StoryContinuityBible(series_id="test_series")

    entry1 = ContinuityLedgerEntry(
        episode_num=1,
        title="Part 1",
        revealed_facts=["Bus broke down on mountain pass"],
        introduced_characters=["Isaiah"],
        introduced_locations=["Mountain Pass"],
        opening_frame_motif="motif_empty_seat",
        closing_frame_motif="motif_mist",
        withheld_until_next=["The driver's exact prophecy"],
        hand_off_notes="Hands off in mist",
    )
    engine.record_episode_in_ledger(bible, entry1)

    # Ep 2 with redundant intro should be flagged
    redundant_narration = "Meet Isaiah, my childhood friend who was there."
    is_valid, errors = engine.validate_episode_continuity(bible, 2, redundant_narration)
    assert not is_valid
    assert any("redundant" in e.lower() for e in errors)

    # Ep 2 with premature revelation of withheld secret should be flagged
    premature_narration = "The driver's exact prophecy was that everyone dies."
    is_valid2, errors2 = engine.validate_episode_continuity(
        bible, 2, premature_narration, upcoming_secrets=["The driver's exact prophecy"]
    )
    assert not is_valid2
    assert any("premature" in e.lower() for e in errors2)


# ── Visual System Tests ──

def test_visual_bible_schema_conformance():
    vd = VisualDirector()
    bible = vd.create_horror_visual_bible(
        series_id="test_horror",
        title="The Scariest Story",
        logline="A man discovers that a forgotten childhood story predicted his death.",
    )
    assert bible["schema_version"] == "1.0"
    assert bible["profile"] == "psychological_horror"
    assert len(bible["visual_identity"]["palette"]["colors"]) >= 4
    assert len(bible["characters"]) >= 2
    assert len(bible["locations"]) >= 3


def test_episode_storyboard_schema_conformance():
    vd = VisualDirector()
    bible = vd.create_horror_visual_bible("test_horror", "The Scariest Story", "Logline description here.")
    ep = EpisodeRecord(
        episode_id="test_horror_ep01",
        series_id="test_horror",
        episode_num=1,
        title="Part 1: The Mountain Pass",
        adapted_narration="The bus stopped in the mist. The driver gathered the children around him.",
        hook="The bus stopped in the mist.",
        cliffhanger="The driver gathered the children around him.",
    )
    storyboard = vd.create_episode_storyboard("test_horror", ep, bible, duration_s=45.0)

    assert storyboard["schema_version"] == "1.0"
    assert storyboard["series_id"] == "test_horror"
    assert storyboard["episode_number"] == 1
    assert len(storyboard["scenes"]) >= 3
    for s in storyboard["scenes"]:
        assert s["tension_level"] >= 1
        assert "palette" in s
        assert "lighting" in s


def test_renderer_adapter_translation():
    vd = VisualDirector()
    bible = vd.create_horror_visual_bible("test_horror", "Title", "Logline description text.")
    ep = EpisodeRecord(
        episode_id="test_horror_ep01",
        series_id="test_horror",
        episode_num=1,
        title="Part 1",
        adapted_narration="Sentence one. Sentence two. Sentence three.",
    )
    storyboard = vd.create_episode_storyboard("test_horror", ep, bible)

    ra = RendererAdapter()
    script_data, downgrades = ra.translate_storyboard_to_script_data(storyboard, bible)
    assert script_data["style"] == "paper-atlas"
    assert len(script_data["lines"]) >= 3
    assert "visual_profile" in script_data


def test_visual_qc_scoring():
    vd = VisualDirector()
    bible = vd.create_horror_visual_bible("test_horror", "Title", "Logline description text.")
    ep = EpisodeRecord(
        episode_id="test_horror_ep01",
        series_id="test_horror",
        episode_num=1,
        title="Part 1",
        adapted_narration="Sentence one. Sentence two. Sentence three.",
    )
    storyboard = vd.create_episode_storyboard("test_horror", ep, bible)

    qc = VisualQCEvaluator()
    score = qc.evaluate_storyboard(storyboard, bible)

    assert score.average_score >= 7.5
    assert score.serialized_score_min >= 8.0
    assert score.verdict in ("SHIP", "REVISE")


# ── Scheduling & State Management Tests ──

def test_series_database_lifecycle(temp_db):
    s_db, raw_db = temp_db
    series = SeriesRecord(
        series_id="pilot_horror",
        title="The Scariest Story",
        full_script=SAMPLE_HORROR_STORY,
        planned_episodes=3,
        status=SeriesStatus.ACTIVE,
    )
    s_db.save_series(series)

    # Check persistence
    fetched = s_db.get_series("pilot_horror")
    assert fetched is not None
    assert fetched.status == SeriesStatus.ACTIVE
    assert fetched.next_episode_num == 1

    # Add episodes
    for i in range(1, 4):
        ep = EpisodeRecord(
            episode_id=f"pilot_horror_ep{i:02d}",
            series_id="pilot_horror",
            episode_num=i,
            title=f"Part {i}",
            adapted_narration=f"Narration for episode {i}",
            status=EpisodeStatus.READY,
        )
        s_db.save_episode(ep)

    # Next eligible should be Ep 1
    next_ep = s_db.get_next_eligible_episode("pilot_horror")
    assert next_ep is not None
    assert next_ep.episode_num == 1

    # Mark Ep 1 published
    s_db.mark_episode_published("pilot_horror", "pilot_horror_ep01", "yt_123")
    fetched = s_db.get_series("pilot_horror")
    assert fetched.next_episode_num == 2
    assert "pilot_horror_ep01" in fetched.published_episode_ids

    # Next eligible is now Ep 2
    next_ep2 = s_db.get_next_eligible_episode("pilot_horror")
    assert next_ep2.episode_num == 2

    # Simulate failure on Ep 2: sequence must NOT advance!
    s_db.record_episode_failure("pilot_horror", "pilot_horror_ep02", "Simulated render timeout")
    fetched = s_db.get_series("pilot_horror")
    assert fetched.next_episode_num == 2
    # Failed episode halts advancement
    assert s_db.get_next_eligible_episode("pilot_horror") is None

    # Reset Ep 2 to READY and publish it
    ep2 = s_db.get_episode("pilot_horror_ep02")
    ep2.status = EpisodeStatus.READY
    s_db.save_episode(ep2)
    s_db.mark_episode_published("pilot_horror", "pilot_horror_ep02", "yt_456")

    # Publish Ep 3 (final episode)
    s_db.mark_episode_published("pilot_horror", "pilot_horror_ep03", "yt_789")
    fetched = s_db.get_series("pilot_horror")
    assert fetched.status == SeriesStatus.COMPLETED
    assert fetched.completion_state["total_published"] == 3

    # Completed series is no longer active
    assert s_db.get_active_series() is None


def test_slot2_priority_integration(temp_db, monkeypatch):
    s_db, _ = temp_db
    import sys
    import curiosity_engine.creator_series.pipeline_integration as cpi_module
    import curiosity_engine.runner.pipeline as pipeline_mod

    monkeypatch.setattr(cpi_module, "series_db", s_db)

    # When no series exists -> Slot 2 is automatic
    choice, payload = get_slot2_content_choice()
    assert choice == "automatic"
    assert payload is None

    # Create active series with 1 episode
    series = SeriesRecord(
        series_id="active_test",
        title="Active Story",
        full_script=SAMPLE_HORROR_STORY,
        planned_episodes=1,
        status=SeriesStatus.ACTIVE,
    )
    s_db.save_series(series)
    ep = EpisodeRecord(
        episode_id="active_test_ep01",
        series_id="active_test",
        episode_num=1,
        title="Part 1",
        adapted_narration="Narration text",
        status=EpisodeStatus.READY,
    )
    s_db.save_episode(ep)

    # Now Slot 2 prioritizes Creator Series
    choice, payload = get_slot2_content_choice()
    assert choice == "creator_series"
    assert payload is not None
    s_rec, ep_rec = payload
    assert s_rec.series_id == "active_test"
    assert ep_rec.episode_num == 1


# ── Dashboard API Tests ──

def test_dashboard_series_api(temp_db, monkeypatch):
    s_db, _ = temp_db
    import curiosity_engine.dashboard.series_api as sapi_module

    monkeypatch.setattr(sapi_module, "series_db", s_db)

    client = TestClient(app)

    # 1. Create series
    res = client.post(
        "/api/series/create",
        json={
            "series_id": "api_test_series",
            "title": "API Test Series",
            "full_script": SAMPLE_HORROR_STORY,
            "content_type": "psychological_horror",
            "rights_status": "UNVERIFIED_EVALUATION_ONLY",
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "success"
    assert data["series"]["series_id"] == "api_test_series"

    # 2. Analyze
    res_an = client.post("/api/series/api_test_series/analyze")
    assert res_an.status_code == 200
    assert "analysis" in res_an.json()

    # 3. Segment
    res_seg = client.post("/api/series/api_test_series/segment", params={"episode_count": 3})
    assert res_seg.status_code == 200
    assert res_seg.json()["planned_episodes"] == 3

    # 4. Activate
    res_act = client.post("/api/series/api_test_series/activate")
    assert res_act.status_code == 200
    assert res_act.json()["series_status"] == "ACTIVE"

    # 5. Pause
    res_pause = client.post("/api/series/api_test_series/pause")
    assert res_pause.status_code == 200
    assert res_pause.json()["series_status"] == "PAUSED"

    # 6. Resume
    res_resume = client.post("/api/series/api_test_series/resume")
    assert res_resume.status_code == 200
    assert res_resume.json()["series_status"] == "ACTIVE"
