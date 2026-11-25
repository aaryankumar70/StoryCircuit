"""FastAPI backend, automatic end-of-day garbage cleanup, and dashboard endpoints."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import logging
import os
from pathlib import Path
import shutil
import threading
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from reelforge import config
from reelforge.brain.llm_client import ZeroCostLLM
from reelforge.brain.splitter import analyze_and_split_script
from reelforge.models import SourceMode, VisualStyle
from reelforge.pipeline import run_generation_job
from reelforge.progress import build_daily_summary, build_slot_timeline, summarize_job_progress
from reelforge.scheduler.daily import publish_job_to_youtube, run_daily_slots, run_plan_item_now
from reelforge.storage.cleanup import cleanup_ended_day_videos, get_output_storage_stats
from reelforge.storage.db import ReelDatabase
from reelforge.youtube.oauth import YouTubeOAuthManager
from reelforge.youtube.uploader import YouTubeUploader, clear_health_cache

logger = logging.getLogger("reelforge.web")

# Single worker ensures bounded CPU/RAM usage on laptop hardware
_WORKER = ThreadPoolExecutor(max_workers=1)
_DB = ReelDatabase()
_OAUTH = YouTubeOAuthManager()
_DAILY_LOCK = threading.Lock()
_DAILY_RUNNING = False
_LAST_CLEANUP: Optional[Dict[str, Any]] = None
_BG_STOP = threading.Event()


def get_db() -> ReelDatabase:
    return _DB


def _run_cleanup_now() -> Dict[str, Any]:
    global _LAST_CLEANUP
    res = cleanup_ended_day_videos(get_db())
    _LAST_CLEANUP = res
    return res


def _maintenance_loop() -> None:
    """Background end-of-day garbage remover (runs right after midnight rollover)."""
    last_cleaned_date: Optional[str] = None
    while not _BG_STOP.wait(60.0):
        try:
            tz = ZoneInfo(config.SCHEDULER_TIMEZONE)
            today_str = datetime.now(tz).strftime("%Y-%m-%d")
            if config.AUTO_GARBAGE_CLEANUP and last_cleaned_date != today_str:
                _run_cleanup_now()
                last_cleaned_date = today_str
        except Exception:
            logger.exception("Background garbage cleanup tick error")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    try:
        get_db().recover_interrupted_jobs()
        if config.AUTO_GARBAGE_CLEANUP:
            _run_cleanup_now()
    except Exception:
        logger.exception("Startup recovery/cleanup warning")

    thread: Optional[threading.Thread] = None
    if os.environ.get("REELFORGE_DISABLE_BG_THREADS", "0") != "1":
        _BG_STOP.clear()
        thread = threading.Thread(target=_maintenance_loop, daemon=True, name="reelforge-cleanup")
        thread.start()
    try:
        yield
    finally:
        _BG_STOP.set()
        if thread and thread.is_alive():
            thread.join(timeout=1.0)


app = FastAPI(title="StoryCircuit Studio", version="0.2.0", lifespan=_lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


class GenerateRequest(BaseModel):
    mode: SourceMode = SourceMode.RANDOM
    topic: str = ""
    category: str = "auto"
    style: str = "auto"
    custom_script: str = ""
    visual_mode: Optional[str] = None
    auto_upload: bool = True


class PlanItemRequest(BaseModel):
    planned_date: str
    slot_num: int = Field(default=1, ge=1, le=2)
    publish_time: str = ""
    topic: str = ""
    category: str = "story"
    style: str = "auto"
    custom_script: str = ""
    notes: str = ""


class BulkPlanRequest(BaseModel):
    items: List[PlanItemRequest]


class ScriptAnalyzeRequest(BaseModel):
    script: str
    title: str = ""
    category: str = "story"


class QueueSplitRequest(BaseModel):
    script: str
    title: str = ""
    category: str = "story"
    style: str = "auto"
    start_date: str = ""
    slot1_time: str = ""
    slot2_time: str = ""
    videos_per_day: int = Field(default=2, ge=1, le=2)


class UploadRequest(BaseModel):
    force_mode: Optional[str] = None


class YouTubeSettingsRequest(BaseModel):
    mode: Optional[str] = Field(default=None, pattern="^(simulation|live)$")
    privacy_status: str = Field(default="private", pattern="^(private|unlisted|public)$")


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
        active_snap["video_format"] = focus_raw.get("video_format") or "short"

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
        "worker_busy": bool(active_raw) or _DAILY_RUNNING,
        "daily_running": _DAILY_RUNNING,
        "ollama_online": llm.is_ollama_available(),
        "ollama_model": config.OLLAMA_MODEL,
        "gemini_configured": bool(config.GEMINI_API_KEY),
        "youtube": yt.get_connection_status(verify_network=False),
        "oauth": _OAUTH.get_status(),
        "visual_mode": config.VISUAL_MODE,
        "auto_cleanup": config.AUTO_GARBAGE_CLEANUP,
        "storage": get_output_storage_stats(),
        "last_cleanup": _LAST_CLEANUP,
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
    updates = {"YOUTUBE_PRIVACY_STATUS": req.privacy_status}
    if req.mode:
        updates["YOUTUBE_PUBLISHING_MODE"] = req.mode
    config.save_env_values(updates)
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
        tz = ZoneInfo(config.SCHEDULER_TIMEZONE)
        today_str = datetime.now(tz).strftime("%Y-%m-%d")
        job = run_generation_job(
            db,
            mode=req.mode,
            topic=req.topic,
            category=req.category,
            style=req.style,
            custom_script=req.custom_script,
            visual_mode=req.visual_mode,
            scheduled_date=today_str,
        )
        if req.auto_upload and job.get("status") == "qc_passed":
            try:
                publish_job_to_youtube(db, job["id"])
            except Exception as exc:
                logger.error("Auto-upload skipped/failed for %s: %s", job["id"], exc)
                db.update_job(job["id"], error=f"Auto-upload pending: {exc}")

    _WORKER.submit(_task)
    return {"queued": True, "message": "Generation & YouTube scheduling queued on local worker."}


@app.post("/api/run-daily")
def api_run_daily(auto_upload: bool = True) -> Dict[str, Any]:
    global _DAILY_RUNNING
    with _DAILY_LOCK:
        if _DAILY_RUNNING:
            return {"queued": False, "already_running": True, "message": "Today's 2-video cycle is already running."}
        _DAILY_RUNNING = True

    def _task() -> None:
        global _DAILY_RUNNING
        try:
            run_daily_slots(get_db(), auto_upload=auto_upload)
        finally:
            with _DAILY_LOCK:
                _DAILY_RUNNING = False

    _WORKER.submit(_task)
    return {"queued": True, "message": "Today's 2-video AI generation & YouTube auto-scheduling started."}


@app.post("/api/scripts/analyze")
def api_analyze_script(req: ScriptAnalyzeRequest) -> Dict[str, Any]:
    if not req.script.strip():
        raise HTTPException(status_code=400, detail="Script text cannot be empty.")
    return analyze_and_split_script(
        req.script,
        base_title=req.title,
        category=req.category,
    )


@app.post("/api/scripts/queue-split")
def api_queue_split(req: QueueSplitRequest) -> Dict[str, Any]:
    if not req.script.strip():
        raise HTTPException(status_code=400, detail="Script text cannot be empty.")
    analysis = analyze_and_split_script(req.script, base_title=req.title, category=req.category)
    parts = analysis.get("parts") or []
    if not parts:
        raise HTTPException(status_code=400, detail="Could not extract spoken parts from script.")

    tz = ZoneInfo(config.SCHEDULER_TIMEZONE)
    start_str = req.start_date.strip() or datetime.now(tz).strftime("%Y-%m-%d")
    start_dt = datetime.strptime(start_str, "%Y-%m-%d").date()
    t1 = req.slot1_time.strip() or config.SLOT1_TIME
    t2 = req.slot2_time.strip() or config.SLOT2_TIME

    db = get_db()
    created_ids: List[str] = []
    for idx, part in enumerate(parts):
        day_offset = idx // req.videos_per_day
        slot_num = 1 if req.videos_per_day == 1 else ((idx % 2) + 1)
        planned_date = (start_dt + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        pub_time = t1 if slot_num == 1 else t2
        pid = db.add_plan_item(
            planned_date=planned_date,
            slot_num=slot_num,
            publish_time=pub_time,
            topic=part["title"],
            category=req.category,
            style=req.style,
            custom_script=part["script"],
            notes=f"Auto-split {part['part_number']}/{part['total_parts']} (~{part['estimated_duration_sec']}s)",
        )
        created_ids.append(pid)

    return {
        "queued_count": len(created_ids),
        "ids": created_ids,
        "possible_videos": analysis["possible_videos"],
        "parts": parts,
    }


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
        inner_db = get_db()
        new_job = run_generation_job(
            inner_db,
            mode=mode,
            topic=job.get("title") or "",
            category=job.get("category") or "auto",
            style=job.get("style") or "auto",
            custom_script=custom_script,
            scheduled_date=job.get("scheduled_date"),
            slot_num=job.get("slot_num"),
        )
        if new_job.get("status") == "qc_passed":
            try:
                publish_job_to_youtube(inner_db, new_job["id"])
            except Exception as exc:
                logger.error("Retry upload skipped/failed for %s: %s", new_job["id"], exc)
                inner_db.update_job(new_job["id"], error=f"Upload pending: {exc}")

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
    return {"items": get_db().list_plan_items(limit=250)}


@app.post("/api/plan")
def api_plan_add(req: PlanItemRequest) -> Dict[str, Any]:
    topic = req.topic.strip()
    if not topic and req.custom_script.strip():
        topic = " ".join(req.custom_script.strip().split()[:7]).rstrip(".,!?;:")
    if not topic:
        raise HTTPException(status_code=400, detail="Provide a topic or custom script.")
    pid = get_db().add_plan_item(
        planned_date=req.planned_date,
        slot_num=req.slot_num,
        publish_time=req.publish_time,
        topic=topic,
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
            publish_time=it.publish_time,
            topic=it.topic or " ".join(it.custom_script.strip().split()[:7]).rstrip(".,!?;:") or "Planned Story",
            category=it.category,
            style=it.style,
            custom_script=it.custom_script,
            notes=it.notes,
        )
        for it in req.items
    ]
    return {"ids": ids, "count": len(ids)}


@app.post("/api/plan/{plan_id}/run")
def api_plan_run_now(plan_id: str) -> Dict[str, Any]:
    item = get_db().get_plan_item(plan_id)
    if not item:
        raise HTTPException(status_code=404, detail="Plan item not found")
    _WORKER.submit(run_plan_item_now, get_db(), plan_id, auto_upload=True)
    return {"queued": True, "message": f"Running planned video '{item['topic']}' & auto-scheduling to YouTube."}


@app.delete("/api/plan/{plan_id}")
def api_plan_delete(plan_id: str) -> Dict[str, Any]:
    get_db().delete_plan_item(plan_id)
    return {"deleted": plan_id}


@app.post("/api/cleanup")
def api_cleanup_now() -> Dict[str, Any]:
    return _run_cleanup_now()


@app.get("/api/history")
def api_history() -> Dict[str, Any]:
    return {"history": get_db().list_history(limit=100)}
