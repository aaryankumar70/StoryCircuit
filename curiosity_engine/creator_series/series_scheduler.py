"""Series Scheduling Planner for CurioLoop Creator Series (Step 5).

Provides flexible, timezone-aware schedule calculations and calendar generation:
- Timezone: Asia/Kolkata (IST = UTC+05:30) default
- Preset Schedules:
  * Schedule A: 1 episode per day (Evening slot, e.g., 20:30 IST)
  * Schedule B: 2 episodes per day (Morning 09:00 IST & Evening 20:30 IST)
  * Schedule C: Custom frequency / slot selection
- Cadence options: daily, alternate (every 2 days), custom intervals or days of week
- Calendar preview generator: Exact release datetimes per episode & estimated series completion date
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from curiosity_engine.creator_series.models import (
    EpisodeRecord,
    EpisodeStatus,
    SeriesRecord,
    SeriesStatus,
)
from curiosity_engine.creator_series.series_db import series_db

logger = logging.getLogger("curiosity_engine.series_scheduler")

DEFAULT_TIMEZONE = "Asia/Kolkata"
SCHEDULE_A_DEFAULT_TIME = "20:30"
SCHEDULE_B_MORNING_TIME = "09:00"
SCHEDULE_B_EVENING_TIME = "20:30"

WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY_ABBRS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def get_timezone(tz_name: Optional[str] = None) -> ZoneInfo:
    """Retrieve a timezone, rejecting invalid names instead of silently changing schedules."""
    name = tz_name or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except Exception as exc:
        raise ValueError(f"Unknown timezone '{name}'. Use an IANA timezone such as Asia/Kolkata.") from exc


def normalize_schedule_type(schedule_type: Optional[str]) -> str:
    """Normalize schedule preset type to 'A', 'B', or 'C'."""
    raw = str(schedule_type or "A").strip().upper()
    if raw not in {"A", "B", "C", "CUSTOM"}:
        raise ValueError("schedule_type must be A, B, or C.")
    return "C" if raw == "CUSTOM" else raw


def parse_time_str(time_str: str) -> Tuple[int, int]:
    """Parse 'HH:MM' string into (hour, minute)."""
    parts = str(time_str).strip().split(":")
    h = int(parts[0]) if len(parts) > 0 else 20
    m = int(parts[1]) if len(parts) > 1 else 30
    h = max(0, min(23, h))
    m = max(0, min(59, m))
    return h, m


class SeriesScheduler:
    """Calculates release schedules, previews calendar dates, and manages scheduling commitments."""

    def __init__(self, tz_name: str = DEFAULT_TIMEZONE, s_db: Optional[SeriesDatabase] = None):
        self.default_tz = get_timezone(tz_name)
        self._custom_s_db = s_db

    def _get_s_db(self, s_db_override: Optional[SeriesDatabase] = None) -> SeriesDatabase:
        if s_db_override is not None:
            return s_db_override
        if self._custom_s_db is not None:
            return self._custom_s_db
        import curiosity_engine.creator_series.series_db as sdb_mod
        return sdb_mod.series_db

    def generate_calendar_preview(
        self,
        series_id: Optional[str] = None,
        episode_count: Optional[int] = None,
        schedule_type: str = "A",
        start_date: Optional[Union[str, date]] = None,
        start_time: Optional[str] = None,
        timezone_name: str = DEFAULT_TIMEZONE,
        cadence: str = "daily",
        custom_slots: Optional[List[str]] = None,
        custom_days: Optional[List[str]] = None,
        interval_days: int = 1,
        min_lead_minutes: int = 15,
        s_db: Optional[SeriesDatabase] = None,
    ) -> Dict[str, Any]:
        """Generate a complete release calendar preview for a series or episode count.

        Args:
            series_id: Optional ID of an existing series to pull episodes and titles from.
            episode_count: Number of episodes to schedule. If None and series_id provided,
                           fetches episode count from the series records.
            schedule_type: 'A' (1/day evening), 'B' (2/day morning+evening), 'C' (custom).
            start_date: Start date string 'YYYY-MM-DD' or date object. If None, chooses
                        today if lead time allows, otherwise tomorrow in target timezone.
            start_time: Slot start time 'HH:MM'. Default depends on schedule_type.
            timezone_name: Target timezone string, default 'Asia/Kolkata'.
            cadence: 'daily', 'alternate' (every 2 days), or 'custom'.
            custom_slots: List of 'HH:MM' strings for custom schedule C.
            custom_days: List of day names (e.g. ['Monday', 'Wednesday']) for custom schedule C.
            interval_days: Custom day interval if cadence='custom' (default 1).
            min_lead_minutes: Minimum minutes in the future required from now.

        Returns:
            Dictionary containing series_id, schedule parameters, completion dates, and
            detailed calendar list for all episodes.
        """
        tz = get_timezone(timezone_name)
        now_local = datetime.now(tz)
        norm_type = normalize_schedule_type(schedule_type)

        if cadence not in {"daily", "alternate", "custom"}:
            raise ValueError("cadence must be daily, alternate, or custom")
        if int(interval_days) < 1:
            raise ValueError("interval_days must be at least 1")
        requested_times = list(custom_slots or [])
        if norm_type == "C":
            if not requested_times:
                requested_times = [start_time or SCHEDULE_A_DEFAULT_TIME]
            for value in requested_times:
                try:
                    h, m = (int(part) for part in str(value).split(":"))
                except Exception as exc:
                    raise ValueError(f"Invalid custom time '{value}'; expected HH:MM.") from exc
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError(f"Invalid custom time '{value}'; expected a 24-hour HH:MM time.")
        if start_time:
            try:
                h, m = (int(part) for part in start_time.split(":"))
            except Exception as exc:
                raise ValueError(f"Invalid start_time '{start_time}'; expected HH:MM.") from exc
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError(f"Invalid start_time '{start_time}'; expected a 24-hour HH:MM time.")

        # 1. Resolve existing episodes or count
        db = self._get_s_db(s_db)
        episodes_list: List[Dict[str, Any]] = []
        if series_id:
            db_episodes = db.get_episodes_for_series(series_id)
            if db_episodes:
                for ep in db_episodes:
                    episodes_list.append({
                        "episode_num": ep.episode_num,
                        "episode_id": ep.episode_id,
                        "title": ep.title,
                        "status": ep.lifecycle_status,
                        "estimated_duration": ep.estimated_duration,
                    })

        total_episodes = episode_count or len(episodes_list) or 1
        if len(episodes_list) < total_episodes:
            for i in range(len(episodes_list) + 1, total_episodes + 1):
                episodes_list.append({
                    "episode_num": i,
                    "episode_id": f"{series_id or 'series'}_ep{i:02d}",
                    "title": f"Episode {i}",
                    "status": "Planned",
                    "estimated_duration": 48.0,
                })

        # 2. Determine base start date
        if start_date:
            if isinstance(start_date, str):
                base_date = datetime.strptime(start_date.strip(), "%Y-%m-%d").date()
            else:
                base_date = start_date
        else:
            base_date = now_local.date()

        # 3. Determine slots & cadence step
        cadence_lower = str(cadence or "daily").strip().lower()
        if cadence_lower == "alternate":
            effective_interval = 2
        elif cadence_lower == "custom" and interval_days > 1:
            effective_interval = interval_days
        else:
            effective_interval = 1

        # 4. Compute episode release datetimes based on preset
        calendar_items: List[Dict[str, Any]] = []

        if norm_type == "A":
            # Preset Schedule A: 1 episode per day (Evening slot, 20:30 IST)
            effective_time = start_time or SCHEDULE_A_DEFAULT_TIME
            h, m = parse_time_str(effective_time)

            curr_date = base_date
            # Check lead time for first episode
            first_dt = datetime(curr_date.year, curr_date.month, curr_date.day, h, m, 0, tzinfo=tz)
            if not start_date and first_dt < (now_local + timedelta(minutes=min_lead_minutes)):
                curr_date = curr_date + timedelta(days=1)

            for idx in range(total_episodes):
                ep_date = curr_date + timedelta(days=idx * effective_interval)
                ep_dt = datetime(ep_date.year, ep_date.month, ep_date.day, h, m, 0, tzinfo=tz)
                ep_meta = episodes_list[idx] if idx < len(episodes_list) else {}
                calendar_items.append(
                    self._build_calendar_item(
                        episode_num=idx + 1,
                        episode_meta=ep_meta,
                        dt=ep_dt,
                        slot_label=f"Schedule A - Evening Slot ({h:02d}:{m:02d} IST)",
                    )
                )

        elif norm_type == "B":
            # Preset Schedule B: 2 episodes per day (Morning 09:00 IST & Evening 20:30 IST)
            morning_h, morning_m = parse_time_str(SCHEDULE_B_MORNING_TIME)
            evening_h, evening_m = parse_time_str(SCHEDULE_B_EVENING_TIME)

            start_evening_first = False
            if start_time:
                req_h, _ = parse_time_str(start_time)
                if req_h >= 12:
                    start_evening_first = True

            curr_date = base_date
            first_morning = datetime(curr_date.year, curr_date.month, curr_date.day, morning_h, morning_m, 0, tzinfo=tz)
            first_evening = datetime(curr_date.year, curr_date.month, curr_date.day, evening_h, evening_m, 0, tzinfo=tz)

            if not start_date:
                if now_local >= (first_evening - timedelta(minutes=min_lead_minutes)):
                    # Both slots passed today, move to tomorrow morning
                    curr_date = curr_date + timedelta(days=1)
                    start_evening_first = False
                elif now_local >= (first_morning - timedelta(minutes=min_lead_minutes)):
                    # Morning passed today, start evening
                    start_evening_first = True

            ep_idx = 0
            day_cursor = curr_date

            while ep_idx < total_episodes:
                # If day_cursor is active day
                # Slot 1 on this day (unless start_evening_first on day 0)
                if not (ep_idx == 0 and start_evening_first):
                    dt_m = datetime(day_cursor.year, day_cursor.month, day_cursor.day, morning_h, morning_m, 0, tzinfo=tz)
                    ep_meta = episodes_list[ep_idx] if ep_idx < len(episodes_list) else {}
                    calendar_items.append(
                        self._build_calendar_item(
                            episode_num=ep_idx + 1,
                            episode_meta=ep_meta,
                            dt=dt_m,
                            slot_label=f"Schedule B - Morning Slot ({morning_h:02d}:{morning_m:02d} IST)",
                        )
                    )
                    ep_idx += 1

                if ep_idx >= total_episodes:
                    break

                # Slot 2 on this day
                dt_e = datetime(day_cursor.year, day_cursor.month, day_cursor.day, evening_h, evening_m, 0, tzinfo=tz)
                ep_meta = episodes_list[ep_idx] if ep_idx < len(episodes_list) else {}
                calendar_items.append(
                    self._build_calendar_item(
                        episode_num=ep_idx + 1,
                        episode_meta=ep_meta,
                        dt=dt_e,
                        slot_label=f"Schedule B - Evening Slot ({evening_h:02d}:{evening_m:02d} IST)",
                    )
                )
                ep_idx += 1

                # Advance to next active day
                day_cursor = day_cursor + timedelta(days=effective_interval)

        else:
            # Preset Schedule C: Custom frequency / slot selection
            slots = custom_slots if (custom_slots and len(custom_slots) > 0) else [start_time or SCHEDULE_A_DEFAULT_TIME]
            slot_times = [parse_time_str(s) for s in slots]
            # sort slot times chronologically
            slot_times.sort(key=lambda x: (x[0], x[1]))

            norm_custom_days: Optional[set[int]] = None
            if custom_days:
                norm_custom_days = set()
                for d_str in custom_days:
                    d_clean = str(d_str).strip().lower()
                    matched = False
                    for idx, (name, abbr) in enumerate(zip(WEEKDAY_NAMES, WEEKDAY_ABBRS)):
                        if d_clean == name or d_clean == abbr:
                            norm_custom_days.add(idx)
                            matched = True
                    if not matched:
                        raise ValueError(f"Invalid custom day '{d_str}'; use a weekday name or abbreviation.")
                if not norm_custom_days:
                    raise ValueError("custom_days must contain at least one valid weekday.")

            ep_idx = 0
            day_cursor = base_date

            # If no custom days, advance by effective_interval days
            while ep_idx < total_episodes:
                # Check if day_cursor matches custom_days if specified
                if norm_custom_days is not None and day_cursor.weekday() not in norm_custom_days:
                    day_cursor = day_cursor + timedelta(days=1)
                    continue

                for h, m in slot_times:
                    if ep_idx >= total_episodes:
                        break
                    dt_slot = datetime(day_cursor.year, day_cursor.month, day_cursor.day, h, m, 0, tzinfo=tz)
                    ep_meta = episodes_list[ep_idx] if ep_idx < len(episodes_list) else {}
                    calendar_items.append(
                        self._build_calendar_item(
                            episode_num=ep_idx + 1,
                            episode_meta=ep_meta,
                            dt=dt_slot,
                            slot_label=f"Schedule C - Custom Slot ({h:02d}:{m:02d} IST)",
                        )
                    )
                    ep_idx += 1

                step = effective_interval if norm_custom_days is None else 1
                day_cursor = day_cursor + timedelta(days=step)

        # 5. Calculate estimated series completion date
        final_item = calendar_items[-1] if calendar_items else None
        if calendar_items:
            first_local = datetime.fromisoformat(calendar_items[0]["scheduled_datetime_ist"])
            if first_local < now_local + timedelta(minutes=min_lead_minutes):
                raise ValueError(f"First Creator release must be at least {min_lead_minutes} minutes in the future.")
        completion_date = final_item["date"] if final_item else base_date.strftime("%Y-%m-%d")
        completion_dt_ist = final_item["scheduled_datetime_ist"] if final_item else None
        completion_dt_utc = final_item["scheduled_datetime_utc"] if final_item else None

        preset_descriptions = {
            "A": "Schedule A: 1 episode per day (Evening slot, 20:30 IST)",
            "B": "Schedule B: 2 episodes per day (Morning 09:00 IST & Evening 20:30 IST)",
            "C": "Schedule C: Custom frequency / slot selection",
        }

        return {
            "status": "success",
            "series_id": series_id,
            "schedule_type": norm_type,
            "schedule_name": preset_descriptions.get(norm_type, "Custom"),
            "timezone": str(tz),
            "cadence": cadence,
            "total_episodes": total_episodes,
            "start_date": calendar_items[0]["date"] if calendar_items else base_date.strftime("%Y-%m-%d"),
            "start_time": calendar_items[0]["time"] if calendar_items else (start_time or "20:30"),
            "estimated_completion_date": completion_date,
            "estimated_completion_datetime_ist": completion_dt_ist,
            "estimated_completion_datetime_utc": completion_dt_utc,
            "calendar": calendar_items,
        }

    def _build_calendar_item(
        self,
        episode_num: int,
        episode_meta: Dict[str, Any],
        dt: datetime,
        slot_label: str,
    ) -> Dict[str, Any]:
        """Construct a standardized single episode calendar entry."""
        dt_utc = dt.astimezone(timezone.utc)
        round_trip = dt_utc.astimezone(dt.tzinfo).replace(tzinfo=None)
        if round_trip != dt.replace(tzinfo=None):
            raise ValueError(f"Scheduled local time {dt.isoformat()} does not exist because of a timezone clock change.")
        return {
            "episode_num": episode_num,
            "episode_id": episode_meta.get("episode_id", f"ep_{episode_num:02d}"),
            "title": episode_meta.get("title", f"Episode {episode_num}"),
            "date": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%H:%M"),
            "day_of_week": dt.strftime("%A"),
            "slot_label": slot_label,
            "scheduled_datetime_ist": dt.isoformat(),
            "scheduled_datetime_utc": dt_utc.isoformat(),
            "status": episode_meta.get("status", "Planned"),
            "estimated_duration": episode_meta.get("estimated_duration", 48.0),
        }

    def commit_series_schedule(
        self,
        series_id: str,
        schedule_config: Dict[str, Any],
        s_db: Optional[SeriesDatabase] = None,
    ) -> Dict[str, Any]:
        """Lock in publication schedule for a series, update episodes, and activate.

        Args:
            series_id: ID of the series to commit schedule for.
            schedule_config: Config options including schedule_type, start_date, start_time,
                             timezone, cadence, custom_slots, custom_days.
            s_db: Optional SeriesDatabase instance for isolation/testing.

        Returns:
            Committed schedule details with updated episode records.
        """
        db = self._get_s_db(s_db)
        series = db.get_series(series_id)
        if not series:
            raise ValueError(f"Series '{series_id}' does not exist.")

        episodes = db.get_episodes_for_series(series_id)
        if not episodes:
            raise ValueError(f"Series '{series_id}' has no episodes to schedule.")

        # Generate exact calendar preview
        preview = self.generate_calendar_preview(
            series_id=series_id,
            episode_count=len(episodes),
            schedule_type=schedule_config.get("schedule_type", "A"),
            start_date=schedule_config.get("start_date"),
            start_time=schedule_config.get("start_time"),
            timezone_name=schedule_config.get("timezone", DEFAULT_TIMEZONE),
            cadence=schedule_config.get("cadence", "daily"),
            custom_slots=schedule_config.get("custom_slots"),
            custom_days=schedule_config.get("custom_days"),
            s_db=db,
        )

        # Update Series publication schedule
        series.publication_schedule = {
            "schedule_type": preview["schedule_type"],
            "schedule_name": preview["schedule_name"],
            "start_date": preview["start_date"],
            "start_time": preview["start_time"],
            "timezone": preview["timezone"],
            "cadence": preview["cadence"],
            "estimated_completion_date": preview["estimated_completion_date"],
            "estimated_completion_datetime_ist": preview["estimated_completion_datetime_ist"],
            "committed_at": datetime.now(timezone.utc).isoformat(),
            "custom_slots": schedule_config.get("custom_slots"),
            "custom_days": schedule_config.get("custom_days"),
        }
        # Update each episode's scheduled_publication_time
        cal_map = {item["episode_num"]: item for item in preview["calendar"]}
        updated_episodes = []
        for ep in episodes:
            cal_info = cal_map.get(ep.episode_num)
            if cal_info:
                ep.scheduled_publication_time = cal_info["scheduled_datetime_ist"]
                # If episode is currently draft or adapted, mark as planned or ready for publishing
                if ep.status in (EpisodeStatus.DRAFT, EpisodeStatus.ADAPTED, EpisodeStatus.PLANNED):
                    ep.status = EpisodeStatus.SCHEDULED
            updated_episodes.append(ep)

        # Schedule details and every episode timestamp commit as one JSON transaction.
        series.status = SeriesStatus.ACTIVE
        db.save_series_and_episodes(series, updated_episodes)

        logger.info(
            f"Committed schedule for series '{series_id}' ({len(episodes)} episodes). "
            f"Estimated completion: {preview['estimated_completion_date']}."
        )

        return {
            "status": "success",
            "series_id": series_id,
            "series_status": series.status.value,
            "publication_schedule": series.publication_schedule,
            "total_episodes": len(updated_episodes),
            "estimated_completion_date": preview["estimated_completion_date"],
            "calendar": preview["calendar"],
            "episodes": [e.to_dict() for e in updated_episodes],
        }


series_scheduler = SeriesScheduler()
