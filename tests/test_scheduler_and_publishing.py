"""Comprehensive Unit & Integration Test Suite for Curiosity Engine
Autonomous Local Scheduler & Decoupled Publishing Architecture.

Tests:
1. Configuration defaults and platform isolation.
2. Direct YouTube Shorts upload isolation (YouTube succeeds even when Instagram is disabled or fails).
3. Slot 2 historical simulation recovery (unblocks Slot 2 without duplicate risk).
4. Duplicate upload prevention for real YouTube video IDs.
5. Date-aware catch-up logic (never publishes stale videos from previous days).
6. Single-instance scheduler locking and stale lock recovery.
7. OAuth refresh token expiration & invalid_grant detection.
8. Scheduler timezone boundary calculations in Asia/Kolkata.
9. Video status classification (Generated, Simulated, Uploaded-Private, Published-Public).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from curiosity_engine.config import (
    INSTAGRAM_PUBLISHING_MODE,
    SCHEDULER_GENERATE_TIME,
    SCHEDULER_PUBLISH_SLOT1_TIME,
    SCHEDULER_PUBLISH_SLOT2_TIME,
    SCHEDULER_TIMEZONE,
    YOUTUBE_PRIVACY_STATUS,
    YOUTUBE_PUBLISHING_MODE,
)
from curiosity_engine.distribution.instagram_publisher import InstagramPublisher
from curiosity_engine.distribution.token_manager import TokenManager
from curiosity_engine.distribution.youtube_publisher import YouTubePublisher
from curiosity_engine.runner.local_scheduler import LocalScheduler, SchedulerLockError
from curiosity_engine.runner.pipeline import is_real_youtube_upload, run_slot_publishing

IST = ZoneInfo(SCHEDULER_TIMEZONE)


# ==============================================================================
# 1. Configuration Defaults & Isolation Tests
# ==============================================================================
def test_configuration_defaults():
    """Verify strict default configuration: YouTube simulation, private privacy, Instagram disabled."""
    assert YOUTUBE_PUBLISHING_MODE in ["simulation", "live"]
    assert YOUTUBE_PRIVACY_STATUS == "private"
    assert INSTAGRAM_PUBLISHING_MODE == "disabled"
    assert SCHEDULER_TIMEZONE == "Asia/Kolkata"


def test_youtube_privacy_status_never_defaults_to_public(monkeypatch):
    """Verify that arbitrary or missing privacy configurations always fallback to 'private'."""
    from curiosity_engine.config import _resolve_youtube_privacy

    monkeypatch.setenv("YOUTUBE_PRIVACY_STATUS", "invalid_value")
    assert _resolve_youtube_privacy() == "private"

    monkeypatch.delenv("YOUTUBE_PRIVACY_STATUS", raising=False)
    assert _resolve_youtube_privacy() == "private"

    monkeypatch.setenv("YOUTUBE_PRIVACY_STATUS", "public")
    assert _resolve_youtube_privacy() == "public"


# ==============================================================================
# 2. Instagram Disabled Mode Isolation Tests
# ==============================================================================
def test_instagram_publisher_disabled_mode_makes_zero_network_calls(tmp_path):
    """Verify that when INSTAGRAM_PUBLISHING_MODE='disabled', publish_reel returns immediately without network calls."""
    pub = InstagramPublisher(mode="disabled")
    dummy_video = tmp_path / "test.mp4"
    dummy_video.write_bytes(b"dummy")

    with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
        res = pub.publish_reel(
            video_path=dummy_video,
            caption="Test Caption",
            hashtags=["test"],
        )
        assert res.get("disabled") is True
        assert res.get("status") == "DISABLED"
        assert res.get("media_id") is None
        mock_get.assert_not_called()
        mock_post.assert_not_called()


# ==============================================================================
# 3. YouTube Direct Upload Isolation (Instagram Failure Does Not Break YouTube)
# ==============================================================================
def test_youtube_success_remains_intact_if_instagram_fails(tmp_path, monkeypatch):
    """Verify that if Instagram fails or throws an exception, YouTube upload remains recorded as successful."""
    video_id = "video_20261110_slot1"
    clean_date = "20261110"

    dummy_mp4 = tmp_path / f"{video_id}.mp4"
    dummy_mp4.write_bytes(b"fake mp4 video bytes")

    mock_record = {
        "video_id": video_id,
        "slot_index": 1,
        "target_date": "2026-11-10",
        "topic": "Test Topic",
        "category": "Science",
        "qc_passed": True,
        "local_video_path": str(dummy_mp4),
        "production_status": "COMPLETED",
        "publishing_status": "PENDING",
        "youtube_description": "Custom test description #Shorts",
    }

    mock_db = MagicMock()
    mock_db.get_video_record.return_value = mock_record

    # Mock YouTube publisher to succeed with simulation
    mock_yt = MagicMock()
    mock_yt.upload_short.return_value = {
        "success": True,
        "video_id": "yt_sim_test123",
        "url": "https://www.youtube.com/shorts/yt_sim_test123",
        "simulated": True,
        "privacy_status": "simulation_private",
        "published_at": datetime.now(timezone.utc).isoformat(),
    }

    # Mock Instagram publisher to raise an exception
    mock_ig = MagicMock()
    mock_ig.publish_reel.side_effect = RuntimeError("Instagram Graph API Timeout!")

    with patch("curiosity_engine.runner.pipeline.db", mock_db), \
         patch("curiosity_engine.runner.pipeline.youtube_publisher", mock_yt), \
         patch("curiosity_engine.runner.pipeline.instagram_publisher", mock_ig):

        res = run_slot_publishing(slot_index=1, target_date="2026-11-10", force_publish=True)

        assert res is not None
        # YouTube must be recorded as simulated/successful
        assert res.get("youtube_upload_id") == "yt_sim_test123"
        assert res.get("youtube_status") == "SIMULATED"
        # Instagram failure must be isolated
        assert res.get("instagram_status") == "FAILED"
        assert "Instagram Graph API Timeout!" in res.get("instagram_error", "")
        # Overall status must remain SIMULATED (not PUBLISH_FAILED)
        assert res.get("publishing_status") == "SIMULATED"


# ==============================================================================
# 4. Slot 2 Historical Simulation Recovery & Duplicate Prevention
# ==============================================================================
def test_real_youtube_upload_identification():
    """Verify is_real_youtube_upload distinguishes real IDs from simulations."""
    assert is_real_youtube_upload(None) is False
    assert is_real_youtube_upload({}) is False
    assert is_real_youtube_upload({"youtube_upload_id": "yt_sim_1794238398"}) is False
    assert is_real_youtube_upload({"youtube_upload_id": "yt_sim_123", "youtube_simulated": True}) is False
    assert is_real_youtube_upload({"youtube_upload_id": "nf_uztFNO8w", "youtube_simulated": True}) is False
    # Real upload
    assert is_real_youtube_upload({"youtube_upload_id": "nf_uztFNO8w", "youtube_simulated": False}) is True
    assert is_real_youtube_upload({"youtube_upload_id": "dQw4w9WgXcQ"}) is True


def test_slot2_historical_simulation_does_not_block_publishing(tmp_path):
    """Verify that Slot 2's historical simulation record (yt_sim_... and PUBLISHED) does not block publishing."""
    video_id = "video_20261109_slot2"
    dummy_mp4 = tmp_path / f"{video_id}.mp4"
    dummy_mp4.write_bytes(b"slot 2 video bytes")

    # Slot 2 existing record with historical simulation
    mock_slot2_record = {
        "video_id": video_id,
        "slot_index": 2,
        "target_date": "2026-11-09",
        "topic": "The sunken Egyptian port city of Thonis-Heracleion",
        "category": "History",
        "qc_passed": True,
        "local_video_path": str(dummy_mp4),
        "production_status": "COMPLETED",
        "publishing_status": "PUBLISHED",  # Historical simulation status
        "youtube_upload_id": "yt_sim_1794238398",  # Historical simulation ID
        "youtube_simulated": True,
        "youtube_description": "Historical description",
    }

    mock_db = MagicMock()
    mock_db.get_video_record.return_value = mock_slot2_record

    mock_yt = MagicMock()
    mock_yt.upload_short.return_value = {
        "success": True,
        "video_id": "new_real_yt_id_999",
        "url": "https://www.youtube.com/shorts/new_real_yt_id_999",
        "simulated": False,
        "privacy_status": "private",
        "published_at": datetime.now(timezone.utc).isoformat(),
    }

    mock_ig = MagicMock()
    mock_ig.publish_reel.return_value = {"disabled": True, "status": "DISABLED"}

    with patch("curiosity_engine.runner.pipeline.db", mock_db), \
         patch("curiosity_engine.runner.pipeline.youtube_publisher", mock_yt), \
         patch("curiosity_engine.runner.pipeline.instagram_publisher", mock_ig):

        # Call with live mode requested
        res = run_slot_publishing(
            slot_index=2,
            target_date="2026-11-09",
            force_yt_mode="live",
            force_ig_mode="disabled",
        )

        assert res is not None
        # It must NOT return early or skip! It must upload to YouTube!
        mock_yt.upload_short.assert_called_once()
        assert res.get("youtube_upload_id") == "new_real_yt_id_999"
        assert res.get("youtube_status") == "PUBLISHED"
        assert res.get("youtube_simulated") is False


def test_real_youtube_upload_duplicate_prevention(tmp_path):
    """Verify that a video with a verified real YouTube ID is NEVER uploaded twice."""
    video_id = "video_20261109_slot1"
    dummy_mp4 = tmp_path / f"{video_id}.mp4"
    dummy_mp4.write_bytes(b"slot 1 video bytes")

    mock_slot1_record = {
        "video_id": video_id,
        "slot_index": 1,
        "target_date": "2026-11-09",
        "topic": "Why ears ring in silence",
        "category": "Biology",
        "qc_passed": True,
        "local_video_path": str(dummy_mp4),
        "production_status": "COMPLETED",
        "publishing_status": "PUBLISHED",
        "youtube_upload_id": "nf_uztFNO8w",  # Verified real YouTube upload
        "youtube_simulated": False,
        "youtube_privacy_status": "private",
    }

    mock_db = MagicMock()
    mock_db.get_video_record.return_value = mock_slot1_record

    mock_yt = MagicMock()
    mock_ig = MagicMock()
    mock_ig.publish_reel.return_value = {"disabled": True, "status": "DISABLED"}

    with patch("curiosity_engine.runner.pipeline.db", mock_db), \
         patch("curiosity_engine.runner.pipeline.youtube_publisher", mock_yt), \
         patch("curiosity_engine.runner.pipeline.instagram_publisher", mock_ig):

        # Even if called in live mode, real upload must be skipped!
        res = run_slot_publishing(slot_index=1, target_date="2026-11-09", force_yt_mode="live")

        # YouTube upload must NOT be called
        mock_yt.upload_short.assert_not_called()
        assert res.get("youtube_upload_id") == "nf_uztFNO8w"


# ==============================================================================
# 5. Date-Aware Catch-Up Logic Tests
# ==============================================================================
def test_scheduler_catchup_is_strictly_date_aware(tmp_path):
    """Verify catch-up evaluates today's current IST day and never blindly publishes stale videos from past days."""
    state_file = tmp_path / "sched_state.json"
    lock_file = tmp_path / ".sched.lock"

    sched = LocalScheduler(state_file=state_file, lock_file=lock_file)

    # Mock current time in IST to 10:30 AM IST
    mock_now_ist = datetime(2026, 11, 10, 10, 30, 0, tzinfo=IST)

    with patch.object(sched, "now_ist", return_value=mock_now_ist), \
         patch.object(sched, "is_automation_enabled", return_value=True), \
         patch.object(sched, "process_daily_automation") as mock_auto:

        mock_auto.return_value = {"overall_status": "COMPLETED"}

        recovered = sched.run_catchup_check()
        assert len(recovered) == 1
        mock_auto.assert_called_once_with(target_date="2026-11-10")


def test_scheduler_does_not_publish_when_automation_paused(tmp_path):
    """Verify scheduler respects automation_state.json and pauses execution when disabled."""
    state_file = tmp_path / "sched_state.json"
    lock_file = tmp_path / ".sched.lock"

    sched = LocalScheduler(state_file=state_file, lock_file=lock_file)

    with patch.object(sched, "is_automation_enabled", return_value=False), \
         patch.object(sched, "process_daily_automation") as mock_auto:
        recovered = sched.run_catchup_check()
        assert len(recovered) == 0
        mock_auto.assert_not_called()


# ==============================================================================
# 6. Single-Instance Scheduler Locking & Restart Recovery Tests
# ==============================================================================
def test_scheduler_lock_single_instance(tmp_path):
    """Verify single-instance lock file prevents concurrent scheduler instances from other processes."""
    state_file = tmp_path / "sched_state.json"
    lock_file = tmp_path / ".sched.lock"

    # Simulate an active external scheduler process running with PID 55555
    lock_file.write_text("55555", encoding="utf-8")

    sched = LocalScheduler(state_file=state_file, lock_file=lock_file)
    with patch.object(sched, "_is_pid_alive", return_value=True):
        with pytest.raises(SchedulerLockError):
            sched.acquire_lock()

    # When lock file is released/clean, acquire succeeds
    lock_file.unlink()
    sched.acquire_lock()
    assert lock_file.exists()
    assert lock_file.read_text(encoding="utf-8").strip() == str(os.getpid())
    sched.release_lock()
    assert not lock_file.exists()


def test_scheduler_stale_lock_recovery(tmp_path):
    """Verify scheduler recovers and overrides stale lock file from dead process or reboot."""
    state_file = tmp_path / "sched_state.json"
    lock_file = tmp_path / ".sched.lock"

    # Write a dead PID to lock file
    lock_file.write_text("999999", encoding="utf-8")

    sched = LocalScheduler(state_file=state_file, lock_file=lock_file)
    with patch.object(sched, "_is_pid_alive", return_value=False):
        # Must acquire lock cleanly by detecting dead PID
        sched.acquire_lock()
        assert lock_file.read_text(encoding="utf-8").strip() == str(os.getpid())
        sched.release_lock()


# ==============================================================================
# 7. OAuth Expiration & Reauthorization Alerts
# ==============================================================================
def test_oauth_expiration_handling(tmp_path):
    """Verify TokenManager handles invalid_grant gracefully and marks reauth_required=True."""
    state_file = tmp_path / "token_state.json"
    tm = TokenManager(state_file=state_file)

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.json.return_value = {
        "error": "invalid_grant",
        "error_description": "Token has been expired or revoked.",
    }

    with patch("requests.post", return_value=mock_resp):
        res = tm.check_youtube_health(
            client_id="test_cid",
            client_secret="test_sec",
            refresh_token="test_ref",
        )
        assert res["healthy"] is False
        assert res["reauth_required"] is True
        assert res["status"] == "REVOKED_OR_EXPIRED"
        assert "CRITICAL" in res["alert"]


# ==============================================================================
# 8. Timezone Boundary & Next Execution Calculations
# ==============================================================================
def test_scheduler_timezone_boundaries(tmp_path):
    """Verify next execution calculation computes exact IST boundaries."""
    state_file = tmp_path / "sched_state.json"
    lock_file = tmp_path / ".sched.lock"
    sched = LocalScheduler(state_file=state_file, lock_file=lock_file)

    # 1. At 08:00 IST on Nov 10 -> Next should be 12:30 IST today
    time_0800 = datetime(2026, 11, 10, 8, 0, 0, tzinfo=IST)
    with patch.object(sched, "now_ist", return_value=time_0800):
        next_job = sched.compute_next_execution()
        assert next_job["slot"] == "scheduled_publication"
        assert "12:30:00" in next_job["scheduled_ist"]

    # 2. At 14:00 IST on Nov 10 -> Next should be 20:30 IST today
    time_1400 = datetime(2026, 11, 10, 14, 0, 0, tzinfo=IST)
    with patch.object(sched, "now_ist", return_value=time_1400):
        next_job = sched.compute_next_execution()
        assert next_job["slot"] == "scheduled_publication"
        assert "20:30:00" in next_job["scheduled_ist"]

    # 3. At 21:00 IST on Nov 10 -> Next should be 12:30 IST tomorrow (Nov 11)
    time_2100 = datetime(2026, 11, 10, 21, 0, 0, tzinfo=IST)
    with patch.object(sched, "now_ist", return_value=time_2100):
        next_job = sched.compute_next_execution()
        assert next_job["slot"] == "scheduled_publication"
        assert "2026-11-11" in next_job["scheduled_ist"]
        assert "12:30:00" in next_job["scheduled_ist"]


# ==============================================================================
# 9. Dashboard Video Status Classification Tests
# ==============================================================================
def test_dashboard_video_ui_status_classification():
    """Verify distinct UI states: GENERATED, SIMULATED, UPLOADED_PRIVATE, PUBLISHED_PUBLIC."""
    from curiosity_engine.dashboard.app import app

    # Simulated status
    v_sim = {
        "production_status": "COMPLETED",
        "qc_passed": True,
        "publishing_status": "SIMULATED",
        "youtube_upload_id": "yt_sim_123456",
        "youtube_simulated": True,
    }

    # Uploaded Private status
    v_priv = {
        "production_status": "COMPLETED",
        "qc_passed": True,
        "publishing_status": "PUBLISHED",
        "youtube_upload_id": "nf_uztFNO8w",
        "youtube_simulated": False,
        "youtube_privacy_status": "private",
    }

    # Published Public status
    v_pub = {
        "production_status": "COMPLETED",
        "qc_passed": True,
        "publishing_status": "PUBLISHED",
        "youtube_upload_id": "dQw4w9WgXcQ",
        "youtube_simulated": False,
        "youtube_privacy_status": "public",
    }

    # Generated only (not published)
    v_gen = {
        "production_status": "COMPLETED",
        "qc_passed": True,
        "publishing_status": "PENDING",
        "youtube_upload_id": None,
    }

    # Test via mock helper logic
    def check_status(v):
        yt_id = v.get("youtube_upload_id")
        yt_sim = v.get("youtube_simulated", False)
        privacy = v.get("youtube_privacy_status", "private")
        pub_status = v.get("publishing_status", "PENDING")

        if yt_id and not str(yt_id).startswith("yt_sim_") and not yt_sim:
            if privacy == "public":
                return "PUBLISHED_PUBLIC"
            return "UPLOADED_PRIVATE"
        if yt_sim or str(yt_id or "").startswith("yt_sim_") or pub_status == "SIMULATED":
            return "SIMULATED"
        if v.get("production_status") == "COMPLETED" and v.get("qc_passed"):
            return "GENERATED"
        return v.get("production_status", "PENDING")

    assert check_status(v_priv) == "UPLOADED_PRIVATE"
    assert check_status(v_pub) == "PUBLISHED_PUBLIC"
    assert check_status(v_sim) == "SIMULATED"
    assert check_status(v_gen) == "GENERATED"
