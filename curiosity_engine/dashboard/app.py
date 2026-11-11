"""FastAPI Management Dashboard for Curiosity Engine.
Provides monitoring, video previews, publication links, error logs, emergency controls,
and token health audits.

Security: Bound strictly to localhost (127.0.0.1) and protected via dynamic X-Studio-Auth token.
All sensitive credentials are scrubbed from dashboard responses.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from curiosity_engine import config
from curiosity_engine.config import (
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    DASHBOARD_SECRET_KEY,
    DATA_DIR,
    INSTAGRAM_PUBLISHING_MODE,
    MAX_DAILY_VIDEOS,
    MAX_DURATION_SEC,
    MAX_QC_RECOVERY_ATTEMPTS,
    MIN_DURATION_SEC,
    OUTPUT_DIR,
    PROJECT_ROOT,
    PUBLISHING_MODE,
    SCHEDULER_PUBLISH_SLOT1_TIME,
    SCHEDULER_PUBLISH_SLOT2_TIME,
    TARGET_DURATION_MAX_SEC,
    TARGET_DURATION_MIN_SEC,
    YOUTUBE_PRIVACY_STATUS,
    YOUTUBE_PUBLISHING_MODE,
    YOUTUBE_UPLOAD_DAILY_LIMIT,
    get_hidden_subprocess_kwargs,
)
from curiosity_engine.distribution.token_manager import token_manager
from curiosity_engine.distribution.youtube_analytics import performance_tracker
from curiosity_engine.distribution.youtube_publisher import (
    NON_PRODUCTION_TEST_YOUTUBE_IDS,
    youtube_publisher,
)
from curiosity_engine.distribution.youtube_quota import youtube_quota
from curiosity_engine.notifications.telegram_notifier import (
    get_telegram_notifier,
    redact_telegram_secrets,
)
from curiosity_engine.runner.automation_state import AutomationStateManager
from curiosity_engine.runner.local_scheduler import scheduler
from curiosity_engine.runner.pipeline import (
    is_real_youtube_upload,
    run_daily_generation,
    run_slot_publishing,
)
from curiosity_engine.runner.progress_tracker import build_slot_progress_snapshot
from curiosity_engine.runner.storage_cleanup import get_storage_summary
from curiosity_engine.state.db import db

IST = ZoneInfo("Asia/Kolkata")
DASHBOARD_LOCK_FILE = DATA_DIR / ".dashboard.lock"
REAUTH_LOCK_FILE = DATA_DIR / ".reauth.lock"
REAUTH_STATUS_FILE = DATA_DIR / "reauth_status.json"
REAUTH_LOG_FILE = DATA_DIR / "reauth.log"
_reauth_mutex = threading.Lock()

logger = logging.getLogger("curiosity_engine.dashboard")

app = FastAPI(title="Curiosity Engine Studio Dashboard", version="1.1.0")

TEMPLATES_PATH = Path(__file__).parent / "templates"


def verify_auth_header(x_studio_auth: Optional[str] = Header(None)) -> str:
    """Validate that mutating requests supply the local random dashboard secret."""
    if not x_studio_auth or x_studio_auth.strip() != DASHBOARD_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Invalid or missing X-Studio-Auth authorization header.",
        )
    return x_studio_auth


@app.on_event("startup")
def startup_token_audit():
    """Perform one-time token health audit and record active dashboard PID lock on startup.
    Avoids redundant network calls on repeated /api/status polling.
    """
    if "PYTEST_CURRENT_TEST" not in os.environ:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            DASHBOARD_LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed writing dashboard PID lockfile: {e}")

    try:
        token_manager.audit_configured_tokens_on_startup()
    except Exception as e:
        logger.warning(f"Startup token audit encountered non-fatal error: {e}")


@app.on_event("shutdown")
def shutdown_cleanup():
    """Remove dashboard PID lockfile cleanly if it belongs to this process."""
    if "PYTEST_CURRENT_TEST" in os.environ:
        return
    try:
        if DASHBOARD_LOCK_FILE.exists() and DASHBOARD_LOCK_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
            DASHBOARD_LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def sanitize_data(data: Any) -> Any:
    """Recursively redact sensitive credential substrings from outgoing API responses."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                sanitized[k] = sanitize_data(v)
            elif any(secret_term in k.lower() for secret_term in ["token", "secret", "key", "password", "chat_id"]):
                if isinstance(v, str) and len(v) > 8:
                    sanitized[k] = f"{v[:3]}...{v[-3:]}"
                else:
                    sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_data(v)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_data(item) for item in data]
    elif isinstance(data, str):
        # Redact known API key / OAuth token / Telegram bot token / secret patterns
        scrubbed = redact_telegram_secrets(data)
        scrubbed = re.sub(r"AIza[0-9A-Za-z-_]{35}", "[REDACTED_API_KEY]", scrubbed)
        scrubbed = re.sub(r"EAAG[0-9A-Za-z]+", "[REDACTED_IG_TOKEN]", scrubbed)
        scrubbed = re.sub(r"1//[0-9A-Za-z-_]+", "[REDACTED_YT_REFRESH_TOKEN]", scrubbed)
        scrubbed = re.sub(r"ya29\.[0-9A-Za-z-_\.]+", "[REDACTED_ACCESS_TOKEN]", scrubbed)
        scrubbed = re.sub(r"GOCSPX-[0-9A-Za-z-_]+", "[REDACTED_CLIENT_SECRET]", scrubbed)
        return scrubbed
    return data


def compute_ui_status(v: Dict[str, Any]) -> str:
    """Compute trustworthy normalized badge status for video card in dashboard.
    Never returns SCHEDULED for simulated uploads or unconfirmed schedules.
    """
    yt_id = v.get("youtube_upload_id")
    yt_sim = bool(v.get("youtube_simulated", False)) or str(yt_id or "").startswith("yt_sim_")
    privacy = v.get("youtube_privacy_status", "private")
    pub_status = v.get("publishing_status", "PENDING")
    prod_status = v.get("production_status", "PENDING")
    yt_status = v.get("youtube_status", "")

    if (
        prod_status in ("FAILED", "REJECTED_QC")
        or pub_status in ("PUBLISH_FAILED", "FAILED")
        or yt_status == "FAILED"
        or v.get("qc_passed") is False
    ):
        return "FAILED"

    if yt_sim or pub_status == "SIMULATED" or yt_status == "SIMULATED":
        return "SIMULATED"

    is_real_yt = bool(yt_id and not str(yt_id).startswith("yt_sim_") and not yt_sim)
    if is_real_yt:
        if str(privacy or "").lower() == "public":
            return "PUBLISHED_PUBLIC"
        if (
            v.get("schedule_confirmed") is True
            or v.get("scheduled_publish_at")
            or pub_status == "SCHEDULED"
            or yt_status == "SCHEDULED"
        ):
            return "SCHEDULED"
        return "UPLOADED_PRIVATE"

    if prod_status == "COMPLETED" and v.get("qc_passed"):
        return "GENERATED"
    return prod_status


def _resolve_local_mp4_path(video_id: str) -> Optional[Path]:
    """Return existing local rendered MP4 path under OUTPUT_DIR, if present."""
    clean_id = Path(str(video_id or "")).name
    if not clean_id:
        return None
    primary = OUTPUT_DIR / f"{clean_id}.mp4"
    if primary.is_file():
        return primary
    nested = OUTPUT_DIR / clean_id / "renders" / f"{clean_id}.mp4"
    if nested.is_file():
        return nested
    return None


def _enrich_video_record(v: Dict[str, Any]) -> Dict[str, Any]:
    """Attach normalized UI status, duration, recovery, and local availability metadata."""
    out = dict(v)
    out["ui_status"] = compute_ui_status(out)
    vid = str(out.get("video_id") or "")
    out["has_local_mp4"] = _resolve_local_mp4_path(vid) is not None
    out["local_file_cleaned"] = bool(out.get("local_file_cleaned", False))
    script_obj = out.get("script") if isinstance(out.get("script"), dict) else {}
    qc_checks = (out.get("qc_results") or {}).get("checks") or {}
    raw_dur = out.get("duration_sec") or qc_checks.get("duration_sec") or script_obj.get("duration")
    try:
        out["duration_sec"] = round(float(raw_dur), 2) if raw_dur is not None else None
    except (TypeError, ValueError):
        out["duration_sec"] = None
    out["recovery_attempts"] = int(out.get("recovery_attempts") or 0)
    out["qc_recovery_history"] = list(out.get("qc_recovery_history") or out.get("recovery_history") or [])
    out["recovery_history"] = out["qc_recovery_history"]
    out["youtube_title"] = out.get("youtube_title") or script_obj.get("title") or out.get("topic")
    out["youtube_tags"] = list(out.get("youtube_tags") or [])
    return out


def _format_ist_slot_label(hhmm: str) -> str:
    """Format 24h HH:MM slot string as friendly IST display label."""
    try:
        parts = str(hhmm).strip().split(":")
        hour = int(parts[0])
        minute = int(parts[1])
        suffix = "PM" if hour >= 12 else "AM"
        hr12 = hour % 12 or 12
        return f"{hr12}:{minute:02d} {suffix} IST"
    except Exception:
        return f"{hhmm} IST"


def _derive_slot_lifecycle_stage(
    slot_index: int,
    video_rec: Optional[Dict[str, Any]],
    sched_slot_rec: Optional[Dict[str, Any]],
    automation_enabled: bool = True,
    oauth_paused: bool = False,
) -> Dict[str, Any]:
    """Map slot production & publishing telemetry into structured lifecycle + progress + ETA snapshot."""
    slot_time = SCHEDULER_PUBLISH_SLOT1_TIME if slot_index == 1 else SCHEDULER_PUBLISH_SLOT2_TIME
    return build_slot_progress_snapshot(
        slot_index=slot_index,
        video_rec=video_rec,
        sched_slot_rec=sched_slot_rec,
        target_time_ist=_format_ist_slot_label(slot_time),
        automation_enabled=automation_enabled,
        oauth_paused=oauth_paused,
        output_dir=OUTPUT_DIR,
    )


def _compute_daily_progress(
    todays_videos: List[Dict[str, Any]],
    slot_timeline: List[Dict[str, Any]],
    now_ist: datetime,
) -> Dict[str, Any]:
    """Compute honest daily target counts where only public YouTube videos count toward target."""
    real_vids = [v for v in todays_videos if isinstance(v, dict) and not v.get("is_test")]
    published_public = 0
    scheduled_private = 0
    generated_pending = 0
    failed = 0

    for v in real_vids:
        ui = compute_ui_status(v)
        if ui == "PUBLISHED_PUBLIC":
            published_public += 1
        elif ui == "SCHEDULED":
            scheduled_private += 1
        elif ui == "FAILED":
            failed += 1
        elif ui in ("GENERATED", "UPLOADED_PRIVATE"):
            generated_pending += 1

    # Count missed slot windows only after the scheduled IST publish minute passed without public/scheduled output
    missed = 0
    slot_minutes = {
        1: SCHEDULER_PUBLISH_SLOT1_TIME,
        2: SCHEDULER_PUBLISH_SLOT2_TIME,
    }
    for s in slot_timeline:
        idx = int(s.get("slot_index") or 0)
        hhmm = slot_minutes.get(idx, "23:59")
        try:
            hh, mm = [int(x) for x in hhmm.split(":")]
            slot_dt = now_ist.replace(hour=hh, minute=mm, second=0, microsecond=0)
        except Exception:
            slot_dt = now_ist
        if now_ist > slot_dt and s.get("stage") not in ("Published", "Scheduled"):
            missed += 1

    remaining = max(0, MAX_DAILY_VIDEOS - published_public - scheduled_private)
    return {
        "published_public_count": published_public,
        "daily_target": MAX_DAILY_VIDEOS,
        "scheduled_count": scheduled_private,
        "generated_pending_count": generated_pending,
        "failed_count": failed,
        "missed_count": missed,
        "remaining_slots": remaining,
        "target_met": published_public >= MAX_DAILY_VIDEOS,
        "note": "Published count increments only when YouTube video status is live public (private/scheduled are tracked separately).",
    }


def _parse_iso_dt(value: Any) -> Optional[datetime]:
    """Parse an ISO timestamp cleanly into timezone-aware UTC datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def classify_error_log_entry(
    entry: Dict[str, Any],
    videos_by_id: Dict[str, Dict[str, Any]],
    daily_records: Dict[str, Any],
    scheduler_last_error: Optional[str],
    yt_token_info: Dict[str, Any],
    oauth_paused: bool,
) -> Dict[str, Any]:
    """Classify a persisted error log entry as RESOLVED vs UNRESOLVED without mutating history."""
    out = dict(entry) if isinstance(entry, dict) else {"message": str(entry), "component": "UNKNOWN", "timestamp": ""}
    msg = str(out.get("message") or "")
    comp = str(out.get("component") or "")
    ctx = out.get("context") if isinstance(out.get("context"), dict) else {}
    err_dt = _parse_iso_dt(out.get("timestamp"))

    # Resolve target video_id explicitly from context, message, or timestamp+slot
    target_vid = ctx.get("video_id")
    if not target_vid:
        m = re.search(r"\b(video_\d{8}_slot\d+)\b", msg)
        if m:
            target_vid = m.group(1)
    if not target_vid and ctx.get("slot") in (1, 2) and err_dt is not None:
        clean_day = err_dt.astimezone(IST).strftime("%Y%m%d")
        target_vid = f"video_{clean_day}_slot{ctx['slot']}"

    resolved = False
    resolution_note: Optional[str] = None

    if target_vid and target_vid in videos_by_id:
        v = videos_by_id[target_vid]
        prod_ok = v.get("production_status") == "COMPLETED" and v.get("qc_passed") is True
        has_active_err = bool(
            v.get("error")
            or v.get("youtube_error")
            or v.get("youtube_rejection_reason")
            or v.get("publishing_status") in ("FAILED", "PUBLISH_FAILED", "REJECTED")
            or v.get("youtube_status") in ("FAILED", "REJECTED")
        )
        v_updated = _parse_iso_dt(v.get("youtube_published_public_at") or v.get("updated_at") or v.get("created_at"))
        newer_or_equal = (v_updated is None or err_dt is None or v_updated >= err_dt)

        msg_lower = msg.lower()
        is_prod_err = any(k in msg_lower for k in ("producing", "production", "visual", "audio mix", "qc"))
        real_yt = is_real_youtube_upload(v)
        pub_ok = real_yt and (
            v.get("schedule_confirmed") is True or str(v.get("youtube_privacy_status") or "").lower() == "public"
        )

        if prod_ok and not has_active_err and newer_or_equal and (is_prod_err or pub_ok):
            resolved = True
            state_desc = compute_ui_status(v)
            yt_ref = f" ({v.get('youtube_upload_id')})" if real_yt and v.get("youtube_upload_id") else ""
            resolution_note = f"Recovered: {target_vid} passed QC and is {state_desc}{yt_ref}"

    if not resolved and target_vid and re.match(r"^video_(\d{4})(\d{2})(\d{2})_slot(\d+)$", str(target_vid)):
        dm = re.match(r"^video_(\d{4})(\d{2})(\d{2})_slot(\d+)$", str(target_vid))
        day_iso = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"
        slot_key = f"slot{dm.group(4)}"
        day_rec = daily_records.get(day_iso) if isinstance(daily_records, dict) else None
        if isinstance(day_rec, dict) and day_rec.get("overall_status") == "COMPLETED":
            slot_rec = day_rec.get(slot_key, {})
            if slot_rec.get("scheduled_status") == "SCHEDULED" and not slot_rec.get("error"):
                resolved = True
                resolution_note = f"Recovered: {target_vid} completed and confirmed SCHEDULED"

    if not resolved and (
        "oauth" in comp.lower() or any(tok in msg.lower() for tok in ("invalid_grant", "oauth", "refresh token"))
    ):
        if yt_token_info.get("healthy") and not oauth_paused:
            auth_dt = _parse_iso_dt(yt_token_info.get("authorized_at") or yt_token_info.get("last_checked"))
            if auth_dt and (err_dt is None or auth_dt >= err_dt):
                resolved = True
                resolution_note = "Resolved: YouTube OAuth reauthorized and healthy"

    if not resolved and scheduler_last_error is None:
        # Check if an error happened on a day that subsequently finished COMPLETED without active failure
        if err_dt is not None:
            day_iso = err_dt.astimezone(IST).strftime("%Y-%m-%d")
            day_rec = daily_records.get(day_iso) if isinstance(daily_records, dict) else None
            if isinstance(day_rec, dict) and day_rec.get("overall_status") == "COMPLETED" and not day_rec.get("last_failure"):
                resolved = True
                resolution_note = f"Recovered: automation cycle for {day_iso} completed cleanly"

    out["resolved"] = resolved
    out["status"] = "RESOLVED" if resolved else "UNRESOLVED"
    out["resolution_note"] = resolution_note
    return out


def _read_reauth_status() -> Dict[str, Any]:
    """Read current/latest YouTube OAuth reauthorization status safely."""
    lock_active = False
    lock_pid = None
    if REAUTH_LOCK_FILE.exists():
        try:
            pid_str = REAUTH_LOCK_FILE.read_text(encoding="utf-8").strip()
            if pid_str.isdigit() and scheduler._is_pid_alive(int(pid_str)):
                lock_active = True
                lock_pid = int(pid_str)
            else:
                REAUTH_LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    state: Dict[str, Any] = {
        "state": "running" if lock_active else "idle",
        "lock_active": lock_active,
        "pid": lock_pid,
        "message": None,
        "started_at": None,
        "finished_at": None,
        "can_upload": None,
        "can_update_schedule": None,
        "resumed_automation": False,
        "estimated_reauth_date_ist": None,
    }
    if REAUTH_STATUS_FILE.exists():
        try:
            loaded = json.loads(REAUTH_STATUS_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state.update(loaded)
        except Exception:
            pass
    state["lock_active"] = lock_active
    if lock_active and state.get("state") != "running":
        state["state"] = "running"
    elif not lock_active and state.get("state") == "running":
        state["state"] = "failed"
        if not state.get("message"):
            state["message"] = "Reauthorization process exited unexpectedly."
    return state


def _write_reauth_status(payload: Dict[str, Any]) -> None:
    """Atomically persist dashboard reauthorization status."""
    REAUTH_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REAUTH_STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, REAUTH_STATUS_FILE)


@app.get("/", response_class=HTMLResponse)
def index_page() -> str:
    """Serve modern single-page dashboard HTML with dynamic auth token injection."""
    html_file = TEMPLATES_PATH / "index.html"
    if not html_file.exists():
        raise HTTPException(status_code=404, detail="Dashboard template not found.")

    raw_html = html_file.read_text(encoding="utf-8")
    # Injected token allows browser sessions on 127.0.0.1 to call authenticated endpoints seamlessly
    injected_html = raw_html.replace("<!-- {{AUTH_SECRET_INJECTION}} -->", f'<script>const STUDIO_AUTH_KEY = "{DASHBOARD_SECRET_KEY}";</script>')
    return injected_html


@app.get("/api/status")
def get_system_status() -> Dict[str, Any]:
    """Return comprehensive studio telemetry, dedicated upload quotas, and token health."""
    today_str = scheduler.now_ist().strftime("%Y-%m-%d")
    todays_videos = db.get_todays_videos(today_str)
    recent_videos = db.get_all_videos(limit=20)
    error_logs = db.get_recent_logs(limit=10)

    # YouTube Dedicated Upload Quota (100 uploads/day) - count real uploads only
    now_ist = scheduler.now_ist()
    yt_uploads_today = len([v for v in todays_videos if is_real_youtube_upload(v)])

    try:
        yt_api_quota_estimate = youtube_quota.get_quota_status()
    except Exception:
        yt_api_quota_estimate = {
            "is_estimate": True,
            "daily_reference_units": 10000,
            "estimated_units_used": 0,
            "remaining_units": 10000,
            "usage_percent": 0.0,
            "operations_breakdown": {},
        }

    quota_status = {
        "gemini": {
            "tier": "Free Tier (15 RPM / 1M TPM)",
            "daily_requests_used": len(recent_videos) * 3,
            "daily_limit": 1500,
            "status": "HEALTHY",
        },
        "youtube": {
            "tier": "Dedicated Upload Quota Bucket",
            "daily_uploads_used": yt_uploads_today,
            "daily_limit": YOUTUBE_UPLOAD_DAILY_LIMIT,
            "status": "HEALTHY" if yt_uploads_today < YOUTUBE_UPLOAD_DAILY_LIMIT else "QUOTA_EXHAUSTED",
        },
        "youtube_api_estimate": yt_api_quota_estimate,
        "instagram": {
            "tier": "Instagram Login (v22.0)",
            "hourly_calls_used": len([v for v in todays_videos if v.get("instagram_media_id")]) * 3,
            "hourly_limit": 200,
            "status": "HEALTHY",
        },
    }

    # Automation state
    state_mgr = AutomationStateManager(DATA_DIR / "automation_state.json")
    auto_summary = state_mgr.get_summary()
    automation_enabled = bool(auto_summary.get("enabled", True))
    oauth_paused = bool(auto_summary.get("oauth_paused", False))
    oauth_pause_reason = auto_summary.get("oauth_pause_reason")

    # Token Health Status
    config.sync_env_if_updated()
    token_health = token_manager.get_summary()
    yt_tok = token_health.get("youtube", {}) if isinstance(token_health, dict) else {}

    # Scheduler Telemetry
    scheduler_telemetry = scheduler.get_telemetry()

    # Telegram Notification Health
    notif_health = get_telegram_notifier().get_health(history_limit=20)

    # Next Upcoming Scheduled Video & Last Confirmed Public Publication
    now_utc = datetime.now(timezone.utc)
    all_vids_full = db.get_all_videos(limit=100)
    if not isinstance(all_vids_full, list):
        all_vids_full = recent_videos

    future_scheduled: List[tuple] = []
    confirmed_public_list: List[Dict[str, Any]] = []
    successful_prod_list: List[Dict[str, Any]] = []
    videos_by_id: Dict[str, Dict[str, Any]] = {}
    for v in all_vids_full:
        if not isinstance(v, dict):
            continue
        vid_key = str(v.get("video_id") or "")
        if vid_key:
            videos_by_id[vid_key] = v
        if v.get("is_test"):
            continue
        yt_id = str(v.get("youtube_upload_id") or "")
        if yt_id in NON_PRODUCTION_TEST_YOUTUBE_IDS:
            continue
        if v.get("production_status") == "COMPLETED" and v.get("qc_passed") is True:
            successful_prod_list.append(v)
        if is_real_youtube_upload(v) and str(v.get("youtube_privacy_status") or "").lower() == "public":
            confirmed_public_list.append(v)
        if is_real_youtube_upload(v) and v.get("scheduled_publish_at") and str(v.get("youtube_privacy_status") or "").lower() != "public":
            try:
                pub_dt = datetime.fromisoformat(str(v["scheduled_publish_at"]).replace("Z", "+00:00"))
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt > now_utc:
                    future_scheduled.append((pub_dt, v))
            except Exception:
                pass

    future_scheduled.sort(key=lambda item: item[0])
    next_sched_video = None
    if future_scheduled:
        nxt_dt, nxt_v = future_scheduled[0]
        next_sched_video = {
            "video_id": nxt_v.get("video_id"),
            "youtube_id": nxt_v.get("youtube_upload_id"),
            "topic": nxt_v.get("topic"),
            "title": (nxt_v.get("script") or {}).get("title", nxt_v.get("topic")),
            "slot_index": nxt_v.get("slot_index"),
            "scheduled_publish_at": nxt_v.get("scheduled_publish_at"),
            "scheduled_publish_at_ist": nxt_dt.astimezone(IST).strftime("%Y-%m-%d %H:%M IST"),
        }

    confirmed_public_list.sort(
        key=lambda x: str(x.get("youtube_published_public_at") or x.get("updated_at") or x.get("created_at") or ""),
        reverse=True,
    )
    last_public_pub = None
    if confirmed_public_list:
        lp = confirmed_public_list[0]
        last_public_pub = {
            "video_id": lp.get("video_id"),
            "youtube_id": lp.get("youtube_upload_id"),
            "title": (lp.get("script") or {}).get("title", lp.get("topic")),
            "published_at": lp.get("youtube_published_public_at") or lp.get("youtube_published_at"),
        }

    successful_prod_list.sort(
        key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""),
        reverse=True,
    )
    latest_successful_production = None
    if successful_prod_list:
        lsp = successful_prod_list[0]
        lsp_sched_ist = None
        if lsp.get("scheduled_publish_at"):
            lsp_dt = _parse_iso_dt(lsp.get("scheduled_publish_at"))
            if lsp_dt:
                lsp_sched_ist = lsp_dt.astimezone(IST).strftime("%Y-%m-%d %H:%M IST")
        latest_successful_production = {
            "video_id": lsp.get("video_id"),
            "youtube_id": lsp.get("youtube_upload_id") if is_real_youtube_upload(lsp) else None,
            "title": (lsp.get("script") or {}).get("title", lsp.get("topic")),
            "slot_index": lsp.get("slot_index"),
            "ui_status": compute_ui_status(lsp),
            "scheduled_publish_at_ist": lsp_sched_ist,
            "updated_at": lsp.get("updated_at") or lsp.get("created_at"),
        }

    # Classify preserved historical error logs as RESOLVED vs UNRESOLVED
    daily_records = auto_summary.get("daily_records", {}) if isinstance(auto_summary, dict) else {}
    sched_err = scheduler_telemetry.get("last_error")
    classified_logs = [
        classify_error_log_entry(
            entry=log_entry,
            videos_by_id=videos_by_id,
            daily_records=daily_records,
            scheduler_last_error=sched_err,
            yt_token_info=yt_tok,
            oauth_paused=oauth_paused,
        )
        for log_entry in error_logs
    ]
    resolved_logs = [e for e in classified_logs if e.get("resolved")]
    unresolved_logs = [e for e in classified_logs if not e.get("resolved")]

    unresolved_failures: List[str] = []
    if sched_err:
        unresolved_failures.append(str(sched_err))
    if oauth_paused and oauth_pause_reason:
        unresolved_failures.append(f"OAuth paused: {oauth_pause_reason}")
    elif yt_tok.get("reauth_required") and yt_tok.get("alert"):
        unresolved_failures.append(str(yt_tok.get("alert")))
    for v in todays_videos:
        if not isinstance(v, dict) or v.get("is_test"):
            continue
        if compute_ui_status(v) == "FAILED":
            v_err = v.get("youtube_error") or v.get("error") or f"{v.get('video_id')} failed"
            unresolved_failures.append(str(v_err))
    for ul in unresolved_logs:
        msg_txt = str(ul.get("message") or "")
        if msg_txt and msg_txt not in unresolved_failures:
            unresolved_failures.append(msg_txt)

    todays_prod_count = len([v for v in todays_videos if not v.get("is_test") and v.get("production_status") == "COMPLETED"])
    last_failure_str = unresolved_failures[0] if unresolved_failures else None

    reauth_info = _read_reauth_status()

    operational_status = {
        "scheduler_running": bool(scheduler_telemetry.get("is_running")),
        "scheduler_pid": scheduler_telemetry.get("pid"),
        "dashboard_health": {
            "status": "HEALTHY",
            "host": DASHBOARD_HOST,
            "port": DASHBOARD_PORT,
            "pid": os.getpid(),
            "url": f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}",
        },
        "youtube_auth_health": {
            "status": yt_tok.get("status", "UNKNOWN"),
            "healthy": bool(yt_tok.get("healthy")),
            "can_upload": yt_tok.get("can_upload"),
            "can_update_schedule": yt_tok.get("can_update_schedule"),
            "reauth_required": bool(yt_tok.get("reauth_required", False)),
            "estimated_reauth_date_ist": yt_tok.get("estimated_reauth_date_ist"),
            "hours_until_expiry": yt_tok.get("hours_until_expiry"),
            "warning_24h_due": bool(yt_tok.get("warning_24h_due", False)),
            "oauth_paused": oauth_paused,
            "oauth_pause_reason": oauth_pause_reason,
        },
        "next_scheduled_video": next_sched_video,
        "todays_production_count": todays_prod_count,
        "daily_limit": MAX_DAILY_VIDEOS,
        "latest_successful_production": latest_successful_production,
        "telegram_health": {
            "status": notif_health.get("status"),
            "configured": notif_health.get("configured"),
            "last_success_at": notif_health.get("last_success_at"),
            "pending_count": notif_health.get("pending_count", 0),
            "last_error": notif_health.get("last_error"),
        },
        "last_successful_publication": last_public_pub,
        "last_failure": last_failure_str,
        "unresolved_failures": unresolved_failures,
        "unresolved_failures_count": len(unresolved_failures),
        "resolved_failures_count": len(resolved_logs),
        "last_resolved_failure": resolved_logs[0] if resolved_logs else None,
    }

    enriched_todays = [_enrich_video_record(v) for v in todays_videos if isinstance(v, dict)]
    enriched_recent = [_enrich_video_record(v) for v in recent_videos if isinstance(v, dict)]

    today_auto = (scheduler_telemetry.get("today_automation") or {}) if isinstance(scheduler_telemetry, dict) else {}
    slot_rec_map = {}
    for ev in enriched_todays:
        if not ev.get("is_test") and ev.get("slot_index") in (1, 2):
            slot_rec_map[int(ev["slot_index"])] = ev
    slot_timeline = [
        _derive_slot_lifecycle_stage(
            1,
            slot_rec_map.get(1),
            today_auto.get("slot1"),
            automation_enabled=automation_enabled,
            oauth_paused=oauth_paused,
        ),
        _derive_slot_lifecycle_stage(
            2,
            slot_rec_map.get(2),
            today_auto.get("slot2"),
            automation_enabled=automation_enabled,
            oauth_paused=oauth_paused,
        ),
    ]
    daily_progress = _compute_daily_progress(enriched_todays, slot_timeline, now_ist)

    try:
        storage_summary = get_storage_summary()
    except Exception:
        storage_summary = {}

    try:
        performance_summary = performance_tracker.get_summary()
    except Exception:
        performance_summary = {}

    operational_status["storage_summary"] = storage_summary
    operational_status["quota_estimate"] = yt_api_quota_estimate
    operational_status["daily_progress"] = daily_progress

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "today_date": today_str,
        "publishing_mode": PUBLISHING_MODE,
        "youtube_publishing_mode": YOUTUBE_PUBLISHING_MODE,
        "youtube_privacy_status": YOUTUBE_PRIVACY_STATUS,
        "instagram_publishing_mode": INSTAGRAM_PUBLISHING_MODE,
        "automation_enabled": automation_enabled,
        "oauth_paused": oauth_paused,
        "oauth_pause_reason": oauth_pause_reason,
        "todays_videos": enriched_todays,
        "recent_videos": enriched_recent,
        "quotas": quota_status,
        "daily_progress": daily_progress,
        "slot_timeline": slot_timeline,
        "storage": storage_summary,
        "performance": performance_summary,
        "policy": {
            "min_duration_sec": MIN_DURATION_SEC,
            "max_duration_sec": MAX_DURATION_SEC,
            "target_duration_min_sec": TARGET_DURATION_MIN_SEC,
            "target_duration_max_sec": TARGET_DURATION_MAX_SEC,
            "max_qc_recovery_attempts": MAX_QC_RECOVERY_ATTEMPTS,
            "daily_limit": MAX_DAILY_VIDEOS,
        },
        "token_health": token_health,
        "scheduler": scheduler_telemetry,
        "notifications": notif_health,
        "reauth": reauth_info,
        "operational_status": operational_status,
        "error_logs": classified_logs,
        "schedule": [
            {"time_ist": "First Login (IST)", "action": "Generate Missing Videos, QC & Private Upload"},
            {"time_ist": "12:30 IST (07:00 UTC)", "action": "Slot 1 YouTube Scheduled Publication"},
            {"time_ist": "20:30 IST (15:00 UTC)", "action": "Slot 2 YouTube Scheduled Publication"},
        ],
    }

    return sanitize_data(payload)


@app.get("/api/video/{video_id}/stream")
def stream_video(video_id: str):
    """Stream rendered MP4 video for in-dashboard playback and quality inspection."""
    # Prevent directory traversal
    clean_id = Path(video_id).name
    mp4_file = OUTPUT_DIR / f"{clean_id}.mp4"

    if not mp4_file.exists():
        sub_file = OUTPUT_DIR / clean_id / f"renders/{clean_id}.mp4"
        if sub_file.exists():
            mp4_file = sub_file

    if not mp4_file.exists():
        raise HTTPException(status_code=404, detail=f"Rendered video '{clean_id}.mp4' not found.")

    return FileResponse(
        path=str(mp4_file),
        media_type="video/mp4",
        filename=f"{clean_id}.mp4",
    )


@app.get("/api/video/{video_id}/preview")
def get_preview_thumbnail(video_id: str):
    """Serve preview thumbnail for in-dashboard card rendering."""
    clean_id = Path(video_id).name
    jpg_candidates = [
        OUTPUT_DIR / f"{clean_id}_preview_t5.jpg",
        OUTPUT_DIR / f"{clean_id}_preview_t6.jpg",
        OUTPUT_DIR / f"{clean_id}_preview_t15.jpg",
        OUTPUT_DIR / f"{clean_id}_preview_t18.jpg",
    ]
    for candidate in jpg_candidates:
        if candidate.exists():
            return FileResponse(path=str(candidate), media_type="image/jpeg")

    raise HTTPException(status_code=404, detail="Thumbnail preview not available.")


class DescriptionPayload(BaseModel):
    description: str = Field(..., max_length=5000)


@app.get("/api/video/{video_id}/description")
def get_video_description(video_id: str) -> Dict[str, Any]:
    """Retrieve current YouTube description, claims, and verified sources for a video."""
    clean_id = Path(video_id).name
    record = db.get_video_record(clean_id)
    if not record:
        raise HTTPException(status_code=404, detail="Video record not found")

    desc = record.get("youtube_description")
    if not desc:
        from curiosity_engine.content.description_generator import description_generator
        desc_data = description_generator.generate(
            topic=record.get("topic", clean_id),
            category=record.get("category", "Science"),
            script_data=record.get("script", {}),
            sources=record.get("sources", []),
            claims=record.get("claims", []),
        )
        desc = desc_data["full_description"]
        record["youtube_description"] = desc
        if not record.get("youtube_tags") and desc_data.get("tags"):
            record["youtube_tags"] = desc_data["tags"]
        db.save_video_record(clean_id, record)

    return {
        "video_id": clean_id,
        "title": record.get("youtube_title") or record.get("script", {}).get("title", record.get("topic")),
        "description": desc,
        "youtube_tags": record.get("youtube_tags", []),
        "sources": record.get("sources", []),
        "is_edited": record.get("description_edited", False),
        "char_count": len(desc),
    }


@app.put("/api/video/{video_id}/description")
@app.post("/api/video/{video_id}/description")
def update_video_description(
    video_id: str,
    payload: DescriptionPayload,
    auth: str = Depends(verify_auth_header),
) -> Dict[str, Any]:
    """Update and persist edited YouTube description before publishing (Requires X-Studio-Auth)."""
    clean_id = Path(video_id).name
    record = db.get_video_record(clean_id)
    if not record:
        raise HTTPException(status_code=404, detail="Video record not found")

    new_text = payload.description.strip()
    if len(new_text) > 5000:
        raise HTTPException(status_code=400, detail="Description exceeds YouTube limit of 5,000 characters.")

    record["youtube_description"] = new_text
    record["description_edited"] = True
    record["description_updated_at"] = datetime.now(timezone.utc).isoformat()
    db.save_video_record(clean_id, record)

    return {
        "success": True,
        "video_id": clean_id,
        "description": new_text,
        "char_count": len(new_text),
    }


@app.post("/api/trigger/generate")
def trigger_generation(
    background_tasks: BackgroundTasks,
    auth: str = Depends(verify_auth_header),
):
    """Manually trigger Job 1 generation (Requires X-Studio-Auth)."""
    background_tasks.add_task(run_daily_generation)
    return {"message": "Job 1 (Generation) initiated in background."}


@app.post("/api/trigger/publish/{slot}")
def trigger_publishing(
    slot: int,
    background_tasks: BackgroundTasks,
    auth: str = Depends(verify_auth_header),
):
    """Manually trigger Slot 1 or Slot 2 publishing (Requires X-Studio-Auth)."""
    if slot not in [1, 2]:
        raise HTTPException(status_code=400, detail="Slot must be 1 or 2.")
    background_tasks.add_task(run_slot_publishing, slot_index=slot)
    return {"message": f"Publishing for Slot {slot} initiated in background."}


@app.post("/api/toggle_automation")
def toggle_automation(auth: str = Depends(verify_auth_header)):
    """Toggle automated scheduling on or off (Requires X-Studio-Auth)."""
    from curiosity_engine.runner.automation_state import automation_state
    curr = automation_state.is_enabled()
    new_state = not curr
    automation_state.set_enabled(new_state)
    return {"enabled": new_state}


@app.post("/api/trigger/retry/{video_id}")
def retry_video(
    video_id: str,
    background_tasks: BackgroundTasks,
    auth: str = Depends(verify_auth_header),
):
    """Safely retry production, upload, or scheduling for a failed video slot (Requires X-Studio-Auth)."""
    clean_id = Path(video_id).name
    slot = 1 if "slot1" in clean_id else (2 if "slot2" in clean_id else 1)
    background_tasks.add_task(scheduler.retry_slot, slot_index=slot)
    return {"message": f"Retry initiated for {clean_id} (Slot {slot}) in background."}


@app.post("/api/scheduler/stop")
def stop_scheduler(auth: str = Depends(verify_auth_header)):
    """Safely stop the scheduler daemon process (Requires X-Studio-Auth)."""
    from scripts.manage_windows_task import stop_daemon
    res = stop_daemon()
    return res


@app.post("/api/scheduler/start")
def start_scheduler(auth: str = Depends(verify_auth_header)):
    """Launch the scheduler daemon in background (Requires X-Studio-Auth)."""
    from scripts.manage_windows_task import start_daemon_background
    res = start_daemon_background()
    return res


@app.get("/api/scheduler/task_status")
def query_windows_task():
    """Query current Windows startup automation status."""
    from scripts.manage_windows_task import get_task_status
    return get_task_status()


@app.get("/api/scheduler/validate")
def validate_scheduler_config(network: bool = False):
    """Read-only configuration, executable, model, and OAuth validation."""
    return sanitize_data(scheduler.validate_environment(check_oauth_network=network))


@app.get("/api/scheduler/dry-run")
def dry_run_scheduler_preview():
    """Strict read-only evaluation of intended scheduler actions without side effects."""
    return sanitize_data(scheduler.evaluate_dry_run())


@app.get("/api/scheduled_videos")
def get_scheduled_videos():
    """Retrieve all videos with API-confirmed future publication schedules (never includes unconfirmed simulations)."""
    videos = db.get_all_videos(limit=50)
    scheduled = [
        v for v in videos
        if not v.get("youtube_simulated", False)
        and v.get("youtube_upload_id")
        and not str(v.get("youtube_upload_id", "")).startswith("yt_sim_")
        and (v.get("schedule_confirmed") or v.get("scheduled_publish_at"))
    ]
    return {"count": len(scheduled), "videos": scheduled, "scheduled_videos": scheduled}


def _monitor_reauth_process(proc: subprocess.Popen, started_at: str) -> None:
    """Wait for OAuth subprocess completion, validate scopes, hot-reload env, and resume if healthy."""
    try:
        try:
            out, err = proc.communicate(timeout=300)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            rc = -1
        finally:
            try:
                REAUTH_LOCK_FILE.unlink(missing_ok=True)
            except Exception:
                pass

        finished_at = datetime.now(IST).isoformat()
        combined = sanitize_data(((out or "") + "\n" + (err or "")).strip())
        if isinstance(combined, str) and len(combined) > 1500:
            combined = combined[-1500:]
        try:
            REAUTH_LOG_FILE.write_text(str(combined), encoding="utf-8")
        except Exception:
            pass

        if rc == 0:
            config.sync_env_if_updated(force=True)
            youtube_publisher.refresh_credentials_if_changed()
            yt_health = token_manager.get_summary().get("youtube", {})
            if not yt_health.get("healthy"):
                yt_health = token_manager.check_youtube_health()
            env_val = scheduler.validate_environment(check_oauth_network=False)
            can_up = bool(yt_health.get("can_upload"))
            can_sched = bool(yt_health.get("can_update_schedule"))
            resumed = False
            if yt_health.get("healthy") and can_up and can_sched:
                resumed = AutomationStateManager(DATA_DIR / "automation_state.json").resume_after_oauth()
            final_state = {
                "state": "succeeded" if (yt_health.get("healthy") and can_up and can_sched and env_val.get("valid")) else "failed",
                "lock_active": False,
                "pid": None,
                "started_at": started_at,
                "finished_at": finished_at,
                "can_upload": can_up,
                "can_update_schedule": can_sched,
                "resumed_automation": resumed,
                "estimated_reauth_date_ist": yt_health.get("estimated_reauth_date_ist"),
                "validation_valid": bool(env_val.get("valid")),
                "message": (
                    "YouTube OAuth reauthorized and full scopes verified."
                    if (yt_health.get("healthy") and can_up and can_sched)
                    else f"Reauthorization completed with incomplete scopes or validation issues (can_upload={can_up}, can_update_schedule={can_sched})."
                ),
            }
            _write_reauth_status(final_state)
        else:
            _write_reauth_status({
                "state": "failed",
                "lock_active": False,
                "pid": None,
                "started_at": started_at,
                "finished_at": finished_at,
                "can_upload": False,
                "can_update_schedule": False,
                "resumed_automation": False,
                "message": f"Authorization exited with status {rc}. Check logs or run reauthorize_youtube.bat.",
            })
    except Exception as exc:
        _write_reauth_status({
            "state": "failed",
            "lock_active": False,
            "pid": None,
            "started_at": started_at,
            "finished_at": datetime.now(IST).isoformat(),
            "message": sanitize_data(f"Reauthorization monitor error: {exc}"),
        })


@app.post("/api/oauth/reauthorize")
def trigger_youtube_reauthorize(auth: str = Depends(verify_auth_header)):
    """Start guarded full-scope YouTube OAuth reauthorization flow (Requires X-Studio-Auth)."""
    with _reauth_mutex:
        current = _read_reauth_status()
        if current.get("lock_active"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="YouTube OAuth reauthorization is already running.",
            )

        auth_script = PROJECT_ROOT / "scripts" / "auth_youtube.py"
        if not auth_script.exists():
            raise HTTPException(status_code=500, detail="auth_youtube.py script not found.")

        REAUTH_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [sys.executable, str(auth_script), "--force", "--scope-mode", "full", "--yes"],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **get_hidden_subprocess_kwargs(),
        )
        REAUTH_LOCK_FILE.write_text(str(proc.pid), encoding="utf-8")
        started_at = datetime.now(IST).isoformat()
        initial_status = {
            "state": "running",
            "lock_active": True,
            "pid": proc.pid,
            "started_at": started_at,
            "finished_at": None,
            "message": "Waiting for browser Google OAuth consent approval on http://localhost:8080/...",
        }
        _write_reauth_status(initial_status)
        t = threading.Thread(target=_monitor_reauth_process, args=(proc, started_at), daemon=True)
        t.start()
        return {"started": True, **initial_status}


@app.get("/api/oauth/reauthorize/status")
def get_youtube_reauthorize_status():
    """Poll current YouTube OAuth reauthorization job status."""
    return sanitize_data(_read_reauth_status())


@app.get("/api/notifications")
def get_notifications_status(limit: int = 30):
    """Return sanitized Telegram notification health and recent alert history."""
    safe_limit = max(1, min(100, int(limit)))
    return sanitize_data(get_telegram_notifier().get_health(history_limit=safe_limit))


@app.get("/api/logs/tail")
def get_sanitized_log_tail(source: str = "dashboard", lines: int = 80):
    """Return sanitized tail of scheduler, dashboard, or startup log files."""
    allowed_logs = {
        "scheduler": DATA_DIR / "scheduler.log",
        "dashboard": DATA_DIR / "dashboard.log",
        "startup": DATA_DIR / "startup.log",
    }
    target = allowed_logs.get(source.strip().lower())
    if target is None:
        raise HTTPException(status_code=400, detail="Unsupported log source. Allowed: scheduler, dashboard, startup.")
    safe_lines = max(5, min(300, int(lines)))
    if not target.exists():
        return {"source": source, "exists": False, "path": str(target), "lines": []}
    try:
        raw_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        tailed = [sanitize_data(line) for line in raw_lines[-safe_lines:]]
        return {"source": source, "exists": True, "path": str(target), "lines": tailed}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed reading log file: {exc}")


@app.get("/api/storage")
def get_storage_telemetry():
    """Return local output storage footprint and safe cleanup audit telemetry."""
    return sanitize_data(get_storage_summary())


@app.get("/api/analytics")
@app.get("/api/performance")
def get_performance_analytics():
    """Return read-only YouTube public video performance metrics and honest sample/scope disclosures."""
    return sanitize_data(performance_tracker.get_summary())


@app.post("/api/performance/refresh")
def refresh_performance_analytics(auth: str = Depends(verify_auth_header)):
    """Trigger read-only YouTube Data API public statistics refresh (Requires X-Studio-Auth)."""
    res = performance_tracker.refresh_public_video_metrics(youtube_publisher)
    return sanitize_data(res)


def start_local_dashboard():
    """Launch the dashboard bound strictly to localhost (127.0.0.1)."""
    import uvicorn
    uvicorn.run(app, host=DASHBOARD_HOST, port=DASHBOARD_PORT)


if __name__ == "__main__":
    start_local_dashboard()
