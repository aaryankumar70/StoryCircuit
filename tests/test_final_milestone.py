"""Comprehensive Test Suite for CurioLoop Local Autonomous Automation & Recovery.
Covers all requirements across Phases 1-7 and Incident Recovery & Stabilization:
- Publication time calculations & IST -> UTC RFC 3339 conversion
- YouTube Data API v3 upload+publishAt, standalone schedule_publication, scope & OAuth error handling
- Renderer reliability: FFmpeg failures, missing MP4, corrupt/partial MP4 cleanup, timeout handling
- Pipeline stage resume from ASSETS_READY & slot-independent production/recovery
- Curated fallback prioritization when Gemini is unavailable
- Whisper HuggingFace snapshot & flat model.bin resolution + inline fallback
- Dry-run strict read-only safety & --once safeguard
- Availability-driven startup idempotency & pause/resume
- Single non-admin Windows Startup VBS launcher & graceful daemon stop
- Trustworthy Dashboard UI badges (SCHEDULED never claimed for unconfirmed/simulated) & diagnostic endpoints
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from curiosity_engine.config import DASHBOARD_SECRET_KEY
from curiosity_engine.content.topic_discovery import select_daily_topics
from curiosity_engine.dashboard.app import app, compute_ui_status
from curiosity_engine.distribution.youtube_publisher import (
    DailyPublishingLimitError,
    YouTubeAuthError,
    YouTubePublisher,
    YouTubePublisherError,
)
from curiosity_engine.production.aligner import resolve_whisper_model_path
from curiosity_engine.production.renderer import (
    _run_subprocess_logged,
    validate_rendered_mp4,
)
from curiosity_engine.runner.automation_state import AutomationStateManager
from curiosity_engine.runner.local_scheduler import (
    IST,
    LocalScheduler,
    allocate_slot_publication_time,
    calculate_publication_times,
)
from curiosity_engine.runner.pipeline import (
    assert_daily_publication_capacity,
    assert_no_duplicate_mp4_upload,
    compute_file_sha256,
    get_production_publications_by_ist_date,
    is_slot_generation_complete,
    produce_single_video,
    run_daily_generation,
)
from curiosity_engine.state.db import DatabaseClient
from scripts.manage_windows_task import (
    get_pythonw_path,
    get_startup_vbs_path,
    get_task_status,
)


# =============================================================================
# 1. Publication Times & Timezone Calculations
# =============================================================================
class TestPublicationTimeCalculation:
    """Tests for dynamic publication slot calculation based on startup time."""

    def test_startup_morning_schedules_today_1230_and_2030(self):
        morning_ist = datetime(2026, 11, 10, 8, 30, 0, tzinfo=IST)
        t1, t2 = calculate_publication_times(morning_ist, tz=IST)

        assert (t1.year, t1.month, t1.day, t1.hour, t1.minute) == (2026, 11, 10, 12, 30)
        assert (t2.year, t2.month, t2.day, t2.hour, t2.minute) == (2026, 11, 10, 20, 30)
        assert t2 > t1

    def test_startup_after_midday_schedules_tomorrow_1230_and_today_2030(self):
        afternoon_ist = datetime(2026, 11, 10, 14, 0, 0, tzinfo=IST)
        t1, t2 = calculate_publication_times(afternoon_ist, tz=IST)

        # Policy: 12:15 PM-8:15 PM -> Slot 1: Tomorrow 12:30 PM, Slot 2: Today 8:30 PM
        assert (t1.year, t1.month, t1.day, t1.hour, t1.minute) == (2026, 11, 11, 12, 30)
        assert (t2.year, t2.month, t2.day, t2.hour, t2.minute) == (2026, 11, 10, 20, 30)
        assert t1 > afternoon_ist and t2 > afternoon_ist

    def test_startup_late_evening_schedules_tomorrow_1230_and_tomorrow_2030(self):
        night_ist = datetime(2026, 11, 10, 21, 0, 0, tzinfo=IST)
        t1, t2 = calculate_publication_times(night_ist, tz=IST)

        assert (t1.year, t1.month, t1.day, t1.hour, t1.minute) == (2026, 11, 11, 12, 30)
        assert (t2.year, t2.month, t2.day, t2.hour, t2.minute) == (2026, 11, 11, 20, 30)
        assert t2 > t1

    def test_lead_time_boundary_safety(self):
        close_to_noon = datetime(2026, 11, 10, 12, 20, 0, tzinfo=IST)
        t1, t2 = calculate_publication_times(close_to_noon, tz=IST, min_lead_minutes=15)

        assert t1.day == 11 and t1.hour == 12 and t1.minute == 30
        assert t2.day == 10 and t2.hour == 20 and t2.minute == 30
        assert t1 > close_to_noon and t2 > close_to_noon

    def test_compute_next_execution_picks_earliest_future_slot(self, tmp_path):
        sched = LocalScheduler(
            state_file=tmp_path / "sched.json",
            lock_file=tmp_path / "sched.lock",
        )
        afternoon_ist = datetime(2026, 11, 10, 14, 0, 0, tzinfo=IST)
        with patch.object(sched, "now_ist", return_value=afternoon_ist):
            nxt = sched.compute_next_execution()
        assert nxt["scheduled_ist"] == "2026-11-10T20:30:00+05:30"

    def test_rfc3339_utc_conversion(self):
        dt_ist = datetime(2026, 11, 10, 12, 30, 0, tzinfo=IST)
        rfc3339 = dt_ist.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        assert rfc3339 == "2026-11-10T07:00:00.000Z"

    def test_daily_publication_limit_max_two_per_ist_day(self):
        mock_db = MagicMock()
        mock_db.get_all_videos.return_value = [
            {
                "video_id": "video_20261111_slot1",
                "youtube_upload_id": "yt_real_1",
                "youtube_simulated": False,
                "schedule_confirmed": True,
                "scheduled_publish_at": "2026-11-11T07:00:00.000Z",  # 12:30 IST
            },
            {
                "video_id": "video_20261111_slot2",
                "youtube_upload_id": "yt_real_2",
                "youtube_simulated": False,
                "schedule_confirmed": True,
                "scheduled_publish_at": "2026-11-11T15:00:00.000Z",  # 20:30 IST
            },
        ]
        with patch("curiosity_engine.runner.pipeline.db", mock_db):
            with pytest.raises(DailyPublishingLimitError):
                assert_daily_publication_capacity(
                    datetime(2026, 11, 11, 16, 0, tzinfo=IST),
                    candidate_video_id="video_20261111_extra",
                )
            # Same record updating idempotently is permitted
            assert_daily_publication_capacity(
                datetime(2026, 11, 11, 12, 30, tzinfo=IST),
                candidate_video_id="video_20261111_slot1",
                candidate_yt_id="yt_real_1",
            )

    def test_private_test_videos_never_counted_toward_daily_limit(self):
        mock_db = MagicMock()
        mock_db.get_all_videos.return_value = [
            {
                "video_id": "disposable_test_1",
                "youtube_upload_id": "N3QUKd0u71U",
                "youtube_simulated": False,
                "youtube_privacy_status": "private",
                "schedule_confirmed": False,
                "is_test": True,
            },
            {
                "video_id": "video_20261109_slot1",
                "youtube_upload_id": "nf_uztFNO8w",
                "youtube_simulated": False,
                "youtube_privacy_status": "private",
                "publishing_status": "PUBLISHED",
                "schedule_confirmed": False,
            },
            {
                "video_id": "video_20261109_slot2",
                "youtube_upload_id": "yt_sim_1794238398",
                "youtube_simulated": True,
                "schedule_confirmed": True,
                "scheduled_publish_at": "2026-11-10T15:00:00.000Z",
            },
        ]
        with patch("curiosity_engine.runner.pipeline.db", mock_db):
            assert get_production_publications_by_ist_date() == {}
            assert_daily_publication_capacity(
                datetime(2026, 11, 10, 20, 30, tzinfo=IST),
                candidate_video_id="video_20261110_slot2",
                candidate_yt_id="nf_uztFNO8w",
            )

    def test_allocate_slot_publication_time_respects_occupied_slots_and_max_two(self):
        now_morning_nov11 = datetime(2026, 11, 11, 8, 0, 0, tzinfo=IST)
        occupied = {"2026-11-11": {"12:30"}}
        s1_dt = allocate_slot_publication_time(1, now_morning_nov11, occupied_by_date=occupied, tz=IST)
        s2_dt = allocate_slot_publication_time(2, now_morning_nov11, occupied_by_date=occupied, tz=IST)

        # Nov 11 12:30 is occupied -> Slot 1 advances to Nov 12 12:30; Slot 2 fills Nov 11 20:30
        assert (s1_dt.year, s1_dt.month, s1_dt.day, s1_dt.hour, s1_dt.minute) == (2026, 11, 12, 12, 30)
        assert (s2_dt.year, s2_dt.month, s2_dt.day, s2_dt.hour, s2_dt.minute) == (2026, 11, 11, 20, 30)

    def test_duplicate_mp4_sha256_blocked_across_records(self, tmp_path):
        mp4 = tmp_path / "video.mp4"
        mp4.write_bytes(b"identical-mp4-bytes")
        sha = compute_file_sha256(mp4)
        mock_db = MagicMock()
        mock_db.get_all_videos.return_value = [
            {
                "video_id": "video_20261109_slot1",
                "youtube_upload_id": "nf_uztFNO8w",
                "youtube_simulated": False,
                "mp4_sha256": sha,
            }
        ]
        with patch("curiosity_engine.runner.pipeline.db", mock_db):
            with pytest.raises(YouTubePublisherError) as exc_info:
                assert_no_duplicate_mp4_upload(mp4, candidate_video_id="video_20261110_slot2")
            assert "duplicate mp4 upload blocked" in str(exc_info.value).lower()

    def test_process_daily_automation_executes_slots_chronologically(self, tmp_path):
        sched = LocalScheduler(
            state_file=tmp_path / "sched.json",
            lock_file=tmp_path / "sched.lock",
        )
        afternoon_nov10 = datetime(2026, 11, 10, 14, 30, 0, tzinfo=IST)
        call_order = []

        def fake_exec(**kwargs):
            call_order.append((kwargs["slot_idx"], kwargs["target_pub_dt"].strftime("%Y-%m-%d %H:%M")))
            return automation_state_mock_rec

        automation_state_mock_rec = {
            "slot1": {"scheduled_status": "SCHEDULED"},
            "slot2": {"scheduled_status": "SCHEDULED"},
        }
        mock_auto = MagicMock()
        mock_auto.is_enabled.return_value = True
        mock_auto.get_daily_record.return_value = {
            "overall_status": "PARTIAL",
            "generation": {"status": "COMPLETED"},
            "slot1": {},
            "slot2": {},
        }
        mock_auto.update_daily_record.return_value = automation_state_mock_rec

        mock_db = MagicMock()
        mock_db.get_all_videos.return_value = []
        mock_db.get_video_record.side_effect = lambda vid: {"video_id": vid, "production_status": "COMPLETED", "qc_passed": True}

        with patch.object(sched, "now_ist", return_value=afternoon_nov10), \
             patch.object(sched, "reconcile_daily_state", return_value=automation_state_mock_rec), \
             patch.object(sched, "_execute_slot_upload_and_schedule", side_effect=fake_exec), \
             patch("curiosity_engine.runner.local_scheduler.automation_state", mock_auto), \
             patch("curiosity_engine.runner.local_scheduler.db", mock_db), \
             patch("curiosity_engine.runner.local_scheduler.is_slot_generation_complete", return_value=True), \
             patch("curiosity_engine.runner.local_scheduler.get_occupied_publication_windows", return_value={}):
            sched.process_daily_automation(target_date="2026-11-10")

        # Today 20:30 (Slot 2) MUST execute chronologically before Tomorrow 12:30 (Slot 1)
        assert call_order == [(2, "2026-11-10 20:30"), (1, "2026-11-11 12:30")]


# =============================================================================
# 2. YouTube Scheduled Publishing, Scopes & Error Handling
# =============================================================================
class TestYouTubeScheduledPublishing:
    """Tests for YouTube Data API status.publishAt scheduling, scopes, and errors."""

    def test_schedule_publication_simulation_mode_marks_unconfirmed(self):
        publisher = YouTubePublisher(mode="simulation")
        pub_dt = datetime.now(IST) + timedelta(hours=3)
        res = publisher.schedule_publication("yt_sim_12345", pub_dt)

        assert res["success"] is True
        assert res["simulated"] is True
        assert res["schedule_confirmed"] is False

    def test_schedule_publication_rejects_past_timestamp(self):
        publisher = YouTubePublisher(mode="simulation")
        past_dt = datetime.now(IST) - timedelta(minutes=10)
        with pytest.raises(YouTubePublisherError) as exc_info:
            publisher.schedule_publication("yt_sim_12345", past_dt)
        assert "past" in str(exc_info.value).lower()

    def test_schedule_publication_live_requires_credentials(self):
        publisher = YouTubePublisher(mode="live", client_id="", client_secret="", refresh_token="")
        pub_dt = datetime.now(IST) + timedelta(hours=3)
        with pytest.raises(YouTubeAuthError) as exc_info:
            publisher.schedule_publication("real_yt_123", pub_dt)
        assert "OAuth credentials are not configured" in str(exc_info.value)

    def test_schedule_publication_live_success_confirms_api_response(self):
        publisher = YouTubePublisher(mode="live", client_id="cid", client_secret="sec", refresh_token="ref")
        future_dt = datetime.now(IST) + timedelta(hours=5)
        expected_utc = future_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        mock_service = MagicMock()
        mock_videos = MagicMock()
        mock_videos.list.return_value.execute.return_value = {
            "items": [{"status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}}]
        }
        mock_videos.update.return_value.execute.return_value = {
            "id": "real_video_xyz",
            "status": {
                "privacyStatus": "private",
                "publishAt": expected_utc,
            },
        }
        mock_service.videos.return_value = mock_videos
        publisher.service = mock_service
        publisher.is_configured = MagicMock(return_value=True)

        res = publisher.schedule_publication("real_video_xyz", future_dt, force_mode="live")

        assert res["success"] is True
        assert res["schedule_confirmed"] is True
        assert res["privacy_status"] == "private"
        assert res["publish_at"] == expected_utc
        assert res["simulated"] is False

    def test_schedule_publication_handles_insufficient_scope_403(self):
        from googleapiclient.errors import HttpError
        from httplib2 import Response

        publisher = YouTubePublisher(mode="live", client_id="cid", client_secret="sec", refresh_token="ref")
        future_dt = datetime.now(IST) + timedelta(hours=5)
        mock_service = MagicMock()
        mock_videos = MagicMock()
        mock_videos.list.return_value.execute.return_value = {"items": []}
        mock_videos.update.return_value.execute.side_effect = HttpError(
            Response({"status": 403}),
            b'{"error": {"code": 403, "errors": [{"reason": "insufficientPermissions"}]}}',
        )
        mock_service.videos.return_value = mock_videos
        publisher.service = mock_service
        publisher.is_configured = MagicMock(return_value=True)

        with pytest.raises(YouTubeAuthError) as exc_info:
            publisher.schedule_publication("real_video_xyz", future_dt, force_mode="live")
        assert "insufficientPermissions" in str(exc_info.value)

    def test_cancel_schedule_live_clears_publish_at_and_stays_private(self):
        publisher = YouTubePublisher(mode="live", client_id="cid", client_secret="sec", refresh_token="ref")
        mock_service = MagicMock()
        mock_videos = MagicMock()
        mock_videos.list.return_value.execute.side_effect = [
            {"items": [{"status": {"privacyStatus": "private", "publishAt": "2026-11-12T07:00:00.000Z"}}]},
            {"items": [{"status": {"privacyStatus": "private", "uploadStatus": "processed"}, "snippet": {"title": "Test"}}]},
        ]
        mock_videos.update.return_value.execute.return_value = {
            "id": "real_video_xyz",
            "status": {"privacyStatus": "private"},
        }
        mock_service.videos.return_value = mock_videos
        publisher.service = mock_service
        publisher.is_configured = MagicMock(return_value=True)

        res = publisher.cancel_schedule("real_video_xyz", force_mode="live")
        assert res["success"] is True
        assert res["schedule_cancelled"] is True
        assert res["privacy_status"] == "private"
        assert res["publish_at"] is None
        assert mock_videos.update.call_count == 1
        update_call = mock_videos.update.call_args.kwargs
        assert "publishAt" not in update_call["body"]["status"]

    def test_cancel_schedule_live_delayed_propagation_succeeds(self):
        publisher = YouTubePublisher(mode="live", client_id="cid", client_secret="sec", refresh_token="ref")
        mock_service = MagicMock()
        mock_videos = MagicMock()
        mock_videos.list.return_value.execute.side_effect = [
            {"items": [{"status": {"privacyStatus": "private", "publishAt": "2026-11-17T12:00:00Z"}}]},
            {"items": [{"status": {"privacyStatus": "private", "publishAt": "2026-11-17T12:00:00Z"}, "snippet": {"title": "Test"}}]},
            {"items": [{"status": {"privacyStatus": "private", "publishAt": "2026-11-17T12:00:00Z"}, "snippet": {"title": "Test"}}]},
            {"items": [{"status": {"privacyStatus": "private", "uploadStatus": "uploaded"}, "snippet": {"title": "Test"}}]},
        ]
        mock_videos.update.return_value.execute.return_value = {
            "id": "real_video_xyz",
            "status": {"privacyStatus": "private", "publishAt": "2026-11-17T12:00:00Z"},
        }
        mock_service.videos.return_value = mock_videos
        publisher.service = mock_service
        publisher.is_configured = MagicMock(return_value=True)

        with patch("curiosity_engine.distribution.youtube_publisher.time.monotonic", side_effect=[0.0, 2.0, 4.0]), \
             patch("curiosity_engine.distribution.youtube_publisher.time.sleep") as mock_sleep:
            res = publisher.cancel_schedule("real_video_xyz", force_mode="live")

        assert res["success"] is True
        assert res["schedule_cancelled"] is True
        assert res["privacy_status"] == "private"
        assert res["publish_at"] is None
        assert mock_videos.update.call_count == 1
        assert mock_videos.list.return_value.execute.call_count == 4
        assert mock_sleep.call_count == 2

    def test_cancel_schedule_live_timeout_raises_last_observed_state(self):
        publisher = YouTubePublisher(mode="live", client_id="cid", client_secret="sec", refresh_token="ref")
        mock_service = MagicMock()
        mock_videos = MagicMock()
        mock_videos.list.return_value.execute.side_effect = [
            {"items": [{"status": {"privacyStatus": "private", "publishAt": "2026-11-17T12:00:00Z"}}]},
            {"items": [{"status": {"privacyStatus": "private", "publishAt": "2026-11-17T12:00:00Z"}, "snippet": {"title": "Test"}}]},
            {"items": [{"status": {"privacyStatus": "private", "publishAt": "2026-11-17T12:00:00Z"}, "snippet": {"title": "Test"}}]},
        ]
        mock_videos.update.return_value.execute.return_value = {
            "id": "real_video_xyz",
            "status": {"privacyStatus": "private", "publishAt": "2026-11-17T12:00:00Z"},
        }
        mock_service.videos.return_value = mock_videos
        publisher.service = mock_service
        publisher.is_configured = MagicMock(return_value=True)

        with patch("curiosity_engine.distribution.youtube_publisher.time.monotonic", side_effect=[0.0, 10.0, 21.0]), \
             patch("curiosity_engine.distribution.youtube_publisher.time.sleep"):
            with pytest.raises(YouTubePublisherError) as exc_info:
                publisher.cancel_schedule("real_video_xyz", force_mode="live")

        err_msg = str(exc_info.value)
        assert mock_videos.update.call_count == 1
        assert "timed out" in err_msg.lower()
        assert "privacyStatus='private'" in err_msg
        assert "publishAt='2026-11-17T12:00:00Z'" in err_msg

    def test_reconcile_existing_upload_skips_other_db_claimed_ids(self):
        publisher = YouTubePublisher(mode="live", client_id="cid", client_secret="sec", refresh_token="ref")
        mock_service = MagicMock()
        mock_service.channels.return_value.list.return_value.execute.return_value = {
            "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU123"}}}]
        }
        mock_service.playlistItems.return_value.list.return_value.execute.return_value = {
            "items": [
                {"snippet": {"title": "Duplicate Title #Shorts", "resourceId": {"videoId": "hist_vid_1"}}},
            ]
        }
        publisher.service = mock_service

        # If hist_vid_1 belongs to another DB record, reconciliation must NOT steal it
        assert publisher.reconcile_existing_upload("Duplicate Title #Shorts", exclude_video_ids={"hist_vid_1"}) is None
        # Without exclusion, it returns hist_vid_1
        mock_service.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"status": {"privacyStatus": "private"}, "snippet": {"title": "Duplicate Title #Shorts"}}]
        }
        matched = publisher.reconcile_existing_upload("Duplicate Title #Shorts")
        assert matched is not None and matched["video_id"] == "hist_vid_1"

    def test_sanitize_data_redacts_access_tokens_and_client_secrets(self):
        from curiosity_engine.dashboard.app import sanitize_data
        raw = {
            "err": "Bad token ya29.a0AfH6SM_test_access_token_xyz and secret GOCSPX-abcDEF123456789"
        }
        clean = sanitize_data(raw)
        assert "ya29." not in clean["err"]
        assert "GOCSPX-" not in clean["err"]
        assert "[REDACTED_ACCESS_TOKEN]" in clean["err"]
        assert "[REDACTED_CLIENT_SECRET]" in clean["err"]


# =============================================================================
# 3. Renderer, MP4 Integrity, Stage Resume, Whisper & Slot Independence
# =============================================================================
class TestRendererAndPipelineReliability:
    """Tests for FFmpeg failures, missing/corrupt MP4, stage resume, QC failures, and slot isolation."""

    def test_missing_mp4_fails_validation(self, tmp_path):
        missing = tmp_path / "does_not_exist.mp4"
        with pytest.raises(FileNotFoundError):
            validate_rendered_mp4(missing)

    def test_corrupt_or_partial_mp4_fails_validation(self, tmp_path):
        # Write 150 KB of garbage bytes (simulating truncated render without moov atom)
        corrupt = tmp_path / "partial.mp4"
        corrupt.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\xaa" * 150_000)

        with pytest.raises(RuntimeError) as exc_info:
            validate_rendered_mp4(corrupt)
        assert "ffprobe rejected" in str(exc_info.value).lower() or "corrupt" in str(exc_info.value).lower()

    def test_undersized_mp4_fails_validation(self, tmp_path):
        tiny = tmp_path / "tiny.mp4"
        tiny.write_bytes(b"tiny")
        with pytest.raises(RuntimeError) as exc_info:
            validate_rendered_mp4(tiny)
        assert "partial/corrupt" in str(exc_info.value)

    def test_subprocess_nonzero_exit_and_timeout_raise(self, tmp_path):
        log_path = tmp_path / "proc.log"
        # Non-zero exit code
        with pytest.raises(RuntimeError) as exc_info:
            _run_subprocess_logged(
                [sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"],
                cwd=tmp_path,
                env=os.environ.copy(),
                log_path=log_path,
                timeout_sec=10,
                step_name="TestSubprocess",
            )
        assert "exit=3" in str(exc_info.value)

        # Timeout
        with pytest.raises(RuntimeError) as exc_t:
            _run_subprocess_logged(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                cwd=tmp_path,
                env=os.environ.copy(),
                log_path=log_path,
                timeout_sec=1,
                step_name="TimeoutStep",
            )
        assert "timed out" in str(exc_t.value)

    def test_whisper_model_path_resolution_supports_hf_snapshot_and_flat(self, tmp_path):
        # 1. HuggingFace snapshot layout (like D:\yt\models\whisper-small)
        hf_dir = tmp_path / "whisper_hf"
        rev = "abc123def456"
        (hf_dir / "refs").mkdir(parents=True)
        (hf_dir / "refs" / "main").write_text(rev, encoding="utf-8")
        snap_dir = hf_dir / "snapshots" / rev
        snap_dir.mkdir(parents=True)
        (snap_dir / "model.bin").write_bytes(b"model")
        assert resolve_whisper_model_path(hf_dir) == str(snap_dir)

        # 2. Flat layout
        flat_dir = tmp_path / "whisper_flat"
        flat_dir.mkdir()
        (flat_dir / "model.bin").write_bytes(b"model")
        assert resolve_whisper_model_path(flat_dir) == str(flat_dir)

        # 3. Missing model returns None cleanly (allows inline fallback)
        assert resolve_whisper_model_path(tmp_path / "missing_dir") is None

    def test_resume_from_assets_ready_skips_prepare_project(self, tmp_path):
        """If ASSETS_READY assets exist and are valid, produce_single_video must NOT wipe or regenerate TTS."""
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        out_dir = tmp_path / "output"
        vid_id = "video_20261110_slot1"
        proj_dir = out_dir / vid_id
        (proj_dir / "src").mkdir(parents=True)
        (proj_dir / "data").mkdir(parents=True)
        (proj_dir / "index.html").write_text("<html></html>", encoding="utf-8")
        (proj_dir / "src" / "main.js").write_text("// ok", encoding="utf-8")
        (proj_dir / "script.json").write_text(json.dumps({"title": "Test", "lines": [{"text": "Hi."}]}), encoding="utf-8")
        (proj_dir / "data" / "narration.wav").write_bytes(b"RIFF" + b"\x00" * 20_000)
        (proj_dir / "data" / "lines.json").write_text(json.dumps({"duration": 25.0, "lines": []}), encoding="utf-8")
        (proj_dir / "data" / "words.json").write_text(json.dumps([{"w": "Hi", "line": 0, "s": 0.1, "e": 0.4}]), encoding="utf-8")

        iso_db.save_video_record(vid_id, {
            "video_id": vid_id,
            "slot_index": 1,
            "target_date": "2026-11-10",
            "topic": "Resumed Topic",
            "category": "History",
            "style": "paper-atlas",
            "production_status": "ASSETS_READY",
            "script": {"title": "Resumed Title", "lines": [{"text": "Hi"}], "sources": ["https://www.oxrep.ox.ac.uk/"]},
            "youtube_description": "Saved custom description",
        })

        mock_qc = MagicMock(passed=True)
        mock_qc.to_dict.return_value = {"passed": True, "checks": {}, "issues": []}

        with patch("curiosity_engine.runner.pipeline.db", iso_db), \
             patch("curiosity_engine.runner.pipeline.OUTPUT_DIR", out_dir), \
             patch("curiosity_engine.runner.pipeline.prepare_project") as mock_prep, \
             patch("curiosity_engine.runner.pipeline.render_project_video") as mock_render, \
             patch("curiosity_engine.runner.pipeline.validate_rendered_mp4", return_value={"duration": 25.0}), \
             patch("curiosity_engine.runner.pipeline.verify_video", return_value=mock_qc):

            # Render creates fake final MP4 on disk
            def _fake_render(p_dir, out_mp4, **kwargs):
                out_mp4.write_bytes(b"valid mp4 placeholder")
                return out_mp4

            mock_render.side_effect = _fake_render
            res = produce_single_video(vid_id, {}, slot_index=1, target_date="2026-11-10")

            mock_prep.assert_not_called()
            mock_render.assert_called_once()
            assert res["production_status"] == "COMPLETED"
            assert res["qc_passed"] is True
            assert res["error"] is None
            assert res["youtube_description"] == "Saved custom description"

    def test_qc_failure_records_rejected_status_and_blocks_upload(self, tmp_path):
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        out_dir = tmp_path / "output"
        vid_id = "video_20261110_slot2"
        out_dir.mkdir(parents=True)
        mp4 = out_dir / f"{vid_id}.mp4"
        mp4.write_bytes(b"rendered mp4 placeholder")

        iso_db.save_video_record(vid_id, {
            "video_id": vid_id,
            "slot_index": 2,
            "target_date": "2026-11-10",
            "topic": "Bad Audio Video",
            "category": "Science",
            "script": {"title": "Bad", "lines": [{"text": "One"}], "sources": ["https://nasa.gov"]},
            "youtube_description": "Desc",
        })

        failed_qc = MagicMock(passed=False, issues=["Integrated loudness -32.0 LUFS outside range"])
        failed_qc.to_dict.return_value = {"passed": False, "checks": {}, "issues": failed_qc.issues}

        with patch("curiosity_engine.runner.pipeline.db", iso_db), \
             patch("curiosity_engine.runner.pipeline.OUTPUT_DIR", out_dir), \
             patch("curiosity_engine.runner.pipeline.validate_rendered_mp4", return_value={"duration": 25.0}), \
             patch("curiosity_engine.runner.pipeline.verify_video", return_value=failed_qc):

            with pytest.raises(RuntimeError) as exc_info:
                produce_single_video(vid_id, {}, slot_index=2, target_date="2026-11-10")
            assert "rejected by QC" in str(exc_info.value)

            saved = iso_db.get_video_record(vid_id)
            assert saved["qc_passed"] is False
            assert "loudness" in saved["error"].lower()

    def test_slot_independent_generation_preserves_completed_slot(self, tmp_path):
        """If Slot 2 is complete + valid MP4 and Slot 1 is missing, run_daily_generation ONLY runs Slot 1."""
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        out_dir = tmp_path / "output"
        out_dir.mkdir(parents=True)
        mp4_2 = out_dir / "video_20261110_slot2.mp4"
        mp4_2.write_bytes(b"valid s2")

        iso_db.save_video_record("video_20261110_slot2", {
            "video_id": "video_20261110_slot2",
            "slot_index": 2,
            "target_date": "2026-11-10",
            "topic": "Slot 2 Existing Topic",
            "production_status": "COMPLETED",
            "qc_passed": True,
            "local_video_path": str(mp4_2),
            "youtube_upload_id": "real_s2_id",
            "youtube_simulated": False,
        })

        with patch("curiosity_engine.runner.pipeline.db", iso_db), \
             patch("curiosity_engine.runner.pipeline.OUTPUT_DIR", out_dir), \
             patch("curiosity_engine.runner.pipeline.validate_rendered_mp4", return_value={"duration": 25.0}), \
             patch("curiosity_engine.runner.pipeline.select_daily_topics", return_value=(
                 {"topic": "Fresh S1", "category": "Tech", "style": "stick-story"},
                 {"topic": "Fresh S2", "category": "History", "style": "paper-atlas"},
             )), \
             patch("curiosity_engine.runner.pipeline.produce_single_video") as mock_prod:

            mock_prod.return_value = {"video_id": "video_20261110_slot1", "qc_passed": True}
            v1, v2 = run_daily_generation(target_date="2026-11-10")

            # Must invoke produce_single_video ONLY once (for slot 1) and preserve slot 2
            mock_prod.assert_called_once()
            assert mock_prod.call_args[1]["slot_index"] == 1
            assert v2["youtube_upload_id"] == "real_s2_id"

    def test_topic_discovery_prioritizes_unused_curated_topic_when_gemini_missing(self, tmp_path):
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        today = "2026-11-10"
        # Mark two of three curated topics as used yesterday
        iso_db.record_topic("The sunken Egyptian port city of Thonis-Heracleion", "History", today)
        iso_db.record_topic("Why do your ears ring in absolute silence?", "Biology", today)

        with patch("curiosity_engine.content.topic_discovery.db", iso_db), \
             patch("curiosity_engine.content.topic_discovery.gemini_client.is_configured", return_value=False), \
             patch("curiosity_engine.content.topic_discovery.gemini_client.generate_json", return_value=None):

            t1, t2 = select_daily_topics(today, record_usage=False)
            # Unused topic ("Carrington solar storm") MUST be picked first instead of repeating both yesterday topics
            assert "solar storm" in t1["topic"].lower()
            assert t1["topic"] != t2["topic"]


# =============================================================================
# 4. Dry-Run Read-Only Safety, --once Safeguard & Duplicate Prevention
# =============================================================================
class TestAvailabilityDrivenAndDryRunSafety:
    """Tests for strict read-only dry-run, --once confirmation guard, and duplicate prevention."""

    @pytest.fixture
    def isolated_automation_state(self, tmp_path):
        return AutomationStateManager(state_path=tmp_path / "automation_state.json")

    def test_dry_run_is_strictly_read_only(self, tmp_path):
        """evaluate_dry_run() must perform zero mutations to DB, automation_state, or filesystem."""
        db_file = tmp_path / "db.json"
        state_file = tmp_path / "automation_state.json"
        iso_db = DatabaseClient(custom_file=db_file)
        iso_state = AutomationStateManager(state_path=state_file)
        sched = LocalScheduler(state_file=tmp_path / "sched.json", lock_file=tmp_path / ".sched.lock")

        db_before = db_file.read_text(encoding="utf-8") if db_file.exists() else None
        state_before = state_file.read_text(encoding="utf-8")

        with patch("curiosity_engine.runner.local_scheduler.automation_state", iso_state), \
             patch("curiosity_engine.runner.local_scheduler.db", iso_db), \
             patch("curiosity_engine.runner.local_scheduler.run_daily_generation") as mock_gen, \
             patch("curiosity_engine.distribution.youtube_publisher.youtube_publisher.upload_short") as mock_up:

            plan = sched.evaluate_dry_run(target_date="2026-11-10")

            assert plan["dry_run"] is True
            assert plan["read_only"] is True
            assert "slot1" in plan["slots"] and "slot2" in plan["slots"]
            mock_gen.assert_not_called()
            mock_up.assert_not_called()

        # Zero state mutation on disk
        assert state_file.read_text(encoding="utf-8") == state_before
        assert (db_file.read_text(encoding="utf-8") if db_file.exists() else None) == db_before

    def test_cli_once_without_confirm_blocked_safely(self):
        """Running scripts/run_scheduler.py --once without --confirm must exit cleanly with safeguard code 2."""
        proc = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "run_scheduler.py"), "--once"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert proc.returncode == 2
        assert "SAFEGUARD BLOCKED" in proc.stdout

    def test_subsequent_startup_does_not_duplicate(self, isolated_automation_state, tmp_path):
        today_str = "2026-11-10"
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        out_dir = tmp_path / "output"
        out_dir.mkdir(parents=True)
        for s in (1, 2):
            mp4 = out_dir / f"video_20261110_slot{s}.mp4"
            mp4.write_bytes(b"valid")
            iso_db.save_video_record(f"video_20261110_slot{s}", {
                "video_id": f"video_20261110_slot{s}",
                "production_status": "COMPLETED",
                "qc_passed": True,
                "local_video_path": str(mp4),
                "youtube_upload_id": f"yt_sim_{s}",
                "youtube_simulated": True,
            })

        scheduler = LocalScheduler(
            state_file=tmp_path / "scheduler_state.json",
            lock_file=tmp_path / ".scheduler.lock",
        )

        with patch("curiosity_engine.runner.local_scheduler.YOUTUBE_PUBLISHING_MODE", "simulation"), \
             patch("curiosity_engine.runner.local_scheduler.automation_state", isolated_automation_state), \
             patch("curiosity_engine.runner.local_scheduler.db", iso_db), \
             patch("curiosity_engine.runner.pipeline.db", iso_db), \
             patch("curiosity_engine.runner.local_scheduler.is_slot_generation_complete", return_value=True), \
             patch("curiosity_engine.runner.local_scheduler.run_daily_generation") as mock_gen, \
             patch("curiosity_engine.distribution.youtube_publisher.youtube_publisher.upload_short") as mock_upload:

            isolated_automation_state.update_daily_record(today_str, {
                "overall_status": "COMPLETED",
                "slot1": {"scheduled_status": "SIMULATED", "youtube_video_id": "yt_sim_1"},
                "slot2": {"scheduled_status": "SIMULATED", "youtube_video_id": "yt_sim_2"},
            })

            # Simulate multiple restarts consecutively
            for _ in range(5):
                rec = scheduler.process_daily_automation(target_date=today_str)
                assert rec["overall_status"] == "COMPLETED"

            mock_gen.assert_not_called()
            mock_upload.assert_not_called()

    def test_catchup_skips_when_automation_paused(self, isolated_automation_state, tmp_path):
        scheduler = LocalScheduler(
            state_file=tmp_path / "scheduler_state.json",
            lock_file=tmp_path / ".scheduler.lock",
        )
        with patch("curiosity_engine.runner.local_scheduler.automation_state", isolated_automation_state):
            isolated_automation_state.set_enabled(False)
            with patch("curiosity_engine.runner.local_scheduler.run_daily_generation") as mock_gen:
                res = scheduler.run_catchup_check()
                assert res == []
                mock_gen.assert_not_called()

            plan = scheduler.evaluate_dry_run("2026-11-10")
            assert plan["automation_enabled"] is False
            assert "SKIP_AUTOMATION_PAUSED" in plan["slots"]["slot1"]["intended_actions"]


# =============================================================================
# 5. Independent Failure Recovery & Slot-Level Retries
# =============================================================================
class TestFailureRecoveryAndRetry:
    """Tests for isolated slot retries and partial failure isolation (zero production data writes)."""

    def test_retry_slot_only_targets_specified_slot(self, tmp_path):
        today_str = "2026-11-10"
        scheduler = LocalScheduler(
            state_file=tmp_path / "scheduler_state.json",
            lock_file=tmp_path / ".scheduler.lock",
        )
        isolated_state = AutomationStateManager(state_path=tmp_path / "automation_state.json")
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        iso_db.save_video_record("video_20261110_slot1", {
            "video_id": "video_20261110_slot1",
            "production_status": "COMPLETED",
            "qc_passed": True,
            "local_video_path": str(tmp_path / "slot1.mp4"),
        })

        def _fake_gen(target_date=None, force_rebuild=False, slots=None):
            iso_db.save_video_record("video_20261110_slot2", {
                "video_id": "video_20261110_slot2",
                "production_status": "COMPLETED",
                "qc_passed": True,
                "local_video_path": str(tmp_path / "slot2.mp4"),
            })
            return (None, iso_db.get_video_record("video_20261110_slot2"))

        with patch("curiosity_engine.runner.local_scheduler.automation_state", isolated_state), \
             patch("curiosity_engine.runner.local_scheduler.db", iso_db), \
             patch("curiosity_engine.runner.pipeline.db", iso_db), \
             patch("curiosity_engine.runner.local_scheduler.is_slot_generation_complete", side_effect=lambda v: iso_db.get_video_record(v) is not None and bool(iso_db.get_video_record(v).get("qc_passed"))), \
             patch("curiosity_engine.runner.local_scheduler.run_daily_generation", side_effect=_fake_gen) as mock_gen, \
             patch.object(scheduler, "process_daily_automation") as mock_batch:

            scheduler.retry_slot(slot_index=2, target_date=today_str)

            mock_gen.assert_called_once_with(target_date=today_str, force_rebuild=False, slots=[2])
            mock_batch.assert_called_once_with(target_date=today_str)

    def test_existing_private_upload_not_reuploaded_on_scheduling_retry(self, tmp_path):
        """If YouTube upload succeeded (real ID obtained) but scheduling failed, retry skips upload and schedules."""
        today_str = "2026-11-10"
        scheduler = LocalScheduler(
            state_file=tmp_path / "scheduler_state.json",
            lock_file=tmp_path / ".scheduler.lock",
        )
        isolated_state = AutomationStateManager(state_path=tmp_path / "test_state.json")
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        iso_db.save_video_record("video_20261110_slot1", {
            "video_id": "video_20261110_slot1",
            "slot_index": 1,
            "target_date": today_str,
            "production_status": "COMPLETED",
            "qc_passed": True,
            "youtube_upload_id": "existing_yt_id_123",
            "youtube_simulated": False,
            "schedule_confirmed": False,
            "local_video_path": str(tmp_path / "s1.mp4"),
        })
        iso_db.save_video_record("video_20261110_slot2", {
            "video_id": "video_20261110_slot2",
            "slot_index": 2,
            "target_date": today_str,
            "production_status": "COMPLETED",
            "qc_passed": True,
            "youtube_upload_id": "existing_yt_id_456",
            "youtube_simulated": False,
            "schedule_confirmed": True,
            "scheduled_publish_at": "2099-11-10T15:00:00.000Z",
            "scheduled_publish_at_ist": "2099-11-10T20:30:00+05:30",
            "local_video_path": str(tmp_path / "s2.mp4"),
        })

        with patch("curiosity_engine.runner.local_scheduler.automation_state", isolated_state), \
             patch("curiosity_engine.runner.local_scheduler.db", iso_db), \
             patch("curiosity_engine.runner.pipeline.db", iso_db), \
             patch("curiosity_engine.runner.local_scheduler.is_slot_generation_complete", return_value=True), \
             patch("curiosity_engine.runner.local_scheduler.YOUTUBE_PUBLISHING_MODE", "live"), \
             patch("curiosity_engine.runner.local_scheduler.token_manager.check_youtube_health", return_value={"healthy": True}), \
             patch("curiosity_engine.runner.local_scheduler.youtube_publisher.get_video_status", return_value=None), \
             patch("curiosity_engine.runner.local_scheduler.youtube_publisher.upload_short") as mock_upload, \
             patch("curiosity_engine.runner.local_scheduler.youtube_publisher.schedule_publication") as mock_sched:

            mock_sched.return_value = {
                "success": True,
                "status": "SCHEDULED",
                "schedule_confirmed": True,
                "publish_at": "2026-11-10T07:00:00.000Z",
                "simulated": False,
            }

            rec = scheduler.process_daily_automation(target_date=today_str)

            mock_upload.assert_not_called()
            mock_sched.assert_called_once()
            assert rec["slot1"]["scheduled_status"] == "SCHEDULED"
            assert iso_db.get_video_record("video_20261110_slot1")["schedule_confirmed"] is True


# =============================================================================
# 6. Windows Task Automation Manager & VBS Launcher
# =============================================================================
class TestWindowsStartupAutomation:
    """Tests for single non-admin Startup VBS registration and daemon status."""

    def test_startup_vbs_path_and_arguments(self):
        vbs_path = get_startup_vbs_path()
        assert vbs_path.name == "CurioLoopScheduler.vbs"
        assert "Startup" in str(vbs_path)
        if vbs_path.exists():
            content = vbs_path.read_text(encoding="utf-8")
            assert "manage_windows_task.py" in content
            assert "boot" in content

    def test_pythonw_path_resolution(self):
        pyw = get_pythonw_path()
        assert pyw.exists()
        assert "python" in pyw.name.lower()

    def test_query_task_status_returns_complete_fields(self):
        status = get_task_status()
        assert "task_name" in status
        assert "startup_vbs_registered" in status
        assert "schtasks_status" in status
        assert "is_daemon_running" in status
        assert "dashboard_running" in status
        assert "dashboard_url" in status
        assert status["schtasks_status"] == "NOT_REGISTERED"


# =============================================================================
# 7. Dashboard Integration, Trustworthy UI Badges & Diagnostics Endpoints
# =============================================================================
class TestDashboardIntegrationAndUIStatus:
    """Tests for trustworthy UI badges (no fake SCHEDULED) and read-only diagnostic endpoints."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_compute_ui_status_never_marks_simulated_as_scheduled(self):
        # Simulated record even with preview timestamps MUST stay SIMULATED
        v_sim = {
            "qc_passed": True,
            "publishing_status": "SCHEDULED",
            "youtube_status": "SIMULATED",
            "youtube_upload_id": "yt_sim_12345",
            "youtube_simulated": True,
            "scheduled_publish_at": "2026-11-10T07:00:00.000Z",
        }
        assert compute_ui_status(v_sim) == "SIMULATED"

        # Real API-confirmed upload -> SCHEDULED
        v_sched = {
            "qc_passed": True,
            "publishing_status": "SCHEDULED",
            "youtube_status": "SCHEDULED",
            "youtube_upload_id": "yt_real_123",
            "youtube_simulated": False,
            "schedule_confirmed": True,
            "scheduled_publish_at": "2026-11-10T07:00:00.000Z",
        }
        assert compute_ui_status(v_sched) == "SCHEDULED"

        # Real private upload without confirmed schedule -> UPLOADED_PRIVATE
        v_private = {
            "qc_passed": True,
            "publishing_status": "UPLOADED_PRIVATE",
            "youtube_status": "UPLOADED_PRIVATE",
            "youtube_upload_id": "nf_uztFNO8w",
            "youtube_simulated": False,
            "schedule_confirmed": False,
        }
        assert compute_ui_status(v_private) == "UPLOADED_PRIVATE"

        # Failed states
        assert compute_ui_status({"qc_passed": False, "production_status": "REJECTED_QC"}) == "FAILED"
        assert compute_ui_status({"qc_passed": True, "publishing_status": "PUBLISH_FAILED"}) == "FAILED"

    def test_dashboard_validate_and_dry_run_endpoints(self, client):
        res_val = client.get("/api/scheduler/validate")
        assert res_val.status_code == 200
        val_data = res_val.json()
        assert "valid" in val_data
        assert "checks" in val_data

        res_dry = client.get("/api/scheduler/dry-run")
        assert res_dry.status_code == 200
        dry_data = res_dry.json()
        assert dry_data["dry_run"] is True
        assert dry_data["read_only"] is True
        assert "slots" in dry_data

    def test_dashboard_scheduled_videos_excludes_simulated(self, client):
        res = client.get("/api/scheduled_videos")
        assert res.status_code == 200
        data = res.json()
        for v in data["videos"]:
            assert not v.get("youtube_simulated", False)
            assert not str(v.get("youtube_upload_id", "")).startswith("yt_sim_")

    def test_dashboard_task_status_and_retry_endpoints(self, client):
        headers = {"X-Studio-Auth": DASHBOARD_SECRET_KEY}
        res_ts = client.get("/api/scheduler/task_status")
        assert res_ts.status_code == 200
        assert "startup_vbs_registered" in res_ts.json()

        with patch("curiosity_engine.dashboard.app.scheduler.retry_slot") as mock_retry:
            res = client.post("/api/trigger/retry/slot1", headers=headers)
            assert res.status_code == 200
            assert "Slot 1" in res.json()["message"]
