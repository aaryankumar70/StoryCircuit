from datetime import datetime, timedelta, timezone

from curiosity_engine.creator_series.creator_queue import CreatorProductionQueue
from curiosity_engine.creator_series.queue_manager import JobType, ProductionQueueManager
from curiosity_engine.creator_series.models import EpisodeRecord, EpisodeStatus, SeriesRecord, SeriesStatus
from curiosity_engine.creator_series.pipeline_integration import get_slot2_content_choice
from curiosity_engine.creator_series.series_db import SeriesDatabase
from curiosity_engine.state.db import DatabaseClient


def test_creator_jobs_wait_for_due_time_and_use_dedicated_queue(tmp_path):
    db = DatabaseClient(custom_file=tmp_path / "isolated.json")
    series_db = SeriesDatabase(db_client=db)
    queue = CreatorProductionQueue(state_file=tmp_path / "creator_queue.json", s_db=series_db)
    scheduled = datetime(2026, 12, 1, 15, 0, tzinfo=timezone.utc)
    series = SeriesRecord(
        series_id="creator_due_series", title="Due time", full_script="A saved story",
        planned_episodes=1, episode_ids=["creator_due_ep01"], status=SeriesStatus.ACTIVE,
    )
    episode = EpisodeRecord(
        episode_id="creator_due_ep01", series_id=series.series_id, episode_num=1,
        title="Part one", adapted_narration="A story ending at the right time.",
        status=EpisodeStatus.SCHEDULED, is_approved=True,
        scheduled_publication_time=scheduled.isoformat(),
    )
    series_db.save_series(series)
    series_db.save_episode(episode)

    jobs = queue.enqueue_series(series.series_id)
    assert len(jobs) == 1
    assert jobs[0]["job_type"] == "CREATOR_SERIES"
    assert jobs[0]["not_before"] == (scheduled - timedelta(minutes=60)).isoformat()
    assert queue.claim_next_due(now=scheduled - timedelta(minutes=61)) is None
    claimed = queue.claim_next_due(now=scheduled - timedelta(minutes=60))
    assert claimed["job_id"] == jobs[0]["job_id"]
    assert claimed["status"] == "RUNNING"

    # Creator never claims Automatic Studio's second slot.
    assert get_slot2_content_choice() == ("automatic", None)


def test_creator_job_persisted_and_cancelled_without_affecting_auto_queue(tmp_path):
    state_file = tmp_path / "creator_queue.json"
    db = DatabaseClient(custom_file=tmp_path / "isolated.json")
    series_db = SeriesDatabase(db_client=db)
    queue = CreatorProductionQueue(state_file=state_file, s_db=series_db)
    series = SeriesRecord(
        series_id="creator_cancel_series", title="Cancel", full_script="A saved story",
        planned_episodes=1, episode_ids=["creator_cancel_ep01"], status=SeriesStatus.ACTIVE,
    )
    episode = EpisodeRecord(
        episode_id="creator_cancel_ep01", series_id=series.series_id, episode_num=1,
        title="Part one", adapted_narration="A story.", is_approved=True,
        scheduled_publication_time=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    )
    series_db.save_series(series)
    series_db.save_episode(episode)
    queue.enqueue_series(series.series_id)

    reloaded = CreatorProductionQueue(state_file=state_file, s_db=series_db)
    assert reloaded.get_series_jobs(series.series_id)[0]["status"] == "QUEUED"
    assert reloaded.cancel_series(series.series_id)["cancelled"] == 1
    assert reloaded.get_series_jobs(series.series_id)[0]["status"] == "CANCELLED"


def test_creator_and_automatic_queues_persist_independently(tmp_path):
    automatic_file = tmp_path / "production_queue.json"
    automatic = ProductionQueueManager(state_file=automatic_file)
    automatic.ensure_automatic_studio_reserved("2026-12-01")
    before = automatic_file.read_text(encoding="utf-8")

    creator = CreatorProductionQueue(state_file=tmp_path / "creator_series_queue.json")
    creator.set_series_paused("unrelated_series", True)

    assert automatic_file.read_text(encoding="utf-8") == before
    persisted = ProductionQueueManager(state_file=automatic_file)
    auto_jobs = [job for job in persisted._jobs.values() if job.job_type == JobType.AUTOMATIC_STUDIO]
    assert len(auto_jobs) == 2
    assert {job.target_slot for job in auto_jobs} == {"09:00 IST", "19:00 IST"}
