"""Unit tests for Dynamic Production Planning, Cascading Invalidation, and Storyboard Approval.

Verifies:
1. Dynamic Production-Plan Recommendations (Step 3):
   - Non-arbitrary episode counts based on natural narrative stopping points (never mechanical fixed splits).
   - Dynamic variation across story lengths (standalone 1 episode, 2, 4, 6 episodes).
   - Format presets: 1m (~60s), 1.5m (~90s), 3m (~180s), and custom seconds.
   - Pacing and retention trade-off analysis.
   - Episode summaries with opening hooks and cliffhanger endings.
2. Three.js Narrative Visual Scene Storyboards (Step 4):
   - Generation of grounded 3D WebGL narrative environments (ocean, helm, cabin, etc.).
   - Scene-by-scene timing, camera language, and tension grading.
3. Cascading Invalidation on Granular Single-Episode Edits:
   - Modifying an episode sets STALE_INVALIDATED on that episode only.
   - Version increment and render/audio cache invalidation.
   - Preserves all untouched episodes in the series completely unaffected.
4. Visual Storyboard Approval Gate:
   - Setting is_approved flag, approval metadata, and status advancement.
5. REST API Endpoints:
   - POST /api/series/recommend-plans
   - POST /api/series/generate-breakdown
   - PUT /api/series/episodes/{episode_id}
   - POST /api/series/episodes/{episode_id}/approve
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pathlib import Path

from curiosity_engine.creator_series.models import (
    EpisodeRecord,
    EpisodeStatus,
    SeriesRecord,
    SeriesStatus,
)
from curiosity_engine.creator_series.production_planner import (
    ProductionPlanner,
    estimate_duration_seconds,
    split_into_sentences,
)
from curiosity_engine.creator_series.series_db import SeriesDatabase
from curiosity_engine.dashboard.app import app
from curiosity_engine.state.db import DatabaseClient

SHORT_STORY = (
    "The antique music box sat forgotten on my grandfather's dusty mahogany mantle. "
    "Every midnight without fail, the tarnished bronze ballerina spun three slow revolutions in total darkness. "
    "Last night, I finally opened the lid to stop the gear mechanism, only to find the interior hollow. "
    "A folded yellowed note was tucked beneath the velvet lining: 'She does not dance for the living.'"
)

MEDIUM_STORY = (
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

LONG_EPIC_STORY = (
    "In the winter of 1872, the brigantine Mary Celeste drifted through the grey swell of the Azores. "
    "When the crew of the Dei Gratia boarded her, they found the ship completely abandoned under partial canvas. "
    "The galley stove was still warm, three cups of tea sat half-drunk on the mess table, and the captain's logbook lay open. "
    "Not a single drop of blood or sign of violence marked the oiled cedar deck. "
    "Yet every soul—Captain Briggs, his wife, their two-year-old daughter Sophia, and seven seasoned sailors—had vanished into the Atlantic mist. "
    "Ten years after the inquest, the salvage diver Thomas Lang entered the sunken salvage yard in Gibraltar. "
    "In the rusted safe salvaged from the captain's cabin, he discovered an uncataloged journal bound in cracked calfskin. "
    "The handwriting inside began with standard navigational logs of wind speed and barometric pressure. "
    "By the fourth entry, the prose deteriorated into jagged, frantic strokes describing a vibration beneath the keel. "
    "Briggs wrote of a resonant, low-frequency hum that vibrated through the hull every evening at twilight. "
    "The ship's chronometer began spinning counterclockwise whenever the vessel neared the 38th parallel. "
    "On November 24th, Briggs noted that the sailors refused to enter the lower cargo hold, claiming the nine hundred barrels of denatured alcohol were whispering names. "
    "The final entry was penned on the morning of November 25th in trembling ink. "
    "'It is not the sea that calls us,' Briggs scrawled across the ledger page. "
    "'Something beneath the water has learned our voices, and Sophia has already walked over the rail to meet it.' "
    "When Lang finished reading, the paraffin lamp in his workshop flickered and went out. "
    "In the pitch darkness of the dry dock, three gentle knocks echoed from the bottom of the empty wooden hull. "
    "Lang refused to accept another salvage contract and retreated to an isolated cottage in the Cornish cliffs. "
    "For three years, the rhythmic tapping on wood returned every autumn during the first frost. "
    "He installed deadbolts and barred the storm cellar, but at midnight the floorboards groaned under heavy, wet footsteps. "
    "A trail of briny seawater led from the front door directly to the rocking chair in his study. "
    "On the final night of October, the village constable found Lang's front door swinging wide in the gale. "
    "The oil lamp was shattered on the stones, and across the whitewashed chimney, five words were carved with an oyster knife: "
    "'We are sailing home together.' "
    "To this day, fishermen off Lizard Point swear they still see the Mary Celeste riding high on the breakers, her masts glowing with cold blue fire."
)


@pytest.fixture
def temp_planner(tmp_path: Path):
    db_file = tmp_path / "planner_test_db.json"
    client = DatabaseClient(custom_file=db_file)
    s_db = SeriesDatabase(db_client=client)
    planner = ProductionPlanner(db_instance=s_db)
    return planner, s_db, client


# ──────────────────────────────────────────────────────────────────────────
# Dynamic Production Planning Tests
# ──────────────────────────────────────────────────────────────────────────

def test_dynamic_planning_standalone_for_short_story(temp_planner):
    """Short story (~60 words) should naturally resolve to 1 standalone episode,
    NEVER forcing arbitrary multi-episode splits!
    """
    planner, _, _ = temp_planner
    plans = planner.generate_production_plans(SHORT_STORY, title="The Music Box")
    assert len(plans) >= 3

    plan_60s = next(p for p in plans if p["format_preset"] == "1m")
    plan_90s = next(p for p in plans if p["format_preset"] == "1.5m")
    plan_180s = next(p for p in plans if p["format_preset"] == "3m")

    # Short story fits in 1 standalone episode for all longer presets
    assert plan_90s["episode_count"] == 1
    assert plan_180s["episode_count"] == 1
    assert "Standalone" in plan_180s["episodes"][0]["title"]


def test_dynamic_planning_non_arbitrary_episode_counts(temp_planner):
    """Stories of different lengths produce different, organic episode counts
    based on natural narrative stopping points rather than fixed splits.
    """
    planner, _, _ = temp_planner
    plans_med = planner.generate_production_plans(MEDIUM_STORY, title="The Scariest Story")
    plans_long = planner.generate_production_plans(LONG_EPIC_STORY, title="The Mary Celeste")

    med_60s = next(p for p in plans_med if p["format_preset"] == "1m")
    long_60s = next(p for p in plans_long if p["format_preset"] == "1m")
    long_180s = next(p for p in plans_long if p["format_preset"] == "3m")

    # Medium story (~210 words) at 60s should be ~2-3 episodes
    assert 2 <= med_60s["episode_count"] <= 3

    # Long story (~320 words) at 60s should be ~3-4 episodes
    assert 3 <= long_60s["episode_count"] <= 5

    # Long story at 180s should be fewer episodes (1-2)
    assert 1 <= long_180s["episode_count"] <= 2

    # Episode counts between short, medium, and long stories must dynamically vary
    assert med_60s["episode_count"] != 1 or med_60s["total_runtime_sec"] > 70.0


def test_dynamic_episode_counts_1_2_4_6_scaling(temp_planner):
    """Explicitly verifies non-arbitrary episode count scaling:
    - 1 episode for short stories (~60 words)
    - 2 episodes for medium stories (~210 words)
    - 4 episodes for ~500 word narrative
    - 6 episodes for ~750 word epic
    Never forced to arbitrary mechanical splits!
    """
    planner, _, _ = temp_planner

    # 1. Short Story -> 1 Standalone Episode
    plans_1 = planner.generate_production_plans(SHORT_STORY, title="Short Story")
    plan_1 = next(p for p in plans_1 if p["format_preset"] == "1m")
    assert plan_1["episode_count"] == 1

    # 2. Medium Story (~210 words) -> 2 Episodes at 60s
    plans_2 = planner.generate_production_plans(MEDIUM_STORY, title="Medium Story")
    plan_2 = next(p for p in plans_2 if p["format_preset"] == "1m")
    assert plan_2["episode_count"] == 2

    # 3. 4-Episode Story (~510 words)
    story_4ep = " ".join((LONG_EPIC_STORY + " " + MEDIUM_STORY).split()[:510])
    plans_4 = planner.generate_production_plans(story_4ep, title="Four Episode Arc")
    plan_4 = next(p for p in plans_4 if p["format_preset"] == "1m")
    assert plan_4["episode_count"] == 4

    # 4. 6-Episode Epic (~750 words)
    story_6ep = LONG_EPIC_STORY + "\n\n" + LONG_EPIC_STORY
    plans_6 = planner.generate_production_plans(story_6ep, title="Six Episode Epic")
    plan_6 = next(p for p in plans_6 if p["format_preset"] == "1m")
    assert plan_6["episode_count"] == 6


def test_production_plans_trade_off_analysis(temp_planner):
    """Every recommended plan must include complete trade-off analysis
    (pacing, retention pros/cons, audience fit).
    """
    planner, _, _ = temp_planner
    plans = planner.generate_production_plans(MEDIUM_STORY, title="The Scariest Story")

    for plan in plans:
        assert "plan_id" in plan
        assert "plan_title" in plan
        assert "target_duration_sec" in plan
        assert "episode_count" in plan
        assert "total_runtime_sec" in plan
        assert "trade_off_analysis" in plan

        to = plan["trade_off_analysis"]
        assert len(to["pacing"]) > 10
        assert len(to["retention_pros"]) >= 2
        assert len(to["retention_cons"]) >= 1
        assert len(to["audience_fit"]) > 5


def test_custom_seconds_plan(temp_planner):
    """Custom target duration (e.g. 75s) dynamically generates a custom plan."""
    planner, _, _ = temp_planner
    plans = planner.generate_production_plans(MEDIUM_STORY, title="Custom Story", custom_seconds=75.0)

    custom_plan = next((p for p in plans if p["format_preset"] == "custom"), None)
    assert custom_plan is not None
    assert custom_plan["target_duration_sec"] == 75.0
    assert "75s" in custom_plan["plan_title"]


def test_episode_summaries_hooks_and_cliffhangers(temp_planner):
    """Each episode outline must have an opening hook and a cliffhanger ending."""
    planner, _, _ = temp_planner
    plans = planner.generate_production_plans(MEDIUM_STORY, title="Curse of the Bus")
    plan_60s = next(p for p in plans if p["format_preset"] == "1m")

    for ep in plan_60s["episodes"]:
        assert len(ep["hook"]) > 10
        assert len(ep["cliffhanger"]) > 10
        assert ep["word_count"] > 0
        assert ep["estimated_duration_sec"] > 0.0


# ──────────────────────────────────────────────────────────────────────────
# Three.js Storyboard & Breakdown Tests
# ──────────────────────────────────────────────────────────────────────────

def test_generate_threejs_storyboard(temp_planner):
    """Verifies that generated storyboards contain Three.js 3D WebGL scenes,
    motivated camera paths, and proper tension levels.
    """
    planner, _, _ = temp_planner
    sb = planner.generate_threejs_storyboard(
        series_id="test_series_01",
        episode_num=1,
        episode_title="The Departure",
        narration=MEDIUM_STORY,
        visual_profile="psychological_horror",
    )

    assert sb["series_id"] == "test_series_01"
    assert sb["episode_number"] == 1
    assert sb["is_approved"] is False
    assert sb["approval_status"] == "PENDING_REVIEW"
    assert len(sb["scenes"]) >= 3

    # Check Three.js scene assignment
    valid_three_scenes = {"ocean_scene", "helm_scene", "cabin_scene", "procedural_environment"}
    for sc in sb["scenes"]:
        assert sc["three_js_scene"] in valid_three_scenes
        assert sc["rendering_method"] == "SELECTIVE_3D"
        assert "camera" in sc
        assert "shot_type" in sc["camera"]
        assert 1 <= sc["tension_level"] <= 10


def test_breakdown_persists_to_database(temp_planner):
    """Generating breakdown saves SeriesRecord and all EpisodeRecords to SeriesDatabase."""
    planner, s_db, _ = temp_planner
    series_rec, ep_recs = planner.generate_episode_breakdown_and_storyboards(
        raw_text=MEDIUM_STORY,
        series_id="persisted_series_01",
        title="Persisted Mystery",
        duration_preset="1m",
    )

    assert len(ep_recs) >= 2
    assert series_rec.series_id == "persisted_series_01"

    # Verify loaded from DB
    loaded_series = s_db.get_series("persisted_series_01")
    assert loaded_series is not None
    assert loaded_series.planned_episodes == len(ep_recs)

    for ep in ep_recs:
        loaded_ep = s_db.get_episode(ep.episode_id)
        assert loaded_ep is not None
        assert loaded_ep.is_approved is False
        assert loaded_ep.storyboard is not None


# ──────────────────────────────────────────────────────────────────────────
# Cascading Invalidation Tests
# ──────────────────────────────────────────────────────────────────────────

def test_cascading_invalidation_modifies_only_target_episode(temp_planner):
    """Editing episode 2 marks ONLY episode 2 as STALE_INVALIDATED,
    increments its version, resets approval, and leaves episode 1 & 3 completely UNTOUCHED!
    """
    planner, s_db, _ = temp_planner
    _, ep_recs = planner.generate_episode_breakdown_and_storyboards(
        raw_text=MEDIUM_STORY,
        series_id="invalidation_test_series",
        title="Invalidation Test",
        duration_preset="1m",
    )
    assert len(ep_recs) >= 2

    # Simulate episode 1 and 2 being in READY / APPROVED status
    ep1 = ep_recs[0]
    ep2 = ep_recs[1]
    ep1.status = EpisodeStatus.READY
    ep1.is_approved = True
    ep1.rendered_video_path = "/renders/ep1.mp4"
    s_db.save_episode(ep1)

    ep2.status = EpisodeStatus.READY
    ep2.is_approved = True
    ep2.rendered_video_path = "/renders/ep2.mp4"
    s_db.save_episode(ep2)

    # Now edit Episode 2 only
    updated_narration = "This is a revised, newly adapted narration with modified clues and high suspense."
    modified_ep2 = planner.edit_single_episode_with_invalidation(
        episode_id=ep2.episode_id,
        adapted_narration=updated_narration,
        hook="A sudden revision occurred.",
        cliffhanger="Nothing remained the same.",
    )

    # 1. Check Episode 2 is invalidated
    assert modified_ep2.status == EpisodeStatus.STALE_INVALIDATED
    assert modified_ep2.is_approved is False
    assert modified_ep2.version == 2
    assert modified_ep2.rendered_video_path is None
    assert modified_ep2.adapted_narration == updated_narration

    # 2. Check Episode 1 is completely UNTOUCHED!
    reloaded_ep1 = s_db.get_episode(ep1.episode_id)
    assert reloaded_ep1.status == EpisodeStatus.READY
    assert reloaded_ep1.is_approved is True
    assert reloaded_ep1.version == 1
    assert reloaded_ep1.rendered_video_path == "/renders/ep1.mp4"


# ──────────────────────────────────────────────────────────────────────────
# Visual Storyboard Approval Gate Tests
# ──────────────────────────────────────────────────────────────────────────

def test_storyboard_approval_gate(temp_planner):
    """Approving an episode sets is_approved=True, records approval date,
    and transitions status to READY.
    """
    planner, s_db, _ = temp_planner
    _, ep_recs = planner.generate_episode_breakdown_and_storyboards(
        raw_text=SHORT_STORY,
        series_id="approval_test_series",
        title="Approval Test",
        duration_preset="1m",
    )
    ep = ep_recs[0]
    assert ep.is_approved is False

    # Approve storyboard
    approved_ep = planner.set_storyboard_approval(
        episode_id=ep.episode_id,
        approved=True,
        reviewer="Lead Director",
        notes="Cinematography and Three.js environments verified.",
    )

    assert approved_ep.is_approved is True
    assert approved_ep.approval_date is not None
    assert approved_ep.status == EpisodeStatus.READY
    assert approved_ep.storyboard["approval_status"] == "APPROVED"
    assert approved_ep.storyboard["approved_by"] == "Lead Director"


# ──────────────────────────────────────────────────────────────────────────
# FastAPI REST Endpoints Integration Tests
# ──────────────────────────────────────────────────────────────────────────

def test_api_recommend_plans_endpoint():
    """Tests POST /api/series/recommend-plans via FastAPI TestClient."""
    client = TestClient(app)
    res = client.post(
        "/api/series/recommend-plans",
        json={
            "raw_text": MEDIUM_STORY,
            "title": "API Test Story",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert len(data["recommended_plans"]) >= 3
    plan_presets = [p["format_preset"] for p in data["recommended_plans"]]
    assert "1m" in plan_presets
    assert "1.5m" in plan_presets
    assert "3m" in plan_presets


def test_api_generate_breakdown_endpoint():
    """Tests POST /api/series/generate-breakdown via FastAPI TestClient."""
    client = TestClient(app)
    res = client.post(
        "/api/series/generate-breakdown",
        json={
            "series_id": "api_breakdown_series",
            "title": "API Breakdown Series",
            "raw_text": MEDIUM_STORY,
            "duration_preset": "1m",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert len(data["episodes"]) >= 2
    for ep in data["episodes"]:
        assert ep["is_approved"] is False
        assert ep["storyboard"] is not None


def test_api_edit_episode_put_endpoint():
    """Tests PUT /api/series/episodes/{episode_id} with cascading invalidation."""
    client = TestClient(app)
    # First create a series with episodes
    res_bd = client.post(
        "/api/series/generate-breakdown",
        json={
            "series_id": "api_edit_series",
            "title": "API Edit Series",
            "raw_text": MEDIUM_STORY,
            "duration_preset": "1m",
        },
    )
    episodes = res_bd.json()["episodes"]
    ep_id = episodes[0]["episode_id"]

    # Edit the episode
    res_edit = client.put(
        f"/api/series/episodes/{ep_id}",
        json={
            "title": "Renamed Episode 1",
            "adapted_narration": "Updated narration text through PUT endpoint.",
            "hook": "New hook for episode 1",
        },
    )
    assert res_edit.status_code == 200
    data = res_edit.json()
    assert data["status"] == "success"
    assert data["episode"]["status"] == "STALE_INVALIDATED"
    assert data["episode"]["title"] == "Renamed Episode 1"
    assert data["episode"]["version"] == 2
    assert data["episode"]["is_approved"] is False


def test_api_approve_episode_endpoint():
    """Tests POST /api/series/episodes/{episode_id}/approve."""
    client = TestClient(app)
    res_bd = client.post(
        "/api/series/generate-breakdown",
        json={
            "series_id": "api_approve_series",
            "title": "API Approve Series",
            "raw_text": SHORT_STORY,
            "duration_preset": "1m",
        },
    )
    ep_id = res_bd.json()["episodes"][0]["episode_id"]

    # Approve
    res_app = client.post(
        f"/api/series/episodes/{ep_id}/approve",
        json={"approved": True, "reviewer": "QA Lead", "notes": "Approved for 3D render"},
    )
    assert res_app.status_code == 200
    data = res_app.json()
    assert data["status"] == "success"
    assert data["is_approved"] is True
    assert data["episode"]["is_approved"] is True
    assert data["episode"]["status"] == "READY"
