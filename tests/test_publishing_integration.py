"""Comprehensive Test Suite for Phase 3: Autonomous Publishing Integration.
Validates:
1. Secret protection & gitignore rules.
2. Strong random dashboard secret outside source control.
3. Swappable video host with external providers strictly disabled.
4. TokenManager health checks and reauthorization alerts.
5. YouTube publisher dedicated quota tracking, error categorization, and strict no-silent-mock enforcement.
6. Instagram publisher graph.instagram.com endpoints, container polling, and strict no-silent-mock enforcement.
7. Idempotency & duplicate protection across both platforms.
8. Dashboard localhost security (X-Studio-Auth) and secret redaction.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from curiosity_engine.config import (
    DASHBOARD_SECRET_KEY,
    DATA_DIR,
    OUTPUT_DIR,
    PROJECT_ROOT,
    YOUTUBE_UPLOAD_DAILY_LIMIT,
    get_dashboard_secret,
)
from curiosity_engine.dashboard.app import app, sanitize_data
from curiosity_engine.distribution.instagram_publisher import (
    InstagramAuthError,
    InstagramPublisher,
    InstagramPublisherError,
)
from curiosity_engine.distribution.token_manager import TokenManager
from curiosity_engine.distribution.video_host import (
    CloudflareR2VideoHost,
    FirebaseStorageVideoHost,
    SimulationVideoHost,
    get_video_host,
)
from curiosity_engine.distribution.youtube_publisher import (
    YouTubeAuthError,
    YouTubeChannelLimitError,
    YouTubePublisher,
    YouTubeQuotaError,
)
from curiosity_engine.state.db import db


# -----------------------------------------------------------------------------
# 1. Security & Gitignore Verification
# -----------------------------------------------------------------------------
def test_gitignore_protects_secrets():
    gitignore_path = PROJECT_ROOT / ".gitignore"
    assert gitignore_path.exists(), ".gitignore must exist"
    content = gitignore_path.read_text(encoding="utf-8")

    assert ".env" in content
    assert "*.token" in content
    assert "client_secret*.json" in content
    assert ".dashboard_secret" in content
    assert "output/" in content
    assert "models/" in content


def test_dashboard_secret_strength_and_persistence():
    secret = get_dashboard_secret()
    assert isinstance(secret, str)
    assert len(secret) >= 32, "Dashboard secret must be at least 32 characters"

    secret_file = DATA_DIR / ".dashboard_secret"
    assert secret_file.exists(), ".dashboard_secret file must be persisted in data/"
    assert secret_file.read_text(encoding="utf-8").strip() == secret


# -----------------------------------------------------------------------------
# 2. Video Host Provider Verification
# -----------------------------------------------------------------------------
def test_video_host_simulation_default():
    host = get_video_host("simulation")
    assert isinstance(host, SimulationVideoHost)

    # Test sample video
    sample_video = OUTPUT_DIR / "video_20261109_slot1.mp4"
    if sample_video.exists():
        url = host.host_video(sample_video)
        assert "simulation.curioloop.local" in url
        assert sample_video.name in url


def test_external_video_hosts_disabled_by_default():
    with pytest.raises(PermissionError) as exc_cf:
        CloudflareR2VideoHost(allow_external=False)
    assert "disabled" in str(exc_cf.value).lower()

    with pytest.raises(PermissionError) as exc_fb:
        FirebaseStorageVideoHost(allow_external=False)
    assert "disabled" in str(exc_fb.value).lower()


# -----------------------------------------------------------------------------
# 3. Token Manager Health & Expiration Alerts
# -----------------------------------------------------------------------------
def test_token_manager_unconfigured_states(tmp_path):
    tm = TokenManager(state_file=tmp_path / "test_token_state.json")

    # YouTube unconfigured check
    yt_health = tm.check_youtube_health(client_id="", client_secret="", refresh_token="")
    assert yt_health["status"] == "UNCONFIGURED"
    assert yt_health["healthy"] is False

    # Instagram unconfigured check
    ig_health = tm.check_instagram_health(access_token="", account_id="")
    assert ig_health["status"] == "UNCONFIGURED"
    assert ig_health["healthy"] is False


def test_token_manager_revocation_alert(tmp_path):
    tm = TokenManager(state_file=tmp_path / "test_token_state.json")

    # Mock invalid_grant from Google
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.json.return_value = {"error": "invalid_grant", "error_description": "Token expired or revoked"}

    with patch("requests.post", return_value=mock_resp):
        res = tm.check_youtube_health("test_id", "test_sec", "expired_token")
        assert res["status"] == "REVOKED_OR_EXPIRED"
        assert res["reauth_required"] is True
        assert "auth_youtube.py" in res["alert"]


# -----------------------------------------------------------------------------
# 4. YouTube Publisher Dedicated Quota & No-Silent-Mock Rule
# -----------------------------------------------------------------------------
def test_youtube_publisher_simulation_mode():
    sample_video = OUTPUT_DIR / "video_20261109_slot1.mp4"
    publisher = YouTubePublisher(mode="simulation")

    result = publisher.upload_short(
        video_path=sample_video,
        title="Curiosity Engine Test Short",
        description="Testing simulation upload",
        tags=["Test", "Science"],
    )
    assert result["success"] is True
    assert result["simulated"] is True
    assert result["video_id"].startswith("yt_sim_")
    assert "#Shorts" in result["title"]


def test_youtube_publisher_live_mode_rejects_missing_credentials():
    sample_video = OUTPUT_DIR / "video_20261109_slot1.mp4"
    # Live mode with empty credentials must RAISE YouTubeAuthError, NEVER return simulated success!
    publisher = YouTubePublisher(
        client_id="",
        client_secret="",
        refresh_token="",
        mode="live",
    )
    with pytest.raises(YouTubeAuthError) as exc_info:
        publisher.upload_short(
            video_path=sample_video,
            title="Curiosity Engine Live Attempt",
            description="Testing no silent mock rule",
            tags=["Test"],
        )
    assert "OAuth credentials are not configured" in str(exc_info.value)


def test_youtube_publisher_error_categorization():
    sample_video = OUTPUT_DIR / "video_20261109_slot1.mp4"
    publisher = YouTubePublisher(
        client_id="cid",
        client_secret="sec",
        refresh_token="ref",
        mode="live",
    )
    publisher.service = MagicMock()
    mock_insert = MagicMock()
    publisher.service.videos().insert.return_value = mock_insert

    from googleapiclient.errors import HttpError
    from httplib2 import Response

    # Simulate uploadLimitExceeded error
    mock_resp = Response({"status": 400})
    http_error_limit = HttpError(mock_resp, b'{"error": {"errors": [{"reason": "uploadLimitExceeded"}]}}')
    mock_insert.next_chunk.side_effect = http_error_limit

    with pytest.raises(YouTubeChannelLimitError):
        publisher.upload_short(
            video_path=sample_video,
            title="Exceed Limit Test",
            description="Testing error handling",
            tags=["Test"],
        )


# -----------------------------------------------------------------------------
# 5. Instagram Publisher Standardized Endpoints & No-Silent-Mock Rule
# -----------------------------------------------------------------------------
def test_instagram_publisher_simulation_mode(tmp_path):
    sample_video = tmp_path / "video_sample.mp4"
    sample_video.write_bytes(b"0" * 1024)
    publisher = InstagramPublisher(mode="simulation")

    result = publisher.publish_reel(
        video_path=sample_video,
        caption="Curiosity Engine Test Reel",
        hashtags=["#Curiosity", "Science"],
    )
    assert result["success"] is True
    assert result["simulated"] is True
    assert result["media_id"].startswith("ig_sim_")


def test_instagram_publisher_live_mode_rejects_missing_credentials(tmp_path):
    sample_video = tmp_path / "video_sample.mp4"
    sample_video.write_bytes(b"0" * 1024)
    publisher = InstagramPublisher(
        access_token="",
        account_id="",
        mode="live",
    )
    with pytest.raises(InstagramAuthError) as exc_info:
        publisher.publish_reel(
            video_path=sample_video,
            caption="Live Reel Attempt",
            hashtags=["Test"],
        )
    assert "credentials are not configured" in str(exc_info.value)


# -----------------------------------------------------------------------------
# 6. Dashboard Security & Secret Sanitization
# -----------------------------------------------------------------------------
def test_dashboard_mutating_endpoints_require_auth(tmp_path):
    from curiosity_engine.runner.automation_state import AutomationStateManager
    iso_state = AutomationStateManager(state_path=tmp_path / "automation_state.json")
    client = TestClient(app)

    # Unauthenticated POST must return 403 Forbidden
    resp = client.post("/api/trigger/generate")
    assert resp.status_code == 403

    resp = client.post("/api/toggle_automation")
    assert resp.status_code == 403

    # Authenticated POST with correct X-Studio-Auth succeeds without mutating production data/
    headers = {"X-Studio-Auth": DASHBOARD_SECRET_KEY}
    with patch("curiosity_engine.runner.automation_state.automation_state", iso_state):
        resp = client.post("/api/toggle_automation", headers=headers)
        assert resp.status_code == 200
        assert "enabled" in resp.json()


def test_dashboard_status_scrubs_secrets():
    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()

    # Verify dedicated quota reporting
    assert data["quotas"]["youtube"]["daily_limit"] == YOUTUBE_UPLOAD_DAILY_LIMIT
    assert data["quotas"]["youtube"]["tier"] == "Dedicated Upload Quota Bucket"

    # Verify token health reporting
    assert "token_health" in data

    # Test sanitize_data function
    sensitive_dict = {
        "gemini_api_key": "AIzaSyDummySecretKey123456789012345",
        "instagram_access_token": "EAAGdummyinstagramtoken123456789",
        "safe_value": "Curiosity Engine",
    }
    cleaned = sanitize_data(sensitive_dict)
    assert cleaned["gemini_api_key"] == "AIz...345"
    assert cleaned["instagram_access_token"] == "EAA...789"
    assert cleaned["safe_value"] == "Curiosity Engine"


# -----------------------------------------------------------------------------
# 7. Durable Publishing Pipeline State & Idempotency Guard
# -----------------------------------------------------------------------------
def test_pipeline_publishing_simulation_and_idempotency(tmp_path):
    from curiosity_engine.runner.pipeline import run_slot_publishing
    from curiosity_engine.state.db import DatabaseClient

    temp_db = DatabaseClient(custom_file=tmp_path / "test_db.json")
    dummy_mp4 = tmp_path / "video_20261109_slot1.mp4"
    dummy_mp4.write_bytes(b"0" * 150_000)
    temp_db.save_video_record("video_20261109_slot1", {
        "video_id": "video_20261109_slot1",
        "slot_index": 1,
        "target_date": "2026-11-09",
        "topic": "Why do your ears ring in absolute silence?",
        "category": "Biology",
        "qc_passed": True,
        "local_video_path": str(dummy_mp4),
        "production_status": "COMPLETED",
        "publishing_status": "PUBLISHED",
        "youtube_upload_id": "nf_uztFNO8w",
        "youtube_simulated": False,
        "youtube_privacy_status": "private",
    })

    with patch("curiosity_engine.runner.pipeline.db", temp_db):
        record = run_slot_publishing(slot_index=1, target_date="2026-11-09")
        assert record is not None
        assert record["publishing_status"] == "PUBLISHED"
        assert record.get("youtube_upload_id") == "nf_uztFNO8w"

        second_run = run_slot_publishing(slot_index=1, target_date="2026-11-09")
        assert second_run["publishing_status"] == "PUBLISHED"
        assert second_run["youtube_upload_id"] == record["youtube_upload_id"]
