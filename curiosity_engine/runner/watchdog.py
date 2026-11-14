"""Autonomous Production Watchdog & Per-Slot Worker Lock Manager for CurioLoop.

Monitors today's daily slots (12:30 PM & 8:30 PM IST), detects stalled, orphaned,
crashed, failed, or missed slot jobs, distinguishes external dependency outages
from recoverable local failures, enforces single-worker locks per slot, and drives
bounded exponential-backoff recovery without disturbing actively rendering jobs
or completed/scheduled production assets.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from curiosity_engine import config
from curiosity_engine.runner import progress_tracker
from curiosity_engine.state.db import db

logger = logging.getLogger("curiosity_engine.watchdog")
IST = ZoneInfo(config.SCHEDULER_TIMEZONE)

WATCHDOG_CHECK_INTERVAL_SEC = 60
MAX_WATCHDOG_RECOVERY_CYCLES = 3
DEFAULT_BACKOFF_SCHEDULE_SEC = (120, 300, 600)
API_OUTAGE_COOLDOWN_SEC = 300

STAGE_STALL_TIMEOUTS_SEC: Dict[str, int] = {
    "selecting_topic": 180,
    "writing_script": 300,
    "generating_narration": 420,
    "preparing_visuals": 600,
    "rendering_video": 420,
    "running_qc": 300,
    "qc_recovery": 900,
    "uploading_privately": 600,
    "scheduling_publication": 300,
}

IN_PROGRESS_PROD_STATES = {
    "STARTING",
    "SELECTING_TOPIC",
    "WRITING_SCRIPT",
    "SCRIPTED",
    "GENERATING_AUDIO",
    "ASSETS_READY",
    "RENDERING",
    "RENDERED",
    "RECOVERING",
    "QC_RECOVERING",
}


class WorkerLockError(RuntimeError):
    """Raised when a per-slot production worker is already actively running."""


def is_pid_alive(pid: int) -> bool:
    """Return True if process PID is currently active on Windows or POSIX and belongs to a Python process."""
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, int(pid))
            if handle == 0:
                return False
            try:
                exit_code = ctypes.c_ulong()
                ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                if not ok or exit_code.value != STILL_ACTIVE:
                    return False
                buf = ctypes.create_unicode_buffer(1024)
                size = ctypes.c_ulong(1024)
                if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    exe_name = Path(buf.value).name.lower()
                    return exe_name in ("python.exe", "pythonw.exe")
                return True
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def classify_failure(error_text: Optional[str]) -> str:
    """Classify an error into oauth_paused | api_outage | permanent_invalid | recoverable."""
    lower = str(error_text or "").lower()
    if not lower:
        return "recoverable"

    oauth_markers = (
        "invalid_grant",
        "revoked",
        "oauth_paused",
        "reauth_required",
        "token has been expired",
        "insufficientpermissions",
        "youtube oauth not healthy",
    )
    if any(m in lower for m in oauth_markers):
        return "oauth_paused"

    permanent_markers = (
        "youtube rejected uploaded video",
        "non_production_test",
        "protected disposable test video",
        "terms of service",
        "copyright claim",
    )
    if any(m in lower for m in permanent_markers):
        return "permanent_invalid"

    api_markers = (
        "quotaexceeded",
        "uploadlimitexceeded",
        "ratelimitexceeded",
        "429",
        "503",
        "502",
        "500",
        "service unavailable",
        "connectionerror",
        "connection reset",
        "connection refused",
        "temporary failure in name resolution",
        "timed out",
        "network is unreachable",
        "ssl",
    )
    if any(m in lower for m in api_markers):
        return "api_outage"

    return "recoverable"


def slot_lock_path(slot_index: int, data_dir: Optional[Path] = None) -> Path:
    """Return lock file path for a specific daily production slot (1 or 2)."""
    if data_dir is not None:
        return Path(data_dir) / f".worker_slot{int(slot_index)}.lock"
    if "PYTEST_CURRENT_TEST" in os.environ:
        return Path(tempfile.gettempdir()) / f"curiosity_engine_pytest_slot{int(slot_index)}.lock"
    return Path(config.DATA_DIR) / f".worker_slot{int(slot_index)}.lock"


def read_slot_lock(slot_index: int, lock_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Read lock metadata dict if present, supporting both JSON and legacy integer formats."""
    path = lock_path or slot_lock_path(slot_index)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        if raw.isdigit():
            return {"pid": int(raw), "slot_index": int(slot_index)}
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def inspect_slot_worker(
    slot_index: int,
    video_id: Optional[str] = None,
    lock_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Inspect whether a slot worker lock exists, whether its PID is alive, and whether render.log is advancing."""
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    lock_info = read_slot_lock(slot_index, lock_path=lock_path)
    out_root = Path(output_dir or config.OUTPUT_DIR)

    pid = int(lock_info["pid"]) if lock_info and str(lock_info.get("pid", "")).isdigit() else None
    pid_alive = bool(pid and is_pid_alive(pid))
    locked_vid = (lock_info or {}).get("video_id") or video_id
    stale_lock = bool(lock_info is not None and not pid_alive)

    render_log_age_sec: Optional[float] = None
    render_active = False
    live_render: Optional[Dict[str, Any]] = None
    if locked_vid:
        render_log = out_root / str(locked_vid) / "logs" / "render.log"
        if render_log.exists():
            try:
                mtime = datetime.fromtimestamp(render_log.stat().st_mtime, tz=timezone.utc)
                render_log_age_sec = max(0.0, (now - mtime).total_seconds())
                live_render = progress_tracker.parse_live_render_progress(str(locked_vid), output_dir=out_root)
                render_active = bool(pid_alive and render_log_age_sec < STAGE_STALL_TIMEOUTS_SEC["rendering_video"])
            except Exception:
                pass

    return {
        "locked": lock_info is not None,
        "pid": pid,
        "pid_alive": pid_alive,
        "stale_lock": stale_lock,
        "video_id": locked_vid,
        "started_at": (lock_info or {}).get("started_at"),
        "render_active": render_active,
        "render_log_age_sec": render_log_age_sec,
        "live_render": live_render,
    }


def acquire_slot_worker_lock(
    slot_index: int,
    video_id: str,
    lock_path: Optional[Path] = None,
) -> Path:
    """Acquire an exclusive per-slot lock, automatically overriding stale locks from crashed PIDs."""
    path = lock_path or slot_lock_path(slot_index)
    path.parent.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()

    existing = read_slot_lock(slot_index, lock_path=path)
    if existing:
        existing_pid = int(existing.get("pid") or 0)
        if existing_pid and existing_pid != pid and is_pid_alive(existing_pid):
            raise WorkerLockError(
                f"Slot {slot_index} worker already running (PID {existing_pid}, video {existing.get('video_id')})."
            )
        logger.warning(
            "Cleaning stale worker lock for Slot %s (dead PID %s, previous video %s).",
            slot_index,
            existing_pid,
            existing.get("video_id"),
        )

    payload = {
        "pid": pid,
        "slot_index": int(slot_index),
        "video_id": str(video_id),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)
    return path


def release_slot_worker_lock(
    slot_index: int,
    video_id: Optional[str] = None,
    lock_path: Optional[Path] = None,
    force: bool = False,
) -> bool:
    """Release per-slot lock if owned by current PID (or if force=True for stale lock cleanup)."""
    path = lock_path or slot_lock_path(slot_index)
    if not path.exists():
        return False
    if force:
        path.unlink(missing_ok=True)
        return True
    existing = read_slot_lock(slot_index, lock_path=path)
    if not existing or int(existing.get("pid") or 0) == os.getpid():
        path.unlink(missing_ok=True)
        return True
    if video_id and existing.get("video_id") == video_id and not is_pid_alive(int(existing.get("pid") or 0)):
        path.unlink(missing_ok=True)
        return True
    return False


@dataclass
class WatchdogConfig:
    """Configuration controlling Watchdog thresholds, retries, and cadence."""

    check_interval_sec: int = WATCHDOG_CHECK_INTERVAL_SEC
    max_recovery_cycles: int = MAX_WATCHDOG_RECOVERY_CYCLES
    backoff_schedule_sec: Tuple[int, ...] = DEFAULT_BACKOFF_SCHEDULE_SEC
    api_outage_cooldown_sec: int = API_OUTAGE_COOLDOWN_SEC
    slot1_time_str: str = config.SCHEDULER_PUBLISH_SLOT1_TIME
    slot2_time_str: str = config.SCHEDULER_PUBLISH_SLOT2_TIME


class ProductionWatchdog:
    """Persistent autonomous monitor and bounded recovery coordinator for daily slots."""

    def __init__(
        self,
        state_file: Optional[Path] = None,
        watchdog_config: Optional[WatchdogConfig] = None,
        db_client: Any = None,
    ):
        self._explicit_state_file = state_file
        self.cfg = watchdog_config or WatchdogConfig()
        self._db_client = db_client

    def _resolve_state_file(self) -> Path:
        if self._explicit_state_file is not None:
            return Path(self._explicit_state_file)
        if "PYTEST_CURRENT_TEST" in os.environ:
            return Path(tempfile.gettempdir()) / "curiosity_engine_pytest_watchdog.json"
        return Path(config.DATA_DIR) / "watchdog_state.json"

    def _resolve_db(self) -> Any:
        return self._db_client if self._db_client is not None else db

    def _load_state(self) -> Dict[str, Any]:
        sf = self._resolve_state_file()
        if sf.exists():
            try:
                loaded = json.loads(sf.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    loaded.setdefault("slots", {})
                    return loaded
            except Exception:
                pass
        return {
            "status": "HEALTHY",
            "last_check_at": None,
            "next_check_at": None,
            "check_count": 0,
            "slots": {},
        }

    def _save_state(self, state: Dict[str, Any]) -> None:
        sf = self._resolve_state_file()
        sf.parent.mkdir(parents=True, exist_ok=True)
        tmp = sf.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        tmp.replace(sf)

    def _slot_key(self, date_str: str, slot_index: int) -> str:
        return f"{date_str}:slot{int(slot_index)}"

    def _notify(self, method_name: str, **kwargs: Any) -> None:
        try:
            from curiosity_engine.notifications.telegram_notifier import get_telegram_notifier
            notifier = get_telegram_notifier()
            fn = getattr(notifier, method_name, None)
            if callable(fn):
                fn(**kwargs)
        except Exception as exc:
            logger.debug("Watchdog notification %s skipped: %s", method_name, exc)

    def _slot_is_completed_for_day(self, v_rec: Optional[Dict[str, Any]], slot_rec: Dict[str, Any]) -> bool:
        """Return True when production is QC-verified and distribution is complete (or no work remains)."""
        if slot_rec.get("scheduled_status") in ("SCHEDULED", "SIMULATED"):
            return True
        if not v_rec:
            return False
        pub_status = str(v_rec.get("publishing_status") or "").upper()
        yt_status = str(v_rec.get("youtube_status") or "").upper()
        if pub_status in ("SCHEDULED", "PUBLISHED") or yt_status in ("SCHEDULED", "PUBLISHED", "SIMULATED"):
            return True
        if v_rec.get("schedule_confirmed") and v_rec.get("scheduled_publish_at"):
            return True
        return False

    def _is_generation_finished(self, v_rec: Optional[Dict[str, Any]], output_dir: Path) -> bool:
        if not v_rec:
            return False
        if v_rec.get("production_status") == "COMPLETED" and v_rec.get("qc_passed") is True:
            vid_id = str(v_rec.get("video_id") or "")
            mp4 = Path(v_rec.get("local_video_path") or (output_dir / f"{vid_id}.mp4"))
            return mp4.exists() or bool(v_rec.get("youtube_upload_id"))
        return False

    def _detect_stall_reason(
        self,
        slot_index: int,
        vid_id: str,
        v_rec: Optional[Dict[str, Any]],
        worker_info: Dict[str, Any],
        output_dir: Path,
        now_utc: datetime,
    ) -> Optional[Tuple[str, str]]:
        """Return (stage_name, reason) if job is stuck/orphaned/stalled; None if healthy or not running."""
        if not v_rec:
            return None

        prod_status = str(v_rec.get("production_status") or "").upper()
        if prod_status not in IN_PROGRESS_PROD_STATES:
            return None

        # Never kill or flag a worker whose PID is alive and whose render.log recently grew
        if worker_info.get("pid_alive"):
            stage_prog = v_rec.get("stage_progress") or {}
            active_stage = str(stage_prog.get("active_stage") or "").lower() or "rendering_video"
            if active_stage == "rendering_video" and worker_info.get("render_active"):
                return None
            # Alive PID in non-render stage: compare elapsed against stage stall timeout
            stage_starts = stage_prog.get("stage_started_at") or {}
            started_dt = _parse_iso(
                stage_starts.get(active_stage)
                or stage_prog.get("active_stage_started_at")
                or v_rec.get("updated_at")
            )
            if started_dt:
                elapsed = (now_utc - started_dt).total_seconds()
                threshold = STAGE_STALL_TIMEOUTS_SEC.get(active_stage, 600)
                if active_stage == "rendering_video":
                    log_age = worker_info.get("render_log_age_sec")
                    if log_age is not None and log_age < threshold:
                        return None
                    if log_age is None and elapsed < threshold:
                        return None
                    age_disp = int(log_age if log_age is not None else elapsed)
                    return active_stage, f"Render made no log progress for {age_disp}s (threshold {threshold}s)"
                if elapsed >= threshold:
                    return active_stage, f"Stage '{active_stage}' exceeded {threshold}s ({int(elapsed)}s elapsed)"
            return None

        # PID is dead or lock is missing while DB says IN_PROGRESS -> orphaned/crashed worker!
        stage_prog = v_rec.get("stage_progress") or {}
        active_stage = str(stage_prog.get("active_stage") or "").lower() or prod_status.lower()
        return (
            active_stage,
            f"Worker interrupted/crashed while in stage '{active_stage}' (no active worker PID for {vid_id})",
        )

    def _window_passed(self, now_ist: datetime, date_str: str, hhmm: str) -> bool:
        try:
            year, month, day = [int(p) for p in date_str.split("-")]
            h, m = [int(p) for p in hhmm.split(":")]
            slot_dt = datetime(year, month, day, h, m, 0, tzinfo=IST)
            return now_ist >= slot_dt
        except Exception:
            return False

    def prepare_slot_for_recovery_cycle(self, video_id: str, db_client: Any = None) -> None:
        """Clear prior QC-hash exhaustion block when Watchdog starts a fresh bounded recovery cycle."""
        store = db_client or self._resolve_db()
        rec = store.get_video_record(video_id)
        if not rec or not isinstance(rec, dict):
            return
        if not (rec.get("production_status") == "COMPLETED" and rec.get("qc_passed") is True):
            rec["failed_mp4_sha256"] = None
            rec["recovery_attempts"] = 0
            rec["watchdog_recovering"] = True
            store.save_video_record(video_id, rec)

    def run_health_check(
        self,
        now_ist: Optional[datetime] = None,
        automation_enabled: bool = True,
        oauth_healthy: bool = True,
        oauth_status: str = "HEALTHY",
        oauth_reason: Optional[str] = None,
        daily_record: Optional[Dict[str, Any]] = None,
        recover_fn: Optional[Callable[[int, str, str], bool]] = None,
        output_dir: Optional[Path] = None,
        data_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Execute a single ~60s autonomous watchdog scan and perform bounded safe recovery."""
        now_local = (now_ist or datetime.now(IST)).astimezone(IST)
        now_utc = now_local.astimezone(timezone.utc)
        today_str = now_local.strftime("%Y-%m-%d")
        clean_date = today_str.replace("-", "")
        out_root = Path(output_dir or config.OUTPUT_DIR)
        store = self._resolve_db()

        state = self._load_state()
        state["last_check_at"] = now_utc.isoformat()
        state["next_check_at"] = (now_utc + timedelta(seconds=self.cfg.check_interval_sec)).isoformat()
        state["check_count"] = int(state.get("check_count") or 0) + 1

        actions_taken: List[Dict[str, Any]] = []
        any_waiting = False
        any_degraded = False

        if not automation_enabled:
            state["status"] = "PAUSED"
            self._save_state(state)
            return {"status": "PAUSED", "actions": actions_taken, "watchdog": state}

        for slot_index in (1, 2):
            vid_id = f"video_{clean_date}_slot{slot_index}"
            s_key = self._slot_key(today_str, slot_index)
            slot_entry = dict(state["slots"].get(s_key) or {
                "date": today_str,
                "slot_index": slot_index,
                "video_id": vid_id,
                "recovery_cycles": 0,
                "max_cycles": self.cfg.max_recovery_cycles,
                "next_retry_after": None,
                "last_failure_kind": None,
                "last_error": None,
                "last_recovery_action": None,
                "stalled": False,
                "last_stall_stage": None,
                "waiting_state": None,
                "permanently_failed": False,
                "recovered_count": 0,
            })

            v_rec = store.get_video_record(vid_id)
            daily_slot = (daily_record or {}).get(f"slot{slot_index}", {}) or {}
            lpath = slot_lock_path(slot_index, data_dir=data_dir)
            worker_info = inspect_slot_worker(
                slot_index, video_id=vid_id, lock_path=lpath, output_dir=out_root, now_utc=now_utc
            )

            # Release stale dead-PID lock automatically
            if worker_info["stale_lock"]:
                release_slot_worker_lock(slot_index, video_id=vid_id, lock_path=lpath, force=True)
                actions_taken.append({"slot": slot_index, "action": "cleaned_stale_lock", "pid": worker_info["pid"]})

            # 1. Completely finished for today -> clear transient stall/waiting/error flags and leave untouched
            if self._slot_is_completed_for_day(v_rec, daily_slot):
                slot_entry["stalled"] = False
                slot_entry["waiting_state"] = None
                slot_entry["permanently_failed"] = False
                slot_entry["last_failure_kind"] = None
                slot_entry["last_error"] = None
                slot_entry["next_retry_after"] = None
                state["slots"][s_key] = slot_entry
                continue

            # 2. Check if active live worker is running cleanly
            if worker_info["pid_alive"] and worker_info["locked"]:
                stall = self._detect_stall_reason(slot_index, vid_id, v_rec, worker_info, out_root, now_utc)
                if stall is None:
                    slot_entry["stalled"] = False
                    slot_entry["waiting_state"] = None
                    state["slots"][s_key] = slot_entry
                    continue

            # 3. External dependency pause check (OAuth expired/revoked)
            slot_err = str(
                (v_rec or {}).get("youtube_error")
                or (v_rec or {}).get("error")
                or daily_slot.get("error")
                or ""
            )
            failure_kind = classify_failure(slot_err)
            if (not oauth_healthy and oauth_status in ("REVOKED_OR_EXPIRED", "REAUTH_REQUIRED")) or failure_kind == "oauth_paused":
                any_waiting = True
                slot_entry["last_failure_kind"] = "oauth_paused"
                slot_entry["last_error"] = oauth_reason or slot_err or f"YouTube OAuth {oauth_status}"
                slot_entry["waiting_state"] = "Waiting for YouTube OAuth reconnection"
                slot_entry["last_recovery_action"] = "Paused automatically until OAuth restored (retry budget preserved)"
                state["slots"][s_key] = slot_entry
                actions_taken.append({"slot": slot_index, "action": "waiting_oauth"})
                continue

            # 4. Determine if generation is already QC-passed and only upload/schedule remains
            gen_done = self._is_generation_finished(v_rec, out_root)
            slot_hhmm = self.cfg.slot1_time_str if slot_index == 1 else self.cfg.slot2_time_str
            window_passed = self._window_passed(now_local, today_str, slot_hhmm)

            # Check API outage vs permanent invalid error on upload/schedule
            if failure_kind == "permanent_invalid":
                any_degraded = True
                slot_entry["last_failure_kind"] = "permanent_invalid"
                slot_entry["last_error"] = slot_err
                slot_entry["permanently_failed"] = True
                slot_entry["last_recovery_action"] = "Stopped automatic retries (permanent error)"
                state["slots"][s_key] = slot_entry
                continue

            if failure_kind == "api_outage":
                any_waiting = True
                next_after = _parse_iso(slot_entry.get("next_retry_after"))
                slot_entry["last_failure_kind"] = "api_outage"
                slot_entry["last_error"] = slot_err
                slot_entry["waiting_state"] = "Waiting for YouTube/API recovery cooldown"
                if next_after and now_utc < next_after:
                    state["slots"][s_key] = slot_entry
                    continue
                if recover_fn:
                    slot_entry["next_retry_after"] = (now_utc + timedelta(seconds=self.cfg.api_outage_cooldown_sec)).isoformat()
                    slot_entry["last_recovery_action"] = "Retrying upload/schedule after API cooldown (without burning production cycles)"
                    state["slots"][s_key] = slot_entry
                    self._save_state(state)
                    try:
                        recover_fn(slot_index, today_str, "api_cooldown_retry")
                        actions_taken.append({"slot": slot_index, "action": "api_cooldown_retry"})
                    except Exception as exc:
                        logger.warning("API cooldown retry for Slot %s raised: %s", slot_index, exc)
                else:
                    state["slots"][s_key] = slot_entry
                continue

            # 5. Detect stalled / orphaned / failed / missed production slot
            stall = self._detect_stall_reason(slot_index, vid_id, v_rec, worker_info, out_root, now_utc)
            prod_status = str((v_rec or {}).get("production_status") or "").upper()
            pub_status = str((v_rec or {}).get("publishing_status") or "").upper()
            is_failed = prod_status in ("FAILED", "REJECTED_QC") or pub_status in ("FAILED", "PUBLISH_FAILED")
            is_missing = (v_rec is None) or (prod_status == "" and not gen_done)

            reason: Optional[str] = None
            trigger_kind: str = ""
            if stall is not None:
                st_stage, st_reason = stall
                reason = st_reason
                trigger_kind = "stalled"
                slot_entry["stalled"] = True
                slot_entry["last_stall_stage"] = st_stage
                slot_entry["last_error"] = st_reason
                self._notify(
                    "notify_production_stalled",
                    video_id=vid_id,
                    slot_index=slot_index,
                    stage=st_stage,
                    reason=st_reason,
                    recovery_action="Scheduling automatic recovery cycle",
                )
            elif is_failed:
                reason = slot_err or f"Slot {slot_index} status={prod_status or pub_status}"
                trigger_kind = "failed"
                slot_entry["last_error"] = reason
            elif gen_done and not self._slot_is_completed_for_day(v_rec, daily_slot):
                reason = f"Slot {slot_index} produced & QC-passed awaiting upload/schedule"
                trigger_kind = "pending_upload"
            elif is_missing and window_passed:
                reason = f"Missed slot {slot_index} ({slot_hhmm} IST) with no generated job"
                trigger_kind = "missed_slot"

            if not reason:
                slot_entry["stalled"] = False
                slot_entry["waiting_state"] = None
                state["slots"][s_key] = slot_entry
                continue

            # Check retry exhaustion & backoff window
            cycles = int(slot_entry.get("recovery_cycles") or 0)
            if slot_entry.get("permanently_failed") or cycles >= self.cfg.max_recovery_cycles:
                any_degraded = True
                slot_entry["permanently_failed"] = True
                slot_entry["waiting_state"] = None
                slot_entry["last_recovery_action"] = (
                    f"Recovery attempts exhausted ({cycles}/{self.cfg.max_recovery_cycles})"
                )
                state["slots"][s_key] = slot_entry
                self._notify(
                    "notify_production_permanently_failed",
                    video_id=vid_id,
                    slot_index=slot_index,
                    topic=str((v_rec or {}).get("topic") or vid_id),
                    reason=reason,
                    cycles_used=cycles,
                    max_cycles=self.cfg.max_recovery_cycles,
                    slot_missed=window_passed,
                )
                continue

            next_after = _parse_iso(slot_entry.get("next_retry_after"))
            if next_after and now_utc < next_after:
                rem = int((next_after - now_utc).total_seconds())
                slot_entry["waiting_state"] = f"Backoff wait ({rem}s remaining before Cycle {cycles + 1}/{self.cfg.max_recovery_cycles})"
                state["slots"][s_key] = slot_entry
                any_waiting = True
                continue

            # Launch bounded recovery cycle
            next_cycle = cycles + 1
            backoff_idx = min(len(self.cfg.backoff_schedule_sec) - 1, max(0, next_cycle - 1))
            delay_after = int(self.cfg.backoff_schedule_sec[backoff_idx]) if self.cfg.backoff_schedule_sec else 0
            slot_entry["recovery_cycles"] = next_cycle
            slot_entry["stalled"] = False
            slot_entry["waiting_state"] = f"Recovering (Cycle {next_cycle}/{self.cfg.max_recovery_cycles})"
            slot_entry["next_retry_after"] = (now_utc + timedelta(seconds=delay_after)).isoformat()
            slot_entry["last_failure_kind"] = trigger_kind
            slot_entry["last_recovery_action"] = (
                f"Cycle {next_cycle}/{self.cfg.max_recovery_cycles}: {trigger_kind}"
            )
            state["slots"][s_key] = slot_entry
            self._save_state(state)

            if not gen_done:
                self.prepare_slot_for_recovery_cycle(vid_id, db_client=store)

            self._notify(
                "notify_recovery_started",
                video_id=vid_id,
                slot_index=slot_index,
                reason=reason,
                attempt=next_cycle,
                max_attempts=self.cfg.max_recovery_cycles,
                action=f"Autonomous watchdog recovery ({trigger_kind})",
            )

            actions_taken.append({
                "slot": slot_index,
                "video_id": vid_id,
                "action": "recover",
                "trigger": trigger_kind,
                "cycle": next_cycle,
            })

            if recover_fn:
                try:
                    ok = recover_fn(slot_index, today_str, reason)
                    # Reload fresh state after recovery executes
                    state = self._load_state()
                    cur_entry = dict(state["slots"].get(s_key) or slot_entry)
                    if ok:
                        cur_entry["recovered_count"] = int(cur_entry.get("recovered_count") or 0) + 1
                        cur_entry["waiting_state"] = None
                        cur_entry["stalled"] = False
                        cur_entry["last_recovery_action"] = (
                            f"Recovered cleanly on Cycle {next_cycle}/{self.cfg.max_recovery_cycles}"
                        )
                    else:
                        cur_entry["waiting_state"] = (
                            f"Next retry in {delay_after}s" if next_cycle < self.cfg.max_recovery_cycles
                            else "Max recovery cycles exhausted"
                        )
                        if next_cycle >= self.cfg.max_recovery_cycles:
                            cur_entry["permanently_failed"] = True
                            cur_entry["waiting_state"] = None
                            any_degraded = True
                            self._notify(
                                "notify_production_permanently_failed",
                                video_id=vid_id,
                                slot_index=slot_index,
                                topic=str((v_rec or {}).get("topic") or vid_id),
                                reason=str(cur_entry.get("last_error") or reason),
                                cycles_used=next_cycle,
                                max_cycles=self.cfg.max_recovery_cycles,
                                slot_missed=window_passed,
                            )
                    state["slots"][s_key] = cur_entry
                except Exception as exc:
                    logger.error("Watchdog recovery for %s raised: %s", vid_id, exc)
                    slot_entry["last_error"] = str(exc)
                    if next_cycle >= self.cfg.max_recovery_cycles:
                        slot_entry["permanently_failed"] = True
                        slot_entry["waiting_state"] = None
                        any_degraded = True
                        self._notify(
                            "notify_production_permanently_failed",
                            video_id=vid_id,
                            slot_index=slot_index,
                            topic=str((v_rec or {}).get("topic") or vid_id),
                            reason=str(exc),
                            cycles_used=next_cycle,
                            max_cycles=self.cfg.max_recovery_cycles,
                            slot_missed=window_passed,
                        )
                    state["slots"][s_key] = slot_entry

        if any_degraded:
            state["status"] = "DEGRADED"
        elif any(a.get("action") == "recover" for a in actions_taken):
            state["status"] = "RECOVERING"
        elif any_waiting:
            state["status"] = "WAITING_DEPENDENCY"
        else:
            state["status"] = "HEALTHY"

        self._save_state(state)
        return {
            "status": state["status"],
            "actions": actions_taken,
            "watchdog": state,
        }

    def get_health_summary(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """Return safe dashboard telemetry for the autonomous watchdog (no secret field names)."""
        today_str = target_date or datetime.now(IST).strftime("%Y-%m-%d")
        state = self._load_state()
        slots_out: Dict[str, Any] = {}
        for idx in (1, 2):
            s_key = self._slot_key(today_str, idx)
            entry = state.get("slots", {}).get(s_key, {})
            slots_out[f"slot{idx}"] = {
                "recovery_cycles": int(entry.get("recovery_cycles") or 0),
                "max_cycles": int(entry.get("max_cycles") or self.cfg.max_recovery_cycles),
                "stalled": bool(entry.get("stalled", False)),
                "waiting_state": entry.get("waiting_state"),
                "permanently_failed": bool(entry.get("permanently_failed", False)),
                "last_failure_kind": entry.get("last_failure_kind"),
                "last_error": entry.get("last_error"),
                "last_recovery_action": entry.get("last_recovery_action"),
                "next_retry_after": entry.get("next_retry_after"),
            }
        return {
            "status": state.get("status", "HEALTHY"),
            "last_check_at": state.get("last_check_at"),
            "next_check_at": state.get("next_check_at"),
            "check_count": int(state.get("check_count") or 0),
            "check_interval_sec": self.cfg.check_interval_sec,
            "max_recovery_cycles": self.cfg.max_recovery_cycles,
            "slots": slots_out,
        }


production_watchdog = ProductionWatchdog()
