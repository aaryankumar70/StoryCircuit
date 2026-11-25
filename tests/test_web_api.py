"""Tests for FastAPI dashboard, progress telemetry, and YouTube OAuth/client JSON endpoints."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from reelforge import config
from reelforge.progress import build_progress_payload
from reelforge.storage.db import ReelDatabase
from reelforge.web import app as web_app


def test_web_endpoints(tmp_path, monkeypatch):
    test_db = ReelDatabase(tmp_path / "web.db")
    monkeypatch.setattr(web_app, "get_db", lambda: test_db)
    client = TestClient(web_app.app)

    r_home = client.get("/")
    assert r_home.status_code == 200
    assert "StoryCircuit Studio" in r_home.text
    assert "Daily Publishing Progress" in r_home.text
    assert "Today's Shorts &amp; Preview" in r_home.text
    assert "Dual-Slot Production &amp; Publishing Timeline" in r_home.text
    assert "client_secret.json" in r_home.text
    assert "Generate Today's 2 Videos" in r_home.text
    # Ensure test/demo buttons are removed from dashboard
    assert "Test Connection" not in r_home.text
    assert "Check YouTube" not in r_home.text
    assert "Upload / Simulate" not in r_home.text
    assert "Mode: Simulation" not in r_home.text

    r_status = client.get("/api/status")
    assert r_status.status_code == 200
    st = r_status.json()
    assert "daily_summary" in st
    assert len(st["slot_timeline"]) == 2
    assert "youtube" in st
    assert "oauth" in st
    assert "storage" in st

    r_plan = client.post(
        "/api/plan",
        json={
            "planned_date": "2026-11-26",
            "slot_num": 1,
            "publish_time": "14:15",
            "topic": "Flannan Isles Lighthouse",
            "style": "graphic_noir",
        },
    )
    assert r_plan.status_code == 200
    pid = r_plan.json()["id"]

    r_list = client.get("/api/plan")
    assert r_list.status_code == 200
    assert any(it["id"] == pid and it["publish_time"] == "14:15" for it in r_list.json()["items"])

    r_analyze = client.post(
        "/api/scripts/analyze",
        json={
            "title": "Long Mystery",
            "category": "mystery",
            "script": " ".join([f"Sentence {i} reveals another strange clue inside the archive." for i in range(40)]),
        },
    )
    assert r_analyze.status_code == 200
    assert r_analyze.json()["possible_videos"] >= 2

    r_cleanup = client.post("/api/cleanup")
    assert r_cleanup.status_code == 200
    assert "deleted_count" in r_cleanup.json()

    r_del = client.delete(f"/api/plan/{pid}")
    assert r_del.status_code == 200
    assert client.get("/api/jobs").status_code == 200
    assert client.get("/api/history").status_code == 200


def test_client_secret_upload_and_progress_snapshot(tmp_path, monkeypatch):
    test_db = ReelDatabase(tmp_path / "web2.db")
    monkeypatch.setattr(web_app, "get_db", lambda: test_db)
    monkeypatch.setattr(config, "CLIENT_SECRET_PATH", tmp_path / "client_secret.json")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "")
    monkeypatch.setattr(config, "YOUTUBE_CLIENT_ID", "")
    monkeypatch.setattr(config, "YOUTUBE_CLIENT_SECRET", "")
    monkeypatch.setattr(config, "YOUTUBE_REFRESH_TOKEN", "")

    client = TestClient(web_app.app)

    bad = client.post(
        "/api/youtube/client-secret",
        files={"file": ("bad.json", b'{"foo": "bar"}', "application/json")},
    )
    assert bad.status_code == 400

    valid_payload = json.dumps({
        "installed": {
            "client_id": "1234567890-test.apps.googleusercontent.com",
            "client_secret": "test-secret-xyz",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }).encode("utf-8")

    ok = client.post(
        "/api/youtube/client-secret",
        files={"file": ("client_secret.json", valid_payload, "application/json")},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["saved"] is True
    assert body["client_type"] == "installed"
    assert body["youtube"]["client_json_present"] is True
    assert body["youtube"]["state"] == "needs_auth"
    assert (tmp_path / "client_secret.json").exists()

    # Verify live progress snapshot surfaces in /api/status
    st_before = client.get("/api/status").json()
    today = st_before["today"]
    jid = test_db.create_job(
        source_mode="random",
        title="Test Progress Short",
        category="history",
        style="editorial_dark",
        script_text="Sample narration.",
        storyboard={"beats": []},
        scheduled_date=today,
        slot_num=1,
        status="rendering",
    )
    test_db.update_job(
        jid,
        progress_json=build_progress_payload(
            stage="rendering_video",
            stage_label="Rendering clips (4/8)",
            percent=74,
            detail="Clip 4/8",
            completed_stages=["selecting_topic", "writing_script", "generating_narration", "preparing_music", "resolving_visuals"],
        ),
    )
    st_after = client.get("/api/status").json()
    assert st_after["worker_busy"] is True
    assert st_after["active_job"]["percent"] == 74
    assert st_after["slot_timeline"][0]["percent"] == 74
    assert st_after["slot_timeline"][0]["phase"] == "production"

    # Active rendering job cannot be deleted (409), completed/failed job can be deleted (200)
    assert client.delete(f"/api/jobs/{jid}").status_code == 409
    test_db.update_job(jid, status="failed")
    assert client.delete(f"/api/jobs/{jid}").status_code == 200
    assert test_db.get_job(jid) is None
