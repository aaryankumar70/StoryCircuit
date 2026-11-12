"""Comprehensive tests for Autonomous Production Watchdog, Renderer Stall Guard,
Content Quality & Novelty, Metadata Hygiene, Hashtags, Telegram Alerts,
and Honest YouTube Performance Auditing.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from curiosity_engine.content.description_generator import (
    DescriptionGenerator,
    generate_youtube_title,
    recommend_hashtags,
    validate_no_external_links,
)
from curiosity_engine.content.scriptwriter import (
    improve_script_quality,
    score_script_quality,
)
from curiosity_engine.content.topic_discovery import (
    compute_topic_similarity,
    evaluate_topic_candidate,
    is_near_duplicate_topic,
    score_topic_details,
)
from curiosity_engine.distribution.youtube_analytics import YouTubePerformanceTracker
from curiosity_engine.distribution.youtube_publisher import YouTubePublisher
from curiosity_engine.notifications.telegram_notifier import TelegramNotifier
from curiosity_engine.production.renderer import _run_subprocess_logged
from curiosity_engine.runner.progress_tracker import build_slot_progress_snapshot
from curiosity_engine.runner.watchdog import (
    ProductionWatchdog,
    WatchdogConfig,
    WorkerLockError,
    acquire_slot_worker_lock,
    classify_failure,
    inspect_slot_worker,
    release_slot_worker_lock,
)
from curiosity_engine.state.db import DatabaseClient


# ---------------------------------------------------------------------------
# 1. Renderer Stall Guard & Inside-Out Regression Check
# ---------------------------------------------------------------------------
def test_inside_out_scenes_no_undefined_arm_or_squint():
    scenes_path = Path("d:/yt/templates/inside-out/src/core/scenes.js")
    src = scenes_path.read_text(encoding="utf-8")
    assert "K.ARM.chin" not in src
    assert "squint" not in src
    assert "K.ARM.mouth" in src


def test_renderer_subprocess_aborts_on_stall(tmp_path: Path):
    log_path = tmp_path / "stall.log"
    with pytest.raises(RuntimeError, match="stalled with no progress"):
        _run_subprocess_logged(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            cwd=tmp_path,
            env=os.environ.copy(),
            log_path=log_path,
            timeout_sec=10,
            step_name="Test render",
            stall_timeout_sec=1,
        )


def test_renderer_subprocess_succeeds_cleanly(tmp_path: Path):
    log_path = tmp_path / "ok.log"
    _run_subprocess_logged(
        [sys.executable, "-c", "print('frame 1/1 done')"],
        cwd=tmp_path,
        env=os.environ.copy(),
        log_path=log_path,
        timeout_sec=10,
        step_name="Test ok",
        stall_timeout_sec=5,
    )
    assert "frame 1/1 done" in log_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 2. Watchdog: Stalls, Live Worker Protection, Missed Slots, Backoff, Locks
# ---------------------------------------------------------------------------
def test_watchdog_detects_crashed_worker_and_recovers(tmp_path: Path, monkeypatch):
    fake_db = DatabaseClient(custom_file=tmp_path / "db.json")

    now_ist = datetime(2026, 11, 12, 13, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    vid1 = "video_20261112_slot1"
    fake_db.save_video_record(vid1, {
        "video_id": vid1,
        "slot_index": 1,
        "target_date": "2026-11-12",
        "topic": "Why Ears Ring",
        "production_status": "ASSETS_READY",
        "stage_progress": {"active_stage": "preparing_visuals", "stage_started_at": {"preparing_visuals": (now_ist - timedelta(minutes=20)).astimezone(timezone.utc).isoformat()}},
    })
    # Completed slot 2 should NEVER be touched
    vid2 = "video_20261112_slot2"
    fake_db.save_video_record(vid2, {
        "video_id": vid2,
        "slot_index": 2,
        "target_date": "2026-11-12",
        "topic": "Completed Story",
        "production_status": "COMPLETED",
        "qc_passed": True,
        "schedule_confirmed": True,
        "scheduled_publish_at": "2026-11-13T15:00:00.000Z",
        "publishing_status": "SCHEDULED",
    })

    # Write a dead PID stale lock for slot 1
    lpath = tmp_path / ".worker_slot1.lock"
    lpath.write_text('{"pid": 999999, "slot_index": 1, "video_id": "video_20261112_slot1"}', encoding="utf-8")

    alerts: List[str] = []
    monkeypatch.setattr(ProductionWatchdog, "_notify", lambda self, m, **kw: alerts.append(m))

    wd = ProductionWatchdog(
        state_file=tmp_path / "wd.json",
        watchdog_config=WatchdogConfig(backoff_schedule_sec=(0, 0, 0)),
        db_client=fake_db,
    )
    recovered_slots: List[int] = []
    res = wd.run_health_check(
        now_ist=now_ist,
        automation_enabled=True,
        oauth_healthy=True,
        daily_record={"slot2": {"scheduled_status": "SCHEDULED"}},
        recover_fn=lambda slot, date_str, reason: recovered_slots.append(slot) or True,
        output_dir=tmp_path,
        data_dir=tmp_path,
    )
    assert recovered_slots == [1]
    assert "notify_production_stalled" in alerts
    assert "notify_recovery_started" in alerts
    assert not lpath.exists()
    assert res["status"] == "RECOVERING"


def test_watchdog_protects_actively_rendering_live_worker(tmp_path: Path):
    fake_db = DatabaseClient(custom_file=tmp_path / "db.json")

    now_ist = datetime(2026, 11, 12, 11, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    vid1 = "video_20261112_slot1"
    fake_db.save_video_record(vid1, {
        "video_id": vid1,
        "slot_index": 1,
        "target_date": "2026-11-12",
        "production_status": "RENDERING",
        "stage_progress": {
            "active_stage": "rendering_video",
            "stage_started_at": {"rendering_video": (now_ist - timedelta(minutes=25)).astimezone(timezone.utc).isoformat()},
        },
    })
    # Live current process owns lock and render.log just wrote fresh frames
    lpath = tmp_path / ".worker_slot1.lock"
    acquire_slot_worker_lock(1, vid1, lock_path=lpath)
    rlog = tmp_path / vid1 / "logs" / "render.log"
    rlog.parent.mkdir(parents=True, exist_ok=True)
    rlog.write_text("400/1500 frames rendered\n", encoding="utf-8")

    try:
        wd = ProductionWatchdog(state_file=tmp_path / "wd.json", db_client=fake_db)
        called: List[int] = []
        res = wd.run_health_check(
            now_ist=now_ist,
            automation_enabled=True,
            recover_fn=lambda slot, d, r: called.append(slot) or True,
            output_dir=tmp_path,
            data_dir=tmp_path,
        )
        assert called == []
        assert lpath.exists()
        assert res["status"] == "HEALTHY"
    finally:
        release_slot_worker_lock(1, vid1, lock_path=lpath)


def test_worker_lock_prevents_duplicate_slot_job(tmp_path: Path):
    lpath = tmp_path / ".worker_slot2.lock"
    # Fake a live sibling process by mocking is_pid_alive
    acquire_slot_worker_lock(2, "video_20261112_slot2", lock_path=lpath)
    try:
        # Modify lock PID to another active PID
        other_pid = os.getpid() + 100000
        lpath.write_text(f'{{"pid": {other_pid}, "slot_index": 2, "video_id": "video_20261112_slot2"}}', encoding="utf-8")
        # Override is_pid_alive inside watchdog module temporarily
        import curiosity_engine.runner.watchdog as wd_mod
        orig = wd_mod.is_pid_alive
        wd_mod.is_pid_alive = lambda p: p == other_pid
        try:
            with pytest.raises(WorkerLockError):
                acquire_slot_worker_lock(2, "video_20261112_slot2", lock_path=lpath)
        finally:
            wd_mod.is_pid_alive = orig
    finally:
        lpath.unlink(missing_ok=True)


def test_watchdog_triggers_missed_slots_and_enforces_max_3_cycles(tmp_path: Path, monkeypatch):
    fake_db = DatabaseClient(custom_file=tmp_path / "db.json")

    alerts: List[str] = []
    monkeypatch.setattr(ProductionWatchdog, "_notify", lambda self, m, **kw: alerts.append(m))

    now_ist = datetime(2026, 11, 12, 21, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    wd = ProductionWatchdog(
        state_file=tmp_path / "wd.json",
        watchdog_config=WatchdogConfig(max_recovery_cycles=3, backoff_schedule_sec=(120, 300, 600)),
        db_client=fake_db,
    )

    # First check after 20:30 window -> detects BOTH missed slots & attempts Cycle 1
    attempts: List[int] = []
    wd.run_health_check(
        now_ist=now_ist,
        automation_enabled=True,
        recover_fn=lambda slot, d, r: attempts.append(slot) or False,
        output_dir=tmp_path,
        data_dir=tmp_path,
    )
    assert sorted(attempts) == [1, 2]

    # Immediately 10s later -> backoff (120s) prevents premature hammer!
    attempts.clear()
    wd.run_health_check(
        now_ist=now_ist + timedelta(seconds=10),
        automation_enabled=True,
        recover_fn=lambda slot, d, r: attempts.append(slot) or False,
        output_dir=tmp_path,
        data_dir=tmp_path,
    )
    assert attempts == []

    # After backoff cycle 2 & 3 -> reaches permanent failure & stops retrying
    fake_db.save_video_record("video_20261112_slot1", {"video_id": "video_20261112_slot1", "production_status": "FAILED", "error": "Visual check failed"})
    fake_db.save_video_record("video_20261112_slot2", {"video_id": "video_20261112_slot2", "production_status": "FAILED", "error": "Visual check failed"})
    wd.run_health_check(now_ist=now_ist + timedelta(minutes=3), recover_fn=lambda s, d, r: attempts.append(s) or False, output_dir=tmp_path, data_dir=tmp_path)
    wd.run_health_check(now_ist=now_ist + timedelta(minutes=10), recover_fn=lambda s, d, r: attempts.append(s) or False, output_dir=tmp_path, data_dir=tmp_path)

    assert "notify_production_permanently_failed" in alerts
    summary = wd.get_health_summary("2026-11-12")
    assert summary["slots"]["slot1"]["permanently_failed"] is True
    assert summary["slots"]["slot1"]["recovery_cycles"] == 3

    # 4th check does NOT burn more attempts
    attempts.clear()
    wd.run_health_check(now_ist=now_ist + timedelta(minutes=30), recover_fn=lambda s, d, r: attempts.append(s) or False, output_dir=tmp_path, data_dir=tmp_path)
    assert attempts == []


def test_watchdog_preserves_retry_budget_on_oauth_and_api_outages(tmp_path: Path):
    fake_db = DatabaseClient(custom_file=tmp_path / "db.json")
    vid1 = "video_20261112_slot1"
    fake_db.save_video_record(vid1, {
        "video_id": vid1,
        "slot_index": 1,
        "target_date": "2026-11-12",
        "production_status": "COMPLETED",
        "qc_passed": True,
        "youtube_error": "invalid_grant: Token has been expired or revoked.",
    })
    (tmp_path / f"{vid1}.mp4").write_bytes(b"fake" * 100)

    wd = ProductionWatchdog(state_file=tmp_path / "wd.json", db_client=fake_db)
    now_ist = datetime(2026, 11, 12, 14, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    called: List[int] = []
    res = wd.run_health_check(
        now_ist=now_ist,
        automation_enabled=True,
        oauth_healthy=False,
        oauth_status="REVOKED_OR_EXPIRED",
        recover_fn=lambda s, d, r: called.append(s) or False,
        output_dir=tmp_path,
        data_dir=tmp_path,
    )
    assert called == []
    assert res["status"] == "WAITING_DEPENDENCY"
    assert wd.get_health_summary("2026-11-12")["slots"]["slot1"]["recovery_cycles"] == 0
    assert classify_failure("HttpError 503 Service Unavailable") == "api_outage"


# ---------------------------------------------------------------------------
# 3. Telegram Lifecycle Alerts & Progress Snapshots
# ---------------------------------------------------------------------------
def test_telegram_new_watchdog_lifecycle_alerts(tmp_path: Path):
    sent_payloads: List[Dict[str, Any]] = []

    def fake_post(url, json=None, timeout=15):
        sent_payloads.append(json or {})
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"ok": True, "result": {"message_id": len(sent_payloads)}}
        return resp

    notifier = TelegramNotifier(
        bot_token="123456:FAKE_TOKEN_XYZ",
        chat_id="999999999",
        state_file=tmp_path / "tg.json",
        http_post=fake_post,
    )
    r1 = notifier.notify_production_started("video_20261112_slot1", "2026-11-12", 1, "12:30 PM IST", "Why Ears Ring", started_at_ist="2026-11-12 10:00 IST")
    r2 = notifier.notify_production_stalled("video_20261112_slot1", 1, "rendering_video", "Render made no log progress")
    r3 = notifier.notify_recovery_started("video_20261112_slot1", 1, "Stalled worker", 1, 3, "Restarting Slot 1")
    r4 = notifier.notify_production_permanently_failed("video_20261112_slot1", 1, "Why Ears Ring", "Visual check failed", 3, 3, slot_missed=True)

    assert all(r.get("sent") for r in (r1, r2, r3, r4))
    all_text = "\n".join(p.get("text", "") for p in sent_payloads)
    assert "video_20261112_slot1" in all_text
    assert "Production Stalled" in all_text
    assert "Automatic Recovery Started" in all_text
    assert "Permanently Failed" in all_text


def test_progress_snapshot_surfaces_watchdog_states():
    snap = build_slot_progress_snapshot(
        slot_index=1,
        video_rec={"video_id": "video_20261112_slot1", "production_status": "ASSETS_READY", "topic": "T"},
        sched_slot_rec={},
        target_time_ist="12:30 PM IST",
        watchdog_slot={
            "stalled": True,
            "recovery_cycles": 1,
            "max_cycles": 3,
            "last_error": "No progress for 420s",
            "last_recovery_action": "Cycle 1/3: stalled",
        },
    )
    assert snap["phase"] == "stalled"
    assert snap["stage"] == "Stalled"
    assert snap["recovery_cycles"] == 1


# ---------------------------------------------------------------------------
# 4. Content Novelty, Script Scoring, Link Removal & Honest Hashtags
# ---------------------------------------------------------------------------
def test_topic_similarity_prevents_heracleion_repeat_and_rejects_cliches():
    sim = compute_topic_similarity(
        "The sunken Egyptian port of Heracleion",
        "The sunken Egyptian port city of Thonis-Heracleion",
    )
    assert sim >= 0.50
    is_dup, matched = is_near_duplicate_topic(
        "The sunken Egyptian port of Heracleion",
        ["The sunken Egyptian port city of Thonis-Heracleion"],
    )
    assert is_dup and matched

    ok_bad, reason = evaluate_topic_candidate({
        "topic": "Did you know octopuses have three hearts?",
        "scores": {"factual_reliability": 10, "hook_strength": 9},
    })
    assert not ok_bad
    assert "Did you know" in reason

    details = score_topic_details({"scores": {"originality": 9, "hook_strength": 9.5}})
    assert len(details) >= 8


def test_script_quality_scoring_and_auto_improvement():
    weak_script = {
        "title": "DID YOU KNOW THIS",
        "lines": [
            {"text": "Did you know glass behaves strangely in old windows?", "gap": 0.25},
            {"text": "People often assume glass slowly flows downward over centuries inside medieval cathedrals because panes look thicker below.", "gap": 0.25},
            {"text": "That popular classroom myth actually comes from how old crowns were spun before float glass existed.", "gap": 0.25},
            {"text": "Scientists calculated it would take trillions of years for solid glass molecules to sag cleanly.", "gap": 0.25},
        ],
    }
    raw_score = score_script_quality(weak_script)
    assert "opening_hook_strength" in raw_score["metrics"]
    assert raw_score["metrics"]["opening_hook_strength"] < 6.5

    improved, new_score = improve_script_quality(weak_script)
    assert not improved["lines"][0]["text"].lower().startswith("did you know")
    assert new_score["metrics"]["opening_hook_strength"] > raw_score["metrics"]["opening_hook_strength"]


def test_title_strips_hashtag_stuffing_and_links_never_enter_youtube(tmp_path: Path):
    dirty_title = "What If a Solar Superstorm Hits Today?  #Biology #HumanBody #Neuroscience #ScienceFacts #Shorts"
    clean = generate_youtube_title(dirty_title, duration_sec=32.0)
    assert "#Biology" not in clean
    assert "#HumanBody" not in clean
    assert clean.endswith("#Shorts")
    assert clean.count("#") == 1

    gen = DescriptionGenerator()
    out = gen.generate(
        topic="The 1859 Carrington solar superstorm",
        category="Science",
        script_data={
            "title": "What If a Solar Superstorm Hits Today?",
            "lines": [{"text": "In 1859, auroras burned bright enough for gold miners to cook breakfast by sky light."}],
        },
        sources=["https://nasa.gov/carrington"],
    )
    ok_links, _ = validate_no_external_links(out["full_description"])
    assert ok_links
    assert "https://" not in out["full_description"]
    assert 3 <= len(out["hashtags"]) <= 5

    # Publisher defense-in-depth also strips leaked URLs & extra hashtags in title & snippet
    mp4 = tmp_path / "dummy.mp4"
    mp4.write_bytes(b"0" * 128)
    pub = YouTubePublisher(client_id="cid", client_secret="sec", refresh_token="ref", mode="live")
    pub.service = MagicMock()
    pub.reconcile_existing_upload = lambda *a, **kw: None
    mock_req = MagicMock()
    mock_req.next_chunk.return_value = (None, {"id": "yt_clean_123"})
    pub.service.videos.return_value.insert.return_value = mock_req
    res = pub.upload_short(
        video_path=mp4,
        title="The Sunken Port #History #AncientEgypt #Shorts",
        description="Read more at https://reddit.com/r/history and /u/testuser right now",
        tags=["History", "Heracleion"],
        force_mode="live",
    )
    insert_kwargs = pub.service.videos.return_value.insert.call_args.kwargs
    sent_snippet = insert_kwargs["body"]["snippet"]
    assert "https://" not in sent_snippet["description"]
    assert "/u/" not in sent_snippet["description"]
    assert "#AncientEgypt" not in sent_snippet["title"]
    assert "#AncientEgypt" not in res["title"]


def test_hashtags_differentiate_verified_trends_from_recommendations():
    no_trend = recommend_hashtags(
        topic="Juliane Koepcke Amazon rainforest survival",
        category="Survival",
        trend_signals=None,
    )
    assert no_trend["trend_evidence_available"] is False
    assert no_trend["evidence_mode"] == "recommended_no_trend_data"
    assert 3 <= len(no_trend["hashtags"]) <= 5

    with_trend = recommend_hashtags(
        topic="Juliane Koepcke Amazon rainforest survival",
        category="Survival",
        trend_signals={"observed": True, "trending_tags": ["#Amazon", "#Survival", "#UnrelatedGaming"]},
    )
    assert with_trend["trend_evidence_available"] is True
    assert with_trend["evidence_mode"] == "trend_informed"
    assert "#Amazon" in with_trend["hashtags"]
    assert "#UnrelatedGaming" not in with_trend["hashtags"]


# ---------------------------------------------------------------------------
# 5. Honest YouTube Performance Audit (Small Sample + Scope Limitations)
# ---------------------------------------------------------------------------
def test_youtube_performance_audit_is_honest_about_missing_analytics_scope_and_sample_size(tmp_path: Path, monkeypatch):
    import curiosity_engine.distribution.youtube_analytics as ya_mod

    monkeypatch.setattr(
        ya_mod.token_manager,
        "get_summary",
        lambda: {
            "youtube": {
                "scopes": [
                    "https://www.googleapis.com/auth/youtube.readonly",
                    "https://www.googleapis.com/auth/youtube.upload",
                ]
            }
        },
    )

    mock_service = MagicMock()
    mock_service.channels.return_value.list.return_value.execute.return_value = {
        "items": [{"id": "UC123", "snippet": {"title": "CurioLoop"}, "statistics": {"viewCount": "20", "subscriberCount": "0", "videoCount": "4"}}]
    }
    mock_service.videos.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "y-54SJ4MCFM",
                "snippet": {"title": "The Sunken Egyptian Port of Heracleion #Shorts", "description": "Port city", "categoryId": "27", "tags": ["History"], "publishedAt": "2026-11-11T07:00:06Z"},
                "contentDetails": {"duration": "PT27S"},
                "status": {"privacyStatus": "public"},
                "statistics": {"viewCount": "1", "likeCount": "1", "commentCount": "0"},
            },
            {
                "id": "3jsrFlsAKuc",
                "snippet": {"title": "The Sunken Egyptian Port of Heracleion #Shorts #History #AncientEgypt #Shorts", "description": "Port city", "categoryId": "27", "tags": ["History"], "publishedAt": "2026-11-11T15:00:38Z"},
                "contentDetails": {"duration": "PT27S"},
                "status": {"privacyStatus": "public"},
                "statistics": {"viewCount": "0", "likeCount": "0", "commentCount": "0"},
            },
            {
                "id": "X4hf3o7Nuqk",
                "snippet": {"title": "What If a Solar Superstorm Hits Today?  #Biology #HumanBody #Shorts", "description": "Ever wonder why absolute silence has a sound?", "categoryId": "27", "tags": ["Carrington"], "publishedAt": "2026-11-12T07:00:36Z"},
                "contentDetails": {"duration": "PT32S"},
                "status": {"privacyStatus": "public"},
                "statistics": {"viewCount": "3", "likeCount": "0", "commentCount": "0"},
            },
        ]
    }
    fake_pub = MagicMock()
    fake_pub.service = mock_service

    tracker = YouTubePerformanceTracker(state_file=tmp_path / "perf.json")
    audit = tracker.audit_uploaded_videos(fake_pub, video_ids=["y-54SJ4MCFM", "3jsrFlsAKuc", "X4hf3o7Nuqk"])

    assert audit["analytics_api_available"] is False
    assert "yt-analytics.readonly" in audit["missing_analytics_scopes"][0]
    assert "averageViewDuration" in audit["unavailable_metrics"]
    assert audit["small_sample_warning"] is True
    assert audit["auto_delete_permitted"] is False
    assert audit["videos"][1]["metadata_issues"]  # duplicate + hashtag title
    assert any("does not match" in iss for iss in audit["videos"][2]["metadata_issues"])
    assert audit["videos"][0]["impressions"] is None
    assert audit["videos"][0]["average_view_duration_sec"] is None


def test_dashboard_status_exposes_watchdog_without_secret_redaction_corruption():
    from fastapi.testclient import TestClient
    from curiosity_engine.dashboard.app import app

    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "watchdog" in body
    assert isinstance(body["watchdog"].get("slots"), dict)
    assert "slot_timeline" in body and len(body["slot_timeline"]) == 2
    for slot_snap in body["slot_timeline"]:
        assert "stage_id" in slot_snap
        assert slot_snap.get("recovery_cycles") is not None or "recovery_cycles" in body["watchdog"]["slots"]["slot1"]

