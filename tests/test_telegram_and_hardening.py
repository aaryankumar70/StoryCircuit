"""Tests for Telegram notifications, 7-day OAuth lifecycle, safe reauth,
Windows dual startup isolation, and dashboard operational hardening.
All external HTTP/Google API calls and subprocesses are mocked.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from curiosity_engine import config
from curiosity_engine.dashboard import app as dashboard_app
from curiosity_engine.distribution.token_manager import TokenManager, _build_expiry_fields
from curiosity_engine.distribution.youtube_publisher import YouTubePublisher
from curiosity_engine.notifications.telegram_notifier import (
    TelegramNotifier,
    redact_telegram_secrets,
)
from curiosity_engine.runner.automation_state import AutomationStateManager
from curiosity_engine.runner.local_scheduler import LocalScheduler
from scripts import manage_windows_task as win_mgr


class _FakeResp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class TestTelegramNotifier:
    def test_redacts_tokens_and_never_persists_secrets(self, tmp_path):
        fake_tok = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz123456789"
        fake_chat = "987654321"
        raw_err = f"POST https://api.telegram.org/bot{fake_tok}/sendMessage failed for {fake_chat}"
        scrubbed = redact_telegram_secrets(raw_err, [fake_tok, fake_chat])
        assert fake_tok not in scrubbed
        assert fake_chat not in scrubbed

        calls = []

        def failing_post(url, json=None, timeout=15):
            calls.append(url)
            raise RuntimeError(f"Network down calling https://api.telegram.org/bot{fake_tok}/sendMessage")

        state_file = tmp_path / "notifications_state.json"
        notifier = TelegramNotifier(
            state_file=state_file,
            bot_token=fake_tok,
            chat_id=fake_chat,
            max_retries=2,
            sleep_fn=lambda _: None,
            http_post=failing_post,
        )
        res = notifier.notify_failure(
            failure_type="UPLOAD_FAILURE",
            title="Upload timeout",
            detail="Socket closed",
            video_id="video_20261110_slot1",
        )
        # Never raises to caller; queues cleanly for recovery
        assert res["sent"] is False
        assert res["status"] == "PENDING"
        assert fake_tok not in (res.get("error") or "")

        persisted_raw = state_file.read_text(encoding="utf-8")
        assert fake_tok not in persisted_raw
        assert fake_chat not in persisted_raw
        health = notifier.get_health()
        assert health["configured"] is True
        assert health["pending_count"] == 1
        assert health["status"] == "DEGRADED"

    def test_public_publication_gate_and_dedup(self, tmp_path):
        sent_payloads = []

        def ok_post(url, json=None, timeout=15):
            sent_payloads.append((url, json))
            return _FakeResp(200, {"ok": True, "result": {"message_id": len(sent_payloads)}})

        state_file = tmp_path / "notif.json"
        notifier = TelegramNotifier(
            state_file=state_file,
            bot_token="111111111:AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHH123",
            chat_id="5555555",
            sleep_fn=lambda _: None,
            http_post=ok_post,
        )

        # Must NEVER notify on private upload / schedule
        priv = notifier.notify_publication_success(
            video_id="v1",
            title="Test Video",
            youtube_id="yt12345",
            published_at_ist="2026-11-10 20:30 IST",
            privacy_status="private",
        )
        assert priv["status"] == "SKIPPED_NOT_PUBLIC"
        assert len(sent_payloads) == 0

        # Notify ONLY when privacy_status == 'public'
        pub1 = notifier.notify_publication_success(
            video_id="v1",
            title="Test Video <Science & Space>",
            youtube_id="yt12345",
            published_at_ist="2026-11-10 20:30 IST",
            privacy_status="public",
        )
        assert pub1["sent"] is True
        assert len(sent_payloads) == 1
        assert "yt12345" in sent_payloads[0][1]["text"]
        assert "&lt;Science &amp; Space&gt;" in sent_payloads[0][1]["text"]

        # Repeated notification with same YouTube ID deduplicated
        pub2 = notifier.notify_publication_success(
            video_id="v1",
            title="Test Video",
            youtube_id="yt12345",
            published_at_ist="2026-11-10 20:31 IST",
            privacy_status="public",
        )
        assert pub2["status"] == "DEDUPED"
        assert len(sent_payloads) == 1

    def test_retries_and_restart_recovery_flush(self, tmp_path):
        attempts = {"count": 0}

        def flaky_then_ok(url, json=None, timeout=15):
            attempts["count"] += 1
            if attempts["count"] <= 2:
                return _FakeResp(503, {"ok": False, "description": "Service Unavailable"})
            return _FakeResp(200, {"ok": True})

        state_file = tmp_path / "notif_retry.json"
        # First instance fails persistently (max_retries=1)
        n1 = TelegramNotifier(
            state_file=state_file,
            bot_token="222222222:ZZZZYYYYXXXXWWWWVVVVUUUUTTTTSSSS123",
            chat_id="888888",
            max_retries=1,
            sleep_fn=lambda _: None,
            http_post=lambda url, json=None, timeout=15: _FakeResp(503, {"ok": False}),
        )
        res1 = n1.notify_daily_summary(
            date_str="2026-11-10",
            production_count=2,
            daily_limit=2,
            published_public_count=1,
            scheduled_pending_count=1,
            next_scheduled_ist="2026-11-11 12:30 IST",
            oauth_status="HEALTHY",
            oauth_reauth_ist="2026-11-17 14:00 IST",
        )
        assert res1["status"] == "PENDING"

        # New instance after restart flushes pending queue (including retry backoff recovery)
        n2 = TelegramNotifier(
            state_file=state_file,
            bot_token="222222222:ZZZZYYYYXXXXWWWWVVVVUUUUTTTTSSSS123",
            chat_id="888888",
            max_retries=3,
            sleep_fn=lambda _: None,
            http_post=flaky_then_ok,
        )
        flushed = n2.flush_pending_events()
        assert flushed["flushed"] == 1
        assert flushed["remaining"] == 0
        assert n2.get_health()["status"] == "HEALTHY"


class TestTokenManagerAndOAuthLifecycle:
    def test_seven_day_expiry_warning_calculation(self):
        now = datetime(2026, 11, 17, 1, 0, 0, tzinfo=timezone.utc)
        # Authorized 6 days 12 hours ago -> 12h remaining -> warning_24h_due True
        auth_dt = now - timedelta(days=6, hours=12)
        fields = _build_expiry_fields(auth_dt.isoformat(), now_utc=now)
        assert fields["warning_24h_due"] is True
        assert 11.5 <= fields["hours_until_expiry"] <= 12.5
        assert fields["expiry_policy"] == "TESTING_7_DAYS"
        assert "IST" in fields["estimated_reauth_date_ist"]

        # Freshly authorized -> warning_24h_due False
        fresh = _build_expiry_fields(now.isoformat(), now_utc=now)
        assert fresh["warning_24h_due"] is False
        assert fresh["hours_until_expiry"] == 168.0

    def test_oauth_pause_and_resume_preserves_prior_state(self, tmp_path):
        mgr = AutomationStateManager(tmp_path / "automation_state.json")
        assert mgr.is_enabled() is True

        pause = mgr.pause_for_oauth("invalid_grant: token expired")
        assert pause["paused"] is True
        assert pause["prior_enabled"] is True
        assert mgr.is_enabled() is False

        resumed = mgr.resume_after_oauth()
        assert resumed is True
        assert mgr.is_enabled() is True
        assert mgr.get_oauth_pause()["paused"] is False

        # Respect user manual pause even after OAuth recovery
        mgr.set_enabled(False)
        mgr.pause_for_oauth("revoked")
        resumed2 = mgr.resume_after_oauth()
        assert resumed2 is False
        assert mgr.is_enabled() is False

    def test_env_hot_reload_updates_youtube_publisher(self, tmp_path, monkeypatch):
        fake_env = tmp_path / ".env"
        fake_env.write_text(
            "YOUTUBE_CLIENT_ID=cid_1\n"
            "YOUTUBE_CLIENT_SECRET=sec_1\n"
            "YOUTUBE_REFRESH_TOKEN=1//old_refresh_token\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(config, "ENV_FILE", fake_env)
        monkeypatch.setattr(config, "_LAST_ENV_STATE", None)
        monkeypatch.setenv("YOUTUBE_CLIENT_ID", "cid_1")
        monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "sec_1")
        monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "1//old_refresh_token")

        pub = YouTubePublisher(mode="simulation")
        assert pub.refresh_token == "1//old_refresh_token"

        fake_env.write_text(
            "YOUTUBE_CLIENT_ID=cid_1\n"
            "YOUTUBE_CLIENT_SECRET=sec_1\n"
            "YOUTUBE_REFRESH_TOKEN=1//new_refresh_token_999\n",
            encoding="utf-8",
        )
        # Ensure mtime differs on fast filesystems
        import os
        st = fake_env.stat()
        os.utime(fake_env, (st.st_atime, st.st_mtime + 5))

        changed = pub.refresh_credentials_if_changed()
        assert changed is True
        assert pub.refresh_token == "1//new_refresh_token_999"

    def test_verify_scheduled_publications_public_only_and_skips_test_id(self, tmp_path, monkeypatch):
        from curiosity_engine.runner import local_scheduler as ls_mod

        fake_videos = {
            "N3QUKd0u71U": None,  # Non-production test ID must never be checked
            "realPubId": {
                "video_id": "realPubId",
                "title": "Public Confirmed",
                "privacy_status": "public",
                "upload_status": "processed",
                "publish_at": None,
                "rejection_reason": None,
            },
            "stillPrivId": {
                "video_id": "stillPrivId",
                "title": "Delayed Video",
                "privacy_status": "private",
                "upload_status": "processed",
                "publish_at": "2026-11-10T07:00:00Z",
                "rejection_reason": None,
            },
        }
        past_utc = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        records = [
            {
                "video_id": "test_non_prod",
                "target_date": "2026-11-09",
                "youtube_upload_id": "N3QUKd0u71U",
                "youtube_simulated": False,
                "scheduled_publish_at": past_utc,
                "is_test": True,
            },
            {
                "video_id": "video_20261110_slot1",
                "target_date": "2026-11-10",
                "slot_index": 1,
                "topic": "Deep Ocean Pressure",
                "youtube_upload_id": "realPubId",
                "youtube_simulated": False,
                "scheduled_publish_at": past_utc,
                "youtube_privacy_status": "private",
                "publishing_status": "SCHEDULED",
            },
            {
                "video_id": "video_20261110_slot2",
                "target_date": "2026-11-10",
                "slot_index": 2,
                "topic": "Space Gyroscopes",
                "youtube_upload_id": "stillPrivId",
                "youtube_simulated": False,
                "scheduled_publish_at": past_utc,
                "youtube_privacy_status": "private",
                "publishing_status": "SCHEDULED",
            },
        ]

        saved_records = {}
        fake_db = MagicMock()
        fake_db.get_all_videos.return_value = records
        fake_db.save_video_record.side_effect = lambda vid, data: saved_records.__setitem__(vid, dict(data))

        sent_events = []
        notifier = TelegramNotifier(
            state_file=tmp_path / "notif_pub.json",
            bot_token="333333333:AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHH123",
            chat_id="777777",
            sleep_fn=lambda _: None,
            http_post=lambda url, json=None, timeout=15: sent_events.append(json) or _FakeResp(200, {"ok": True}),
        )

        fake_pub = MagicMock()
        fake_pub.service = object()
        fake_pub.get_video_status.side_effect = lambda yt_id: fake_videos.get(yt_id)

        monkeypatch.setattr(ls_mod, "YOUTUBE_PUBLISHING_MODE", "live")
        monkeypatch.setattr(ls_mod, "db", fake_db)
        monkeypatch.setattr(ls_mod, "youtube_publisher", fake_pub)
        monkeypatch.setattr(ls_mod, "get_telegram_notifier", lambda: notifier)
        monkeypatch.setattr(ls_mod, "automation_state", AutomationStateManager(tmp_path / "auto.json"))

        sched = LocalScheduler(lock_file=tmp_path / ".lock", state_file=tmp_path / "sched.json")
        res = sched.verify_scheduled_publications()

        assert res["checked"] == 2  # Test ID N3QUKd0u71U skipped
        assert res["confirmed_public"] == 1
        assert res["missed"] == 1
        assert saved_records["video_20261110_slot1"]["publishing_status"] == "PUBLISHED"
        assert saved_records["video_20261110_slot1"]["youtube_privacy_status"] == "public"
        assert len(sent_events) == 2  # 1 public publication + 1 missed alert


class TestDashboardHardeningEndpoints:
    def test_reauthorize_requires_auth_and_blocks_concurrent_runs(self, tmp_path, monkeypatch):
        lock_file = tmp_path / ".reauth.lock"
        status_file = tmp_path / "reauth_status.json"
        monkeypatch.setattr(dashboard_app, "REAUTH_LOCK_FILE", lock_file)
        monkeypatch.setattr(dashboard_app, "REAUTH_STATUS_FILE", status_file)

        client = TestClient(dashboard_app.app)
        unauth = client.post("/api/oauth/reauthorize")
        assert unauth.status_code == 403

        # Simulate already-active reauthorization lock owned by live PID (os.getpid())
        import os
        lock_file.write_text(str(os.getpid()), encoding="utf-8")
        conflict = client.post(
            "/api/oauth/reauthorize",
            headers={"X-Studio-Auth": dashboard_app.DASHBOARD_SECRET_KEY},
        )
        assert conflict.status_code == 409

    def test_logs_tail_whitelist_and_secret_redaction(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dashboard_app, "DATA_DIR", tmp_path)
        dash_log = tmp_path / "dashboard.log"
        dash_log.write_text(
            "INFO Server running on 127.0.0.1:8000\n"
            "DEBUG leaked url https://api.telegram.org/bot123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456/sendMessage\n"
            "DEBUG refresh 1//09SecretRefreshTokenXYZ\n",
            encoding="utf-8",
        )
        client = TestClient(dashboard_app.app)
        bad = client.get("/api/logs/tail?source=secret_file")
        assert bad.status_code == 400

        ok = client.get("/api/logs/tail?source=dashboard&lines=10")
        assert ok.status_code == 200
        body = ok.json()
        joined = "\n".join(body["lines"])
        assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456" not in joined
        assert "1//09SecretRefreshTokenXYZ" not in joined
        assert "127.0.0.1:8000" in joined

    def test_status_and_notifications_include_operational_status(self):
        client = TestClient(dashboard_app.app)
        st = client.get("/api/status").json()
        ops = st.get("operational_status")
        assert isinstance(ops, dict)
        for key in (
            "scheduler_running",
            "dashboard_health",
            "youtube_auth_health",
            "next_scheduled_video",
            "todays_production_count",
            "telegram_health",
            "last_successful_publication",
            "last_failure",
        ):
            assert key in ops

        notif = client.get("/api/notifications")
        assert notif.status_code == 200
        assert "status" in notif.json()


class TestWindowsDualStartupManager:
    def test_boot_isolates_scheduler_failure_from_dashboard(self, monkeypatch):
        monkeypatch.setattr(win_mgr, "start_daemon_background", MagicMock(side_effect=RuntimeError("sched boom")))
        monkeypatch.setattr(win_mgr, "start_dashboard_background", MagicMock(return_value={"success": True, "pid": 4321}))
        monkeypatch.setattr(win_mgr, "_append_startup_log", lambda *_: None)

        res = win_mgr.boot_all()
        assert res["success"] is False
        assert res["scheduler"]["success"] is False
        assert res["dashboard"]["success"] is True

    def test_start_dashboard_skips_when_port_already_open(self, tmp_path, monkeypatch):
        monkeypatch.setattr(win_mgr, "DASHBOARD_LOCK_FILE", tmp_path / ".dashboard.lock")
        monkeypatch.setattr(win_mgr, "DASHBOARD_LOG_FILE", tmp_path / "dashboard.log")
        monkeypatch.setattr(win_mgr, "STARTUP_LOG_FILE", tmp_path / "startup.log")
        monkeypatch.setattr(win_mgr, "is_port_open", lambda host, port, timeout=0.8: True)

        popen_mock = MagicMock()
        monkeypatch.setattr(win_mgr.subprocess, "Popen", popen_mock)

        res = win_mgr.start_dashboard_background()
        assert res["success"] is True
        assert res["already_running"] is True
        assert popen_mock.call_count == 0

    def test_start_dashboard_uses_pythonw_redirected_logs_and_no_colors(self, tmp_path, monkeypatch):
        monkeypatch.setattr(win_mgr, "DASHBOARD_LOCK_FILE", tmp_path / ".dashboard.lock")
        log_path = tmp_path / "dashboard.log"
        monkeypatch.setattr(win_mgr, "DASHBOARD_LOG_FILE", log_path)
        monkeypatch.setattr(win_mgr, "STARTUP_LOG_FILE", tmp_path / "startup.log")
        monkeypatch.setattr(win_mgr, "is_port_open", MagicMock(side_effect=[False, True]))

        fake_proc = SimpleNamespace(pid=9988, poll=lambda: None)
        popen_mock = MagicMock(return_value=fake_proc)
        monkeypatch.setattr(win_mgr.subprocess, "Popen", popen_mock)

        res = win_mgr.start_dashboard_background()
        assert res["success"] is True
        assert res["already_running"] is False
        assert res["pid"] == 9988

        args, kwargs = popen_mock.call_args
        cmd = args[0]
        assert "uvicorn" in cmd
        assert "--no-use-colors" in cmd
        assert kwargs["stdout"] is not None
        assert kwargs["stderr"] is not None
        assert (tmp_path / ".dashboard.lock").read_text(encoding="utf-8").strip() == "9988"
