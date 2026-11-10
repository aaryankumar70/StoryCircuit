"""FastAPI Management Dashboard for Curiosity Engine.
Provides monitoring, video previews, publication links, error logs, emergency controls,
and token health audits.

Security: Bound strictly to localhost (127.0.0.1) and protected via dynamic X-Studio-Auth token.
All sensitive credentials are scrubbed from dashboard responses.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from curiosity_engine.config import (
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    DASHBOARD_SECRET_KEY,
    DATA_DIR,
    INSTAGRAM_PUBLISHING_MODE,
    OUTPUT_DIR,
    PUBLISHING_MODE,
    YOUTUBE_PRIVACY_STATUS,
    YOUTUBE_PUBLISHING_MODE,
    YOUTUBE_UPLOAD_DAILY_LIMIT,
)
from curiosity_engine.distribution.token_manager import token_manager
from curiosity_engine.runner.local_scheduler import scheduler
from curiosity_engine.runner.pipeline import (
    is_real_youtube_upload,
    run_daily_generation,
    run_slot_publishing,
)
from curiosity_engine.state.db import db

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
    """Perform one-time token health audit during application startup.
    Avoids redundant network calls on repeated /api/status polling.
    """
    try:
        token_manager.audit_configured_tokens_on_startup()
    except Exception as e:
        logger.warning(f"Startup token audit encountered non-fatal error: {e}")


def sanitize_data(data: Any) -> Any:
    """Recursively redact sensitive credential substrings from outgoing API responses."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                sanitized[k] = sanitize_data(v)
            elif any(secret_term in k.lower() for secret_term in ["token", "secret", "key", "password"]):
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
        # Redact known API key / OAuth token / secret patterns
        scrubbed = re.sub(r"AIza[0-9A-Za-z-_]{35}", "[REDACTED_API_KEY]", data)
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
        if (
            v.get("schedule_confirmed") is True
            or v.get("scheduled_publish_at")
            or pub_status == "SCHEDULED"
            or yt_status == "SCHEDULED"
        ):
            return "SCHEDULED"
        if privacy == "public":
            return "PUBLISHED_PUBLIC"
        return "UPLOADED_PRIVATE"

    if prod_status == "COMPLETED" and v.get("qc_passed"):
        return "GENERATED"
    return prod_status


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
    state_file = DATA_DIR / "automation_state.json"
    automation_enabled = True
    if state_file.exists():
        import json
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                automation_enabled = json.load(f).get("enabled", True)
        except Exception:
            pass

    # Token Health Status
    token_health = token_manager.get_summary()

    # Scheduler Telemetry
    scheduler_telemetry = scheduler.get_telemetry()

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
        "todays_videos": todays_videos,
        "recent_videos": recent_videos,
        "quotas": quota_status,
        "token_health": token_health,
        "scheduler": scheduler_telemetry,
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


def start_local_dashboard():
    """Launch the dashboard bound strictly to localhost (127.0.0.1)."""
    import uvicorn
    uvicorn.run(app, host=DASHBOARD_HOST, port=DASHBOARD_PORT)


if __name__ == "__main__":
    start_local_dashboard()
