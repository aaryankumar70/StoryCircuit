from curiosity_engine.content.youtube_workflows import (
    channel_audit,
    channel_outliers,
    hook_score,
    retention_summary,
    title_pair_check,
    weekly_content_plan,
)


def test_hook_and_title_checks_are_lints_not_performance_predictions():
    hook = hook_score("Why did the archive list two different dates?")
    title = title_pair_check("Why the archive recorded two dates", "Dated clues")
    assert 0 <= hook["heuristic_score"] <= 100
    assert "not a predictor" in hook["note"].lower()
    assert title["issues"] == []
    assert "does not predict" in title["note"].lower()


def test_retention_summary_sorts_data_and_marks_descriptive_cliffs():
    report = retention_summary([(100, 21), (0, 100), (50, 42), (25, 61)], duration_sec=40)
    assert report["points"] == 4
    assert report["end_retention_pct"] == 21
    assert report["largest_cliffs"]
    assert "not why" in report["note"].lower()


def test_outliers_compare_only_within_channel_and_skip_bad_or_small_data():
    rows = [{"channel": "A", "title": f"Video {i}", "views": n} for i, n in enumerate([10, 12, 11, 100])]
    rows += [{"channel": "B", "views": "unknown"}, {"channel": "B", "views": 10}]
    report = channel_outliers(rows)
    assert report["outliers"][0]["title"] == "Video 3"
    assert any(row["channel"] == "B" for row in report["skipped_channels"])
    assert "not evidence" in report["note"].lower()


def test_weekly_plan_respects_actual_estimated_capacity():
    ideas = [{"topic": "One"}, {"topic": "Two"}, {"topic": "Three"}]
    two_hour = weekly_content_plan(ideas, 2)
    assert sum(x["hours_estimate"] for x in two_hour["planned_items"]) <= 2
    assert two_hour["planned_items"][0]["format"] == "short"
    six_hour = weekly_content_plan(ideas, 6, already_in_progress=["One"])
    assert sum(x["hours_estimate"] for x in six_hour["planned_items"]) <= 6
    assert all(x["topic"] != "One" for x in six_hour["planned_items"])


def test_channel_audit_does_not_invent_targets_or_use_nan():
    assert channel_audit({})["priority"] is None
    report = channel_audit({"average_view_percentage": float("nan")}, {"average_view_percentage": 50})
    assert report["priority"] == "gather_more_data"
