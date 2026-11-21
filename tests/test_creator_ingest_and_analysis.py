"""Tests for CurioLoop 2.0 Story Ingestion and Intelligent Story Analysis.
Verifies:
- Entry point 1: Script Upload (.txt, .md, .docx with python-docx and clean zipfile XML fallback)
- Entry point 2: Script Paste Workspace (with word count and 135 WPM duration calibration)
- Entry point 3: Reddit Ingestion (URL normalization, JSON API fetching, rigorous error handling)
- Step 2: Intelligent Story Analysis (without premature episode splitting, full narrative arc,
  genre, characters, turning points, natural boundaries, suspense/cliffhangers, visual continuity)
- REST endpoints in series_api.py: /ingest/upload, /ingest/paste, /ingest/reddit, /analyze
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from curiosity_engine.creator_series.creator_studio_engine import CreatorStudioEngine
from curiosity_engine.creator_series.models import SeriesRecord, SeriesStatus
from curiosity_engine.creator_series.series_db import series_db
from curiosity_engine.dashboard.app import app

client = TestClient(app)

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


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point 1 Tests: Script Upload (TXT, MD, DOCX + Fallback)
# ─────────────────────────────────────────────────────────────────────────────

def test_ingest_txt_file(tmp_path: Path):
    """Verify TXT ingestion extracts text, word count, and preserves original file."""
    txt_file = tmp_path / "sample_story.txt"
    txt_file.write_text("This is an ominous tale of the woods.\nThe shadow moved silently.", encoding="utf-8")

    result = CreatorStudioEngine.ingest_document(txt_file, file_type="txt")
    assert result["title"] == "sample_story"
    assert "ominous tale" in result["raw_text"]
    assert result["word_count"] == 12
    assert result["estimated_spoken_duration_sec"] == pytest.approx(5.3, 0.2)
    assert result["average_wpm"] == 135.0
    assert result["file_type"] == "txt"
    assert result["preserved_path"] is not None
    assert Path(result["preserved_path"]).exists()


def test_ingest_md_file(tmp_path: Path):
    """Verify Markdown ingestion detects # Heading title and word count."""
    md_file = tmp_path / "creepy_log.md"
    md_file.write_text("# Whispers in the Wall\n\nSomething was scratching behind the plaster at 3 AM.", encoding="utf-8")

    result = CreatorStudioEngine.ingest_document(md_file, file_type="md")
    assert result["title"] == "Whispers in the Wall"
    assert "scratching behind the plaster" in result["raw_text"]
    assert result["word_count"] == 14
    assert result["file_type"] == "md"


def test_ingest_docx_via_clean_zipfile_fallback():
    """Verify that DOCX extraction NEVER fails even without external python-docx,
    using standard library zipfile XML extraction.
    """
    # Construct a valid minimal DOCX zip structure in memory
    xml_content = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:body>'
        b'<w:p><w:r><w:t>The Cursed Mountain Log</w:t></w:r></w:p>'
        b'<w:p><w:r><w:t>First paragraph describing the frozen pass.</w:t></w:r></w:p>'
        b'<w:p><w:r><w:t>Second paragraph where the driver appears.</w:t></w:r></w:p>'
        b'</w:body>'
        b'</w:document>'
    )

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr("word/document.xml", xml_content)
    bio.seek(0)

    title, text = CreatorStudioEngine._extract_docx_fallback(bio)
    assert "The Cursed Mountain Log" in title
    assert "frozen pass" in text
    assert "driver appears" in text

    # Ingest directly via ingest_document with bytes
    bio.seek(0)
    ingested = CreatorStudioEngine.ingest_document(
        bio.getvalue(),
        filename="curse.docx",
        file_type="docx",
    )
    assert "Cursed Mountain Log" in ingested["title"]
    assert "driver appears" in ingested["raw_text"]
    assert ingested["word_count"] > 10


def test_ingest_upload_endpoint_txt():
    """Verify POST /api/series/ingest/upload with a text file."""
    content = b"The rain beat against the cabin window as footsteps approached."
    response = client.post(
        "/api/series/ingest/upload",
        files={"file": ("story.txt", content, "text/plain")},
        data={"author": "Test Author", "permission_status": "LICENSED"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "footsteps approached" in data["raw_text"]
    assert data["word_count"] == 10
    assert data["rights"]["author"] == "Test Author"
    assert data["rights"]["permission_verified"] is True


def test_ingest_upload_endpoint_empty_file():
    """Verify POST /api/series/ingest/upload rejects empty files."""
    response = client.post(
        "/api/series/ingest/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_ingest_upload_endpoint_unsupported_ext():
    """Verify POST /api/series/ingest/upload rejects unsupported extensions."""
    response = client.post(
        "/api/series/ingest/upload",
        files={"file": ("virus.exe", b"fake binary", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "unsupported file extension" in response.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point 2 Tests: Script Paste Workspace
# ─────────────────────────────────────────────────────────────────────────────

def test_ingest_paste_workspace():
    """Verify script paste calculates 135 WPM duration and auto-detects title."""
    result = CreatorStudioEngine.ingest_paste(
        raw_text=SAMPLE_CREATOR_STORY,
        source_rights={"author": "Joshua K."},
    )
    assert result["title"] == "The Hollow Road"
    assert result["word_count"] == 240
    # 240 words / 135 WPM * 60 = ~106.7 seconds
    assert 100.0 <= result["estimated_spoken_duration_sec"] <= 115.0
    assert result["average_wpm"] == 135.0
    assert result["rights"]["author"] == "Joshua K."


def test_ingest_paste_endpoint():
    """Verify POST /api/series/ingest/paste endpoint."""
    response = client.post(
        "/api/series/ingest/paste",
        json={
            "raw_text": "A brief two-sentence horror vignette. Then the lights went completely black.",
            "title": "Lights Out",
            "author": "Indie Writer",
        },
    )
    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "success"
    assert res["title"] == "Lights Out"
    assert res["word_count"] == 11
    assert res["rights"]["author"] == "Indie Writer"


def test_ingest_paste_endpoint_empty():
    """Verify POST /api/series/ingest/paste rejects empty text."""
    response = client.post(
        "/api/series/ingest/paste",
        json={"raw_text": "   "},
    )
    assert response.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point 3 Tests: Reddit Ingestion & Error Handling
# ─────────────────────────────────────────────────────────────────────────────

def test_reddit_ingestion_success():
    """Verify valid Reddit post fetching and metadata extraction."""
    fake_reddit_resp = [
        {
            "kind": "Listing",
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "title": "I Worked the Night Shift at an Isolated Radio Tower",
                            "selftext": (
                                "The transmission was supposed to be automated, but at 02:45 the console clicked. "
                                "A rhythmic static buzzed through the speakers before a human voice began reciting my childhood home address. "
                                "I locked the steel blast doors and checked the surveillance monitor."
                            ),
                            "author": "MidnightOperator",
                            "subreddit": "nosleep",
                            "permalink": "/r/nosleep/comments/abc1234/i_worked_the_night_shift/",
                            "score": 1420,
                            "num_comments": 88,
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

    with patch("requests.get", return_value=mock_resp) as mock_get:
        result = CreatorStudioEngine.ingest_reddit(
            "https://www.reddit.com/r/nosleep/comments/abc1234/i_worked_the_night_shift/"
        )
        assert result["title"] == "I Worked the Night Shift at an Isolated Radio Tower"
        assert "childhood home address" in result["raw_text"]
        assert result["author"] == "u/MidnightOperator"
        assert result["subreddit"] == "nosleep"
        assert result["score"] == 1420
        assert result["word_count"] > 30
        assert result["rights"]["attribution_statement"] == "Story originally posted by u/MidnightOperator on r/nosleep"

        # Verify correct user-agent header was passed
        mock_get.assert_called_once()
        headers = mock_get.call_args[1]["headers"]
        assert "CurioLoop" in headers["User-Agent"]


def test_reddit_ingestion_error_handling_removed_or_deleted():
    """Rigorously verify against [deleted], [removed], or moderator deletion — NEVER fake success!"""
    deleted_cases = [
        {"selftext": "[deleted]", "author": "some_user", "removed_by_category": None},
        {"selftext": "[removed]", "author": "some_user", "removed_by_category": None},
        {"selftext": "Valid text body here.", "author": "[deleted]", "removed_by_category": None},
        {"selftext": "Valid text body here.", "author": "user", "removed_by_category": "moderator"},
        {"selftext": "   ", "author": "user", "removed_by_category": None},  # empty selftext
    ]

    for case in deleted_cases:
        fake_data = [
            {
                "kind": "Listing",
                "data": {
                    "children": [
                        {
                            "kind": "t3",
                            "data": {
                                "title": "Removed Post Title",
                                "selftext": case["selftext"],
                                "author": case["author"],
                                "subreddit": "nosleep",
                                "permalink": "/r/nosleep/comments/xyz123/",
                                "score": 1,
                                "removed_by_category": case["removed_by_category"],
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
            with pytest.raises(ValueError) as excinfo:
                CreatorStudioEngine.ingest_reddit("https://www.reddit.com/r/nosleep/comments/xyz123/deleted_post/")
            assert any(term in str(excinfo.value).lower() for term in ["removed", "deleted", "empty"])


def test_reddit_ingestion_http_404_and_403():
    """Verify HTTP 404, 403, and private subreddit errors are caught and reported explicitly."""
    mock_404 = MagicMock(status_code=404)
    with patch("requests.get", return_value=mock_404):
        with pytest.raises(ValueError) as exc404:
            CreatorStudioEngine.ingest_reddit("https://reddit.com/r/nosleep/comments/notfound123/story/")
        assert "404" in str(exc404.value)

    mock_403 = MagicMock(status_code=403)
    with patch("requests.get", return_value=mock_403):
        with pytest.raises(ValueError) as exc403:
            CreatorStudioEngine.ingest_reddit("https://reddit.com/r/privatesub/comments/priv123/story/")
        assert "403" in str(exc403.value)


def test_ingest_reddit_endpoint():
    """Verify POST /api/series/ingest/reddit REST endpoint."""
    fake_reddit_resp = [
        {
            "kind": "Listing",
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "title": "The Old Lighthouse keeper",
                            "selftext": "Every full moon, the light turns crimson. I saw ships that sank fifty years ago sail into port.",
                            "author": "OldSailor",
                            "subreddit": "shortscarystories",
                            "permalink": "/r/shortscarystories/comments/abc/lighthouse/",
                            "score": 350,
                            "num_comments": 15,
                            "over_18": False,
                            "removed_by_category": None,
                        },
                    }
                ]
            },
        }
    ]
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = fake_reddit_resp

    with patch("requests.get", return_value=mock_resp):
        response = client.post(
            "/api/series/ingest/reddit",
            json={"url": "https://www.reddit.com/r/shortscarystories/comments/abc/lighthouse/"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "The Old Lighthouse keeper"
        assert data["author"] == "u/OldSailor"
        assert "crimson" in data["raw_text"]


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 Tests: Intelligent Story Analysis (No premature episode splitting!)
# ─────────────────────────────────────────────────────────────────────────────

def test_intelligent_story_analysis_depth():
    """Verify deep intelligent narrative analysis without prematurely splitting into episodes.
    Checks:
    - Title & Subject premise
    - Genre & Subgenres
    - 135 WPM word count and duration
    - 4-phase narrative arc (exposition, rising tension, climax, resolution)
    - Key characters & entities with roles
    - Major events & turning points
    - Natural chapter/episode boundaries (without splitting text)
    - Suspense/reveals/cliffhangers
    - Continuity & visual requirements
    """
    analysis = CreatorStudioEngine.analyze_story(SAMPLE_CREATOR_STORY, use_local_ai=False)

    # 1. Does NOT immediately split into episodes
    assert "episodes" not in analysis

    # 2. Title & Subject
    assert "The Hollow Road" in analysis["title"]
    assert len(analysis["subject"]) > 20

    # 3. Genre & Category
    assert "Horror" in analysis["genre"]
    assert len(analysis["subgenres"]) >= 1

    # 4. Word count & duration (135 WPM)
    assert analysis["word_count"] == 240
    assert 100.0 <= analysis["estimated_spoken_duration_sec"] <= 115.0
    assert analysis["average_wpm"] == 135.0

    # 5. Narrative Arc (4 stages with tension levels and summaries)
    arc = analysis["narrative_arc"]
    assert "exposition" in arc
    assert "rising_tension" in arc
    assert "climax" in arc
    assert "resolution" in arc
    assert arc["exposition"]["tension_level"] < arc["rising_tension"]["tension_level"]
    assert arc["rising_tension"]["tension_level"] < arc["climax"]["tension_level"]
    assert len(arc["climax"]["key_excerpt"]) > 0

    # 6. Key Characters & Entities
    char_names = [c["name"] for c in analysis["key_characters"]]
    assert "Narrator" in char_names
    assert "Isaiah" in char_names or "Maria" in char_names
    for char in analysis["key_characters"]:
        assert "role" in char
        assert "traits" in char

    # 7. Major Events & Turning Points
    events = analysis["major_events"]
    assert len(events) >= 3
    event_titles = [e["title"] for e in events]
    assert any("Initial" in t or "Incident" in t for t in event_titles)

    # 8. Natural Boundaries (identifies organic stopping points WITHOUT cutting text)
    boundaries = analysis["natural_boundaries"]
    assert len(boundaries) >= 1
    for b in boundaries:
        assert "anchor_sentence" in b
        assert "reason" in b
        assert "boundary_type" in b

    # 9. Suspense & Cliffhangers
    suspense = analysis["suspense_and_cliffhangers"]
    assert len(suspense["withheld_mysteries"]) >= 2
    assert len(suspense["major_reveals"]) >= 2
    assert len(suspense["cliffhanger_opportunities"]) >= 2

    # 10. Continuity & Visual Requirements
    visuals = analysis["continuity_and_visuals"]
    assert visuals["visual_theme"] == "psychological_horror"
    assert len(visuals["lighting_and_atmosphere"]) > 20
    assert len(visuals["color_palette"]) >= 4
    assert len(visuals["key_locations"]) >= 3
    assert len(visuals["recurring_motifs"]) >= 3
    assert len(visuals["cinematic_shot_recommendations"]) >= 3


def test_analyze_story_endpoint_with_raw_text():
    """Verify POST /api/series/analyze returns deep narrative analysis from raw text."""
    response = client.post(
        "/api/series/analyze",
        json={
            "raw_text": SAMPLE_CREATOR_STORY,
            "title": "The Mountain Pass Incident",
            "use_local_ai": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["title"] == "The Mountain Pass Incident"
    assert "Psychological Horror" in data["genre"]
    analysis = data["analysis"]
    assert "narrative_arc" in analysis
    assert "key_characters" in analysis
    assert "continuity_and_visuals" in analysis


def test_analyze_story_endpoint_with_series_id():
    """Verify POST /api/series/analyze can look up text from existing series_id."""
    test_series = SeriesRecord(
        series_id="test_series_analyze_lookup",
        title="Stored Horror Story",
        full_script=SAMPLE_CREATOR_STORY,
        status=SeriesStatus.DRAFT,
    )
    series_db.save_series(test_series)

    response = client.post(
        "/api/series/analyze",
        json={"series_id": "test_series_analyze_lookup", "use_local_ai": False},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["title"] == "Stored Horror Story"
    assert data["word_count"] == 240
    assert "narrative_arc" in data["analysis"]


def test_analyze_story_endpoint_missing_input():
    """Verify POST /api/series/analyze returns 400 when neither raw_text nor series_id is given."""
    response = client.post("/api/series/analyze", json={})
    assert response.status_code == 400
