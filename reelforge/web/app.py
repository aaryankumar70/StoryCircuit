"""FastAPI backend and dashboard endpoints for ReelForge."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from reelforge import config
from reelforge.brain.llm_client import ZeroCostLLM
from reelforge.models import SourceMode, VisualStyle
from reelforge.pipeline import run_generation_job
from reelforge.progress import build_daily_summary, build_slot_timeline, summarize_job_progress
from reelforge.scheduler.daily import publish_job_to_youtube, run_daily_slots
from reelforge.storage.db import ReelDatabase
from reelforge.youtube.oauth import YouTubeOAuthManager
from reelforge.youtube.uploader import YouTubeUploader, clear_health_cache

app = FastAPI(title="StoryCircuit Studio", version="0.1.0")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

# Single worker ensures bounded CPU/RAM usage on laptop hardware
_WORKER = ThreadPoolExecutor(max_workers=1)
_DB = ReelDatabase()
_OAUTH = YouTubeOAuthManager()


class GenerateRequest(BaseModel):
    mode: SourceMode = SourceMode.RANDOM
    topic: str = ""
    category: str = "auto"
    style: str = "auto"
    custom_script: str = ""
    visual_mode: Optional[str] = None
    auto_upload: bool = False


class PlanItemRequest(BaseModel):
    planned_date: str
    slot_num: int = Field(default=1, ge=1, le=2)
    topic: str
    category: str = "story"
    style: str = "auto"
    custom_script: str = ""
    notes: str = ""


class BulkPlanRequest(BaseModel):
    items: List[PlanItemRequest]


class UploadRequest(BaseModel):
    force_mode: Optional[str] = None


class YouTubeSettingsRequest(BaseModel):
    mode: str = Field(pattern="^(simulation|live)$")
    privacy_status: str = Field(default="private", pattern="^(private|unlisted|public)$")


def get_db() -> ReelDatabase:
    return _DB


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "styles": [s.value for s in VisualStyle],
            "slot1": config.SLOT1_TIME,
            "slot2": config.SLOT2_TIME,
            "tz": config.SCHEDULER_TIMEZONE,
        },
    )


@app.get("/api/status")
def api_status() -> Dict[str, Any]:
    db = get_db()
    tz = ZoneInfo(config.SCHEDULER_TIMEZONE)
    today = datetime.now(tz).strftime("%Y-%m-%d")
    today_jobs = db.get_jobs_for_date(today)
    recent_jobs = db.list_jobs(limit=12)
    active_raw = next((j for j in recent_jobs if j.get("status") in {"rendering", "uploading"}), None)
    focus_raw = active_raw or (recent_jobs[0] if recent_jobs else None)
    active_snap = summarize_job_progress(focus_raw)
    if focus_raw:
        active_snap["id"] = focus_raw.get("id")
        active_snap["title"] = focus_raw.get("title")
        active_snap["source_mode"] = focus_raw.get("source_mode")
        active_snap["status"] = focus_raw.get("status")
        active_snap["style"] = focus_raw.get("style")

    llm = ZeroCostLLM()
    yt = YouTubeUploader()
    return {
        "today": today,
        "timezone": config.SCHEDULER_TIMEZONE,
        "slots": {"slot1": config.SLOT1_TIME, "slot2": config.SLOT2_TIME},
        "today_jobs": today_jobs,
        "daily_summary": build_daily_summary(today_jobs, config.MAX_DAILY_VIDEOS),
        "slot_timeline": build_slot_timeline(
            today_jobs,
            slot1_time=config.SLOT1_TIME,
            slot2_time=config.SLOT2_TIME,
        ),
        "active_job": active_snap,
        "worker_busy": bool(active_raw),
        "ollama_online": llm.is_ollama_available(),
        "ollama_model": config.OLLAMA_MODEL,
        "gemini_configured": bool(config.GEMINI_API_KEY),
        "youtube": yt.get_connection_status(verify_network=False),
        "oauth": _OAUTH.get_status(),
        "visual_mode": config.VISUAL_MODE,
    }


@app.post("/api/youtube/client-secret")
async def api_youtube_client_secret(file: UploadFile = File(...)) -> Dict[str, Any]:
    raw = await file.read()
    try:
        return _OAUTH.save_client_secret_bytes(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/youtube/oauth/start")
def api_youtube_oauth_start() -> Dict[str, Any]:
    try:
        return _OAUTH.start_oauth_flow()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/youtube/oauth/status")
def api_youtube_oauth_status() -> Dict[str, Any]:
    return {
        "oauth": _OAUTH.get_status(),
        "youtube": YouTubeUploader().get_connection_status(verify_network=False),
    }


@app.post("/api/youtube/oauth/disconnect")
def api_youtube_oauth_disconnect() -> Dict[str, Any]:
    yt_status = _OAUTH.disconnect()
    return {"youtube": yt_status, "oauth": _OAUTH.get_status()}


@app.post("/api/youtube/check")
def api_youtube_check() -> Dict[str, Any]:
    clear_health_cache()
    return {"youtube": YouTubeUploader().get_connection_status(verify_network=True)}


@app.post("/api/youtube/settings")
def api_youtube_settings(req: YouTubeSettingsRequest) -> Dict[str, Any]:
    config.save_env_values(
        {
            "YOUTUBE_PUBLISHING_MODE": req.mode,
            "YOUTUBE_PRIVACY_STATUS": req.privacy_status,
        }
    )
    clear_health_cache()
    return {"youtube": YouTubeUploader().get_connection_status(verify_network=False)}


@app.get("/api/jobs")
def api_jobs(limit: int = 40) -> Dict[str, Any]:
    return {"jobs": get_db().list_jobs(limit=limit)}


@app.get("/api/jobs/{job_id}")
def api_job_detail(job_id: str) -> Dict[str, Any]:
    job = get_db().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": job}


@app.get("/api/jobs/{job_id}/video")
def api_job_video(job_id: str):
    job = get_db().get_job(job_id)
    if not job or not job.get("video_path"):
        raise HTTPException(status_code=404, detail="Video not found")
    vpath = Path(job["video_path"])
    if not vpath.exists():
        raise HTTPException(status_code=404, detail="Video file missing on disk")
    return FileResponse(vpath, media_type="video/mp4", filename=f"{job_id}.mp4")


@app.post("/api/generate")
def api_generate(req: GenerateRequest) -> Dict[str, Any]:
    if req.mode == SourceMode.CUSTOM_SCRIPT and not req.custom_script.strip():
        raise HTTPException(status_code=400, detail="Custom script cannot be empty.")

    def _task() -> None:
        db = get_db()
        job = run_generation_job(
            db,
            mode=req.mode,
            topic=req.topic,
            category=req.category,
            style=req.style,
            custom_script=req.custom_script,
            visual_mode=req.visual_mode,
        )
        if req.auto_upload and job.get("status") == "qc_passed":
            publish_job_to_youtube(db, job["id"])

    _WORKER.submit(_task)
    return {"queued": True, "message": "Generation queued on local worker."}


@app.post("/api/run-daily")
def api_run_daily(auto_upload: bool = True) -> Dict[str, Any]:
    _WORKER.submit(run_daily_slots, get_db(), auto_upload=auto_upload)
    return {"queued": True, "message": "Daily 2-video cycle queued."}


@app.post("/api/jobs/{job_id}/upload")
def api_upload_job(job_id: str, req: Optional[UploadRequest] = None) -> Dict[str, Any]:
    try:
        res = publish_job_to_youtube(get_db(), job_id, force_mode=(req.force_mode if req else None))
        return {"result": res}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/jobs/{job_id}/retry")
def api_retry_job(job_id: str) -> Dict[str, Any]:
    db = get_db()
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") in {"rendering", "uploading"}:
        raise HTTPException(status_code=409, detail="Job is already running.")

    mode = SourceMode(job.get("source_mode") or SourceMode.RANDOM.value)
    custom_script = job.get("script_text") or "" if mode == SourceMode.CUSTOM_SCRIPT else ""

    def _task() -> None:
        run_generation_job(
            get_db(),
            mode=mode,
            topic=job.get("title") or "",
            category=job.get("category") or "auto",
            style=job.get("style") or "auto",
            custom_script=custom_script,
            scheduled_date=job.get("scheduled_date"),
            slot_num=job.get("slot_num"),
        )

    _WORKER.submit(_task)
    return {"queued": True, "message": f"Retrying job {job_id} on local worker."}


@app.delete("/api/jobs/{job_id}")
def api_delete_job(job_id: str) -> Dict[str, Any]:
    db = get_db()
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") in {"rendering", "uploading"}:
        raise HTTPException(status_code=409, detail="Cannot delete an active job.")
    db.delete_job(job_id)
    out_dir = (config.OUTPUT_DIR / job_id).resolve()
    try:
        if out_dir.exists() and out_dir.is_dir() and out_dir.parent == config.OUTPUT_DIR.resolve():
            shutil.rmtree(out_dir, ignore_errors=True)
    except Exception:
        pass
    return {"deleted": job_id}


@app.get("/api/plan")
def api_plan_list() -> Dict[str, Any]:
    return {"items": get_db().list_plan_items(limit=200)}


@app.post("/api/plan")
def api_plan_add(req: PlanItemRequest) -> Dict[str, Any]:
    pid = get_db().add_plan_item(
        planned_date=req.planned_date,
        slot_num=req.slot_num,
        topic=req.topic,
        category=req.category,
        style=req.style,
        custom_script=req.custom_script,
        notes=req.notes,
    )
    return {"id": pid}


@app.post("/api/plan/bulk")
def api_plan_bulk(req: BulkPlanRequest) -> Dict[str, Any]:
    ids = [
        get_db().add_plan_item(
            planned_date=it.planned_date,
            slot_num=it.slot_num,
            topic=it.topic,
            category=it.category,
            style=it.style,
            custom_script=it.custom_script,
            notes=it.notes,
        )
        for it in req.items
    ]
    return {"ids": ids, "count": len(ids)}


@app.delete("/api/plan/{plan_id}")
def api_plan_delete(plan_id: str) -> Dict[str, Any]:
    get_db().delete_plan_item(plan_id)
    return {"deleted": plan_id}


@app.get("/api/history")
def api_history() -> Dict[str, Any]:
    return {"history": get_db().list_history(limit=100)}
