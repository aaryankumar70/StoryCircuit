"""Comprehensive regression & feature tests for CurioLoop Phase 3 upgrades:
1. 20-60s duration policy & audio/caption/timeline sync validation
2. Bounded automatic QC failure recovery (<=2 attempts), unchanged-hash skip, & exhaustion
3. Ethical Reddit discovery sanitization, topic quality gate, scriptwriter diversity, & scene directives
4. Safe automatic daily local video cleanup in Asia/Kolkata
5. Link-free YouTube titles, descriptions & separated metadata tags
6. Estimated YouTube quota tracker & honest sample-guarded analytics awareness
7. Expanded Telegram notification lifecycle events & dedup
8. Redesigned dashboard telemetry (/api/status, /api/storage, /api/analytics, UI assets)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from curiosity_engine.config import (
    MAX_DURATION_SEC,
    MAX_QC_RECOVERY_ATTEMPTS,
    MIN_DURATION_SEC,
    TARGET_DURATION_MAX_SEC,
    TARGET_DURATION_MIN_SEC,
)
from curiosity_engine.content.description_generator import (
    DescriptionGenerator,
    build_youtube_tags,
    generate_youtube_title,
    strip_external_links,
    validate_no_external_links,
)
from curiosity_engine.content.reddit_discovery import (
    RedditDiscoverySource,
    is_suitable_reddit_post,
    sanitize_reddit_text,
)
from curiosity_engine.content.scriptwriter import (
    assign_line_scenes,
    revise_script_for_duration,
    validate_script_quality,
    write_video_script,
)
from curiosity_engine.content.topic_discovery import evaluate_topic_candidate
from curiosity_engine.dashboard import app as dashboard_app
from curiosity_engine.distribution.youtube_analytics import (
    MIN_SAMPLE_FOR_INSIGHTS,
    YouTubePerformanceTracker,
)
from curiosity_engine.distribution.youtube_quota import YouTubeQuotaTracker
from curiosity_engine.notifications.telegram_notifier import TelegramNotifier
from curiosity_engine.quality.qc_gatekeeper import verify_project_sync, verify_video
from curiosity_engine.runner.local_scheduler import LocalScheduler
from curiosity_engine.runner.pipeline import (
    _compute_file_sha256,
    produce_single_video,
)
from curiosity_engine.runner.storage_cleanup import (
    cleanup_old_generated_videos,
    get_storage_summary,
)
from curiosity_engine.state.db import DatabaseClient

IST = ZoneInfo("Asia/Kolkata")


# =============================================================================
# 1. 20-60s Duration Bounds & Project Sync Validation
# =============================================================================
class TestDurationPolicyAndSync:
    def _mock_probe_and_loudness(self, duration_sec: float):
        probe_data = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": str(duration_sec)},
        }
        loudness_data = {
            "integrated_lufs": -16.0,
            "true_peak_db": -1.5,
            "lra": 5.0,
            "passed": True,
            "issues": [],
        }
        return probe_data, loudness_data

    @pytest.mark.parametrize("duration_sec,expected", [
        (19.5, False),
        (20.0, True),
        (30.0, True),
        (31.6, True),
        (60.0, True),
        (60.5, False),
    ])
    def test_duration_policy_accepts_20_to_60s_and_rejects_outside(self, tmp_path, duration_sec, expected):
        assert MIN_DURATION_SEC == 20.0
        assert MAX_DURATION_SEC == 60.0
        assert TARGET_DURATION_MIN_SEC == 25.0
        assert TARGET_DURATION_MAX_SEC == 45.0

        mp4 = tmp_path / "sample.mp4"
        mp4.write_bytes(b"0" * 150_000)
        probe_data, loud_data = self._mock_probe_and_loudness(duration_sec)

        with patch("curiosity_engine.quality.qc_gatekeeper.check_ffprobe_streams", return_value=probe_data), \
             patch("curiosity_engine.quality.qc_gatekeeper.measure_audio_loudness", return_value=loud_data), \
             patch("curiosity_engine.quality.qc_gatekeeper.check_black_frames", return_value=True):
            report = verify_video(mp4, {"duration": duration_sec, "sources": ["https://nasa.gov"]})

        assert report.passed is expected
        if expected:
            assert report.checks["within_preferred_target"] is (25.0 <= duration_sec <= 45.0)
        else:
            assert any("duration" in i.lower() or "out of range" in i.lower() for i in report.issues)

    def test_verify_project_sync_detects_caption_drift_and_empty_words(self, tmp_path):
        proj = tmp_path / "video_20261111_slot1"
        data_dir = proj / "data"
        data_dir.mkdir(parents=True)
        (data_dir / "narration.wav").write_bytes(b"R" * 12_000)
        (data_dir / "lines.json").write_text(json.dumps([{"text": "Hello world", "s": 0.0, "e": 2.0}]))
        # Captions extend 4s beyond rendered duration -> drift
        (data_dir / "words.json").write_text(json.dumps([
            {"w": "Hello", "s": 0.0, "e": 1.0},
            {"w": "world", "s": 31.0, "e": 34.5},
        ]))

        ok, issues, meta = verify_project_sync(proj, rendered_duration_sec=30.0)
        assert ok is False
        assert any("extend past video end" in i for i in issues)

        # Empty words list fails
        (data_dir / "words.json").write_text("[]")
        ok_empty, issues_empty, _ = verify_project_sync(proj, rendered_duration_sec=30.0)
        assert ok_empty is False
        assert any("empty" in i.lower() for i in issues_empty)


# =============================================================================
# 2. Automatic Bounded QC Recovery & Unchanged Hash Skip
# =============================================================================
class TestAutomaticQCRecovery:
    def test_qc_duration_exceeded_recovers_within_two_attempts(self, tmp_path):
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        out_dir = tmp_path / "output"
        out_dir.mkdir(parents=True)
        vid_id = "video_20261111_slot1"
        mp4 = out_dir / f"{vid_id}.mp4"
        mp4.write_bytes(b"initial-overlong-mp4-bytes")

        long_lines = [{"text": f"Sentence number {i} adds rich historical intrigue to the unfolding story.", "scene": "archive"} for i in range(12)]
        iso_db.save_video_record(vid_id, {
            "video_id": vid_id,
            "slot_index": 1,
            "target_date": "2026-11-11",
            "topic": "Secret Brass Calendar",
            "category": "History",
            "script": {"title": "Secret Brass Calendar", "lines": long_lines, "duration": 64.0, "sources": ["https://britannica.com"]},
            "youtube_description": "Link-free description body.",
        })

        qc_fail = MagicMock(passed=False, issues=["Duration 64.00s exceeds maximum 60.0s"], checks={"duration_sec": 64.0, "failure_categories": ["duration_exceeded"]})
        qc_fail.to_dict.return_value = {"passed": False, "checks": qc_fail.checks, "issues": qc_fail.issues}
        qc_pass = MagicMock(passed=True, issues=[], checks={"duration_sec": 38.5, "within_preferred_target": True})
        qc_pass.to_dict.return_value = {"passed": True, "checks": qc_pass.checks, "issues": []}

        fake_tg = MagicMock()

        def _fake_prep(topic, category, style=None, vid_id=vid_id, script_data=None, **kwargs):
            # Support positional prepare_project(video_id, script_data)
            pdir = out_dir / vid_id
            (pdir / "data").mkdir(parents=True, exist_ok=True)
            (pdir / "src").mkdir(parents=True, exist_ok=True)
            (pdir / "index.html").write_text("<html></html>")
            (pdir / "src" / "main.js").write_text("// ok")
            (pdir / "script.json").write_text("{}")
            (pdir / "data" / "narration.wav").write_bytes(b"W" * 12_000)
            (pdir / "data" / "lines.json").write_text("[]")
            (pdir / "data" / "words.json").write_text("[]")
            return pdir

        def _fake_render(p_dir, target_mp4, **kwargs):
            target_mp4.write_bytes(b"recovered-compact-38s-mp4-bytes")
            return target_mp4

        with patch("curiosity_engine.runner.pipeline.db", iso_db), \
             patch("curiosity_engine.runner.pipeline.OUTPUT_DIR", out_dir), \
             patch("curiosity_engine.runner.pipeline.validate_rendered_mp4", return_value={"duration": 38.5}), \
             patch("curiosity_engine.runner.pipeline.verify_video", side_effect=[qc_fail, qc_pass]), \
             patch("curiosity_engine.runner.pipeline.prepare_project", side_effect=_fake_prep), \
             patch("curiosity_engine.runner.pipeline.render_project_video", side_effect=_fake_render), \
             patch("curiosity_engine.notifications.telegram_notifier.get_telegram_notifier", return_value=fake_tg):

            res = produce_single_video(vid_id, {}, slot_index=1, target_date="2026-11-11")

        assert res["production_status"] == "COMPLETED"
        assert res["qc_passed"] is True
        assert res["qc_recovered"] is True
        assert res["recovery_attempts"] == 1
        assert len(res["qc_recovery_history"]) == 1
        assert res["qc_recovery_history"][0]["sha256_before"] != res["qc_recovery_history"][0]["sha256_after"]
        fake_tg.notify_qc_failed.assert_called_once()
        fake_tg.notify_qc_recovered.assert_called_once()

    def test_unchanged_failed_mp4_never_repeats_blind_qc_without_new_artifact(self, tmp_path):
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        out_dir = tmp_path / "output"
        out_dir.mkdir(parents=True)
        vid_id = "video_20261111_slot2"
        mp4 = out_dir / f"{vid_id}.mp4"
        mp4.write_bytes(b"exact-same-failed-mp4")
        same_hash = _compute_file_sha256(mp4)

        iso_db.save_video_record(vid_id, {
            "video_id": vid_id,
            "slot_index": 2,
            "target_date": "2026-11-11",
            "topic": "Broken Visuals",
            "category": "Science",
            "script": {"title": "Broken", "lines": [{"text": "Hook"}]},
            "youtube_description": "Clean description",
            "failed_mp4_sha256": same_hash,
            "recovery_attempts": 1,
            "qc_results": {"passed": False, "checks": {"failure_categories": ["visual_black_frames"]}, "issues": ["15 black frames"]},
            "error": "Prior QC failure",
        })

        qc_verify_mock = MagicMock()
        # Simulate recovery writing the exact same unchanged bytes -> rejected as unchanged_failed_output
        def _unchanged_prep(vid_arg, script_data=None, **kwargs):
            pdir = out_dir / vid_id
            pdir.mkdir(parents=True, exist_ok=True)
            return pdir

        def _unchanged_render(p_dir, target_mp4, **kwargs):
            target_mp4.write_bytes(b"exact-same-failed-mp4")
            return target_mp4

        with patch("curiosity_engine.runner.pipeline.db", iso_db), \
             patch("curiosity_engine.runner.pipeline.OUTPUT_DIR", out_dir), \
             patch("curiosity_engine.runner.pipeline.verify_video", qc_verify_mock), \
             patch("curiosity_engine.runner.pipeline.prepare_project", side_effect=_unchanged_prep), \
             patch("curiosity_engine.runner.pipeline.render_project_video", side_effect=_unchanged_render), \
             patch("curiosity_engine.notifications.telegram_notifier.get_telegram_notifier", return_value=MagicMock()):

            with pytest.raises(RuntimeError) as exc_info:
                produce_single_video(vid_id, {}, slot_index=2, target_date="2026-11-11")

        # Initial verify_video skipped on unchanged hash, AND post-recovery verify_video skipped because output SHA256 stayed identical!
        qc_verify_mock.assert_not_called()
        assert "rejected by QC" in str(exc_info.value)
        saved = iso_db.get_video_record(vid_id)
        assert saved["recovery_attempts"] == MAX_QC_RECOVERY_ATTEMPTS

        # Second invocation on scheduler sees exhausted recovery_attempts >= 2 + other slot scheduled -> stops auto-retry
        from curiosity_engine.runner.automation_state import AutomationStateManager
        iso_state = AutomationStateManager(state_path=tmp_path / "auto_state.json")
        iso_state.update_daily_record(
            "2026-11-11",
            {
                "slot1": {"scheduled_status": "SCHEDULED"},
                "slot2": {"video_id": vid_id, "generation_status": "FAILED", "error": "QC Failed"},
            },
        )
        sched = LocalScheduler(state_file=tmp_path / "s.json", lock_file=tmp_path / "l.lock")
        with patch("curiosity_engine.runner.local_scheduler.automation_state", iso_state), \
             patch("curiosity_engine.runner.local_scheduler.db", iso_db):
            assert sched._needs_retryable_work("2026-11-11") is False


# =============================================================================
# 3. Ethical Reddit Discovery, Storytelling Scriptwriter & Topic Evaluation
# =============================================================================
class TestContentIntelligenceAndStorytelling:
    def test_reddit_sanitization_removes_usernames_urls_and_subreddits(self):
        raw = "TIL u/space_nerd found out https://reddit.com/r/space/abc in r/space that Voyager's tape recorder still works!"
        clean = sanitize_reddit_text(raw)
        assert "http" not in clean.lower()
        assert "u/space_nerd" not in clean.lower()
        assert "r/space" not in clean.lower()
        assert not clean.lower().startswith("til ")
        assert "Voyager" in clean

        assert is_suitable_reddit_post({"over_18": True, "title": "Some mature thread title over 25 chars", "ups": 500}) is False
        assert is_suitable_reddit_post({"over_18": False, "title": "Fascinating real story of a solo sailor drifting 438 days", "ups": 620}) is True

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            "data": {"children": [{"data": {"title": "TIL u/alice found https://example.com mystery lighthouse logbook", "ups": 420, "over_18": False}}]}
        }
        src = RedditDiscoverySource(http_get=lambda *a, **kw: fake_resp)
        seeds = src.fetch_story_seeds(subreddits=[{"subreddit": "UnresolvedMysteries", "category": "Mysteries", "evidence_type": "unexplained_mystery"}])
        assert len(seeds) == 1
        assert "http" not in seeds[0]["topic"].lower()
        assert "u/alice" not in seeds[0]["topic"].lower()
        assert seeds[0]["evidence_type"] == "unexplained_mystery"

    def test_topic_evaluation_rejects_did_you_know_and_low_scores(self):
        ok_bad_hook, reason = evaluate_topic_candidate({"topic": "Did you know octopuses have three hearts?", "scores": {"factual_reliability": 9.5}})
        assert ok_bad_hook is False
        assert "did you know" in reason.lower()

        ok_low_fact, _ = evaluate_topic_candidate({"topic": "Secret Mars civilization portal", "scores": {"factual_reliability": 5.0}})
        assert ok_low_fact is False

        ok_good, _ = evaluate_topic_candidate({
            "topic": "How a 17-year-old survived a 2-mile freefall into the Peruvian Amazon",
            "scores": {"factual_reliability": 9.6, "hook_strength": 9.1, "storytelling_potential": 9.3, "ending_payoff": 9.0, "surprise_factor": 9.2},
        })
        assert ok_good is True

    def test_scriptwriter_scenes_validation_and_duration_revision(self):
        lines = [
            {"text": "In 1971 a lightning bolt tore apart LANSA Flight 508 over the rainforest."},
            {"text": "Minutes later Juliane Koepcke woke up alone beneath emerald jungle canopy."},
            {"text": "Every river bend echoed with silence as radar planes searched miles away."},
            {"text": "Remembering her biologist father's compass rule she walked downstream."},
            {"text": "Nine days later timber workers spotted her beside a wooden canoe."},
        ]
        script = {"title": "Two Miles Freefall Over the Amazon", "category": "Survival", "lines": lines, "duration": 34.0}
        assign_line_scenes(script)
        assert all("scene" in ln and "visual_type" in ln["scene"] for ln in script["lines"])

        ok_q, q_issues = validate_script_quality({"title": "Weak", "lines": [{"text": "Did you know this fact is cool?"}]})
        assert ok_q is False
        assert len(q_issues) >= 1

        # Excess >60s trims middle elaboration cleanly while preserving hook (index 0) and ending (-1)
        overlong = {"title": "Long Story", "lines": [{"text": f"Beat {i} adds extra suspenseful historical detail about the deep expedition."} for i in range(12)], "duration": 66.0}
        revised, note = revise_script_for_duration(overlong, 66.0)
        assert len(revised["lines"]) < len(overlong["lines"])
        assert revised["lines"][0]["text"] == overlong["lines"][0]["text"]
        assert revised["lines"][-1]["text"] == overlong["lines"][-1]["text"]
        assert "condensed" in note.lower() or "trimmed" in note.lower()


# =============================================================================
# 4. Safe Automatic Daily Local Cleanup (Asia/Kolkata)
# =============================================================================
class TestSafeDailyStorageCleanup:
    def test_cleanup_deletes_eligible_yesterday_and_protects_active_today_unconfirmed_and_code(self, tmp_path):
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        state_file = tmp_path / "cleanup.json"

        # 1. Eligible completed + confirmed scheduled video from yesterday (2026-11-10) -> CLEANED
        y_mp4 = out_dir / "video_20261110_slot1.mp4"
        y_mp4.write_bytes(b"A" * 5000)
        y_prev = out_dir / "video_20261110_slot1_preview_t5.jpg"
        y_prev.write_bytes(b"B" * 500)
        y_dir = out_dir / "video_20261110_slot1"
        (y_dir / "renders").mkdir(parents=True)
        (y_dir / "renders" / "temp.png").write_bytes(b"C" * 2000)
        iso_db.save_video_record("video_20261110_slot1", {
            "video_id": "video_20261110_slot1",
            "target_date": "2026-11-10",
            "topic": "Heracleion",
            "production_status": "COMPLETED",
            "publishing_status": "SCHEDULED",
            "youtube_upload_id": "y-54SJ4MCFM",
            "schedule_confirmed": True,
            "scheduled_publish_at": "2026-11-10T07:00:00Z",
            "youtube_description": "Preserved metadata description",
            "qc_results": {"passed": True},
        })

        # 2. Yesterday unconfirmed/incomplete upload -> PROTECTED
        u_mp4 = out_dir / "video_20261110_slot2.mp4"
        u_mp4.write_bytes(b"D" * 4000)
        iso_db.save_video_record("video_20261110_slot2", {
            "video_id": "video_20261110_slot2",
            "target_date": "2026-11-10",
            "topic": "Unconfirmed slot",
            "production_status": "COMPLETED",
            "publishing_status": "UPLOADED_PRIVATE",
            "youtube_upload_id": "abc123",
            "schedule_confirmed": False,
        })

        # 3. Today's generated MP4 (2026-11-11) -> PROTECTED
        t_mp4 = out_dir / "video_20261111_slot1.mp4"
        t_mp4.write_bytes(b"E" * 6000)
        iso_db.save_video_record("video_20261111_slot1", {
            "video_id": "video_20261111_slot1",
            "target_date": "2026-11-11",
            "topic": "Today Slot",
            "production_status": "COMPLETED",
            "publishing_status": "SCHEDULED",
            "schedule_confirmed": True,
        })

        # 4. Unrelated custom file inside OUTPUT_DIR -> NEVER TOUCHED
        custom_note = out_dir / "manual_backup_do_not_delete.txt"
        custom_note.write_text("important")

        now_ist = datetime(2026, 11, 11, 6, 0, tzinfo=IST)
        with patch("curiosity_engine.runner.storage_cleanup.config.OUTPUT_DIR", out_dir), \
             patch("curiosity_engine.runner.storage_cleanup.config.YOUTUBE_PUBLISHING_MODE", "live"):
            res1 = cleanup_old_generated_videos(
                retention_days=1,
                output_dir=out_dir,
                state_file=state_file,
                db_client=iso_db,
                now_ist=now_ist,
            )

        assert res1["success"] is True
        assert not y_mp4.exists()
        assert not y_prev.exists()
        assert not y_dir.exists()
        assert res1["bytes_reclaimed"] == 7500

        assert u_mp4.exists()
        assert t_mp4.exists()
        assert custom_note.exists()

        # DB metadata preserved!
        rec_cleaned = iso_db.get_video_record("video_20261110_slot1")
        assert rec_cleaned["local_file_cleaned"] is True
        assert rec_cleaned["youtube_upload_id"] == "y-54SJ4MCFM"
        assert rec_cleaned["youtube_description"] == "Preserved metadata description"
        assert rec_cleaned["qc_results"]["passed"] is True

        # Idempotent repeat run deletes 0 bytes
        with patch("curiosity_engine.runner.storage_cleanup.config.OUTPUT_DIR", out_dir):
            res2 = cleanup_old_generated_videos(
                retention_days=1,
                output_dir=out_dir,
                state_file=state_file,
                db_client=iso_db,
                now_ist=now_ist,
            )
            summary = get_storage_summary(output_dir=out_dir, state_file=state_file)
        assert res2["files_deleted"] == 0
        assert res2["dirs_deleted"] == 0
        assert summary["last_cleanup_date_ist"] == "2026-11-11"


# =============================================================================
# 5. Link-Free Descriptions, Titles, Tags, Quota, Analytics & Telegram
# =============================================================================
class TestMetadataQuotaAnalyticsAndTelegram:
    def test_link_free_descriptions_natural_titles_and_separated_tags(self):
        title = generate_youtube_title(
            "SHOCKING CARRINGTON EVENT!! #shorts",
            {"title": "SHOCKING CARRINGTON EVENT!!", "duration": 38.0},
        )
        assert "#Shorts" in title
        assert not title.isupper()

        gen = DescriptionGenerator()
        desc_data = gen.generate(
            topic="1859 Carrington Solar Storm",
            category="Space",
            script_data={"title": title, "duration": 38.0},
            sources=["https://science.nasa.gov/sun", "https://reddit.com/r/space/xyz"],
            claims=["Telegraph lines sparked worldwide in 1859."],
        )
        ok_no_links, link_issues = validate_no_external_links(desc_data["full_description"])
        assert ok_no_links is True, link_issues
        assert "http" not in desc_data["full_description"].lower()
        assert "reddit" not in desc_data["full_description"].lower()
        assert isinstance(desc_data["youtube_tags"], list) and len(desc_data["youtube_tags"]) >= 3
        assert strip_external_links("Read more https://foo.com via u/user1") == "Read more via"

    def test_youtube_quota_tracker_estimates_and_resets_pt(self, tmp_path):
        tracker = YouTubeQuotaTracker(state_file=tmp_path / "quota.json")
        t1 = datetime(2026, 11, 11, 18, 0, tzinfo=timezone.utc)
        tracker.record_operation("videos.insert", now_utc=t1)
        tracker.record_operation("videos.update", count=2, now_utc=t1)
        tracker.record_operation("videos.list", count=3, now_utc=t1)

        st = tracker.get_quota_status(now_utc=t1)
        assert st["is_estimate"] is True
        assert st["estimated_units_used"] == 1600 + 100 + 3
        assert st["remaining_units"] == 10000 - 1703
        assert st["operations_breakdown"]["upload_insert"]["calls"] == 1
        assert st["operations_breakdown"]["schedule_update"]["calls"] == 2
        assert st["operations_breakdown"]["status_list"]["calls"] == 3

    def test_analytics_small_sample_guard_and_scope_disclosure(self, tmp_path):
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        iso_db.save_video_record("video_20261110_slot1", {
            "video_id": "video_20261110_slot1",
            "topic": "Heracleion",
            "category": "History",
            "style": "paper-atlas",
            "duration_sec": 28.0,
            "youtube_upload_id": "y-54SJ4MCFM",
            "youtube_privacy_status": "public",
            "youtube_published_public_at": (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat(),
        })

        fake_service = MagicMock()
        fake_service.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "y-54SJ4MCFM", "statistics": {"viewCount": "10", "likeCount": "2", "commentCount": "0"}}]
        }
        fake_pub = MagicMock(service=fake_service)
        perf = YouTubePerformanceTracker(state_file=tmp_path / "perf.json")

        with patch("curiosity_engine.distribution.youtube_analytics.token_manager.get_summary", return_value={"youtube": {"scopes": ["https://www.googleapis.com/auth/youtube.readonly", "https://www.googleapis.com/auth/youtube.upload"]}}):
            summary = perf.refresh_public_video_metrics(fake_pub, db_client=iso_db)

        assert summary["analytics_access"] == "LIMITED_SCOPE_MISSING"
        assert "yt-analytics.readonly" in summary["limitation_note"]
        assert summary["totals"]["views"] == 10
        assert summary["sample_status"] == "INSUFFICIENT_SAMPLE"
        assert summary["pattern_insights"] == []
        assert f"{MIN_SAMPLE_FOR_INSIGHTS}" in summary["sample_guidance"]

    def test_telegram_expanded_lifecycle_events_and_upload_honesty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "999888777:SecretTestTokenXYZ")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456789")
        sent_messages = []

        class _Resp:
            status_code = 200
            text = '{"ok": true}'
            def json(self):
                return {"ok": True, "result": {"message_id": len(sent_messages)}}

        def _fake_post(url, json=None, timeout=10):
            sent_messages.append(json["text"])
            return _Resp()

        notifier = TelegramNotifier(state_file=tmp_path / "tg.json", http_post=_fake_post)
        r1 = notifier.notify_production_started("video_20261111_slot1", "Antikythera Clock", 1, "History", "20-60s")
        r2 = notifier.notify_qc_failed("video_20261111_slot1", "Antikythera Clock", 1, "Too long", 1, 2, "Revising script")
        r3 = notifier.notify_qc_recovered("video_20261111_slot1", "Antikythera Clock", 1, 1, duration_sec=41.2)
        r4 = notifier.notify_upload_completed("video_20261111_slot1", "Ancient Gears #Shorts", "vidXYZ", "SCHEDULED", "2026-11-12 12:30 IST")
        # Duplicate key is deduplicated
        r4_dup = notifier.notify_upload_completed("video_20261111_slot1", "Ancient Gears #Shorts", "vidXYZ", "SCHEDULED", "2026-11-12 12:30 IST")
        r5 = notifier.notify_daily_summary(
            date_str="2026-11-11",
            production_count=2,
            daily_limit=2,
            published_public_count=0,
            scheduled_pending_count=2,
            next_scheduled_ist="2026-11-11 20:30 IST",
            oauth_status="HEALTHY",
            oauth_reauth_ist="2026-11-17 12:00 IST",
            production_failures_count=0,
            qc_recovery_attempts_count=1,
            remaining_or_missed_slots="All slots covered",
            oauth_warnings="Expiring in 22h",
        )

        assert all(r.get("sent") for r in (r1, r2, r3, r4, r5))
        assert r4_dup.get("sent") is False
        assert r4_dup.get("status") == "DEDUPED"
        assert "private until publishAt" in sent_messages[3]
        assert "QC Recovery Attempts:</b> 1" in sent_messages[4]


# =============================================================================
# 6. Redesigned Dashboard Telemetry & Daily Progress Accuracy
# =============================================================================
class TestDashboardPhase3Telemetry:
    def test_dashboard_status_distinguishes_scheduled_private_from_public_and_exposes_new_sections(self, tmp_path):
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        out_dir = tmp_path / "output"
        out_dir.mkdir(parents=True)
        today_str = "2026-11-11"

        iso_db.save_video_record("video_20261111_slot1", {
            "video_id": "video_20261111_slot1",
            "slot_index": 1,
            "target_date": today_str,
            "topic": "Topic One",
            "category": "History",
            "style": "paper-atlas",
            "duration_sec": 36.4,
            "recovery_attempts": 1,
            "production_status": "COMPLETED",
            "qc_passed": True,
            "publishing_status": "SCHEDULED",
            "youtube_upload_id": "ytLivePriv1",
            "youtube_privacy_status": "private",
            "schedule_confirmed": True,
            "scheduled_publish_at": "2026-11-12T07:00:00Z",
        })
        iso_db.save_video_record("video_20261111_slot2", {
            "video_id": "video_20261111_slot2",
            "slot_index": 2,
            "target_date": today_str,
            "topic": "Topic Two",
            "category": "Space",
            "style": "stick-story",
            "duration_sec": 41.0,
            "production_status": "COMPLETED",
            "qc_passed": True,
            "publishing_status": "PUBLISHED",
            "youtube_upload_id": "ytLivePub2",
            "youtube_privacy_status": "public",
            "schedule_confirmed": True,
            "youtube_published_public_at": "2026-11-11T15:00:05Z",
        })

        quota_tracker = YouTubeQuotaTracker(state_file=tmp_path / "quota.json")
        quota_tracker.record_operation("videos.insert")
        perf_tracker = YouTubePerformanceTracker(state_file=tmp_path / "perf.json")

        fake_sched = MagicMock()
        fake_sched.now_ist.return_value = datetime(2026, 11, 11, 16, 0, tzinfo=IST)
        fake_sched.get_telemetry.return_value = {"is_running": True, "pid": 9012, "today_automation": {}}

        client = TestClient(dashboard_app.app)
        with patch("curiosity_engine.dashboard.app.db", iso_db), \
             patch("curiosity_engine.dashboard.app.OUTPUT_DIR", out_dir), \
             patch("curiosity_engine.dashboard.app.scheduler", fake_sched), \
             patch("curiosity_engine.dashboard.app.youtube_quota", quota_tracker), \
             patch("curiosity_engine.dashboard.app.performance_tracker", perf_tracker), \
             patch("curiosity_engine.dashboard.app.get_storage_summary", return_value={"output_size_mb": 12.5, "mp4_files_on_disk": 1}):

            resp = client.get("/api/status")
            html_resp = client.get("/")
            stor_resp = client.get("/api/storage")
            ana_resp = client.get("/api/analytics")

        assert resp.status_code == 200
        assert html_resp.status_code == 200
        assert stor_resp.status_code == 200
        assert ana_resp.status_code == 200

        body = resp.json()
        # Only slot2 is public -> published_public_count MUST be 1, while scheduled_count MUST be 1
        assert body["daily_progress"]["published_public_count"] == 1
        assert body["daily_progress"]["scheduled_count"] == 1
        assert body["daily_progress"]["daily_target"] == 2
        assert body["quotas"]["youtube_api_estimate"]["is_estimate"] is True
        assert body["quotas"]["youtube_api_estimate"]["estimated_units_used"] == 1600
        assert len(body["slot_timeline"]) == 2
        assert body["slot_timeline"][0]["stage"] == "Scheduled"
        assert body["slot_timeline"][0]["recovery_attempts"] == 1
        assert body["slot_timeline"][1]["stage"] == "Published"
        assert body["policy"]["max_duration_sec"] == 60.0
        assert "CurioLoop Studio" in html_resp.text
        assert "STUDIO_AUTH_KEY" in html_resp.text
