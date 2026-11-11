"""Unit & Integration Tests for CurioLoop YouTube Shorts Description Generation.
Verifies:
1. Source grounding and URL validation (no hallucinated citations).
2. Omission of research section when verified sources are unavailable.
3. Description uniqueness across topics.
4. Formatting constraints (character limit <= 5,000, brand sign-off, engagement question, hashtags).
5. Dashboard description viewing, editing, authorization, and persistence.
"""
from __future__ import annotations

import re
from pathlib import Path
from fastapi.testclient import TestClient

from curiosity_engine.config import DASHBOARD_SECRET_KEY
from curiosity_engine.content.description_generator import (
    BRAND_SIGN_OFF,
    DescriptionGenerator,
    infer_source_title,
    validate_description_sources,
)
from curiosity_engine.dashboard.app import app
from curiosity_engine.state.db import db


def test_infer_source_title():
    assert "NIH" in infer_source_title("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/")
    assert "ScienceDirect" in infer_source_title("https://www.sciencedirect.com/science/article/pii/123")
    assert "Oxford" in infer_source_title("https://www.oxrep.ox.ac.uk/")
    assert "UNESCO" in infer_source_title("https://en.unesco.org/underwater-heritage/thonis-heracleion")


def test_validate_description_sources_grounding():
    allowed = [
        "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3181924/",
        "https://www.sciencedirect.com/science/article/pii/S037859550400262X",
    ]

    valid_text = (
        "Check research: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3181924/ and "
        "https://www.sciencedirect.com/science/article/pii/S037859550400262X."
    )
    is_valid, issues = validate_description_sources(valid_text, allowed)
    assert is_valid is True
    assert len(issues) == 0

    # Fabricated / hallucinated URL
    invalid_text = (
        "Check research: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3181924/ and "
        "https://fake-science-journal.com/hallucinated-paper."
    )
    is_valid, issues = validate_description_sources(invalid_text, allowed)
    assert is_valid is False
    assert any("fake-science-journal.com" in i for i in issues)


def test_description_omits_research_section_when_sources_empty():
    gen = DescriptionGenerator()
    desc_data = gen.generate(
        topic="Uncited Phenomenon",
        category="Science",
        script_data={"title": "Uncited Phenomenon"},
        sources=[],
        claims=["Some claim without verified external links."],
    )
    desc_text = desc_data["full_description"]
    assert "Verified Sources" not in desc_text
    assert "http" not in desc_text
    assert len(desc_data["further_reading"]) == 0


def test_description_formatting_and_constraints():
    gen = DescriptionGenerator()
    sources = ["https://www.oxrep.ox.ac.uk/"]
    desc_data = gen.generate(
        topic="The sunken Egyptian port city of Thonis-Heracleion",
        category="History",
        script_data={"title": "The Sunken Egyptian Port of Heracleion"},
        sources=sources,
        claims=["Founded in the 8th century BC."],
    )

    full_desc = desc_data["full_description"]
    assert len(full_desc) <= 5000
    assert len(full_desc) >= 100
    assert "http" not in full_desc.lower()
    assert BRAND_SIGN_OFF in full_desc
    assert "?" in desc_data["engagement_question"]
    assert 3 <= len(desc_data["hashtags"]) <= 6
    assert all(h.startswith("#") for h in desc_data["hashtags"])
    assert "#CurioLoop" in desc_data["hashtags"]
    assert "#Shorts" in desc_data["hashtags"]
    assert len(desc_data.get("youtube_tags", [])) >= 3


def test_description_uniqueness_across_videos():
    gen = DescriptionGenerator()
    d1 = gen.generate(
        topic="Why do your ears ring in absolute silence?",
        category="Biology",
        script_data={"title": "Why Ears Ring in Absolute Silence"},
        sources=["https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3181924/"],
    )
    d2 = gen.generate(
        topic="The sunken Egyptian port city of Thonis-Heracleion",
        category="History",
        script_data={"title": "The Sunken Egyptian Port of Heracleion"},
        sources=["https://www.oxrep.ox.ac.uk/"],
    )

    assert d1["hook"] != d2["hook"]
    assert d1["body"] != d2["body"]
    assert d1["engagement_question"] != d2["engagement_question"]
    assert set(d1["hashtags"]) != set(d2["hashtags"])


def test_dashboard_description_endpoints(tmp_path):
    from unittest.mock import patch
    from curiosity_engine.state.db import DatabaseClient

    iso_db = DatabaseClient(custom_file=tmp_path / "desc_test_db.json")
    iso_db.save_video_record("video_20261109_slot1", {
        "video_id": "video_20261109_slot1",
        "topic": "Why do your ears ring in absolute silence?",
        "category": "Biology",
        "sources": ["https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3181924/"],
        "claims": ["Brain increases neural gain in anechoic silence."],
        "script": {"title": "Why Ears Ring in Absolute Silence"},
    })
    client = TestClient(app)

    with patch("curiosity_engine.dashboard.app.db", iso_db):
        # 1. GET description
        resp = client.get("/api/video/video_20261109_slot1/description")
        assert resp.status_code == 200
        data = resp.json()
        assert data["video_id"] == "video_20261109_slot1"
        assert "description" in data
        assert len(data["description"]) > 100

        # 2. PUT description without auth header must return 403 Forbidden
        put_resp = client.put(
            "/api/video/video_20261109_slot1/description",
            json={"description": "Updated custom description."},
        )
        assert put_resp.status_code == 403

        # 3. PUT description with valid X-Studio-Auth succeeds and persists
        headers = {"X-Studio-Auth": DASHBOARD_SECRET_KEY}
        custom_text = (
            "Updated custom description hook.\n\n"
            "Here is the edited body text.\n\n"
            f"✨ {BRAND_SIGN_OFF}\n\n#CurioLoop #Biology #Shorts"
        )
        put_resp_auth = client.put(
            "/api/video/video_20261109_slot1/description",
            headers=headers,
            json={"description": custom_text},
        )
        assert put_resp_auth.status_code == 200
        assert put_resp_auth.json()["description"] == custom_text

        # Verify persistence in isolated database
        rec = iso_db.get_video_record("video_20261109_slot1")
        assert rec["youtube_description"] == custom_text
        assert rec["description_edited"] is True
