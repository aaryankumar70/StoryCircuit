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
    OUTPUT_DIR,
    PROJECT_ROOT,
    PUBLISHING_MODE,
    YOUTUBE_PRIVACY_STATUS,
    YOUTUBE_PUBLISHING_MODE,
    YOUTUBE_UPLOAD_DAILY_LIMIT,
)
from curiosity_engine.distribution.token_manager import token_manager
from curiosity_engine.distribution.youtube_publisher import (
    NON_PRODUCTION_TEST_YOUTUBE_IDS,
    youtube_publisher,
)
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
        if privacy == "public" or pub_status == "PUBLISHED":
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
    yt_uploads_today = len([v for v in todays_videos if is_real_youtube_upload(v)])

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
    for v in all_vids_full:
        if not isinstance(v, dict) or v.get("is_test"):
            continue
        yt_id = str(v.get("youtube_upload_id") or "")
        if yt_id in NON_PRODUCTION_TEST_YOUTUBE_IDS:
            continue
        if is_real_youtube_upload(v) and (
            v.get("youtube_privacy_status") == "public" or v.get("publishing_status") == "PUBLISHED"
        ):
            confirmed_public_list.append(v)
        if is_real_youtube_upload(v) and v.get("scheduled_publish_at") and v.get("youtube_privacy_status") != "public":
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

    last_public_pub = None
    if confirmed_public_list:
        lp = confirmed_public_list[0]
        last_public_pub = {
            "video_id": lp.get("video_id"),
            "youtube_id": lp.get("youtube_upload_id"),
            "title": (lp.get("script") or {}).get("title", lp.get("topic")),
            "published_at": lp.get("youtube_published_public_at") or lp.get("youtube_published_at"),
        }

    todays_prod_count = len([v for v in todays_videos if not v.get("is_test") and v.get("production_status") == "COMPLETED"])
    last_failure_str = scheduler_telemetry.get("last_error")
    if not last_failure_str and error_logs:
        last_failure_str = error_logs[0].get("message") if isinstance(error_logs[0], dict) else str(error_logs[0])

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
        "telegram_health": {
            "status": notif_health.get("status"),
            "configured": notif_health.get("configured"),
            "last_success_at": notif_health.get("last_success_at"),
            "pending_count": notif_health.get("pending_count", 0),
            "last_error": notif_health.get("last_error"),
        },
        "last_successful_publication": last_public_pub,
        "last_failure": last_failure_str,
    }

    for v in todays_videos:
        v["ui_status"] = compute_ui_status(v)
    for v in recent_videos:
        v["ui_status"] = compute_ui_status(v)

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
        "todays_videos": todays_videos,
        "recent_videos": recent_videos,
        "quotas": quota_status,
        "token_health": token_health,
        "scheduler": scheduler_telemetry,
        "notifications": notif_health,
        "reauth": reauth_info,
        "operational_status": operational_status,
        "error_logs": error_logs,
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
        db.save_video_record(clean_id, record)

    return {
        "video_id": clean_id,
        "title": record.get("script", {}).get("title", record.get("topic")),
        "description": desc,
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


def start_local_dashboard():
    """Launch the dashboard bound strictly to localhost (127.0.0.1)."""
    import uvicorn
    uvicorn.run(app, host=DASHBOARD_HOST, port=DASHBOARD_PORT)


if __name__ == "__main__":
    start_local_dashboard()
