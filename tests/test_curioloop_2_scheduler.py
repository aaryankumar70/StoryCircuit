"""Unit tests for CurioLoop 2.0 Scheduler enhancements and multi-day drift prevention."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest

from curiosity_engine.runner.local_scheduler import (
    IST,
    allocate_slot_publication_time,
    calculate_publication_times,
)


class TestCurioLoop2Scheduler:
    """Validates scheduler slot allocation, IST/UTC translations, and multi-day drift prevention."""

    def test_same_day_slot1_before_lead_threshold(self):
        """At 10:00 AM IST today, Slot 1 should be scheduled for today at 12:30 PM IST."""
        now = datetime(2026, 11, 21, 10, 0, 0, tzinfo=IST)
        pub_dt = allocate_slot_publication_time(1, now, occupied_by_date={}, tz=IST)
        assert pub_dt.year == 2026
        assert pub_dt.month == 11
        assert pub_dt.day == 21
        assert pub_dt.hour == 12
        assert pub_dt.minute == 30
        assert pub_dt.tzinfo == IST

    def test_same_day_slot2_after_slot1_passed(self):
        """At 2:00 PM IST today, Slot 2 should still be scheduled for today at 20:30 PM IST."""
        now = datetime(2026, 11, 21, 14, 0, 0, tzinfo=IST)
        pub_dt = allocate_slot_publication_time(2, now, occupied_by_date={}, tz=IST)
        assert pub_dt.year == 2026
        assert pub_dt.month == 11
        assert pub_dt.day == 21
        assert pub_dt.hour == 20
        assert pub_dt.minute == 30

    def test_same_day_alternate_slot_allocation(self):
        """When Slot 1 is requested at 1:00 PM IST (past 12:30), allow_same_day_alternate
        should allocate Slot 2 on the same day instead of jumping to tomorrow.
        """
        now = datetime(2026, 11, 21, 13, 0, 0, tzinfo=IST)
        pub_dt = allocate_slot_publication_time(
            1,
            now,
            occupied_by_date={},
            tz=IST,
            allow_same_day_alternate=True,
        )
        assert pub_dt.year == 2026
        assert pub_dt.month == 11
        assert pub_dt.day == 21
        assert pub_dt.hour == 20
        assert pub_dt.minute == 30

    def test_drift_prevention_advances_only_one_day_when_today_full(self):
        """When today has 2 slots occupied, Slot 1 must advance to tomorrow (exactly +1 day),
        NOT drift 2 or 3 days into the future.
        """
        now = datetime(2026, 11, 21, 9, 0, 0, tzinfo=IST)
        occupied = {"2026-11-21": {"12:30", "20:30"}}
        pub_dt = allocate_slot_publication_time(1, now, occupied_by_date=occupied, tz=IST)
        assert pub_dt.year == 2026
        assert pub_dt.month == 11
        assert pub_dt.day == 22  # Exactly tomorrow
        assert pub_dt.hour == 12
        assert pub_dt.minute == 30

    def test_target_date_parameter_preservation(self):
        """Explicitly targeting a specific calendar date (e.g., 2026-11-25) preserves that date."""
        now = datetime(2026, 11, 21, 9, 0, 0, tzinfo=IST)
        pub_dt = allocate_slot_publication_time(
            1,
            now,
            occupied_by_date={},
            tz=IST,
            target_date="2026-11-25",
        )
        assert pub_dt.year == 2026
        assert pub_dt.month == 11
        assert pub_dt.day == 25
        assert pub_dt.hour == 12
        assert pub_dt.minute == 30

    def test_utc_publish_at_iso_format(self):
        """Verify IST to UTC translation: 12:30 PM IST (UTC+5:30) is 07:00:00 UTC."""
        dt_ist = datetime(2026, 11, 21, 12, 30, 0, tzinfo=IST)
        dt_utc = dt_ist.astimezone(timezone.utc)
        assert dt_utc.hour == 7
        assert dt_utc.minute == 0
        assert dt_utc.isoformat() == "2026-11-21T07:00:00+00:00"
