"""Autonomous Local Scheduler for Curiosity Engine.
Manages persistent execution records, locking, restart recovery,
date-aware availability-driven production, slot-independent retries,
read-only dry-run/validation diagnostics, and YouTube scheduled publishing
(status.publishAt) in Asia/Kolkata (IST) timezone.

Schedule:
  - First startup of day: Availability-driven batch production, QC, & private upload
  - Slot 1 publication: 12:30 PM IST (status.publishAt)
  - Slot 2 publication: 8:30 PM IST (status.publishAt)

Strict Constraints:
  - Strict ₹0 budget (no cloud deployment, no external hosting).
  - Asia/Kolkata timezone awareness.
  - Date-aware catch-up (never publishes stale videos from previous days).
  - Single-instance lock enforcement.
  - Independent of web dashboard.
  - Never marks SCHEDULED unless confirmed by real non-simulated YouTube API response.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from curiosity_engine import config
from curiosity_engine.config import (
    DATA_DIR,
    ENV_FILE,
    GEMINI_API_KEY,
    INSTAGRAM_PUBLISHING_MODE,
    KOKORO_DIR,
    MAX_DAILY_VIDEOS,
    OUTPUT_DIR,
    PROJECT_ROOT,
    SCHEDULER_GENERATE_TIME,
    SCHEDULER_PUBLISH_SLOT1_TIME,
    SCHEDULER_PUBLISH_SLOT2_TIME,
    SCHEDULER_TIMEZONE,
    WHISPER_DIR,
    YOUTUBE_PRIVACY_STATUS,
    YOUTUBE_PUBLISHING_MODE,
    get_chrome_executable,
)
from curiosity_engine.content.description_generator import (
    build_youtube_tags,
    generate_youtube_title,
)
from curiosity_engine.content.topic_discovery import select_daily_topics
from curiosity_engine.distribution.token_manager import token_manager
from curiosity_engine.distribution.youtube_analytics import performance_tracker
from curiosity_engine.distribution.youtube_publisher import (
    NON_PRODUCTION_TEST_YOUTUBE_IDS,
    YouTubeAuthError,
    youtube_publisher,
)
from curiosity_engine.notifications.telegram_notifier import get_telegram_notifier
from curiosity_engine.production.aligner import resolve_whisper_model_path
from curiosity_engine.production.renderer import validate_rendered_mp4
from curiosity_engine.runner.automation_state import automation_state
from curiosity_engine.runner.storage_cleanup import cleanup_old_generated_videos
from curiosity_engine.runner.pipeline import (
    _has_valid_project_assets,
    assert_daily_publication_capacity,
    assert_no_duplicate_mp4_upload,
    get_occupied_publication_windows,
    is_real_youtube_upload,
    is_slot_generation_complete,
    produce_single_video,
    run_daily_generation,
    run_slot_publishing,
)
from curiosity_engine.state.db import db

logger = logging.getLogger("curiosity_engine.scheduler")

IST = ZoneInfo(SCHEDULER_TIMEZONE)
SCHEDULER_STATE_FILE = DATA_DIR / "scheduler_state.json"
SCHEDULER_LOCK_FILE = DATA_DIR / ".scheduler.lock"
SCHEDULER_STOP_FILE = DATA_DIR / ".scheduler.stop"
LOG_FILE = DATA_DIR / "scheduler.log"


def calculate_publication_times(
    now_dt: datetime,
    slot1_time_str: str = SCHEDULER_PUBLISH_SLOT1_TIME,
    slot2_time_str: str = SCHEDULER_PUBLISH_SLOT2_TIME,
    tz: Optional[ZoneInfo] = None,
    min_lead_minutes: int = 15,
) -> Tuple[datetime, datetime]:
    """Calculate future scheduled publication datetimes in IST for Slot 1 and Slot 2.

    Rules:
    - Slot 1 target: 12:30 PM IST (configurable)
    - Slot 2 target: 8:30 PM IST (configurable)
    - Times must be at least min_lead_minutes in the future.
    - Before 12:15 PM: Slot 1 -> Today 12:30 PM, Slot 2 -> Today 8:30 PM
    - 12:15 PM–8:15 PM: Slot 1 -> Tomorrow 12:30 PM, Slot 2 -> Today 8:30 PM
    - After 8:15 PM: Slot 1 -> Tomorrow 12:30 PM, Slot 2 -> Tomorrow 8:30 PM
    """
    if tz is None:
        tz = IST

    s1_h, s1_m = [int(p) for p in slot1_time_str.split(":")]
    s2_h, s2_m = [int(p) for p in slot2_time_str.split(":")]
    lead = timedelta(minutes=min_lead_minutes)

    local_now = now_dt.astimezone(tz)
    today = local_now.date()
    tomorrow = today + timedelta(days=1)

    t1_today = datetime(today.year, today.month, today.day, s1_h, s1_m, 0, tzinfo=tz)
    t2_today = datetime(today.year, today.month, today.day, s2_h, s2_m, 0, tzinfo=tz)
    t1_tomorrow = datetime(tomorrow.year, tomorrow.month, tomorrow.day, s1_h, s1_m, 0, tzinfo=tz)
    t2_tomorrow = datetime(tomorrow.year, tomorrow.month, tomorrow.day, s2_h, s2_m, 0, tzinfo=tz)

    t1 = t1_today if local_now < (t1_today - lead) else t1_tomorrow
    t2 = t2_today if local_now < (t2_today - lead) else t2_tomorrow
    return t1, t2


def allocate_slot_publication_time(
    slot_index: int,
    now_dt: datetime,
    occupied_by_date: Optional[Dict[str, set[str]]] = None,
    slot1_time_str: str = SCHEDULER_PUBLISH_SLOT1_TIME,
    slot2_time_str: str = SCHEDULER_PUBLISH_SLOT2_TIME,
    tz: Optional[ZoneInfo] = None,
    min_lead_minutes: int = 15,
    max_per_day: int = MAX_DAILY_VIDEOS,
) -> datetime:
    """Find the earliest future IST slot datetime respecting the max daily publication limit
    and preserving each slot's canonical publication hour (12:30 IST for Slot 1, 20:30 IST for Slot 2).
    """
    if tz is None:
        tz = IST

    target_str = slot1_time_str if slot_index == 1 else slot2_time_str
    s_h, s_m = [int(p) for p in target_str.split(":")]
    slot_hhmm = f"{s_h:02d}:{s_m:02d}"
    lead = timedelta(minutes=min_lead_minutes)
    local_now = now_dt.astimezone(tz)
    base_date = local_now.date()
    occupied = occupied_by_date or {}

    for day_offset in range(0, 30):
        day = base_date + timedelta(days=day_offset)
        candidate = datetime(day.year, day.month, day.day, s_h, s_m, 0, tzinfo=tz)
        if candidate < (local_now + lead):
            continue
        date_key = day.strftime("%Y-%m-%d")
        day_slots = occupied.get(date_key, set())
        if len(day_slots) >= max_per_day:
            continue
        if slot_hhmm in day_slots:
            continue
        return candidate

    # Fallback (should never trigger within 30 days)
    t1, t2 = calculate_publication_times(now_dt, slot1_time_str, slot2_time_str, tz, min_lead_minutes)
    return t1 if slot_index == 1 else t2


class SchedulerLockError(Exception):
    """Raised when another scheduler instance is already running."""
    pass


class LocalScheduler:
    """Production-grade local scheduler with persistent state, slot-independent recovery,
    read-only dry-run & validation diagnostics, and YouTube scheduled-publishing (status.publishAt).
    """

    def __init__(
        self,
        state_file: Optional[Path] = None,
        lock_file: Optional[Path] = None,
        timezone_name: str = SCHEDULER_TIMEZONE,
    ):
        self.state_file = state_file or SCHEDULER_STATE_FILE
        self.lock_file = lock_file or SCHEDULER_LOCK_FILE
        self.tz = ZoneInfo(timezone_name)
        self.running = False
        self._state: Dict[str, Any] = self._load_state()
        self._setup_logging()

    def _setup_logging(self) -> None:
        """Attach persistent file handler only if root logger is not already logging to LOG_FILE."""
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            resolved_log = LOG_FILE.resolve()
            root_has_log = any(
                isinstance(h, logging.FileHandler) and Path(getattr(h, "baseFilename", "")).resolve() == resolved_log
                for h in logging.getLogger().handlers
            )
            logger_has_log = any(
                isinstance(h, logging.FileHandler) and Path(getattr(h, "baseFilename", "")).resolve() == resolved_log
                for h in logger.handlers
            )
            if not root_has_log and not logger_has_log:
                fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
                fh.setLevel(logging.INFO)
                fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
                logger.addHandler(fh)
        except Exception as e:
            logger.warning(f"Failed to attach file handler to scheduler logger: {e}")

    # -------------------------------------------------------------------------
    # State Persistence (Atomic)
    # -------------------------------------------------------------------------
    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load scheduler state ({e}); initializing fresh state.")
        return {
            "timezone": str(self.tz),
            "is_running": False,
            "pid": None,
            "last_heartbeat": None,
            "history": {},
            "missed_jobs": [],
            "last_error": None,
        }

    def _save_state(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.state_file.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, default=str)
            tmp_path.replace(self.state_file)
        except Exception as e:
            logger.error(f"Failed to persist scheduler state: {e}")

    # -------------------------------------------------------------------------
    # Process Locking & Safe Shutdown Signal
    # -------------------------------------------------------------------------
    def acquire_lock(self) -> None:
        """Acquire single-instance lock file with stale lock detection."""
        pid = os.getpid()
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_file.exists():
            try:
                content = self.lock_file.read_text(encoding="utf-8").strip()
                existing_pid = int(content) if content.isdigit() else None
                if existing_pid and self._is_pid_alive(existing_pid) and existing_pid != pid:
                    raise SchedulerLockError(
                        f"Another scheduler instance is already running with PID {existing_pid}."
                    )
                logger.info(f"Overriding stale scheduler lock (PID was {existing_pid}).")
            except ValueError:
                pass

        try:
            self.lock_file.write_text(str(pid), encoding="utf-8")
            atexit.register(self.release_lock)
        except Exception as e:
            raise SchedulerLockError(f"Failed to acquire lock file {self.lock_file}: {e}") from e

    def release_lock(self) -> None:
        """Remove lock file on process exit if owned by this process."""
        try:
            if self.lock_file.exists():
                content = self.lock_file.read_text(encoding="utf-8").strip()
                if content == str(os.getpid()):
                    self.lock_file.unlink(missing_ok=True)
        except Exception:
            pass

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Cross-platform check if process PID is running."""
        if pid <= 0:
            return False
        if sys.platform == "win32":
            try:
                import ctypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                STILL_ACTIVE = 259
                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
                if handle == 0:
                    return False
                try:
                    exit_code = ctypes.c_ulong()
                    ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                    if ok:
                        return exit_code.value == STILL_ACTIVE
                    return True
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)
            except Exception:
                return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    # -------------------------------------------------------------------------
    # Automation Toggle & Clock
    # -------------------------------------------------------------------------
    def is_automation_enabled(self) -> bool:
        """Check whether user has paused automation via dashboard toggle."""
        return automation_state.is_enabled()

    def now_ist(self) -> datetime:
        """Return current datetime in Asia/Kolkata timezone."""
        return datetime.now(self.tz)

    # -------------------------------------------------------------------------
    # Ground-Truth Reconciliation (Fixes stale RUNNING or phantom COMPLETED state)
    # -------------------------------------------------------------------------
    def reconcile_daily_state(self, date_str: str) -> Dict[str, Any]:
        """Reconcile automation_state.json for date_str against actual database & MP4 files.
        Never lets stale 'COMPLETED' without valid MP4 or stale 'RUNNING' persist blindly.
        Always preserves real YouTube upload IDs and API-confirmed schedules.
        """
        rec = automation_state.get_daily_record(date_str)
        clean_date = date_str.replace("-", "")
        updates: Dict[str, Any] = {}

        slot_completes: Dict[int, bool] = {}
        slot_sched_done: Dict[int, bool] = {}

        for slot_idx in (1, 2):
            slot_key = f"slot{slot_idx}"
            vid_id = f"video_{clean_date}_slot{slot_idx}"
            v_rec = db.get_video_record(vid_id)
            cur_slot = rec.get(slot_key, {})

            if not v_rec:
                # No DB record exists -> cannot possibly be COMPLETED
                slot_completes[slot_idx] = False
                slot_sched_done[slot_idx] = False
                if cur_slot.get("generation_status") in ("COMPLETED", "RUNNING") or cur_slot.get("qc_passed"):
                    logger.warning(
                        f"[{vid_id}] Reconciling stale automation state (DB record missing); resetting slot {slot_idx} to PENDING."
                    )
                    updates[slot_key] = {
                        "video_id": vid_id,
                        "generation_status": "PENDING",
                        "qc_passed": False,
                        "qc_results": None,
                        "upload_status": "NOT_STARTED",
                        "youtube_video_id": None,
                        "youtube_simulated": True,
                        "scheduled_status": "NOT_SCHEDULED",
                        "scheduled_publish_at": None,
                        "scheduled_publish_at_ist": None,
                        "error": None,
                    }
                continue

            # DB record exists -> inspect genuine MP4 + QC status
            gen_done = is_slot_generation_complete(vid_id)
            slot_completes[slot_idx] = gen_done
            real_yt = is_real_youtube_upload(v_rec)
            yt_id = v_rec.get("youtube_upload_id")
            sched_confirmed = bool(v_rec.get("schedule_confirmed") and real_yt and v_rec.get("scheduled_publish_at"))
            slot_sched_done[slot_idx] = sched_confirmed

            if gen_done:
                slot_upd: Dict[str, Any] = {
                    "video_id": vid_id,
                    "generation_status": "COMPLETED",
                    "qc_passed": True,
                    "qc_results": v_rec.get("qc_results"),
                    "error": None if v_rec.get("publishing_status") != "PUBLISH_FAILED" else v_rec.get("youtube_error"),
                }
                if real_yt:
                    slot_upd["upload_status"] = "UPLOADED_PRIVATE" if not sched_confirmed else "UPLOADED_PRIVATE"
                    slot_upd["youtube_video_id"] = yt_id
                    slot_upd["youtube_simulated"] = False
                    if sched_confirmed:
                        slot_upd["scheduled_status"] = "SCHEDULED"
                        slot_upd["scheduled_publish_at"] = v_rec.get("scheduled_publish_at")
                        slot_upd["scheduled_publish_at_ist"] = v_rec.get("scheduled_publish_at_ist")
                    elif cur_slot.get("scheduled_status") == "SCHEDULED":
                        slot_upd["scheduled_status"] = "NOT_SCHEDULED"
                elif yt_id and v_rec.get("youtube_simulated"):
                    slot_upd["upload_status"] = "SIMULATED"
                    slot_upd["youtube_video_id"] = yt_id
                    slot_upd["youtube_simulated"] = True
                    slot_upd["scheduled_status"] = "SIMULATED"
                    slot_upd["scheduled_publish_at"] = None
                    slot_upd["scheduled_publish_at_ist"] = None
                    if v_rec.get("intended_publish_at"):
                        slot_upd["intended_publish_at"] = v_rec.get("intended_publish_at")
                        slot_upd["intended_publish_at_ist"] = v_rec.get("intended_publish_at_ist")
                updates[slot_key] = slot_upd
            else:
                prod_st = v_rec.get("production_status", "PENDING")
                reconciled_gen = "FAILED" if prod_st in ("FAILED", "REJECTED_QC") else "INTERRUPTED" if prod_st in ("STARTING", "SCRIPTED", "ASSETS_READY", "RENDERED") else "PENDING"
                updates[slot_key] = {
                    "video_id": vid_id,
                    "generation_status": reconciled_gen,
                    "qc_passed": False,
                    "qc_results": v_rec.get("qc_results"),
                    "error": v_rec.get("error"),
                }

        # Generation overall status
        if slot_completes[1] and slot_completes[2]:
            gen_status = "COMPLETED"
        elif slot_completes[1] or slot_completes[2]:
            gen_status = "PARTIAL"
        elif updates.get("slot1", {}).get("generation_status") in ("FAILED", "INTERRUPTED") or updates.get("slot2", {}).get("generation_status") in ("FAILED", "INTERRUPTED"):
            gen_status = "INTERRUPTED"
        else:
            gen_status = "PENDING"

        updates["generation"] = (
            {"status": gen_status, "error": None}
            if gen_status == "COMPLETED"
            else {"status": gen_status}
        )
        if sched_sched_complete(slot_sched_done):
            updates["overall_status"] = "COMPLETED"
        elif slot_completes[1] or slot_completes[2]:
            updates["overall_status"] = "PARTIAL"
        elif rec.get("overall_status") == "RUNNING":
            updates["overall_status"] = "INTERRUPTED"

        if updates:
            return automation_state.update_daily_record(date_str, updates)
        return rec

    # -------------------------------------------------------------------------
    # Strict Read-Only Dry Run & Configuration Validation (Part 3 & Part 7)
    # -------------------------------------------------------------------------
    def evaluate_dry_run(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """Strict READ-ONLY evaluation of what scheduler would do right now.
        Makes ZERO DB writes, ZERO automation_state writes, ZERO file modifications,
        ZERO Gemini/YouTube upload/schedule calls, and ZERO renders.
        """
        now = self.now_ist()
        today_str = target_date or now.strftime("%Y-%m-%d")
        clean_date = today_str.replace("-", "")

        raw_state = automation_state._load_raw()
        enabled = bool(raw_state.get("enabled", True))
        working_occupied = {k: set(v) for k, v in get_occupied_publication_windows().items()}
        pub_s1 = allocate_slot_publication_time(1, now, occupied_by_date=working_occupied, tz=self.tz)
        working_occupied.setdefault(pub_s1.strftime("%Y-%m-%d"), set()).add(pub_s1.strftime("%H:%M"))
        pub_s2 = allocate_slot_publication_time(2, now, occupied_by_date=working_occupied, tz=self.tz)
        pub_times = {1: pub_s1, 2: pub_s2}

        gemini_configured = bool(GEMINI_API_KEY and len(GEMINI_API_KEY.strip()) > 10)
        slots_plan: Dict[str, Any] = {}
        global_blockers: List[str] = []

        if not enabled:
            global_blockers.append("Automation is currently PAUSED by user/dashboard toggle.")
        if not gemini_configured:
            global_blockers.append("Gemini API key unavailable; topic discovery uses curated fallback.")

        for slot_idx in (1, 2):
            vid_id = f"video_{clean_date}_slot{slot_idx}"
            v_rec = db.get_video_record(vid_id)
            output_mp4 = OUTPUT_DIR / f"{vid_id}.mp4"
            project_dir = OUTPUT_DIR / vid_id
            actions: List[str] = []
            blockers: List[str] = []

            mp4_exists = output_mp4.exists()
            mp4_valid = False
            mp4_error = None
            if mp4_exists:
                try:
                    validate_rendered_mp4(output_mp4)
                    mp4_valid = True
                except Exception as e:
                    mp4_error = str(e)

            assets_ready = _has_valid_project_assets(project_dir)
            qc_passed = bool(v_rec and v_rec.get("qc_passed") and mp4_valid)
            real_yt = is_real_youtube_upload(v_rec)
            yt_id = v_rec.get("youtube_upload_id") if v_rec else None
            schedule_confirmed = bool(v_rec and v_rec.get("schedule_confirmed") and real_yt)

            # Determine planned actions without mutating anything
            if not enabled:
                actions.append("SKIP_AUTOMATION_PAUSED")
            else:
                if qc_passed:
                    actions.append("SKIP_GENERATION_REUSE_QC_PASSED_VIDEO")
                elif mp4_valid and v_rec and v_rec.get("script"):
                    actions.append("RESUME_QC_ON_VALID_MP4")
                elif assets_ready and v_rec and v_rec.get("script"):
                    actions.append("RESUME_RENDER_FROM_EXISTING_ASSETS")
                else:
                    actions.append("GENERATE_SCRIPT_ASSETS_RENDER_AND_QC")

                # Upload & scheduling decision
                if YOUTUBE_PUBLISHING_MODE == "live":
                    if real_yt and schedule_confirmed:
                        actions.append(f"SKIP_UPLOAD_AND_SCHEDULE_CONFIRMED ({yt_id} @ {v_rec.get('scheduled_publish_at_ist')})")
                    elif real_yt and not schedule_confirmed:
                        actions.append(f"RETRY_SCHEDULE_ONLY_USING_EXISTING_ID ({yt_id} -> {pub_times[slot_idx].strftime('%Y-%m-%d %H:%M IST')})")
                    else:
                        actions.append(
                            f"UPLOAD_LIVE_PRIVATE_AND_SCHEDULE ({pub_times[slot_idx].strftime('%Y-%m-%d %H:%M IST')})"
                        )
                else:
                    if yt_id and v_rec and v_rec.get("youtube_simulated"):
                        actions.append("SKIP_SIMULATED_UPLOAD_ALREADY_DONE")
                    else:
                        actions.append(
                            f"SIMULATE_PRIVATE_UPLOAD_AND_PREVIEW_SCHEDULE ({pub_times[slot_idx].strftime('%Y-%m-%d %H:%M IST')})"
                        )

            slots_plan[f"slot{slot_idx}"] = {
                "video_id": vid_id,
                "db_record_exists": bool(v_rec),
                "topic": v_rec.get("topic") if v_rec else None,
                "production_status": v_rec.get("production_status") if v_rec else "NOT_STARTED",
                "assets_ready": assets_ready,
                "mp4_exists": mp4_exists,
                "mp4_valid": mp4_valid,
                "mp4_error": mp4_error,
                "qc_passed": qc_passed,
                "youtube_upload_id": yt_id,
                "youtube_real": real_yt,
                "schedule_confirmed": schedule_confirmed,
                "scheduled_publish_at_utc": pub_times[slot_idx].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "scheduled_publish_at_ist": pub_times[slot_idx].isoformat(),
                "intended_actions": actions,
                "blockers": blockers,
            }

        return {
            "dry_run": True,
            "read_only": True,
            "timestamp_ist": now.isoformat(),
            "target_date": today_str,
            "automation_enabled": enabled,
            "youtube_publishing_mode": YOUTUBE_PUBLISHING_MODE,
            "youtube_privacy_status": YOUTUBE_PRIVACY_STATUS,
            "instagram_publishing_mode": INSTAGRAM_PUBLISHING_MODE,
            "gemini_configured": gemini_configured,
            "fallback_mode": None if gemini_configured else "curated_catalog",
            "global_blockers": global_blockers,
            "slots": slots_plan,
        }

    def validate_environment(self, check_oauth_network: bool = True) -> Dict[str, Any]:
        """Read-only validation of local configuration, executables, models, OAuth, and disk."""
        checks: Dict[str, Any] = {}
        warnings: List[str] = []
        errors: List[str] = []

        # 1. Environment file
        checks["env_file_exists"] = ENV_FILE.exists()
        if not ENV_FILE.exists():
            warnings.append(f".env file not found at {ENV_FILE}")

        # 2. Chrome/Edge binary
        chrome_bin = get_chrome_executable()
        chrome_ok = Path(chrome_bin).exists() or shutil.which(chrome_bin) is not None
        checks["chrome_executable"] = chrome_bin
        checks["chrome_available"] = chrome_ok
        if not chrome_ok:
            errors.append(f"Chrome/Edge binary not found: {chrome_bin}")

        # 3. Node.js / FFmpeg / FFprobe
        for binary in ("node", "ffmpeg", "ffprobe"):
            found = shutil.which(binary)
            checks[f"{binary}_path"] = found
            checks[f"{binary}_available"] = bool(found)
            if not found:
                errors.append(f"Required executable '{binary}' not found on PATH.")

        # 4. Kokoro TTS model files
        kokoro_onnx = KOKORO_DIR / "kokoro-v1.0.onnx"
        kokoro_voices = KOKORO_DIR / "voices-v1.0.bin"
        checks["kokoro_ready"] = kokoro_onnx.exists() and kokoro_voices.exists()
        if not checks["kokoro_ready"]:
            errors.append(f"Kokoro TTS files missing in {KOKORO_DIR}")

        # 5. Whisper alignment model + fallback readiness
        whisper_path = resolve_whisper_model_path(WHISPER_DIR)
        checks["whisper_model_path"] = whisper_path
        checks["whisper_available"] = bool(whisper_path)
        checks["inline_alignment_fallback"] = True
        if not whisper_path:
            warnings.append(f"Local Whisper model.bin not found under {WHISPER_DIR}; inline timing fallback active.")

        # 6. Gemini API (optional free tier + curated fallback)
        gemini_ok = bool(GEMINI_API_KEY and len(GEMINI_API_KEY.strip()) > 10)
        checks["gemini_configured"] = gemini_ok
        checks["curated_fallback_ready"] = True
        if not gemini_ok:
            warnings.append("GEMINI_API_KEY not configured; using verified curated topic fallback (0 cost).")

        # 7. YouTube OAuth health & scopes
        if check_oauth_network:
            yt_health = token_manager.check_youtube_health()
        else:
            yt_health = token_manager.get_summary().get("youtube", {})
        checks["youtube_oauth"] = yt_health
        if not yt_health.get("healthy"):
            warnings.append(f"YouTube OAuth not healthy: {yt_health.get('status')} ({yt_health.get('alert')})")
        elif yt_health.get("can_update_schedule") is False:
            warnings.append(yt_health.get("scope_warning", "Missing youtube.force-ssl scope for videos.update"))

        # 8. Publishing safety policies
        checks["youtube_mode"] = YOUTUBE_PUBLISHING_MODE
        checks["youtube_privacy"] = YOUTUBE_PRIVACY_STATUS
        checks["instagram_mode"] = INSTAGRAM_PUBLISHING_MODE
        if YOUTUBE_PRIVACY_STATUS == "public":
            warnings.append("YOUTUBE_PRIVACY_STATUS is set to 'public' (default safe setting is 'private').")

        # 9. Disk space
        try:
            usage = shutil.disk_usage(PROJECT_ROOT)
            free_gb = round(usage.free / (1024 ** 3), 2)
            checks["disk_free_gb"] = free_gb
            if free_gb < 2.0:
                warnings.append(f"Low disk space on {PROJECT_ROOT.drive or PROJECT_ROOT}: {free_gb} GB remaining.")
        except Exception:
            checks["disk_free_gb"] = None

        # 10. Windows Startup status
        try:
            from scripts.manage_windows_task import get_task_status
            checks["windows_startup"] = get_task_status()
        except Exception as e:
            warnings.append(f"Windows task status query failed: {e}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "checks": checks,
        }

    # -------------------------------------------------------------------------
    # Phase 3 & 4: Availability-Driven Batch Production & Scheduled Publishing
    # -------------------------------------------------------------------------
    def _execute_slot_upload_and_schedule(
        self,
        date_str: str,
        slot_idx: int,
        vid_id: str,
        v_rec: Dict[str, Any],
        target_pub_dt: datetime,
        oauth_ok: bool,
        oauth_err_msg: Optional[str],
    ) -> Dict[str, Any]:
        """Upload (if needed) and confirm API-scheduled publication for a single QC-passed production slot."""
        slot_key = f"slot{slot_idx}"
        rec = automation_state.get_daily_record(date_str)
        current_slot_state = rec.get(slot_key, {})
        target_pub_utc = target_pub_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        yt_id = v_rec.get("youtube_upload_id") or current_slot_state.get("youtube_video_id")
        has_real_yt = is_real_youtube_upload(v_rec)
        needs_upload = (
            not has_real_yt
            if YOUTUBE_PUBLISHING_MODE == "live"
            else not bool(yt_id)
        )

        # 2a. Upload (never re-uploading if a real YouTube ID is already linked)
        if needs_upload:
            if YOUTUBE_PUBLISHING_MODE == "live" and not oauth_ok:
                logger.error(f"[{vid_id}] Skipping live upload: {oauth_err_msg}")
                return automation_state.update_daily_record(date_str, {
                    slot_key: {"upload_status": "FAILED", "error": oauth_err_msg}
                })

            mp4_path = Path(v_rec.get("local_video_path") or (OUTPUT_DIR / f"{vid_id}.mp4"))
            if not mp4_path.exists():
                logger.error(f"Local MP4 not found for {vid_id} at {mp4_path}")
                return automation_state.update_daily_record(date_str, {
                    slot_key: {"upload_status": "FAILED", "error": f"MP4 file not found: {mp4_path}"}
                })

            script = v_rec.get("script", {})
            title = v_rec.get("youtube_title") or generate_youtube_title(
                v_rec.get("topic", "Curiosity Explainer"),
                script,
                duration_sec=v_rec.get("duration_sec"),
            )
            desc = v_rec.get("youtube_description") or script.get("description", title)
            tags = v_rec.get("youtube_tags") or build_youtube_tags(
                v_rec.get("topic", title), v_rec.get("category", "Education"), script
            )

            logger.info(
                f"[{vid_id}] Uploading Slot {slot_idx} to YouTube "
                f"(Mode: {YOUTUBE_PUBLISHING_MODE}, Privacy: private, Target: {target_pub_dt.strftime('%Y-%m-%d %H:%M IST')})..."
            )
            try:
                mp4_sha256: Optional[str] = None
                if YOUTUBE_PUBLISHING_MODE == "live":
                    mp4_sha256 = assert_no_duplicate_mp4_upload(mp4_path, vid_id)
                    assert_daily_publication_capacity(
                        target_pub_dt,
                        candidate_video_id=vid_id,
                        candidate_yt_id=yt_id,
                    )

                all_vids = db.get_all_videos(limit=100)
                if not isinstance(all_vids, list):
                    all_vids = []
                other_real_yt_ids = set(NON_PRODUCTION_TEST_YOUTUBE_IDS) | {
                    str(r.get("youtube_upload_id"))
                    for r in all_vids
                    if isinstance(r, dict) and r.get("video_id") != vid_id and is_real_youtube_upload(r)
                }

                upload_res = youtube_publisher.upload_short(
                    video_path=mp4_path,
                    title=title,
                    description=desc,
                    tags=tags,
                    privacy_status="private",
                    publish_at=target_pub_dt,
                    exclude_youtube_ids=other_real_yt_ids,
                )
                yt_id = upload_res.get("video_id")
                yt_sim = bool(upload_res.get("simulated", False))
                sched_confirmed = bool(upload_res.get("schedule_confirmed") and not yt_sim)

                v_rec["youtube_upload_id"] = yt_id
                v_rec["youtube_url"] = upload_res.get("url")
                v_rec["youtube_simulated"] = yt_sim
                v_rec["youtube_privacy_status"] = "private" if not yt_sim else upload_res.get("privacy_status", "simulation_private")
                v_rec["youtube_published_at"] = upload_res.get("published_at")
                v_rec["schedule_confirmed"] = sched_confirmed

                if yt_sim:
                    v_rec["youtube_status"] = "SIMULATED"
                    v_rec["publishing_status"] = "SIMULATED"
                    v_rec["intended_publish_at"] = target_pub_utc
                    v_rec["intended_publish_at_ist"] = target_pub_dt.isoformat()
                    db.save_video_record(vid_id, v_rec)

                    rec = automation_state.update_daily_record(date_str, {
                        slot_key: {
                            "upload_status": "SIMULATED",
                            "youtube_video_id": yt_id,
                            "youtube_simulated": True,
                            "scheduled_status": "SIMULATED",
                            "scheduled_publish_at": None,
                            "scheduled_publish_at_ist": None,
                            "intended_publish_at": target_pub_utc,
                            "intended_publish_at_ist": target_pub_dt.isoformat(),
                            "error": None,
                        }
                    })
                else:
                    if mp4_sha256:
                        v_rec["mp4_sha256"] = mp4_sha256
                    v_rec["youtube_status"] = "SCHEDULED" if sched_confirmed else "UPLOADED_PRIVATE"
                    v_rec["publishing_status"] = "SCHEDULED" if sched_confirmed else "UPLOADED_PRIVATE"
                    if sched_confirmed:
                        v_rec["scheduled_publish_at"] = upload_res.get("publish_at", target_pub_utc)
                        v_rec["scheduled_publish_at_ist"] = target_pub_dt.isoformat()
                    db.save_video_record(vid_id, v_rec)

                    rec = automation_state.update_daily_record(date_str, {
                        slot_key: {
                            "upload_status": "UPLOADED_PRIVATE",
                            "youtube_video_id": yt_id,
                            "youtube_simulated": False,
                            "scheduled_status": "SCHEDULED" if sched_confirmed else "NOT_SCHEDULED",
                            "scheduled_publish_at": v_rec.get("scheduled_publish_at"),
                            "scheduled_publish_at_ist": v_rec.get("scheduled_publish_at_ist"),
                            "error": None,
                        }
                    })
                    try:
                        get_telegram_notifier().notify_upload_completed(
                            video_id=vid_id,
                            title=title,
                            youtube_id=str(yt_id or ""),
                            upload_status="SCHEDULED" if sched_confirmed else "UPLOADED_PRIVATE",
                            scheduled_time_ist=target_pub_dt.strftime("%Y-%m-%d %H:%M IST") if sched_confirmed else "",
                            youtube_url=str(v_rec.get("youtube_url") or ""),
                            simulated=False,
                        )
                    except Exception:
                        pass
                logger.info(f"[{vid_id}] Upload completed (ID={yt_id}, simulated={yt_sim}, schedule_confirmed={sched_confirmed}).")
            except Exception as e:
                logger.error(f"[{vid_id}] YouTube upload failed: {e}")
                v_rec["youtube_status"] = "FAILED"
                v_rec["publishing_status"] = "PUBLISH_FAILED"
                v_rec["error"] = str(e)
                db.save_video_record(vid_id, v_rec)
                err_lower = str(e).lower()
                if isinstance(e, YouTubeAuthError) or "invalid_grant" in err_lower or "revoked" in err_lower:
                    self._handle_oauth_failure(str(e), "REVOKED_OR_EXPIRED")
                else:
                    fail_type = "YOUTUBE_REJECTION" if "rejected" in err_lower else "UPLOAD_FAILURE"
                    try:
                        get_telegram_notifier().notify_failure(
                            failure_type=fail_type,
                            title=f"Upload failed for {vid_id}",
                            detail=str(e),
                            video_id=vid_id,
                        )
                    except Exception:
                        pass
                return automation_state.update_daily_record(date_str, {
                    slot_key: {"upload_status": "FAILED", "error": str(e)}
                })
        else:
            logger.info(f"[{vid_id}] Existing upload verified ({yt_id}, real={has_real_yt}). Skipping re-upload.")

        # Refresh v_rec state after upload step
        v_rec = db.get_video_record(vid_id) or v_rec
        yt_id = v_rec.get("youtube_upload_id") or yt_id
        has_real_yt = is_real_youtube_upload(v_rec)
        already_confirmed = bool(v_rec.get("schedule_confirmed") and has_real_yt)

        # 3. API-Confirmed Scheduling step for real private uploads lacking confirmation
        if has_real_yt and not already_confirmed:
            logger.info(
                f"[{vid_id}] Confirming/setting scheduled publication for real ID {yt_id} at "
                f"{target_pub_dt.strftime('%Y-%m-%d %H:%M')} IST ({target_pub_utc})..."
            )
            try:
                assert_daily_publication_capacity(
                    target_pub_dt,
                    candidate_video_id=vid_id,
                    candidate_yt_id=yt_id,
                )

                existing_api_st = None
                if YOUTUBE_PUBLISHING_MODE == "live":
                    existing_api_st = youtube_publisher.get_video_status(yt_id)

                if existing_api_st and existing_api_st.get("publish_at") and existing_api_st.get("privacy_status") == "private":
                    v_rec["scheduled_publish_at"] = existing_api_st["publish_at"]
                    v_rec["scheduled_publish_at_ist"] = target_pub_dt.isoformat()
                    v_rec["youtube_status"] = "SCHEDULED"
                    v_rec["publishing_status"] = "SCHEDULED"
                    v_rec["schedule_confirmed"] = True
                    db.save_video_record(vid_id, v_rec)
                    rec = automation_state.update_daily_record(date_str, {
                        slot_key: {
                            "upload_status": "UPLOADED_PRIVATE",
                            "youtube_video_id": yt_id,
                            "youtube_simulated": False,
                            "scheduled_status": "SCHEDULED",
                            "scheduled_publish_at": existing_api_st["publish_at"],
                            "scheduled_publish_at_ist": target_pub_dt.isoformat(),
                            "error": None,
                        }
                    })
                    logger.info(f"[{vid_id}] Verified existing API schedule: {existing_api_st['publish_at']}")
                else:
                    sched_res = youtube_publisher.schedule_publication(
                        video_id=yt_id,
                        publish_at=target_pub_dt,
                        force_mode="live",
                    )
                    if sched_res.get("schedule_confirmed") and not sched_res.get("simulated", False):
                        v_rec["scheduled_publish_at"] = sched_res.get("publish_at", target_pub_utc)
                        v_rec["scheduled_publish_at_ist"] = target_pub_dt.isoformat()
                        v_rec["youtube_status"] = "SCHEDULED"
                        v_rec["publishing_status"] = "SCHEDULED"
                        v_rec["schedule_confirmed"] = True
                        db.save_video_record(vid_id, v_rec)
                        rec = automation_state.update_daily_record(date_str, {
                            slot_key: {
                                "upload_status": "UPLOADED_PRIVATE",
                                "youtube_video_id": yt_id,
                                "youtube_simulated": False,
                                "scheduled_status": "SCHEDULED",
                                "scheduled_publish_at": v_rec["scheduled_publish_at"],
                                "scheduled_publish_at_ist": v_rec["scheduled_publish_at_ist"],
                                "error": None,
                            }
                        })
                        logger.info(f"[{vid_id}] YouTube API confirmed schedule at {v_rec['scheduled_publish_at']}")
                        try:
                            sched_title = str(v_rec.get("youtube_title") or (v_rec.get("script") or {}).get("title") or vid_id)
                            get_telegram_notifier().notify_upload_completed(
                                video_id=vid_id,
                                title=sched_title,
                                youtube_id=str(yt_id or ""),
                                upload_status="SCHEDULED",
                                scheduled_time_ist=target_pub_dt.strftime("%Y-%m-%d %H:%M IST"),
                                youtube_url=str(v_rec.get("youtube_url") or f"https://www.youtube.com/shorts/{yt_id}"),
                                simulated=False,
                            )
                        except Exception:
                            pass
                    else:
                        raise RuntimeError(f"YouTube API did not confirm schedule: {sched_res}")
            except Exception as e:
                logger.error(f"[{vid_id}] Failed to schedule publication: {e}")
                v_rec["youtube_status"] = "UPLOADED_PRIVATE"
                v_rec["publishing_status"] = "UPLOADED_PRIVATE"
                v_rec["schedule_confirmed"] = False
                v_rec["error"] = str(e)
                db.save_video_record(vid_id, v_rec)
                err_lower = str(e).lower()
                if isinstance(e, YouTubeAuthError) or "invalid_grant" in err_lower or "revoked" in err_lower:
                    self._handle_oauth_failure(str(e), "REVOKED_OR_EXPIRED")
                else:
                    fail_type = "YOUTUBE_REJECTION" if "rejected" in err_lower else "SCHEDULE_FAILURE"
                    try:
                        get_telegram_notifier().notify_failure(
                            failure_type=fail_type,
                            title=f"Scheduling failed for {vid_id}",
                            detail=str(e),
                            video_id=vid_id,
                            youtube_id=str(yt_id or ""),
                        )
                    except Exception:
                        pass
                rec = automation_state.update_daily_record(date_str, {
                    slot_key: {"scheduled_status": "FAILED", "error": str(e)}
                })

        return rec

    def process_daily_automation(
        self,
        target_date: Optional[str] = None,
        force_rebuild: bool = False,
    ) -> Dict[str, Any]:
        """Availability-driven batch production & YouTube scheduled publishing for today (IST)."""
        now = self.now_ist()
        today_str = target_date or now.strftime("%Y-%m-%d")
        clean_date = today_str.replace("-", "")

        logger.info(f"=== Starting Daily Automation for Date: {today_str} (force_rebuild={force_rebuild}) ===")

        if not self.is_automation_enabled() and not force_rebuild:
            logger.info("Daily automation is currently PAUSED. Skipping batch run.")
            return automation_state.get_daily_record(today_str)

        if not force_rebuild:
            rec = self.reconcile_daily_state(today_str)
        else:
            rec = automation_state.get_daily_record(today_str)

        v1_id = f"video_{clean_date}_slot1"
        v2_id = f"video_{clean_date}_slot2"

        # If completely finished AND verified against ground-truth, skip zero-work
        v1_ready = (not force_rebuild) and is_slot_generation_complete(v1_id)
        v2_ready = (not force_rebuild) and is_slot_generation_complete(v2_id)
        v1_db = db.get_video_record(v1_id)
        v2_db = db.get_video_record(v2_id)

        both_scheduled_or_sim = (
            rec.get("overall_status") == "COMPLETED"
            and v1_ready
            and v2_ready
            and (
                (v1_db and v1_db.get("schedule_confirmed") and v2_db and v2_db.get("schedule_confirmed"))
                if YOUTUBE_PUBLISHING_MODE == "live"
                else (v1_db and v1_db.get("youtube_upload_id") and v2_db and v2_db.get("youtube_upload_id"))
            )
        )
        if both_scheduled_or_sim and not force_rebuild:
            logger.info(f"Daily automation for {today_str} already verified COMPLETE. No duplicate actions needed.")
            return rec

        # ---------------------------------------------------------------------
        # Stage 1: Slot-Independent Generation & Independent QC
        # ---------------------------------------------------------------------
        missing_slots = []
        if force_rebuild or not v1_ready:
            missing_slots.append(1)
        if force_rebuild or not v2_ready:
            missing_slots.append(2)

        if missing_slots:
            automation_state.update_daily_record(today_str, {
                "overall_status": "RUNNING",
                "generation": {
                    "status": "RUNNING",
                    "started_at": now.isoformat(),
                    "error": None,
                },
            })

            logger.info(f"Initiating slot-independent generation for incomplete slots: {missing_slots}...")
            res1, res2 = run_daily_generation(
                target_date=today_str,
                force_rebuild=force_rebuild,
                slots=missing_slots,
            )

            updates: Dict[str, Any] = {}
            for s_idx, v_id, res in ((1, v1_id, res1), (2, v2_id, res2)):
                s_key = f"slot{s_idx}"
                if res and is_slot_generation_complete(v_id):
                    if s_idx == 1:
                        v1_db, v1_ready = res, True
                    else:
                        v2_db, v2_ready = res, True
                    updates[s_key] = {
                        "video_id": v_id,
                        "generation_status": "COMPLETED",
                        "qc_passed": True,
                        "qc_results": res.get("qc_results"),
                        "error": None,
                    }
                elif s_idx in missing_slots:
                    if s_idx == 1:
                        v1_ready = False
                    else:
                        v2_ready = False
                    err_msg = (res.get("error") if res else f"Slot {s_idx} generation failed")
                    updates[s_key] = {
                        "video_id": v_id,
                        "generation_status": "FAILED",
                        "qc_passed": False,
                        "error": str(err_msg),
                    }
                    try:
                        get_telegram_notifier().notify_failure(
                            failure_type="VIDEO_PROCESSING_FAILURE",
                            title=f"Generation/QC failed for {v_id}",
                            detail=str(err_msg),
                            video_id=v_id,
                        )
                    except Exception:
                        pass

            gen_status = "COMPLETED" if (v1_ready and v2_ready) else ("PARTIAL" if (v1_ready or v2_ready) else "FAILED")
            updates["generation"] = {
                "status": gen_status,
                "completed_at": self.now_ist().isoformat(),
                "retries": rec.get("generation", {}).get("retries", 0),
                "error": None if gen_status == "COMPLETED" else "One or more slots failed production/QC",
            }
            rec = automation_state.update_daily_record(today_str, updates)
        else:
            logger.info("Both slots already generated and passed QC (MP4s verified). Skipping generation stage.")
            rec = automation_state.update_daily_record(today_str, {
                "overall_status": "RUNNING",
                "generation": {
                    "status": "COMPLETED",
                    "completed_at": rec.get("generation", {}).get("completed_at") or now.isoformat(),
                    "error": None,
                },
                "slot1": {"video_id": v1_id, "generation_status": "COMPLETED", "qc_passed": True},
                "slot2": {"video_id": v2_id, "generation_status": "COMPLETED", "qc_passed": True},
            })

        # ---------------------------------------------------------------------
        # Stage 2 & 3: Overdue Chronological Catch-Up + Today's Publishing
        # ---------------------------------------------------------------------
        working_occupied = {k: set(v) for k, v in get_occupied_publication_windows().items()}

        def _resolve_target_dt(slot_idx: int, v_rec: Optional[Dict[str, Any]], cur_slot: Dict[str, Any]) -> datetime:
            existing_pub_utc = (v_rec or {}).get("scheduled_publish_at") or cur_slot.get("scheduled_publish_at")
            if existing_pub_utc and (v_rec or {}).get("schedule_confirmed"):
                try:
                    parsed_dt = datetime.fromisoformat(str(existing_pub_utc).replace("Z", "+00:00"))
                    if parsed_dt > datetime.now(timezone.utc):
                        chosen = parsed_dt.astimezone(self.tz)
                        working_occupied.setdefault(chosen.strftime("%Y-%m-%d"), set()).add(chosen.strftime("%H:%M"))
                        return chosen
                except Exception:
                    pass
            chosen = allocate_slot_publication_time(
                slot_idx,
                self.now_ist(),
                occupied_by_date=working_occupied,
                tz=self.tz,
            )
            working_occupied.setdefault(chosen.strftime("%Y-%m-%d"), set()).add(chosen.strftime("%H:%M"))
            return chosen

        # Pre-flight OAuth refresh in live mode so expired credentials fail fast cleanly
        config.sync_env_if_updated()
        youtube_publisher.refresh_credentials_if_changed()
        oauth_ok = True
        oauth_err_msg = None
        if YOUTUBE_PUBLISHING_MODE == "live":
            try:
                health = token_manager.check_youtube_health()
                if not health.get("healthy"):
                    oauth_ok = False
                    oauth_err_msg = health.get("alert") or f"OAuth unhealthy: {health.get('status')}"
                    if health.get("status") == "REVOKED_OR_EXPIRED" or health.get("reauth_required"):
                        self._handle_oauth_failure(oauth_err_msg, str(health.get("status")))
                elif health.get("warning_24h_due"):
                    try:
                        get_telegram_notifier().notify_oauth_expiry_warning(
                            hours_remaining=float(health.get("hours_until_expiry", 0.0)),
                            estimated_reauth_ist=str(health.get("estimated_reauth_date_ist", "")),
                            date_str=today_str,
                        )
                    except Exception:
                        pass
            except Exception as e:
                oauth_ok = False
                oauth_err_msg = str(e)

        # Process any overdue completed production work (since 2026-11-10) in strict chronological order first
        if YOUTUBE_PUBLISHING_MODE == "live" and oauth_ok:
            all_vids_overdue = db.get_all_videos(limit=200)
            if isinstance(all_vids_overdue, list):
                overdue_recs = [
                    r for r in all_vids_overdue
                    if isinstance(r, dict)
                    and "2026-11-10" <= str(r.get("target_date") or "") < today_str
                    and r.get("production_status") == "COMPLETED"
                    and r.get("qc_passed") is True
                    and not (r.get("schedule_confirmed") and r.get("scheduled_publish_at"))
                    and r.get("publishing_status") != "PUBLISHED"
                    and not r.get("is_test")
                ]
                overdue_recs.sort(key=lambda r: (str(r.get("target_date", "")), int(r.get("slot_index", 1))))
                for od_rec in overdue_recs:
                    od_slot_idx = int(od_rec.get("slot_index", 1))
                    od_vid_id = str(od_rec.get("video_id"))
                    od_date = str(od_rec.get("target_date"))
                    od_dt = allocate_slot_publication_time(
                        od_slot_idx,
                        self.now_ist(),
                        occupied_by_date=working_occupied,
                        tz=self.tz,
                    )
                    working_occupied.setdefault(od_dt.strftime("%Y-%m-%d"), set()).add(od_dt.strftime("%H:%M"))
                    logger.info(
                        f"Processing overdue production work chronologically first: {od_vid_id} -> "
                        f"{od_dt.strftime('%Y-%m-%d %H:%M IST')}"
                    )
                    self._execute_slot_upload_and_schedule(
                        date_str=od_date,
                        slot_idx=od_slot_idx,
                        vid_id=od_vid_id,
                        v_rec=od_rec,
                        target_pub_dt=od_dt,
                        oauth_ok=oauth_ok,
                        oauth_err_msg=oauth_err_msg,
                    )

        pub_slot1_dt = _resolve_target_dt(1, v1_db, rec.get("slot1", {}))
        pub_slot2_dt = _resolve_target_dt(2, v2_db, rec.get("slot2", {}))
        slots_to_process = [
            (1, v1_id, v1_db, v1_ready, pub_slot1_dt),
            (2, v2_id, v2_db, v2_ready, pub_slot2_dt),
        ]
        # Process earliest scheduled publication slot first chronologically
        slots_to_process.sort(key=lambda item: (item[4], item[0]))

        for slot_idx, vid_id, v_rec, ready, target_pub_dt in slots_to_process:
            if not ready or not v_rec:
                logger.warning(f"Skipping upload/schedule for Slot {slot_idx} (video not ready or failed QC).")
                continue
            rec = self._execute_slot_upload_and_schedule(
                date_str=today_str,
                slot_idx=slot_idx,
                vid_id=vid_id,
                v_rec=v_rec,
                target_pub_dt=target_pub_dt,
                oauth_ok=oauth_ok,
                oauth_err_msg=oauth_err_msg,
            )

        # Finalize Overall Status truthfully
        s1_state = rec.get("slot1", {})
        s2_state = rec.get("slot2", {})
        s1_done = s1_state.get("scheduled_status") in ("SCHEDULED", "SIMULATED") if YOUTUBE_PUBLISHING_MODE != "live" else (s1_state.get("scheduled_status") == "SCHEDULED")
        s2_done = s2_state.get("scheduled_status") in ("SCHEDULED", "SIMULATED") if YOUTUBE_PUBLISHING_MODE != "live" else (s2_state.get("scheduled_status") == "SCHEDULED")

        if s1_done and s2_done:
            final_status = "COMPLETED"
        elif s1_done or s2_done or v1_ready or v2_ready:
            final_status = "PARTIAL"
        else:
            final_status = "FAILED"

        rec = automation_state.update_daily_record(today_str, {"overall_status": final_status})
        logger.info(f"=== Daily Automation for {today_str} Finished. Final Status: {final_status} ===")
        return rec

    # -------------------------------------------------------------------------
    # Phase 5: Independent Failure Recovery & Retry
    # -------------------------------------------------------------------------
    def retry_slot(self, slot_index: int, target_date: Optional[str] = None) -> Dict[str, Any]:
        """Retry a specific slot (1 or 2) safely without re-running or overwriting the sibling slot."""
        if slot_index not in (1, 2):
            raise ValueError(f"Invalid slot_index: {slot_index}. Must be 1 or 2.")

        today_str = target_date or self.now_ist().strftime("%Y-%m-%d")
        clean_date = today_str.replace("-", "")
        vid_id = f"video_{clean_date}_slot{slot_index}"
        slot_key = f"slot{slot_index}"

        logger.info(f"Retrying Slot {slot_index} ({vid_id}) for date {today_str}...")

        rec = automation_state.get_daily_record(today_str)
        slot_state = rec.get(slot_key, {})

        # 1. If slot video is incomplete, recover ONLY this slot using run_daily_generation(slots=[slot_index])
        if not is_slot_generation_complete(vid_id):
            try:
                res1, res2 = run_daily_generation(target_date=today_str, force_rebuild=False, slots=[slot_index])
                v_rec = res1 if slot_index == 1 else res2
                if v_rec and is_slot_generation_complete(vid_id):
                    rec = automation_state.update_daily_record(today_str, {
                        slot_key: {
                            "video_id": vid_id,
                            "generation_status": "COMPLETED",
                            "qc_passed": True,
                            "qc_results": v_rec.get("qc_results"),
                            "retry_count": slot_state.get("retry_count", 0) + 1,
                            "error": None,
                        }
                    })
                else:
                    err = (v_rec.get("error") if v_rec else "Slot generation/QC incomplete")
                    automation_state.update_daily_record(today_str, {
                        slot_key: {"generation_status": "FAILED", "qc_passed": False, "error": str(err)}
                    })
                    return automation_state.get_daily_record(today_str)
            except Exception as e:
                logger.error(f"Retry generation failed for {vid_id}: {e}")
                automation_state.update_daily_record(today_str, {
                    slot_key: {"generation_status": "FAILED", "error": str(e)}
                })
                return automation_state.get_daily_record(today_str)

        # 2. Complete upload/scheduling for remaining pending stages without touching completed slots
        return self.process_daily_automation(target_date=today_str)

    # -------------------------------------------------------------------------
    # Catch-Up & Daemon Execution
    # -------------------------------------------------------------------------
    def run_catchup_check(self) -> List[Dict[str, Any]]:
        """Evaluate missed jobs for today upon scheduler startup."""
        now = self.now_ist()
        today_str = now.strftime("%Y-%m-%d")

        if not self.is_automation_enabled():
            logger.info("Automation is currently PAUSED. Skipping startup catch-up.")
            return []

        logger.info(f"Executing availability-driven catch-up check for {today_str}...")
        res = self.process_daily_automation(target_date=today_str)
        return [res]

    def compute_next_execution(self) -> Dict[str, Any]:
        """Compute next upcoming scheduled publication window in IST."""
        now = self.now_ist()
        t1, t2 = calculate_publication_times(now, tz=self.tz)
        future_times = [t for t in (t1, t2) if t > now]
        next_dt = min(future_times) if future_times else min(t1, t2)
        eta = max(0, int((next_dt - now).total_seconds()))
        return {
            "slot": "scheduled_publication",
            "target_date": next_dt.strftime("%Y-%m-%d"),
            "scheduled_ist": next_dt.isoformat(),
            "eta_seconds": eta,
            "human_eta": f"{eta // 3600}h {(eta % 3600) // 60}m",
        }

    def get_telemetry(self) -> Dict[str, Any]:
        """Return rich, truthful scheduler telemetry for dashboard display (read-only)."""
        now = self.now_ist()
        today_str = now.strftime("%Y-%m-%d")
        clean_date = today_str.replace("-", "")

        is_alive = False
        pid = None
        if self.lock_file.exists():
            try:
                pid_str = self.lock_file.read_text(encoding="utf-8").strip()
                if pid_str.isdigit():
                    pid = int(pid_str)
                    is_alive = self._is_pid_alive(pid)
            except Exception:
                is_alive = False

        # Windows Task Status
        from scripts.manage_windows_task import get_task_status
        win_status = get_task_status()

        # Reconcile read-only view against DB so dashboard never shows stale phantom COMPLETED claims
        raw_state = automation_state._load_raw()
        today_rec = raw_state.get("daily_records", {}).get(today_str) or automation_state.get_daily_record(today_str)
        next_exec = self.compute_next_execution()

        # Derive last successful production and last successful real/sim upload from DB
        all_vids = db.get_all_videos(limit=50)
        last_prod = next((v for v in all_vids if v.get("production_status") == "COMPLETED" and v.get("qc_passed")), None)
        last_real_upload = next((v for v in all_vids if is_real_youtube_upload(v)), None)
        last_any_upload = next((v for v in all_vids if v.get("youtube_upload_id")), None)

        last_execution = None
        if last_prod:
            last_execution = {
                "slot": f"Slot {last_prod.get('slot_index', 1)} ({last_prod.get('video_id')})",
                "status": last_prod.get("production_status"),
                "executed_at": last_prod.get("updated_at") or last_prod.get("created_at") or "",
            }

        return {
            "is_running": is_alive,
            "pid": pid,
            "automation_enabled": self.is_automation_enabled(),
            "oauth_paused": bool(raw_state.get("oauth_paused", False)),
            "oauth_pause_reason": raw_state.get("oauth_pause_reason"),
            "timezone": SCHEDULER_TIMEZONE,
            "current_time_ist": now.strftime("%Y-%m-%d %H:%M:%S IST"),
            "production_date": today_str,
            "windows_task": win_status,
            "today_automation": today_rec,
            "next_execution": next_exec,
            "last_execution": last_execution,
            "last_successful_production": {
                "video_id": last_prod.get("video_id"),
                "topic": last_prod.get("topic"),
                "timestamp": last_prod.get("updated_at"),
            } if last_prod else None,
            "last_successful_upload": {
                "video_id": (last_real_upload or last_any_upload).get("video_id"),
                "youtube_id": (last_real_upload or last_any_upload).get("youtube_upload_id"),
                "simulated": not bool(last_real_upload),
                "timestamp": (last_real_upload or last_any_upload).get("youtube_published_at")
                or (last_real_upload or last_any_upload).get("published_at"),
            } if (last_real_upload or last_any_upload) else None,
            "youtube_mode": YOUTUBE_PUBLISHING_MODE,
            "youtube_privacy": YOUTUBE_PRIVACY_STATUS,
            "instagram_mode": INSTAGRAM_PUBLISHING_MODE,
            "last_heartbeat": self._state.get("last_heartbeat"),
            "last_error": self._state.get("last_error"),
        }

    # -------------------------------------------------------------------------
    # Operational Hardening: OAuth Lifecycle, Public Verification, Daily Summary
    # -------------------------------------------------------------------------
    def _handle_oauth_failure(self, reason: str, status_code: str = "REVOKED_OR_EXPIRED") -> None:
        """Safely pause new automation on OAuth rejection/expiry while preserving schedules."""
        reason_lower = str(reason or "").lower()
        is_terminal_auth = status_code in ("REVOKED_OR_EXPIRED", "AUTH_FAILED") or any(
            m in reason_lower for m in ("invalid_grant", "revoked", "expired", "unauthorized")
        )
        if is_terminal_auth:
            automation_state.pause_for_oauth(reason)
            self._state["last_error"] = reason
            self._save_state()
            try:
                get_telegram_notifier().notify_oauth_rejected(reason)
            except Exception as exc:
                logger.warning("Telegram notify_oauth_rejected isolated error: %s", exc)

    def check_oauth_lifecycle_and_notify(self) -> Dict[str, Any]:
        """Validate OAuth health, fire 24h expiry warning, or auto-pause on revocation."""
        config.sync_env_if_updated()
        youtube_publisher.refresh_credentials_if_changed()
        if YOUTUBE_PUBLISHING_MODE != "live":
            return token_manager.get_summary().get("youtube", {})

        health = token_manager.check_youtube_health()
        self._state["last_oauth_health_check"] = self.now_ist().isoformat()
        self._save_state()

        if health.get("healthy"):
            if health.get("warning_24h_due"):
                try:
                    get_telegram_notifier().notify_oauth_expiry_warning(
                        hours_remaining=float(health.get("hours_until_expiry", 0.0)),
                        estimated_reauth_ist=str(health.get("estimated_reauth_date_ist", "")),
                        date_str=self.now_ist().strftime("%Y-%m-%d"),
                    )
                except Exception as exc:
                    logger.warning("Telegram 24h OAuth warning isolated error: %s", exc)
        elif health.get("status") == "REVOKED_OR_EXPIRED" or health.get("reauth_required"):
            self._handle_oauth_failure(
                str(health.get("alert") or "YouTube OAuth refresh token revoked or expired."),
                str(health.get("status") or "REVOKED_OR_EXPIRED"),
            )
        return health

    def verify_scheduled_publications(self) -> Dict[str, int]:
        """Inspect scheduled live videos whose publishAt passed and notify ONLY when truly public."""
        counts = {"checked": 0, "confirmed_public": 0, "rejected": 0, "missed": 0}
        if YOUTUBE_PUBLISHING_MODE != "live" and youtube_publisher.service is None:
            return counts

        config.sync_env_if_updated()
        youtube_publisher.refresh_credentials_if_changed()

        now_utc = datetime.now(timezone.utc)
        now_ist = now_utc.astimezone(self.tz)
        today_str = now_ist.strftime("%Y-%m-%d")
        notifier = get_telegram_notifier()

        all_vids = db.get_all_videos(limit=100)
        if not isinstance(all_vids, list):
            return counts

        for v_rec in all_vids:
            if not isinstance(v_rec, dict):
                continue
            if not is_real_youtube_upload(v_rec):
                continue
            yt_id = str(v_rec.get("youtube_upload_id") or "")
            vid_id = str(v_rec.get("video_id") or "")
            if not yt_id or not vid_id or yt_id in NON_PRODUCTION_TEST_YOUTUBE_IDS or v_rec.get("is_test"):
                continue
            if v_rec.get("youtube_published_public_confirmed") is True or v_rec.get("publishing_status") == "PUBLISHED":
                continue

            sched_utc_str = v_rec.get("scheduled_publish_at")
            if not sched_utc_str:
                continue
            try:
                sched_dt = datetime.fromisoformat(str(sched_utc_str).replace("Z", "+00:00"))
                if sched_dt.tzinfo is None:
                    sched_dt = sched_dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            # Wait until scheduled publishAt timestamp has been reached
            if sched_dt > now_utc:
                continue

            counts["checked"] += 1
            try:
                api_status = youtube_publisher.get_video_status(yt_id)
            except YouTubeAuthError as auth_err:
                self._handle_oauth_failure(str(auth_err), "REVOKED_OR_EXPIRED")
                break
            except Exception as exc:
                logger.warning("Failed checking publication status for %s (%s): %s", vid_id, yt_id, exc)
                continue

            if not api_status:
                continue

            privacy = str(api_status.get("privacy_status") or "").lower()
            upload_st = str(api_status.get("upload_status") or "").lower()
            rejection = api_status.get("rejection_reason")
            title = str(api_status.get("title") or (v_rec.get("script") or {}).get("title") or v_rec.get("topic") or vid_id)

            if rejection or upload_st in ("rejected", "failed"):
                counts["rejected"] += 1
                v_rec["youtube_status"] = "REJECTED"
                v_rec["publishing_status"] = "REJECTED"
                v_rec["youtube_rejection_reason"] = rejection or upload_st
                db.save_video_record(vid_id, v_rec)
                notifier.notify_failure(
                    failure_type="YOUTUBE_REJECTION",
                    title=f"YouTube rejected video: {title}",
                    detail=f"uploadStatus={upload_st}, rejectionReason={rejection}",
                    video_id=vid_id,
                    youtube_id=yt_id,
                    dedup_key=f"yt_rejected:{yt_id}",
                )
            elif privacy == "public":
                counts["confirmed_public"] += 1
                pub_ist_str = now_ist.strftime("%Y-%m-%d %H:%M IST")
                v_rec["youtube_privacy_status"] = "public"
                v_rec["youtube_status"] = "PUBLISHED"
                v_rec["publishing_status"] = "PUBLISHED"
                v_rec["youtube_published_public_confirmed"] = True
                v_rec["youtube_published_public_at"] = now_utc.isoformat()
                db.save_video_record(vid_id, v_rec)

                t_date = str(v_rec.get("target_date") or "")
                s_idx = int(v_rec.get("slot_index") or 0)
                if t_date and s_idx in (1, 2):
                    try:
                        automation_state.update_daily_record(
                            t_date,
                            {
                                f"slot{s_idx}": {
                                    "privacy_status": "public",
                                    "published_public_confirmed": True,
                                    "published_public_at": v_rec["youtube_published_public_at"],
                                }
                            },
                        )
                    except Exception:
                        pass

                notifier.notify_publication_success(
                    video_id=vid_id,
                    title=title,
                    youtube_id=yt_id,
                    published_at_ist=pub_ist_str,
                    privacy_status="public",
                )
            elif (now_utc - sched_dt).total_seconds() >= 1800:
                counts["missed"] += 1
                notifier.notify_failure(
                    failure_type="MISSED_PUBLICATION",
                    title=f"Scheduled publication delayed/missed for {title}",
                    detail=f"privacyStatus is still '{privacy}' 30+ min past publishAt={sched_utc_str}",
                    video_id=vid_id,
                    youtube_id=yt_id,
                    dedup_key=f"missed_pub:{yt_id}:{today_str}",
                )

        return counts

    def maybe_send_daily_summary(self, force_hour_check: bool = True) -> Optional[Dict[str, Any]]:
        """Send one Telegram daily operational summary per IST day after configured summary hour."""
        now_ist = self.now_ist()
        if force_hour_check and now_ist.hour < config.TELEGRAM_DAILY_SUMMARY_HOUR_IST:
            return None

        today_str = now_ist.strftime("%Y-%m-%d")
        all_vids = db.get_all_videos(limit=100)
        if not isinstance(all_vids, list):
            all_vids = []

        today_vids = [v for v in all_vids if isinstance(v, dict) and v.get("target_date") == today_str and not v.get("is_test")]
        prod_count = sum(1 for v in today_vids if v.get("production_status") == "COMPLETED")
        pub_count = sum(
            1 for v in today_vids
            if is_real_youtube_upload(v) and str(v.get("youtube_privacy_status") or "").lower() == "public"
        )

        now_utc = datetime.now(timezone.utc)
        upcoming: List[Tuple[datetime, str]] = []
        sched_pending = 0
        for v in all_vids:
            if not isinstance(v, dict) or not is_real_youtube_upload(v):
                continue
            if str(v.get("youtube_upload_id") or "") in NON_PRODUCTION_TEST_YOUTUBE_IDS or v.get("is_test"):
                continue
            pub_str = v.get("scheduled_publish_at")
            if pub_str and v.get("youtube_privacy_status") != "public":
                try:
                    dt = datetime.fromisoformat(str(pub_str).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt > now_utc:
                        sched_pending += 1
                        upcoming.append((dt.astimezone(self.tz), str(v.get("video_id"))))
                except Exception:
                    pass

        upcoming.sort(key=lambda item: item[0])
        next_sched_str = (
            f"{upcoming[0][0].strftime('%Y-%m-%d %H:%M IST')} ({upcoming[0][1]})"
            if upcoming
            else "None queued"
        )

        yt_health = token_manager.get_summary().get("youtube", {})
        oauth_status = str(yt_health.get("status") or "UNKNOWN")
        reauth_ist = str(yt_health.get("estimated_reauth_date_ist") or "Unknown")
        last_err = str(self._state.get("last_error") or "")

        prod_failures_count = sum(
            1 for v in today_vids
            if v.get("production_status") in ("FAILED", "REJECTED_QC") or v.get("qc_passed") is False
        )
        qc_recovery_attempts = sum(int(v.get("recovery_attempts") or 0) for v in today_vids)
        today_rec = automation_state.get_daily_record(today_str)
        rem_or_missed: List[str] = []
        for s_idx in (1, 2):
            s_st = today_rec.get(f"slot{s_idx}", {})
            if s_st.get("scheduled_status") != "SCHEDULED" and s_st.get("scheduled_status") != "SIMULATED":
                rem_or_missed.append(f"Slot {s_idx} ({s_st.get('generation_status', 'PENDING')})")

        oauth_warn = ""
        if yt_health.get("warning_24h_due"):
            oauth_warn = f"Expires in ~{yt_health.get('hours_until_expiry', '?')}h ({reauth_ist})"
        elif not yt_health.get("healthy") and yt_health.get("status") != "UNCONFIGURED":
            oauth_warn = str(yt_health.get("alert") or oauth_status)[:140]

        return get_telegram_notifier().notify_daily_summary(
            date_str=today_str,
            production_count=prod_count,
            daily_limit=MAX_DAILY_VIDEOS,
            published_public_count=pub_count,
            scheduled_pending_count=sched_pending,
            next_scheduled_ist=next_sched_str,
            oauth_status=oauth_status,
            oauth_reauth_ist=reauth_ist,
            last_failure=last_err,
            production_failures_count=prod_failures_count,
            qc_recovery_attempts_count=qc_recovery_attempts,
            remaining_or_missed_slots=", ".join(rem_or_missed) if rem_or_missed else "All slots covered",
            oauth_warnings=oauth_warn,
        )

    def _needs_retryable_work(self, date_str: str) -> bool:
        """Return True if date_str has unfinished work that is safe to retry automatically."""
        rec = automation_state.get_daily_record(date_str)
        if rec.get("overall_status") == "COMPLETED":
            return False

        terminal_markers = (
            "invalid_grant",
            "revoked",
            "insufficientpermissions",
            "permission_denied",
            "quotaexceeded",
            "uploadlimitexceeded",
            "youtube rejected uploaded video",
            "exhausted",
        )
        all_terminal = True
        for slot_key in ("slot1", "slot2"):
            s_rec = rec.get(slot_key) or {}
            if s_rec.get("scheduled_status") in ("SCHEDULED", "SIMULATED"):
                continue
            err = str(s_rec.get("error") or "").lower()
            if err and any(marker in err for marker in terminal_markers):
                continue
            vid_id = str(s_rec.get("video_id") or "")
            if vid_id:
                v_db = db.get_video_record(vid_id)
                if (
                    v_db
                    and int(v_db.get("recovery_attempts") or 0) >= config.MAX_QC_RECOVERY_ATTEMPTS
                    and not v_db.get("qc_passed")
                ):
                    continue
            all_terminal = False
        return not all_terminal

    def run_daemon(self, poll_interval_sec: int = 15, retry_interval_sec: int = 300) -> None:
        """Run continuous autonomous scheduling daemon with graceful stop support."""
        if SCHEDULER_STOP_FILE.exists():
            try:
                SCHEDULER_STOP_FILE.unlink()
            except Exception:
                pass

        self.acquire_lock()
        self.running = True
        pid = os.getpid()

        self._state["is_running"] = True
        self._state["pid"] = pid
        self._state["last_heartbeat"] = self.now_ist().isoformat()
        self._save_state()

        logger.info(
            f"=== Curiosity Engine Autonomous Scheduler Started (PID: {pid}) ===\n"
            f"Timezone: {SCHEDULER_TIMEZONE}\n"
            f"YouTube Mode: {YOUTUBE_PUBLISHING_MODE} (Privacy: {YOUTUBE_PRIVACY_STATUS})\n"
            f"Instagram Mode: {INSTAGRAM_PUBLISHING_MODE}\n"
            f"Poll Interval: {poll_interval_sec}s\n"
            f"Log: {LOG_FILE}"
        )

        last_attempt_ts = time.monotonic()
        last_oauth_check_ts = time.monotonic()
        last_pub_verify_ts = 0.0
        last_summary_check_ts = 0.0
        last_analytics_sync_ts = 0.0
        retry_attempts_today = 0
        was_enabled = self.is_automation_enabled()

        # Recover any queued Telegram alerts persisted before shutdown/outage
        try:
            get_telegram_notifier().flush_pending_events()
        except Exception:
            pass

        # Safe daily storage cleanup for eligible previous IST days (never deletes pending/today/DB)
        try:
            cleanup_old_generated_videos()
        except Exception as cleanup_exc:
            logger.warning("Startup storage cleanup warning: %s", cleanup_exc)

        # Availability-driven startup execution for current date
        try:
            today_str = self.now_ist().strftime("%Y-%m-%d")
            if was_enabled:
                logger.info(f"Running startup availability-driven daily batch for {today_str}...")
                self.process_daily_automation(target_date=today_str)
                last_attempt_ts = time.monotonic()
            else:
                logger.info("Automation is PAUSED at startup; scheduler remaining idle.")
                self.check_oauth_lifecycle_and_notify()
        except Exception as e:
            logger.error(f"Error during startup daily automation: {e}")
            self._state["last_error"] = str(e)
            self._save_state()

        last_date = self.now_ist().strftime("%Y-%m-%d")

        try:
            while self.running:
                if SCHEDULER_STOP_FILE.exists():
                    logger.info("Graceful shutdown signal detected (.scheduler.stop). Exiting daemon...")
                    break

                config.sync_env_if_updated()
                youtube_publisher.refresh_credentials_if_changed()

                now = self.now_ist()
                mono_now = time.monotonic()
                current_date = now.strftime("%Y-%m-%d")
                is_enabled = self.is_automation_enabled()

                self._state["last_heartbeat"] = now.isoformat()
                self._save_state()

                # Flush any queued offline Telegram alerts on recovery
                try:
                    get_telegram_notifier().flush_pending_events()
                except Exception:
                    pass

                # Periodic public-status verification for scheduled videos (every 120s)
                if (mono_now - last_pub_verify_ts) >= 120:
                    last_pub_verify_ts = mono_now
                    try:
                        self.verify_scheduled_publications()
                    except Exception as exc:
                        logger.warning("Scheduled publication verification check error: %s", exc)

                # Passive YouTube channel performance stats check (every 4 hours in live mode)
                if YOUTUBE_PUBLISHING_MODE == "live" and (mono_now - last_analytics_sync_ts) >= 14400:
                    last_analytics_sync_ts = mono_now
                    try:
                        performance_tracker.refresh_public_video_metrics(youtube_publisher)
                    except Exception as exc:
                        logger.warning("Performance metrics refresh warning: %s", exc)

                # Daily / periodic OAuth health verification (every 6h)
                if (mono_now - last_oauth_check_ts) >= 21600:
                    last_oauth_check_ts = mono_now
                    try:
                        self.check_oauth_lifecycle_and_notify()
                    except Exception as exc:
                        logger.warning("Periodic OAuth health check error: %s", exc)

                # Daily operational summary after configured IST hour (deduped per day)
                if (mono_now - last_summary_check_ts) >= 300:
                    last_summary_check_ts = mono_now
                    try:
                        self.maybe_send_daily_summary()
                    except Exception as exc:
                        logger.warning("Daily summary dispatch check error: %s", exc)

                # Date rollover: When date changes in IST, clean previous days, audit OAuth & trigger batch
                if current_date != last_date:
                    logger.info(f"Date rollover detected ({last_date} -> {current_date}). Initiating daily batch...")
                    last_date = current_date
                    retry_attempts_today = 0
                    last_oauth_check_ts = mono_now
                    try:
                        cleanup_old_generated_videos()
                    except Exception as cleanup_exc:
                        logger.warning("Rollover storage cleanup warning: %s", cleanup_exc)
                    try:
                        self.check_oauth_lifecycle_and_notify()
                    except Exception:
                        pass
                    if is_enabled:
                        try:
                            self.process_daily_automation(target_date=current_date)
                            last_attempt_ts = time.monotonic()
                        except Exception as e:
                            logger.error(f"Error during rollover daily batch: {e}")
                            self._state["last_error"] = str(e)
                            self._save_state()
                elif is_enabled and not was_enabled:
                    logger.info(f"Automation enabled while running; evaluating daily batch for {current_date}...")
                    retry_attempts_today = 0
                    try:
                        self.process_daily_automation(target_date=current_date)
                        last_attempt_ts = time.monotonic()
                    except Exception as e:
                        logger.error(f"Error executing resumed automation for {current_date}: {e}")
                        self._state["last_error"] = str(e)
                        self._save_state()
                elif (
                    is_enabled
                    and retry_attempts_today < 6
                    and (time.monotonic() - last_attempt_ts) >= max(30, int(retry_interval_sec))
                    and self._needs_retryable_work(current_date)
                ):
                    retry_attempts_today += 1
                    logger.info(
                        f"Failure-monitor check ({retry_attempts_today}/6) for incomplete slots on {current_date}..."
                    )
                    last_attempt_ts = time.monotonic()
                    try:
                        self.process_daily_automation(target_date=current_date)
                    except Exception as e:
                        logger.error(f"Error during monitored retry for {current_date}: {e}")
                        self._state["last_error"] = str(e)
                        self._save_state()

                was_enabled = is_enabled

                # Interruptible sleep in 1s chunks for responsive shutdown
                for _ in range(max(1, int(poll_interval_sec))):
                    if not self.running or SCHEDULER_STOP_FILE.exists():
                        break
                    time.sleep(1)

        except KeyboardInterrupt:
            logger.info("Scheduler received shutdown interrupt.")
        finally:
            self.running = False
            self._state["is_running"] = False
            self._state["pid"] = None
            self._save_state()
            if SCHEDULER_STOP_FILE.exists():
                try:
                    SCHEDULER_STOP_FILE.unlink()
                except Exception:
                    pass
            self.release_lock()
            logger.info("Scheduler daemon shut down cleanly.")


def sched_sched_complete(slot_sched_done: Dict[int, bool]) -> bool:
    return bool(slot_sched_done.get(1) and slot_sched_done.get(2))


scheduler = LocalScheduler()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Curiosity Engine Local Scheduler")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="Read-only: print scheduler telemetry and exit")
    group.add_argument("--dry-run", action="store_true", help="Read-only: evaluate planned actions and exit")
    group.add_argument("--validate", action="store_true", help="Read-only: validate config & dependencies and exit")
    group.add_argument("--once", action="store_true", help="Execute single availability-driven catch-up batch (requires --confirm)")
    group.add_argument("--daemon", action="store_true", help="Run continuous autonomous scheduler daemon")
    parser.add_argument("--confirm", action="store_true", help="Explicit confirmation safeguard for --once execution")
    parser.add_argument("--interval", type=int, default=15, help="Daemon polling interval in seconds (default 15)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if args.status:
        print(json.dumps(scheduler.get_telemetry(), indent=2))
        sys.exit(0)
    elif args.dry_run:
        print(json.dumps(scheduler.evaluate_dry_run(), indent=2))
        sys.exit(0)
    elif args.validate:
        report = scheduler.validate_environment()
        print(json.dumps(report, indent=2))
        sys.exit(0 if report["valid"] else 1)
    elif args.once:
        if not args.confirm:
            print(
                "[SAFEGUARD] --once triggers live/real production and publishing pipeline.\n"
                "Use '--dry-run' or '--status' for read-only diagnostics, or pass '--once --confirm' to execute."
            )
            sys.exit(2)
        recovered = scheduler.run_catchup_check()
        print(f"Daily automation evaluated. Output: {len(recovered)}")
        sys.exit(0)
    elif args.daemon:
        scheduler.run_daemon(poll_interval_sec=args.interval)
    else:
        parser.print_help()
        sys.exit(0)
