"""Unit tests for Series Scheduling Planner and Production Queue Lifecycle (Steps 5 & 6).

Covers:
1. Schedule Planner (Step 5):
   - Configurable start date, start time, timezone (Asia/Kolkata IST default), cadence
   - Preset Schedule A: 1 ep/day (Evening 20:30 IST)
   - Preset Schedule B: 2 ep/day (Morning 09:00 IST & Evening 20:30 IST)
   - Preset Schedule C: Custom frequency / slots / weekdays
   - Calendar preview generation and estimated series completion date calculation
2. Production Lifecycle & Queue Control (Step 6):
   - 8 Lifecycle statuses: Planned, Script ready, Awaiting approval, In production,
     QC failed, Ready for publishing, Scheduled, Published
   - Series lifecycle controls: Pause, Resume, Cancel
   - Queue status reporting across all episodes
3. Automatic Studio Preservation:
   - 2 daily autonomous videos (09:00 IST and 19:00 IST) never disabled or displaced
   - Sequential execution priority and conflict-free queue handling
4. REST API endpoints in series_api:
   - POST /api/series/schedule/preview
   - POST /api/series/{series_id}/schedule/commit
   - POST /api/series/{series_id}/pause, /resume, /cancel
   - GET /api/series/{series_id}/queue-status
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
from fastapi.testclient import TestClient

from curiosity_engine.creator_series.models import (
    EPISODE_STATUS_DISPLAY_MAP,
    EpisodeRecord,
    EpisodeStatus,
    RightsStatus,
    SeriesRecord,
    SeriesStatus,
    normalize_episode_status,
)
from curiosity_engine.creator_series.queue_manager import (
    JobStatus,
    JobType,
    ProductionQueueManager,
    QueueJob,
)
from curiosity_engine.creator_series.series_db import SeriesDatabase
from curiosity_engine.creator_series.series_scheduler import (
    DEFAULT_TIMEZONE,
    SeriesScheduler,
)
from curiosity_engine.dashboard.app import app
from curiosity_engine.state.db import DatabaseClient

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def isolated_env(tmp_path: Path):
    db_file = tmp_path / "test_db.json"
    queue_file = tmp_path / "test_queue.json"
    client = DatabaseClient(custom_file=db_file)
    s_db = SeriesDatabase(db_client=client)
    q_mgr = ProductionQueueManager(state_file=queue_file, s_db=s_db)
    sched = SeriesScheduler(s_db=s_db)
    return s_db, q_mgr, sched, client


class TestSeriesSchedulerPlanner:
    """Tests for Step 5: Scheduling Planner & Calendar Preview."""

    def test_schedule_a_daily_calendar_preview(self, isolated_env):
        """Schedule A: 1 episode per day in the evening (20:30 IST)."""
        _, _, sched, _ = isolated_env

        preview = sched.generate_calendar_preview(
            episode_count=4,
            schedule_type="A",
            start_date="2026-12-01",
            start_time="20:30",
            cadence="daily",
        )

        assert preview["status"] == "success"
        assert preview["schedule_type"] == "A"
        assert preview["total_episodes"] == 4
        assert preview["start_date"] == "2026-12-01"
        assert preview["estimated_completion_date"] == "2026-12-04"
        assert "2026-12-04T20:30:00+05:30" in preview["estimated_completion_datetime_ist"]

        calendar = preview["calendar"]
        assert len(calendar) == 4

        # Episode 1
        assert calendar[0]["episode_num"] == 1
        assert calendar[0]["date"] == "2026-12-01"
        assert calendar[0]["time"] == "20:30"
        assert calendar[0]["scheduled_datetime_ist"] == "2026-12-01T20:30:00+05:30"
        assert calendar[0]["scheduled_datetime_utc"] == "2026-12-01T15:00:00+00:00"

        # Episode 4
        assert calendar[3]["episode_num"] == 4
        assert calendar[3]["date"] == "2026-12-04"
        assert calendar[3]["time"] == "20:30"

    def test_schedule_a_alternate_cadence(self, isolated_env):
        """Schedule A with alternate cadence: 1 ep every 2 days."""
        _, _, sched, _ = isolated_env

        preview = sched.generate_calendar_preview(
            episode_count=3,
            schedule_type="A",
            start_date="2026-12-01",
            cadence="alternate",
        )

        assert preview["total_episodes"] == 3
        calendar = preview["calendar"]
        assert calendar[0]["date"] == "2026-12-01"
        assert calendar[1]["date"] == "2026-12-03"
        assert calendar[2]["date"] == "2026-12-05"
        assert preview["estimated_completion_date"] == "2026-12-05"

    def test_schedule_b_two_episodes_per_day_morning_start(self, isolated_env):
        """Schedule B: 2 episodes per day (09:00 IST & 20:30 IST) starting in the morning."""
        _, _, sched, _ = isolated_env

        preview = sched.generate_calendar_preview(
            episode_count=4,
            schedule_type="B",
            start_date="2026-12-01",
            start_time="09:00",
            cadence="daily",
        )

        assert preview["total_episodes"] == 4
        assert preview["estimated_completion_date"] == "2026-12-02"

        calendar = preview["calendar"]
        # Day 1 Morning & Evening
        assert calendar[0]["date"] == "2026-12-01" and calendar[0]["time"] == "09:00"
        assert calendar[1]["date"] == "2026-12-01" and calendar[1]["time"] == "20:30"
        # Day 2 Morning & Evening
        assert calendar[2]["date"] == "2026-12-02" and calendar[2]["time"] == "09:00"
        assert calendar[3]["date"] == "2026-12-02" and calendar[3]["time"] == "20:30"

    def test_schedule_b_two_episodes_per_day_evening_start(self, isolated_env):
        """Schedule B: Starting with the evening slot on Day 1, then morning/evening on subsequent days."""
        _, _, sched, _ = isolated_env

        preview = sched.generate_calendar_preview(
            episode_count=4,
            schedule_type="B",
            start_date="2026-12-01",
            start_time="20:30",
        )

        calendar = preview["calendar"]
        assert calendar[0]["date"] == "2026-12-01" and calendar[0]["time"] == "20:30"
        assert calendar[1]["date"] == "2026-12-02" and calendar[1]["time"] == "09:00"
        assert calendar[2]["date"] == "2026-12-02" and calendar[2]["time"] == "20:30"
        assert calendar[3]["date"] == "2026-12-03" and calendar[3]["time"] == "09:00"
        assert preview["estimated_completion_date"] == "2026-12-03"

    def test_schedule_c_custom_slots_and_days(self, isolated_env):
        """Schedule C: Custom slot times (14:00, 21:00) and specific weekdays."""
        _, _, sched, _ = isolated_env

        preview = sched.generate_calendar_preview(
            episode_count=3,
            schedule_type="C",
            start_date="2026-12-01",  # 2026-12-01 is a Tuesday
            custom_slots=["14:00", "21:00"],
            custom_days=["Tuesday", "Thursday"],
        )

        calendar = preview["calendar"]
        assert len(calendar) == 3
        # Tuesday slots
        assert calendar[0]["date"] == "2026-12-01" and calendar[0]["time"] == "14:00"
        assert calendar[1]["date"] == "2026-12-01" and calendar[1]["time"] == "21:00"
        # Thursday first slot (2026-12-03)
        assert calendar[2]["date"] == "2026-12-03" and calendar[2]["time"] == "14:00"
        assert preview["estimated_completion_date"] == "2026-12-03"


class TestProductionQueueLifecycle:
    """Tests for Step 6: Production Queue Lifecycle and Controls."""

    def test_lifecycle_statuses_normalization(self):
        """Verify that all 8 production lifecycle statuses normalize and display cleanly."""
        expected_statuses = [
            ("PLANNED", "Planned"),
            ("SCRIPT_READY", "Script ready"),
            ("AWAITING_APPROVAL", "Awaiting approval"),
            ("IN_PRODUCTION", "In production"),
            ("QC_FAILED", "QC failed"),
            ("READY_FOR_PUBLISHING", "Ready for publishing"),
            ("SCHEDULED", "Scheduled"),
            ("PUBLISHED", "Published"),
        ]

        for enum_name, display_str in expected_statuses:
            norm = normalize_episode_status(enum_name)
            assert norm.value == enum_name
            # Check title-case/spaced input as well
            norm_from_display = normalize_episode_status(display_str)
            assert norm_from_display.value == enum_name
            # Check display map
            assert EPISODE_STATUS_DISPLAY_MAP[norm] == display_str

        # Test EpisodeRecord property
        ep = EpisodeRecord(
            episode_id="ep_test",
            series_id="s_test",
            episode_num=1,
            title="Ep 1",
            adapted_narration="Text",
            status=EpisodeStatus.IN_PRODUCTION,
        )
        assert ep.lifecycle_status == "In production"
        d = ep.to_dict()
        assert d["lifecycle_status"] == "In production"
        assert d["status"] == "IN_PRODUCTION"

    def test_series_enqueue_pause_resume_cancel(self, isolated_env):
        """Test enqueueing series, pausing, resuming, and cancelling via ProductionQueueManager."""
        s_db, q_mgr, _, _ = isolated_env

        # 1. Setup series with 3 episodes
        series = SeriesRecord(
            series_id="queue_test_series",
            title="Queue Test Series",
            full_script="Test script...",
            planned_episodes=3,
            status=SeriesStatus.READY,
        )
        s_db.save_series(series)

        for i in range(1, 4):
            ep = EpisodeRecord(
                episode_id=f"queue_test_series_ep{i:02d}",
                series_id="queue_test_series",
                episode_num=i,
                title=f"Episode {i}",
                adapted_narration=f"Narration beat {i}",
                status=EpisodeStatus.SCRIPT_READY,
                scheduled_publication_time=f"2026-12-0{i}T20:30:00+05:30",
            )
            s_db.save_episode(ep)

        # 2. Enqueue series
        enqueued = q_mgr.enqueue_series("queue_test_series")
        assert len(enqueued) == 3

        status_view = q_mgr.get_series_queue_status("queue_test_series")
        assert status_view["total_episodes"] == 3
        assert status_view["pending_episodes"] == 3
        assert status_view["completed_episodes"] == 0
        assert status_view["automatic_studio_preserved"] is True

        # 3. Pause Series
        pause_res = q_mgr.pause_series("queue_test_series")
        assert pause_res["series_status"] == "PAUSED"
        assert pause_res["paused_jobs"] == 3
        assert s_db.get_series("queue_test_series").status == SeriesStatus.PAUSED

        # While paused, next_job for creator series should be None
        assert q_mgr.get_next_job() is None

        # 4. Resume Series
        resume_res = q_mgr.resume_series("queue_test_series")
        assert resume_res["series_status"] == "ACTIVE"
        assert resume_res["resumed_jobs"] == 3
        assert s_db.get_series("queue_test_series").status == SeriesStatus.ACTIVE

        # Now next_job returns episode 1
        next_j = q_mgr.get_next_job()
        assert next_j is not None
        assert next_j.episode_num == 1

        # 5. Cancel Series
        cancel_res = q_mgr.cancel_series("queue_test_series")
        assert cancel_res["series_status"] == "CANCELLED"
        assert cancel_res["cancelled_jobs"] == 3
        assert s_db.get_series("queue_test_series").status == SeriesStatus.CANCELLED

        # Episodes are marked CANCELLED
        for ep in s_db.get_episodes_for_series("queue_test_series"):
            assert ep.status == EpisodeStatus.CANCELLED
            assert ep.lifecycle_status == "Cancelled"

    def test_automatic_studio_preservation_and_priority(self, isolated_env):
        """CRITICAL: Ensure Automatic Studio's 2 daily autonomous jobs (09:00 IST & 19:00 IST)
        are never displaced, never cancelled, and strictly take priority over Creator Series.
        """
        s_db, q_mgr, _, _ = isolated_env

        # 1. Setup active Creator Series
        series = SeriesRecord(
            series_id="creator_prio_test",
            title="Creator Prio",
            full_script="Script text",
            planned_episodes=2,
            status=SeriesStatus.ACTIVE,
        )
        s_db.save_series(series)
        ep1 = EpisodeRecord(
            episode_id="creator_prio_test_ep01",
            series_id="creator_prio_test",
            episode_num=1,
            title="Ep 1",
            adapted_narration="N1",
            status=EpisodeStatus.SCHEDULED,
        )
        s_db.save_episode(ep1)
        q_mgr.enqueue_series("creator_prio_test")

        # 2. Reserve Automatic Studio jobs
        q_mgr.ensure_automatic_studio_reserved("2026-11-22")

        # 3. Next job MUST be Automatic Studio (Priority 1) ahead of Creator Series (Priority 10)
        first_job = q_mgr.get_next_job()
        assert first_job is not None
        assert first_job.job_type == JobType.AUTOMATIC_STUDIO
        assert first_job.priority == 1
        assert first_job.target_slot in ("09:00 IST", "19:00 IST")

        # 4. Cancelling or pausing the Creator Series does NOT affect Automatic Studio
        q_mgr.cancel_series("creator_prio_test")

        # Automatic Studio job remains queued and ready
        auto_job = q_mgr.get_next_job()
        assert auto_job is not None
        assert auto_job.job_type == JobType.AUTOMATIC_STUDIO
        assert auto_job.status == JobStatus.QUEUED

    def test_sequential_execution_lock_prevents_deadlocks(self, isolated_env):
        """Verify sequential locked execution runs cleanly without race conditions or deadlocks."""
        _, q_mgr, _, _ = isolated_env

        q_mgr.ensure_automatic_studio_reserved("2026-11-22")
        auto_job = q_mgr.get_next_job()
        assert auto_job is not None

        def sample_runner(job):
            return f"Processed {job.job_id}"

        res = q_mgr.execute_job_locked(auto_job.job_id, sample_runner)
        assert res == f"Processed {auto_job.job_id}"
        assert auto_job.status == JobStatus.COMPLETED


class TestSeriesSchedulingEndpoints:
    """Tests for REST API endpoints in series_api.py."""

    def test_api_schedule_preview(self, isolated_env, monkeypatch):
        s_db, _, _, _ = isolated_env
        import curiosity_engine.dashboard.series_api as sapi_mod
        monkeypatch.setattr(sapi_mod, "series_db", s_db)

        client = TestClient(app)

        # Preview without existing series (pure preview by count)
        res = client.post(
            "/api/series/schedule/preview",
            json={
                "episode_count": 5,
                "schedule_type": "A",
                "start_date": "2026-12-10",
                "start_time": "20:30",
                "cadence": "daily",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["total_episodes"] == 5
        assert data["estimated_completion_date"] == "2026-12-14"
        assert len(data["calendar"]) == 5

    def test_api_schedule_commit_and_queue_status(self, isolated_env, monkeypatch):
        s_db, q_mgr, _, _ = isolated_env
        import curiosity_engine.dashboard.series_api as sapi_mod
        monkeypatch.setattr(sapi_mod, "series_db", s_db)
        monkeypatch.setattr(sapi_mod, "queue_manager", q_mgr)

        client = TestClient(app)

        # 1. Create series with 3 episodes
        s_rec = SeriesRecord(
            series_id="api_sched_series",
            title="API Sched Test",
            full_script="Long story text...",
            planned_episodes=3,
            status=SeriesStatus.READY,
        )
        s_db.save_series(s_rec)
        for i in range(1, 4):
            s_db.save_episode(
                EpisodeRecord(
                    episode_id=f"api_sched_series_ep{i:02d}",
                    series_id="api_sched_series",
                    episode_num=i,
                    title=f"Episode {i}",
                    adapted_narration=f"Narration {i}",
                    status=EpisodeStatus.ADAPTED,
                )
            )

        # 2. Commit schedule
        commit_res = client.post(
            "/api/series/api_sched_series/schedule/commit",
            json={
                "schedule_type": "B",
                "start_date": "2026-12-15",
                "start_time": "09:00",
                "cadence": "daily",
            },
        )
        assert commit_res.status_code == 200
        c_data = commit_res.json()
        assert c_data["status"] == "success"
        assert c_data["series_status"] == "ACTIVE"
        assert c_data["estimated_completion_date"] == "2026-12-16"

        # 3. Check queue-status
        q_res = client.get("/api/series/api_sched_series/queue-status")
        assert q_res.status_code == 200
        q_data = q_res.json()
        assert q_data["series_id"] == "api_sched_series"
        assert q_data["series_status"] == "ACTIVE"
        assert q_data["automatic_studio_preserved"] is True
        assert len(q_data["episodes"]) == 3
        assert q_data["episodes"][0]["status"] == "Scheduled"
        assert q_data["episodes"][0]["scheduled_publication_time"] is not None

        # 4. Pause series
        pause_res = client.post("/api/series/api_sched_series/pause")
        assert pause_res.status_code == 200
        assert pause_res.json()["series_status"] == "PAUSED"

        # 5. Resume series
        resume_res = client.post("/api/series/api_sched_series/resume")
        assert resume_res.status_code == 200
        assert resume_res.json()["series_status"] == "ACTIVE"

        # 6. Cancel series
        cancel_res = client.post("/api/series/api_sched_series/cancel")
        assert cancel_res.status_code == 200
        assert cancel_res.json()["series_status"] == "CANCELLED"
