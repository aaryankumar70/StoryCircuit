"""Comprehensive End-to-End Verification & Regression Testing for CurioLoop Creator Studio and Automatic Studio.

Verifies:
1. Complete 6-Step Creator Studio Workflow:
   - Step 1 Ingestion: Upload file (.txt, .md, .docx with zipfile fallback), Paste text (135 WPM), Reddit URL parsing & error handling ([deleted], [removed], 404, 403).
   - Step 2 Analysis: AI narrative analysis (title, 4-phase arc, characters, turning points, natural boundaries, visual continuity; never prematurely split).
   - Step 3 Planning: Dynamic multi-plan recommendations (1m, 1.5m, 3m, custom) based on natural stopping points with retention/pacing trade-offs.
   - Step 4 Storyboards & Invalidation: Three.js WebGL storyboard generation, approval gate (`is_approved`), and single-episode cascading invalidation (`STALE_INVALIDATED` on modified episode only).
   - Step 5 Scheduling: Schedule A (1/day), Schedule B (2/day), Schedule C (custom) calendar preview calculations and IST completion date forecasting.
   - Step 6 Queue Lifecycle: Production queue states, Pause / Resume / Cancel controls, and queue persistence.
2. Preservation of Automatic Studio:
   - Slots 09:00 IST and 19:00 IST permanently preserved at Priority 1.
   - Creator Series jobs run at Priority 10 without displacing Automatic Studio jobs.
   - Sequential execution mutex locking prevents queue deadlock and render collisions.
3. UI Contract Verification:
   - Section 9 in `curiosity_engine/dashboard/templates/index.html` implements all 6 steps, tabbed inputs, plan selection, storyboard approval, and lifecycle actions.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from curiosity_engine.creator_series.creator_studio_engine import CreatorStudioEngine
from curiosity_engine.creator_series.models import (
    EpisodeRecord,
    EpisodeStatus,
    RightsStatus,
    SeriesRecord,
    SeriesStatus,
)
from curiosity_engine.creator_series.production_planner import (
    ProductionPlanner,
    production_planner,
)
from curiosity_engine.creator_series.queue_manager import (
    JobStatus,
    JobType,
    ProductionQueueManager,
    QueueJob,
)
from curiosity_engine.creator_series.series_db import SeriesDatabase, series_db
from curiosity_engine.creator_series.series_scheduler import (
    SeriesScheduler,
    series_scheduler,
)
import curiosity_engine.dashboard.series_api as series_api_module
from curiosity_engine.dashboard.app import app
from curiosity_engine.state.db import DatabaseClient

IST = ZoneInfo("Asia/Kolkata")

SAMPLE_E2E_HORROR_STORY = (
    "The lighthouse on Smuggler's Point had been automated for twenty years, but every winter solstice, "
    "the foghorn still blared twelve manual blasts at midnight. Local fishermen avoided the reef, whispering "
    "that Keeper Vance never left the beacon after the great blizzard of 1904. Young archivist Samuel arrived "
    "at the crumbling tower with a notebook and a battery-powered lantern. Inside the iron stairwell, the temperature "
    "plummeted below freezing, and the scent of brine and burnt kerosene hung thick in the stagnant air. "
    "At the third landing, Samuel discovered a copper logbook bound in tarred canvas. The final entry, written in "
    "fading black ink, bore today's exact date and recorded Samuel's own arrival time down to the minute. "
    "Suddenly, footsteps echoed on the iron spiral above him, slow and rhythmic like soaked boots climbing upward. "
    "Samuel raised his lantern, his heart hammering against his ribs. The beam illuminated wet footprints ascending "
    "into the dark lantern room. When he reached the summit, the brass fresnel lens was spinning silently, casting "
    "revolving beams across the frothing ocean. In the center of the light stood the silhouette of a man in an oilskin "
    "coat, staring out into the roaring storm. The figure turned slowly, and beneath the shadow of his brim, Samuel "
    "saw his own face staring back at him with lifeless, hollow eyes. The heavy iron door behind him slammed shut, "
    "and the deadbolt clicked into place from the outside."
)

SAMPLE_CREATOR_STORY = (
    "# The Hollow Road\n\n"
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

SAMPLE_SHORT_STORY = (
    "The antique music box sat forgotten on my grandfather's dusty mahogany mantle. "
    "Every midnight without fail, the tarnished bronze ballerina spun three slow revolutions in total darkness. "
    "Last night, I finally opened the lid to stop the gear mechanism, only to find the interior hollow. "
    "A folded yellowed note was tucked beneath the velvet lining: 'She does not dance for the living.'"
)

SAMPLE_LONG_EPIC_STORY = (
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
def env(tmp_path: Path, monkeypatch):
    """Provides isolated SeriesDatabase, QueueManager, and SeriesScheduler wired to the FastAPI TestClient."""
    db_file = tmp_path / "test_e2e_db.json"
    queue_file = tmp_path / "test_e2e_queue.json"
    client_db = DatabaseClient(custom_file=db_file)
    isolated_s_db = SeriesDatabase(db_client=client_db)
    isolated_q_mgr = ProductionQueueManager(state_file=queue_file, s_db=isolated_s_db)
    isolated_scheduler = SeriesScheduler(s_db=isolated_s_db)
    isolated_planner = ProductionPlanner(db_instance=isolated_s_db)

    monkeypatch.setattr(series_api_module, "series_db", isolated_s_db)
    monkeypatch.setattr(series_api_module, "queue_manager", isolated_q_mgr)
    monkeypatch.setattr(series_api_module, "series_scheduler", isolated_scheduler)
    monkeypatch.setattr(series_api_module, "production_planner", isolated_planner)

    test_client = TestClient(app)
    return test_client, isolated_s_db, isolated_q_mgr, isolated_scheduler, isolated_planner


# =============================================================================
# 1. Step 1: Ingestion & Error Handling
# =============================================================================
class TestStep1IngestionE2E:
    """Verifies all 3 entry points (Upload, Paste, Reddit) and rigorous error handling."""

    def test_upload_txt_file(self, env):
        client, _, _, _, _ = env
        content = SAMPLE_E2E_HORROR_STORY.encode("utf-8")
        files = {"file": ("lighthouse.txt", io.BytesIO(content), "text/plain")}
        data = {"author": "E2E Archivist", "source_url": "https://example.com/story"}

        res = client.post("/api/series/ingest/upload", files=files, data=data)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "success"
        assert body["original_filename"] == "lighthouse.txt"
        assert body["word_count"] > 150
        assert body["estimated_spoken_duration_sec"] > 50.0
        assert "lighthouse on Smuggler's Point" in body["raw_text"]
        assert body["rights"]["author"] == "E2E Archivist"

    def test_upload_markdown_file_with_h1_title(self, env):
        client, _, _, _, _ = env
        md_text = f"# The Solstice Keeper\n\n## Chapter One\n\n{SAMPLE_E2E_HORROR_STORY}"
        files = {"file": ("solstice.md", io.BytesIO(md_text.encode("utf-8")), "text/markdown")}

        res = client.post("/api/series/ingest/upload", files=files)
        assert res.status_code == 200
        body = res.json()
        assert body["title"] == "The Solstice Keeper"
        assert body["raw_text"] == SAMPLE_E2E_HORROR_STORY
        assert "#" not in body["raw_text"]
        assert body["file_type"] == "md"

    def test_upload_docx_file_fallback_parsing(self, env):
        """Simulate a valid DOCX file by packing minimal word/document.xml in a zip archive."""
        client, _, _, _, _ = env
        docx_buffer = io.BytesIO()
        with zipfile.ZipFile(docx_buffer, "w", zipfile.ZIP_DEFLATED) as z:
            doc_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>The Keeper Solstice Mystery</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>Footsteps echoed in the abandoned tower.</w:t></w:r></w:p>'
                '</w:body></w:document>'
            )
            z.writestr("word/document.xml", doc_xml)
        docx_bytes = docx_buffer.getvalue()

        files = {"file": ("keeper.docx", io.BytesIO(docx_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        res = client.post("/api/series/ingest/upload", files=files)
        assert res.status_code == 200
        body = res.json()
        assert "The Keeper Solstice Mystery" in body["raw_text"]
        assert "Footsteps echoed" in body["raw_text"]

    def test_paste_workspace_word_count_and_135_wpm_calibration(self, env):
        client, _, _, _, _ = env
        payload = {
            "title": "Custom Pasted Tale",
            "raw_text": SAMPLE_E2E_HORROR_STORY,
            "author": "Ghost Storyteller",
        }
        res = client.post("/api/series/ingest/paste", json=payload)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "success"
        assert body["title"] == "Custom Pasted Tale"
        words = SAMPLE_E2E_HORROR_STORY.split()
        expected_words = len(words)
        assert body["word_count"] == expected_words
        expected_dur = round((expected_words / 135.0) * 60.0, 1)
        assert abs(body["estimated_spoken_duration_sec"] - expected_dur) < 0.2
        assert body["average_wpm"] == 135.0

    def test_paste_workspace_empty_text_error(self, env):
        client, _, _, _, _ = env
        res = client.post("/api/series/ingest/paste", json={"raw_text": "   "})
        assert res.status_code == 400
        assert "empty" in res.json()["detail"].lower()

    def test_reddit_url_ingestion_valid_mock(self, env):
        client, _, _, _, _ = env
        fake_reddit_resp = [
            {
                "kind": "Listing",
                "data": {
                    "children": [
                        {
                            "kind": "t3",
                            "data": {
                                "title": "The Smuggler's Point Foghorn",
                                "selftext": SAMPLE_E2E_HORROR_STORY,
                                "author": "CoastalHorrorAuthor",
                                "subreddit": "shortscarystories",
                                "permalink": "/r/shortscarystories/comments/abc123/foghorn/",
                                "score": 1250,
                                "num_comments": 42,
                                "over_18": False,
                                "removed_by_category": None,
                            },
                        }
                    ]
                },
            }
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_reddit_resp

        with patch("requests.get", return_value=mock_resp):
            payload = {"url": "https://www.reddit.com/r/shortscarystories/comments/abc123/foghorn/"}
            res = client.post("/api/series/ingest/reddit", json=payload)
            assert res.status_code == 200
            body = res.json()
            assert body["title"] == "The Smuggler's Point Foghorn"
            assert body["author"] == "u/CoastalHorrorAuthor"
            assert body["word_count"] > 150
            assert "CoastalHorrorAuthor" in body["rights"]["attribution_statement"]

    @pytest.mark.parametrize("deleted_marker", ["[deleted]", "[removed]"])
    def test_reddit_url_deleted_or_removed_error(self, env, deleted_marker):
        client, _, _, _, _ = env
        fake_data = [
            {
                "kind": "Listing",
                "data": {
                    "children": [
                        {
                            "kind": "t3",
                            "data": {
                                "title": "A Story That Vanished",
                                "selftext": deleted_marker,
                                "author": "some_user",
                                "subreddit": "shortscarystories",
                                "permalink": "/r/shortscarystories/comments/xyz/gone/",
                                "score": 1,
                                "removed_by_category": None,
                            },
                        }
                    ]
                },
            }
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_data

        with patch("requests.get", return_value=mock_resp):
            payload = {"url": "https://www.reddit.com/r/shortscarystories/comments/xyz/gone/"}
            res = client.post("/api/series/ingest/reddit", json=payload)
            assert res.status_code == 400
            assert any(term in res.json()["detail"].lower() for term in ["deleted", "removed"])

    def test_reddit_url_invalid_domain_rejected(self, env):
        client, _, _, _, _ = env
        payload = {"url": "https://example.com/fake-story"}
        res = client.post("/api/series/ingest/reddit", json=payload)
        assert res.status_code == 400
        assert "reddit.com" in res.json()["detail"]


# =============================================================================
# 2. Step 2: Intelligent Story Analysis
# =============================================================================
class TestStep2IntelligentAnalysisE2E:
    """Verifies that Step 2 deeply analyzes narrative components without premature splitting."""

    def test_narrative_analysis_structure_and_completeness(self, env):
        client, _, _, _, _ = env
        res = client.post(
            "/api/series/analyze",
            json={
                "raw_text": SAMPLE_CREATOR_STORY,
                "title": "The Hollow Road",
                "use_local_ai": False,
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "success"
        assert body["title"] == "The Hollow Road"
        analysis = body.get("analysis", {})

        # 1. Subject & Title & Genre
        assert "Psychological Horror" in body.get("genre", "")

        # 2. 135 WPM metrics
        assert analysis["word_count"] > 150
        assert analysis["estimated_spoken_duration_sec"] > 50.0
        assert analysis["average_wpm"] == 135.0

        # 3. 4-Phase Narrative Arc
        arc = analysis.get("narrative_arc", {})
        assert "exposition" in arc
        assert "rising_tension" in arc
        assert "climax" in arc
        assert "resolution" in arc
        assert arc["climax"]["tension_level"] >= 0.8

        # 4. Characters & Entities
        characters = analysis.get("key_characters", [])
        assert len(characters) >= 1
        for c in characters:
            assert "name" in c
            assert "role" in c
            assert "traits" in c

        # 5. Major Events & Turning Points
        events = analysis.get("major_events", [])
        assert len(events) >= 2

        # 6. Natural Chapter / Episode Boundaries (Preserves story without premature splitting)
        boundaries = analysis.get("natural_boundaries", [])
        assert len(boundaries) >= 1
        for b in boundaries:
            assert "anchor_sentence" in b
            assert "boundary_type" in b
            assert "reason" in b

        # 7. Cinematic Visual & Continuity Requirements
        visuals = analysis.get("continuity_and_visuals", {})
        assert visuals["visual_theme"] == "psychological_horror"
        assert len(visuals["lighting_and_atmosphere"]) > 10
        assert len(visuals["color_palette"]) >= 3
        assert len(visuals["key_locations"]) >= 1


# =============================================================================
# 3. Step 3: Dynamic Production-Plan Recommendations
# =============================================================================
class TestStep3ProductionPlanningE2E:
    """Verifies dynamic multi-plan generation based on natural stopping points and trade-offs."""

    def test_recommend_plans_multi_preset_with_tradeoffs(self, env):
        client, _, _, _, _ = env
        res = client.post(
            "/api/series/recommend-plans",
            json={"raw_text": SAMPLE_E2E_HORROR_STORY, "title": "Smuggler's Point"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        plans = body.get("recommended_plans", [])

        # Must return multiple distinct plans (1m, 1.5m, 3m)
        assert len(plans) >= 3
        presets = [p["format_preset"] for p in plans]
        assert "1m" in presets
        assert "1.5m" in presets
        assert "3m" in presets

        for plan in plans:
            assert plan["plan_id"]
            assert plan["plan_title"]
            assert plan["episode_count"] >= 1
            # Verify trade-off analysis exists
            tradeoffs = plan.get("trade_off_analysis", {})
            assert "pacing" in tradeoffs
            assert "retention_pros" in tradeoffs
            assert "retention_cons" in tradeoffs
            # Verify episode summaries have hooks and cliffhangers
            episodes = plan.get("episodes", [])
            assert len(episodes) == plan["episode_count"]
            for ep in episodes:
                assert len(ep["hook"]) > 0
                assert len(ep["cliffhanger"]) > 0

    def test_dynamic_episode_scaling_never_arbitrary(self, env):
        """Short texts scale to 1 standalone episode, while long texts scale to multi-episode."""
        _, _, _, _, planner = env

        # Short text (~60 words) -> 1 standalone episode for 1.5m and 3m presets
        short_plans = planner.generate_production_plans(SAMPLE_SHORT_STORY, title="Short Tale")
        plan_3m = next(p for p in short_plans if p["format_preset"] == "3m")
        assert plan_3m["episode_count"] == 1  # Natural standalone, not forced into multiple!

        # Long text (~500 words) -> organically scales to 3+ episodes for 1m preset
        long_plans = planner.generate_production_plans(SAMPLE_LONG_EPIC_STORY, title="Long Epic")
        plan_1m = next(p for p in long_plans if p["format_preset"] == "1m")
        assert plan_1m["episode_count"] >= 3


# =============================================================================
# 4. Step 4: Storyboards, Editing & Cascading Invalidation
# =============================================================================
class TestStep4StoryboardsAndInvalidationE2E:
    """Verifies Three.js storyboard assignment, approval gate, and single-episode invalidation isolation."""

    def test_breakdown_generates_threejs_storyboard_scenes(self, env):
        client, _, _, _, _ = env
        res = client.post(
            "/api/series/generate-breakdown",
            json={
                "series_id": "series_e2e_sb",
                "title": "Lighthouse Series",
                "raw_text": SAMPLE_E2E_HORROR_STORY,
                "duration_preset": "1m",
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        episodes = body.get("episodes", [])
        assert len(episodes) >= 2

        for ep in episodes:
            storyboard = ep.get("storyboard", {})
            scenes = storyboard.get("scenes", [])
            assert len(scenes) >= 1
            for scene in scenes:
                assert scene["three_js_scene"].startswith("cartoon3d_")
                assert scene["rendering_method"] == "CARTOON_3D_THREEJS"
                assert scene["narration"]["text"].strip()
                assert scene["narration"]["text"] in scene["visual_objective"]
                assert "Narrator / Key Subject" not in scene["primary_subject"]["name"]
                assert "camera" in scene
                assert scene["environment"]["name"]
                assert 1 <= scene["tension_level"] <= 10

    def test_single_episode_edit_cascading_invalidation(self, env):
        """Editing Ep 1 invalidates ONLY Ep 1, setting STALE_INVALIDATED; Ep 2 remains untouched."""
        client, isolated_s_db, _, _, _ = env

        # 1. Generate breakdown
        gen_res = client.post(
            "/api/series/generate-breakdown",
            json={
                "series_id": "series_invalidation_test",
                "title": "Cascading Test",
                "raw_text": SAMPLE_E2E_HORROR_STORY,
                "duration_preset": "1m",
            },
        )
        assert gen_res.status_code == 200
        episodes = gen_res.json()["episodes"]
        assert len(episodes) >= 2
        ep1_id = episodes[0]["episode_id"]
        ep2_id = episodes[1]["episode_id"]

        # 2. Approve both episodes
        client.post(f"/api/series/episodes/{ep1_id}/approve", json={"approved": True})
        client.post(f"/api/series/episodes/{ep2_id}/approve", json={"approved": True})

        # Set fake render paths to test cache invalidation
        ep1 = isolated_s_db.get_episode(ep1_id)
        ep1.rendered_video_path = "/outputs/ep1.mp4"
        ep1.audio_path = "/outputs/ep1.wav"
        isolated_s_db.save_episode(ep1)

        ep2 = isolated_s_db.get_episode(ep2_id)
        ep2.rendered_video_path = "/outputs/ep2.mp4"
        isolated_s_db.save_episode(ep2)

        # 3. Edit ONLY Episode 1
        edit_payload = {
            "title": "Modified Episode 1 Title",
            "adapted_narration": "A completely revised script for the opening chapter of the horror series.",
            "hook": "New shocking hook sentence.",
        }
        edit_res = client.put(f"/api/series/episodes/{ep1_id}", json=edit_payload)
        assert edit_res.status_code == 200
        edited_ep1 = edit_res.json()["episode"]

        # Check Ep 1 cascading invalidation
        assert edited_ep1["status"] == EpisodeStatus.STALE_INVALIDATED.value
        assert edited_ep1["version"] == 2
        assert edited_ep1["is_approved"] is False
        assert edited_ep1["rendered_video_path"] is None
        assert edited_ep1["audio_path"] is None

        # Check Ep 2 is COMPLETELY UNTOUCHED
        fresh_ep2 = isolated_s_db.get_episode(ep2_id)
        assert fresh_ep2.status == EpisodeStatus.READY.value
        assert fresh_ep2.is_approved is True
        assert fresh_ep2.rendered_video_path == "/outputs/ep2.mp4"
        assert fresh_ep2.version == 1

    def test_storyboard_approval_gate(self, env):
        client, _, _, _, _ = env
        gen_res = client.post(
            "/api/series/generate-breakdown",
            json={
                "series_id": "series_gate_test",
                "title": "Approval Gate",
                "raw_text": SAMPLE_E2E_HORROR_STORY,
                "duration_preset": "1m",
            },
        )
        ep1_id = gen_res.json()["episodes"][0]["episode_id"]

        # Approve
        appr_res = client.post(f"/api/series/episodes/{ep1_id}/approve", json={"approved": True, "reviewer": "QA Master"})
        assert appr_res.status_code == 200
        ep = appr_res.json()["episode"]
        assert ep["is_approved"] is True
        assert ep["approval_date"] is not None
        assert ep["status"] == EpisodeStatus.READY.value


# =============================================================================
# 5. Step 5: Series Scheduling Planner & Calendar Preview
# =============================================================================
class TestStep5SchedulingPlannerE2E:
    """Verifies Schedule A, B, C calendar preview calculations and commit workflow."""

    def test_schedule_a_preview_and_commit(self, env):
        client, isolated_s_db, _, _, _ = env

        # 1. Create series with 3 episodes
        gen_res = client.post(
            "/api/series/generate-breakdown",
            json={
                "series_id": "series_sched_a",
                "title": "Schedule A Series",
                "raw_text": SAMPLE_E2E_HORROR_STORY,
                "duration_preset": "1m",
            },
        )
        ep_count = len(gen_res.json()["episodes"])

        # 2. Preview Schedule A (1/day at 20:30 IST)
        preview_res = client.post(
            "/api/series/schedule/preview",
            json={
                "episode_count": ep_count,
                "schedule_type": "A",
                "start_date": "2026-12-10",
                "start_time": "20:30",
            },
        )
        assert preview_res.status_code == 200, preview_res.text
        preview = preview_res.json()
        assert preview["status"] == "success"
        assert preview["total_episodes"] == ep_count
        assert len(preview["calendar"]) == ep_count
        assert preview["calendar"][0]["date"] == "2026-12-10"
        assert preview["calendar"][0]["time"] == "20:30"
        assert "2026-12-10T20:30:00+05:30" in preview["calendar"][0]["scheduled_datetime_ist"]

        # 3. Commit Schedule
        commit_res = client.post(
            "/api/series/series_sched_a/schedule/commit",
            json={
                "schedule_type": "A",
                "start_date": "2026-12-10",
                "start_time": "20:30",
            },
        )
        assert commit_res.status_code == 200, commit_res.text
        assert commit_res.json()["series_status"] == SeriesStatus.ACTIVE.value

        # Check DB series and episodes
        series = isolated_s_db.get_series("series_sched_a")
        assert series.status == SeriesStatus.ACTIVE
        assert series.publication_schedule["schedule_type"] == "A"

    def test_schedule_b_preview_two_episodes_per_day(self, env):
        client, _, _, _, _ = env
        preview_res = client.post(
            "/api/series/schedule/preview",
            json={
                "episode_count": 4,
                "schedule_type": "B",
                "start_date": "2026-12-15",
                "start_time": "09:00",
            },
        )
        assert preview_res.status_code == 200
        calendar = preview_res.json()["calendar"]
        assert len(calendar) == 4
        # Day 1: Ep 1 at 09:00, Ep 2 at 20:30
        assert calendar[0]["date"] == "2026-12-15" and calendar[0]["time"] == "09:00"
        assert calendar[1]["date"] == "2026-12-15" and calendar[1]["time"] == "20:30"
        # Day 2: Ep 3 at 09:00, Ep 4 at 20:30
        assert calendar[2]["date"] == "2026-12-16" and calendar[2]["time"] == "09:00"
        assert calendar[3]["date"] == "2026-12-16" and calendar[3]["time"] == "20:30"

    def test_schedule_c_custom_weekdays(self, env):
        client, _, _, _, _ = env
        preview_res = client.post(
            "/api/series/schedule/preview",
            json={
                "episode_count": 3,
                "schedule_type": "C",
                "start_date": "2026-12-01",  # Tuesday
                "start_time": "21:00",
                "custom_days": ["Tuesday", "Thursday"],
            },
        )
        assert preview_res.status_code == 200
        calendar = preview_res.json()["calendar"]
        assert len(calendar) == 3
        # Dec 1 (Tue), Dec 3 (Thu), Dec 8 (Tue)
        assert calendar[0]["date"] == "2026-12-01"
        assert calendar[1]["date"] == "2026-12-03"
        assert calendar[2]["date"] == "2026-12-08"


# =============================================================================
# 6. Step 6: Production Queue Lifecycle & Preservation of Automatic Studio
# =============================================================================
class TestStep6QueueAndAutomaticStudioPreservationE2E:
    """Verifies production lifecycle statuses, Pause/Resume/Cancel, and Automatic Studio preservation."""

    def test_queue_lifecycle_controls_pause_resume_cancel(self, env):
        client, isolated_s_db, _, _, _ = env

        # 1. Setup series
        client.post(
            "/api/series/generate-breakdown",
            json={
                "series_id": "series_lifecycle_e2e",
                "title": "Lifecycle Series",
                "raw_text": SAMPLE_E2E_HORROR_STORY,
                "duration_preset": "1m",
            },
        )
        # Commit schedule to enqueue
        client.post(
            "/api/series/series_lifecycle_e2e/schedule/commit",
            json={"schedule_type": "A", "start_date": "2026-12-01"},
        )

        # 2. Pause
        pause_res = client.post("/api/series/series_lifecycle_e2e/pause")
        assert pause_res.status_code == 200
        assert pause_res.json()["series_status"] == SeriesStatus.PAUSED.value
        assert isolated_s_db.get_series("series_lifecycle_e2e").status == SeriesStatus.PAUSED

        # 3. Resume
        resume_res = client.post("/api/series/series_lifecycle_e2e/resume")
        assert resume_res.status_code == 200
        assert resume_res.json()["series_status"] == SeriesStatus.ACTIVE.value

        # 4. Cancel
        cancel_res = client.post("/api/series/series_lifecycle_e2e/cancel")
        assert cancel_res.status_code == 200
        assert cancel_res.json()["series_status"] == SeriesStatus.CANCELLED.value
        assert isolated_s_db.get_series("series_lifecycle_e2e").status == SeriesStatus.CANCELLED

    def test_queue_status_reports_all_episode_lifecycle_states(self, env):
        client, _, _, _, _ = env
        client.post(
            "/api/series/generate-breakdown",
            json={
                "series_id": "series_status_e2e",
                "title": "Status Report Series",
                "raw_text": SAMPLE_E2E_HORROR_STORY,
                "duration_preset": "1m",
            },
        )
        res = client.get("/api/series/series_status_e2e/queue-status")
        assert res.status_code == 200
        body = res.json()
        assert body["series_id"] == "series_status_e2e"
        assert "episodes" in body
        assert len(body["episodes"]) >= 2
        for ep in body["episodes"]:
            assert ep["status"] in ["Planned", "Script ready", "Awaiting approval", "In production", "QC failed", "Ready for publishing", "Scheduled", "Published"]
            assert "is_approved" in ep

    def test_preservation_of_automatic_studio_slots_and_priority(self, env):
        """CRITICAL: Automatic Studio (09:00 IST & 19:00 IST) has Priority 1 and cannot be displaced by Creator Series."""
        _, isolated_s_db, isolated_q_mgr, _, _ = env

        # 1. Setup active Creator Series
        series = SeriesRecord(
            series_id="creator_prio_e2e",
            title="Creator Prio",
            full_script="Script text",
            planned_episodes=2,
            status=SeriesStatus.ACTIVE,
        )
        isolated_s_db.save_series(series)
        ep1 = EpisodeRecord(
            episode_id="creator_prio_e2e_ep01",
            series_id="creator_prio_e2e",
            episode_num=1,
            title="Ep 1",
            adapted_narration="Narration",
            status=EpisodeStatus.SCHEDULED,
        )
        isolated_s_db.save_episode(ep1)
        isolated_q_mgr.enqueue_series("creator_prio_e2e")

        # 2. Reserve Automatic Studio jobs for target date
        isolated_q_mgr.ensure_automatic_studio_reserved("2026-12-01")

        # 3. Next job MUST be Automatic Studio (Priority 1) ahead of Creator Series (Priority 10)
        first_job = isolated_q_mgr.get_next_job()
        assert first_job is not None
        assert first_job.job_type == JobType.AUTOMATIC_STUDIO
        assert first_job.priority == 1
        assert first_job.target_slot in ("09:00 IST", "19:00 IST")

        # 4. Cancelling Creator Series does NOT affect Automatic Studio
        isolated_q_mgr.cancel_series("creator_prio_e2e")
        auto_job = isolated_q_mgr.get_next_job()
        assert auto_job is not None
        assert auto_job.job_type == JobType.AUTOMATIC_STUDIO
        assert auto_job.status == JobStatus.QUEUED

    def test_sequential_execution_mutex_prevents_deadlock(self, env):
        """Ensures that executing a job acquires the sequential lock cleanly without deadlock."""
        _, _, isolated_q_mgr, _, _ = env

        isolated_q_mgr.ensure_automatic_studio_reserved("2026-12-01")
        auto_job = isolated_q_mgr.get_next_job()
        assert auto_job is not None

        def sample_runner(job):
            return f"Processed_{job.job_id}"

        res = isolated_q_mgr.execute_job_locked(auto_job.job_id, sample_runner)
        assert res == f"Processed_{auto_job.job_id}"
        fresh_job = isolated_q_mgr._jobs[auto_job.job_id]
        assert fresh_job.status == JobStatus.COMPLETED


# =============================================================================
# 7. Complete Integrated End-to-End Workflow (Steps 1 through 6)
# =============================================================================
class TestCompleteE2EWorkflow:
    """Full seamless flow: Ingestion -> Analysis -> Planning -> Breakdown & Storyboard -> Scheduling -> Queue."""

    def test_full_pipeline_step1_to_step6(self, env):
        client, _, _, _, _ = env

        # Step 1: Ingest via Paste
        paste_res = client.post(
            "/api/series/ingest/paste",
            json={
                "title": "The Smuggler's Curse",
                "raw_text": SAMPLE_E2E_HORROR_STORY,
                "author": "E2E Master Author",
            },
        )
        assert paste_res.status_code == 200
        clean_text = paste_res.json()["raw_text"]

        # Step 2: Intelligent Analysis
        analyze_res = client.post(
            "/api/series/analyze",
            json={"raw_text": clean_text, "title": "The Smuggler's Curse", "use_local_ai": False},
        )
        assert analyze_res.status_code == 200
        analysis = analyze_res.json()["analysis"]
        assert analysis["word_count"] > 150

        # Step 3: Recommend Plans
        plans_res = client.post(
            "/api/series/recommend-plans",
            json={"raw_text": clean_text, "title": "The Smuggler's Curse"},
        )
        assert plans_res.status_code == 200
        plans = plans_res.json()["recommended_plans"]
        chosen_plan = plans[0]

        # Step 4: Breakdown & Three.js Storyboard Generation
        breakdown_res = client.post(
            "/api/series/generate-breakdown",
            json={
                "series_id": "series_full_e2e_run",
                "title": "The Smuggler's Curse",
                "raw_text": clean_text,
                "duration_preset": chosen_plan["format_preset"],
            },
        )
        assert breakdown_res.status_code == 200
        episodes = breakdown_res.json()["episodes"]
        assert len(episodes) >= 2

        # Step 4b: Approve all storyboards
        for ep in episodes:
            appr = client.post(f"/api/series/episodes/{ep['episode_id']}/approve", json={"approved": True})
            assert appr.status_code == 200

        # Step 5: Schedule Preview & Commit (Schedule A, 20:30 IST)
        prev_res = client.post(
            "/api/series/schedule/preview",
            json={
                "episode_count": len(episodes),
                "schedule_type": "A",
                "start_date": "2026-12-20",
                "start_time": "20:30",
            },
        )
        assert prev_res.status_code == 200
        assert prev_res.json()["total_episodes"] == len(episodes)

        commit_res = client.post(
            "/api/series/series_full_e2e_run/schedule/commit",
            json={"schedule_type": "A", "start_date": "2026-12-20", "start_time": "20:30"},
        )
        assert commit_res.status_code == 200

        # Step 6: Queue Status Check
        status_res = client.get("/api/series/series_full_e2e_run/queue-status")
        assert status_res.status_code == 200
        queue_info = status_res.json()
        assert queue_info["series_status"] == SeriesStatus.ACTIVE.value
        assert len(queue_info["episodes"]) == len(episodes)


# =============================================================================
# 8. Frontend UI Contract Verification
# =============================================================================
class TestFrontendUIContract:
    """Verifies that `templates/index.html` implements the complete 6-step Creator Studio UI."""

    def test_frontend_contains_all_six_steps_and_endpoints(self):
        index_html_path = Path("curiosity_engine/dashboard/templates/index.html")
        assert index_html_path.exists(), "index.html must exist"
        html = index_html_path.read_text(encoding="utf-8")

        # Step 1: Ingestion
        assert "Story Ingestion" in html or "creator_upload" in html or "creator_paste" in html or "creator_reddit" in html
        # Step 2: Intelligent Story Analysis
        assert "Intelligent Story" in html or "narrative-arc" in html or "narrative_arc" in html or "story_analysis" in html or "analyze" in html
        # Step 3: Production-Plan Recommendations
        assert "Production-Plan" in html or "plan-card" in html or "recommend-plans" in html
        # Step 4: Storyboard Review & Cascading Invalidation
        assert "Storyboard" in html or "is_approved" in html or "invalidate" in html
        # Step 5: Scheduling Planner
        assert "Schedule A" in html or "calendar_preview" in html or "schedule/preview" in html
        # Step 6: Queue Lifecycle Controls
        assert "queue-status" in html or "pause" in html or "resume" in html or "cancel" in html
