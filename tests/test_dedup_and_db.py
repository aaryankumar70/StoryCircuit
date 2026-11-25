"""Tests for SQLite store, multi-day plan queue, and anti-repeat deduplication."""
from __future__ import annotations

from reelforge.storage.db import ReelDatabase
from reelforge.storage.dedup import find_similar_match


def test_dedup_blocks_exact_and_near_duplicate_topics():
    history = [
        ("The 1914 Christmas Truce in the Trenches", "In December 1914 enemy soldiers stopped firing and sang carols in no man's land."),
    ]
    is_dup, _ = find_similar_match("The 1914 Christmas Truce in the Trenches!", "Different body", history)
    assert is_dup is True

    is_dup2, _ = find_similar_match("1914 Christmas Truce Trenches", "Short summary", history)
    assert is_dup2 is True

    is_dup3, _ = find_similar_match(
        "Voyager 1 Pale Blue Dot",
        "In 1990 NASA turned Voyager camera backward 3.7 billion miles from Earth.",
        history,
    )
    assert is_dup3 is False


def test_database_plan_queue_and_jobs(tmp_path):
    db = ReelDatabase(tmp_path / "test.db")
    p1 = db.add_plan_item(planned_date="2026-11-25", slot_num=1, topic="Antikythera Mechanism", style="vintage_archival")
    p2 = db.add_plan_item(planned_date="2026-11-25", slot_num=2, topic="Wow! Signal", custom_script="In 1977 a telescope heard 6EQUJ5.")

    due1 = db.get_due_plan_item("2026-11-25", 1)
    assert due1 is not None and due1["id"] == p1

    due2 = db.get_due_plan_item("2026-11-25", 2)
    assert due2 is not None and due2["id"] == p2 and "6EQUJ5" in due2["custom_script"]

    jid = db.create_job(
        source_mode="plan",
        title="Antikythera Mechanism",
        category="mystery",
        style="vintage_archival",
        script_text="Bronze gears recovered off Greece.",
        storyboard={"beats": []},
        scheduled_date="2026-11-25",
        slot_num=1,
        status="qc_passed",
    )
    db.update_job(jid, simulated=0, status="scheduled", youtube_id="yt123")
    assert db.count_live_uploads_for_date("2026-11-25") == 1
    assert "yt123" in db.claimed_youtube_ids()
