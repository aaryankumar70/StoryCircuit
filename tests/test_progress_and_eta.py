"""Tests for CurioLoop Compact Live Production Progress, Stage Tracking & ETA Engine.

Covers:
1. Ordered transitions across Topic -> Script -> Narration -> Visuals -> Render -> QC -> Private Upload -> Schedule -> Published
2. Persistence of stage timings & active elapsed clocks across simulated dashboard restarts
3. ETA accuracy with sufficient historical stage data + live render frame telemetry
4. Honest fallback to 'Estimating remaining time...' when historical timing data is insufficient
5. Indeterminate vs determinate progress honesty (no invented intra-stage %)
6. QC recovery attempt telemetry, reason, next action, and resumption into Distribution
7. Terminal failure states preserving prior completed steps & stopping cleanly
8. Clear separation of finished Production waiting on scheduled release vs Published completion
9. Dashboard /api/status integration + UI markup & responsive compact styling
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from curiosity_engine.dashboard import app as dashboard_app
from curiosity_engine.runner.pipeline import produce_single_video, run_slot_publishing
from curiosity_engine.runner.progress_tracker import (
    StageTimingStore,
    build_slot_progress_snapshot,
    complete_qc_recovery,
    record_stage_checkpoint,
    record_stage_complete,
    record_stage_failed,
    record_stage_start,
)
from curiosity_engine.state.db import DatabaseClient


class TestStageTransitionsAndPersistence:
    def test_stages_transition_monotonically_without_premature_100_percent(self, tmp_path):
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        store = StageTimingStore(history_file=tmp_path / "timings.json")
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        vid_id = "video_20261112_slot1"

        t0 = datetime(2026, 11, 12, 0, 0, 0, tzinfo=timezone.utc)
        iso_db.save_video_record(vid_id, {
            "video_id": vid_id,
            "slot_index": 1,
            "target_date": "2026-11-12",
            "topic": "Secret Brass Calendar",
            "production_status": "STARTING",
            "created_at": t0.isoformat(),
        })

        seen_percents = []
        stage_sequence = [
            "selecting_topic",
            "writing_script",
            "generating_narration",
            "preparing_visuals",
            "rendering_video",
            "running_qc",
        ]

        now = t0
        for st_key in stage_sequence:
            now = now + timedelta(seconds=5)
            record_stage_start(vid_id, st_key, db_client=iso_db, timing=store, now_utc=now)
            rec = iso_db.get_video_record(vid_id)
            snap = build_slot_progress_snapshot(
                slot_index=1,
                video_rec=rec,
                sched_slot_rec=None,
                target_time_ist="12:30 PM IST",
                output_dir=out_dir,
                timing=store,
                now_utc=now + timedelta(seconds=2),
            )
            assert snap["stage_id"] == st_key
            assert snap["is_active"] is True
            assert snap["overall_percent"] < 100
            seen_percents.append(snap["overall_percent"])

        # Each subsequent stage monotonically increases overall_percent without exceeding <100
        assert seen_percents == sorted(seen_percents)
        assert seen_percents[-1] > seen_percents[0]

        # Complete production -> Waiting for distribution when pub_status == PENDING
        now = now + timedelta(seconds=5)
        record_stage_complete(vid_id, "running_qc", db_client=iso_db, timing=store, now_utc=now)
        rec = iso_db.get_video_record(vid_id)
        rec["production_status"] = "COMPLETED"
        rec["qc_passed"] = True
        rec["publishing_status"] = "PENDING"
        iso_db.save_video_record(vid_id, rec)

        wait_dist_snap = build_slot_progress_snapshot(
            1, iso_db.get_video_record(vid_id), None, "12:30 PM IST", output_dir=out_dir, timing=store, now_utc=now + timedelta(seconds=1)
        )
        assert wait_dist_snap["production_complete"] is True
        assert wait_dist_snap["phase"] == "waiting_distribution"
        assert wait_dist_snap["is_active"] is False
        assert wait_dist_snap["overall_percent"] == 90

        # Transition actively into Distribution upload & scheduling
        record_stage_start(vid_id, "uploading_privately", db_client=iso_db, timing=store, now_utc=now + timedelta(seconds=2))
        up_snap = build_slot_progress_snapshot(
            1, iso_db.get_video_record(vid_id), None, "12:30 PM IST", output_dir=out_dir, timing=store, now_utc=now + timedelta(seconds=4)
        )
        assert up_snap["production_complete"] is True
        assert up_snap["phase"] == "distribution"
        assert up_snap["is_active"] is True
        assert up_snap["overall_percent"] == 90

        # Confirm scheduled private waiting -> does NOT appear actively processing and never claims 100% public
        rec2 = dict(iso_db.get_video_record(vid_id))
        rec2.update({
            "publishing_status": "SCHEDULED",
            "youtube_upload_id": "yt_real_123",
            "youtube_privacy_status": "private",
            "schedule_confirmed": True,
            "scheduled_publish_at": "2026-11-12T07:00:00Z",
            "ui_status": "SCHEDULED",
        })
        sched_snap = build_slot_progress_snapshot(
            1, rec2, None, "12:30 PM IST", output_dir=out_dir, timing=store, now_utc=now + timedelta(seconds=10)
        )
        assert sched_snap["stage"] == "Scheduled"
        assert sched_snap["phase"] == "waiting_schedule"
        assert sched_snap["is_active"] is False
        assert sched_snap["production_complete"] is True
        assert sched_snap["overall_percent"] == 96
        assert all(s["status"] == "completed" for s in sched_snap["production_stages"])
        assert sched_snap["distribution_stages"][0]["status"] == "completed"
        assert sched_snap["distribution_stages"][1]["status"] == "completed"
        assert sched_snap["distribution_stages"][2]["status"] == "waiting"

        # Transition public -> 100% Published
        rec2["youtube_privacy_status"] = "public"
        rec2["ui_status"] = "PUBLISHED_PUBLIC"
        pub_snap = build_slot_progress_snapshot(
            1, rec2, None, "12:30 PM IST", output_dir=out_dir, timing=store, now_utc=now + timedelta(minutes=60)
        )
        assert pub_snap["stage"] == "Published"
        assert pub_snap["overall_percent"] == 100
        assert pub_snap["phase"] == "completed"
        assert pub_snap["is_active"] is False
        assert all(s["status"] == "completed" for s in pub_snap["distribution_stages"])

    def test_progress_persists_across_dashboard_restart_reload(self, tmp_path):
        db_path = tmp_path / "persisted_db.json"
        store = StageTimingStore(history_file=tmp_path / "timings.json")
        out_dir = tmp_path / "output"
        (out_dir / "video_20261112_slot2" / "logs").mkdir(parents=True)
        (out_dir / "video_20261112_slot2" / "logs" / "render.log").write_text("0/900 frames\n300/900 frames\n")

        writer_db = DatabaseClient(custom_file=db_path)
        t_start = datetime(2026, 11, 12, 2, 0, 0, tzinfo=timezone.utc)
        writer_db.save_video_record("video_20261112_slot2", {
            "video_id": "video_20261112_slot2",
            "slot_index": 2,
            "target_date": "2026-11-12",
            "topic": "Mariana Trench",
            "created_at": t_start.isoformat(),
        })
        record_stage_start("video_20261112_slot2", "selecting_topic", db_client=writer_db, timing=store, now_utc=t_start)
        record_stage_start("video_20261112_slot2", "writing_script", db_client=writer_db, timing=store, now_utc=t_start + timedelta(seconds=3))
        record_stage_start("video_20261112_slot2", "generating_narration", db_client=writer_db, timing=store, now_utc=t_start + timedelta(seconds=9))
        record_stage_start("video_20261112_slot2", "preparing_visuals", db_client=writer_db, timing=store, now_utc=t_start + timedelta(seconds=16))
        record_stage_start("video_20261112_slot2", "rendering_video", detail={"total_frames": 900}, db_client=writer_db, timing=store, now_utc=t_start + timedelta(seconds=30))

        # Brand new DB reader instance simulating dashboard process restart
        restarted_db = DatabaseClient(custom_file=db_path)
        reloaded_rec = restarted_db.get_video_record("video_20261112_slot2")
        query_time = t_start + timedelta(seconds=150)  # 120s into render (300/900 = 1/3 -> ~240s remaining)
        snap = build_slot_progress_snapshot(
            2, reloaded_rec, None, "8:30 PM IST", output_dir=out_dir, timing=store, now_utc=query_time
        )

        assert snap["elapsed_sec"] == 150.0
        assert snap["elapsed_formatted"] == "02:30"
        # Upstream 4% + 8% + 10% + 14% = 36%, plus 1/3 * 48% = 16% -> 52%
        assert snap["overall_percent"] == 52
        assert snap["progress_mode"] == "determinate"
        assert snap["measurable_detail"] == "300/900 frames"


class TestETAAndIndeterminateBehavior:
    def test_eta_unavailable_without_historical_data_and_computed_with_history(self, tmp_path):
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        empty_store = StageTimingStore(history_file=tmp_path / "empty_timings.json")
        out_dir = tmp_path / "output"
        out_dir.mkdir()

        t0 = datetime(2026, 11, 12, 3, 0, 0, tzinfo=timezone.utc)
        iso_db.save_video_record("video_20261112_slot1", {
            "video_id": "video_20261112_slot1",
            "slot_index": 1,
            "target_date": "2026-11-12",
            "topic": "Wow Signal",
            "created_at": t0.isoformat(),
        })
        record_stage_start("video_20261112_slot1", "generating_narration", db_client=iso_db, timing=empty_store, now_utc=t0)
        rec = iso_db.get_video_record("video_20261112_slot1")

        snap_no_hist = build_slot_progress_snapshot(
            1, rec, None, "12:30 PM IST", output_dir=out_dir, timing=empty_store, now_utc=t0 + timedelta(seconds=4)
        )
        assert snap_no_hist["eta_available"] is False
        assert snap_no_hist["eta_text"] == "Estimating remaining time..."
        assert snap_no_hist["progress_mode"] == "indeterminate"
        assert snap_no_hist["intra_stage_percent"] is None

        # Populate realistic historical durations -> ETA becomes available cleanly
        empty_store.record_stage_duration("generating_narration", 10.0)
        empty_store.record_stage_duration("preparing_visuals", 20.0)
        empty_store.record_stage_duration("rendering_video", 300.0, frames_count=900)
        empty_store.record_stage_duration("running_qc", 5.0)

        snap_with_hist = build_slot_progress_snapshot(
            1, rec, None, "12:30 PM IST", output_dir=out_dir, timing=empty_store, now_utc=t0 + timedelta(seconds=4)
        )
        assert snap_with_hist["eta_available"] is True
        # (10 - 4) + 20 + 300 + 5 = 331s = 05:31
        assert snap_with_hist["eta_seconds"] == 331.0
        assert snap_with_hist["eta_text"] == "05:31"

    def test_checkpoints_in_preparing_visuals_stay_determinate_while_unmeasured_starts_indeterminate(self, tmp_path):
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        store = StageTimingStore(history_file=tmp_path / "timings.json")
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        t0 = datetime(2026, 11, 12, 4, 0, 0, tzinfo=timezone.utc)
        iso_db.save_video_record("video_20261112_slot1", {
            "video_id": "video_20261112_slot1",
            "slot_index": 1,
            "target_date": "2026-11-12",
            "created_at": t0.isoformat(),
        })
        record_stage_start("video_20261112_slot1", "preparing_visuals", db_client=iso_db, timing=store, now_utc=t0)
        snap_before = build_slot_progress_snapshot(
            1, iso_db.get_video_record("video_20261112_slot1"), None, "12:30 PM IST", output_dir=out_dir, timing=store, now_utc=t0 + timedelta(seconds=2)
        )
        assert snap_before["progress_mode"] == "indeterminate"

        record_stage_checkpoint("video_20261112_slot1", "preparing_visuals", 0.55, "Visual timeline verified", db_client=iso_db)
        snap_after = build_slot_progress_snapshot(
            1, iso_db.get_video_record("video_20261112_slot1"), None, "12:30 PM IST", output_dir=out_dir, timing=store, now_utc=t0 + timedelta(seconds=6)
        )
        assert snap_after["progress_mode"] == "determinate"
        assert snap_after["intra_stage_percent"] == 55.0
        assert snap_after["measurable_detail"] == "Visual timeline verified"


class TestRecoveryFailureAndPipelineIntegration:
    def test_qc_recovery_tracks_attempt_reason_and_resumes_pipeline(self, tmp_path):
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        store = StageTimingStore(history_file=tmp_path / "timings.json")
        out_dir = tmp_path / "output"
        (out_dir / "video_20261112_slot1" / "logs").mkdir(parents=True)

        t0 = datetime(2026, 11, 12, 5, 0, 0, tzinfo=timezone.utc)
        iso_db.save_video_record("video_20261112_slot1", {
            "video_id": "video_20261112_slot1",
            "slot_index": 1,
            "target_date": "2026-11-12",
            "topic": "Greenland Shark",
            "created_at": t0.isoformat(),
            "recovery_attempts": 1,
        })
        record_stage_start(
            "video_20261112_slot1",
            "qc_recovery",
            detail={
                "attempt": 1,
                "max_attempts": 2,
                "reason": "Duration 63.2s exceeds max 60s",
                "next_action": "Condensing middle narrative beat",
                "substage": "revising_script",
            },
            db_client=iso_db,
            timing=store,
            now_utc=t0,
        )
        # During recovery, starting rendering_video keeps active_stage == "qc_recovery" cleanly
        record_stage_start("video_20261112_slot1", "rendering_video", db_client=iso_db, timing=store, now_utc=t0 + timedelta(seconds=10))
        (out_dir / "video_20261112_slot1" / "logs" / "render.log").write_text("450/900 frames\n")

        rec_snap = build_slot_progress_snapshot(
            1, iso_db.get_video_record("video_20261112_slot1"), None, "12:30 PM IST", output_dir=out_dir, timing=store, now_utc=t0 + timedelta(seconds=55)
        )
        assert rec_snap["stage_id"] == "qc_recovery"
        assert "Attempt 1/2" in rec_snap["stage_label"]
        assert rec_snap["recovery_detail"]["reason"] == "Duration 63.2s exceeds max 60s"
        assert rec_snap["recovery_detail"]["next_action"] == "Condensing middle narrative beat"
        assert rec_snap["progress_mode"] == "determinate"
        assert rec_snap["measurable_detail"] == "450/900 frames"

        # When recovery passes QC cleanly, normal production complete state resumes
        complete_qc_recovery("video_20261112_slot1", db_client=iso_db, timing=store, now_utc=t0 + timedelta(seconds=90))
        done_rec = dict(iso_db.get_video_record("video_20261112_slot1"))
        done_rec["production_status"] = "COMPLETED"
        done_rec["qc_passed"] = True
        done_rec["ui_status"] = "GENERATED"
        done_snap = build_slot_progress_snapshot(
            1, done_rec, None, "12:30 PM IST", output_dir=out_dir, timing=store, now_utc=t0 + timedelta(seconds=95)
        )
        assert done_snap["production_complete"] is True
        assert all(s["status"] == "completed" for s in done_snap["production_stages"])

    def test_terminal_failure_records_exact_failed_stage_and_reason(self, tmp_path):
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        store = StageTimingStore(history_file=tmp_path / "timings.json")
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        t0 = datetime(2026, 11, 12, 6, 0, 0, tzinfo=timezone.utc)
        iso_db.save_video_record("video_20261112_slot1", {
            "video_id": "video_20261112_slot1",
            "slot_index": 1,
            "target_date": "2026-11-12",
            "topic": "Broken Audio",
            "created_at": t0.isoformat(),
        })
        for s in ("selecting_topic", "writing_script", "generating_narration", "preparing_visuals", "rendering_video"):
            t0 += timedelta(seconds=5)
            record_stage_start("video_20261112_slot1", s, db_client=iso_db, timing=store, now_utc=t0)
        record_stage_start("video_20261112_slot1", "running_qc", db_client=iso_db, timing=store, now_utc=t0 + timedelta(seconds=5))
        record_stage_failed("video_20261112_slot1", "running_qc", "Integrated loudness -31 LUFS outside target", db_client=iso_db)

        rec = dict(iso_db.get_video_record("video_20261112_slot1"))
        rec["production_status"] = "FAILED"
        rec["qc_passed"] = False
        rec["ui_status"] = "FAILED"
        rec["error"] = "Integrated loudness -31 LUFS outside target"
        snap = build_slot_progress_snapshot(
            1, rec, None, "12:30 PM IST", output_dir=out_dir, timing=store, now_utc=t0 + timedelta(seconds=10)
        )
        assert snap["phase"] == "failed"
        assert snap["progress_mode"] == "failed"
        assert snap["is_active"] is False
        assert snap["failed_stage"] == "running_qc"
        assert "Running QC" in snap["stage_label"]
        assert snap["production_stages"][5]["status"] == "failed"
        assert snap["overall_percent"] == 84

    def test_pipeline_execution_populates_real_stage_progress_and_dashboard_ui(self, tmp_path):
        iso_db = DatabaseClient(custom_file=tmp_path / "db.json")
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        vid_id = "video_20261112_slot1"

        def _fake_prep(video_id, script_data):
            record_stage_start(video_id, "generating_narration", db_client=iso_db)
            record_stage_complete(video_id, "generating_narration", db_client=iso_db)
            record_stage_start(video_id, "preparing_visuals", db_client=iso_db)
            pdir = out_dir / video_id
            pdir.mkdir(parents=True, exist_ok=True)
            return pdir

        def _fake_render(p_dir, output_mp4, **kwargs):
            record_stage_complete(p_dir.name, "preparing_visuals", db_client=iso_db)
            record_stage_start(p_dir.name, "rendering_video", db_client=iso_db)
            output_mp4.write_bytes(b"0" * 120_000)
            record_stage_complete(p_dir.name, "rendering_video", frames_count=900, db_client=iso_db)
            return output_mp4

        qc_ok = MagicMock(passed=True, issues=[], checks={"duration_sec": 30.0})
        qc_ok.to_dict.return_value = {"passed": True, "checks": {"duration_sec": 30.0}, "issues": []}

        topic_info = {
            "topic": "Antikythera Mechanism",
            "category": "History",
            "style": "paper-atlas",
            "sources": ["https://britannica.com"],
            "claims": ["Bronze gear computer from ancient Greece."],
        }
        script_stub = {
            "title": "Antikythera Mechanism #Shorts",
            "category": "History",
            "style": "paper-atlas",
            "duration": 30.0,
            "lines": [{"text": "Divers found a lump of bronze.", "scene": "ocean"}],
            "sources": ["https://britannica.com"],
        }

        with patch("curiosity_engine.runner.pipeline.db", iso_db), \
             patch("curiosity_engine.runner.pipeline.OUTPUT_DIR", out_dir), \
             patch("curiosity_engine.runner.pipeline.write_video_script", return_value=script_stub), \
             patch("curiosity_engine.runner.pipeline.prepare_project", side_effect=_fake_prep), \
             patch("curiosity_engine.runner.pipeline.render_project_video", side_effect=_fake_render), \
             patch("curiosity_engine.runner.pipeline.verify_video", return_value=qc_ok), \
             patch("curiosity_engine.notifications.telegram_notifier.get_telegram_notifier", return_value=MagicMock()):

            res = produce_single_video(vid_id, topic_info, slot_index=1, target_date="2026-11-12")
            assert set(res["stage_progress"]["completed_stages"]) >= {
                "selecting_topic", "writing_script", "generating_narration", "preparing_visuals", "rendering_video", "running_qc"
            }

            with patch("curiosity_engine.runner.pipeline.youtube_publisher.upload_short", return_value={
                "video_id": "yt_sim_1",
                "url": "",
                "simulated": True,
                "privacy_status": "private",
                "schedule_confirmed": False,
            }):
                pub_rec = run_slot_publishing(1, target_date="2026-11-12", force_yt_mode="simulation", force_ig_mode="disabled")
                assert "uploading_privately" in pub_rec["stage_progress"]["completed_stages"]

        fake_sched = MagicMock()
        fake_sched.now_ist.return_value = datetime(2026, 11, 12, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        fake_sched.get_telemetry.return_value = {"is_running": True, "pid": 9012, "today_automation": {}}

        client = TestClient(dashboard_app.app)
        with patch("curiosity_engine.dashboard.app.db", iso_db), \
             patch("curiosity_engine.dashboard.app.OUTPUT_DIR", out_dir), \
             patch("curiosity_engine.dashboard.app.scheduler", fake_sched):
            status_resp = client.get("/api/status")
            html_resp = client.get("/")

        assert status_resp.status_code == 200
        body = status_resp.json()
        s1 = body["slot_timeline"][0]
        assert len(s1["production_stages"]) == 6
        assert s1["production_stages"][0]["stage_id"] == "selecting_topic"
        assert len(s1["distribution_stages"]) == 3
        assert s1["distribution_stages"][0]["stage_id"] == "uploading_privately"
        assert "elapsed_formatted" in s1
        assert "eta_text" in s1
        assert "overall_percent" in s1

        # Verify compact UI classes & adaptive polling script exist in rendered HTML
        html_txt = html_resp.text
        assert "slot-prog-wrap" in html_txt
        assert "slot-bar-indeterminate" in html_txt
        assert "phase-row" in html_txt
        assert "@media (max-width: 900px)" in html_txt
        assert "pollLoop" in html_txt
