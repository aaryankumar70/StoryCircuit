"""FastAPI Router for CurioLoop Creator Series Management.

Defines RESTful API contracts and business logic for series authoring,
story analysis, episode segmentation, scheduling, and QC inspection.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from curiosity_engine.creator_series.models import (
    EpisodeRecord,
    EpisodeStatus,
    RightsStatus,
    SeriesRecord,
    SeriesStatus,
    VisualProfileType,
)
from curiosity_engine.creator_series.creator_studio_engine import CreatorStudioEngine
from curiosity_engine.creator_series.production_planner import (
    production_planner,
    estimate_duration_seconds,
)
from curiosity_engine.creator_series.queue_manager import queue_manager
from curiosity_engine.creator_series.creator_queue import creator_queue_manager
from curiosity_engine.creator_series.series_db import series_db
from curiosity_engine.creator_series.series_scheduler import series_scheduler
from curiosity_engine.creator_series.story_adapter import story_adapter

logger = logging.getLogger("curiosity_engine.series_api")

router = APIRouter(prefix="/api/series", tags=["Creator Series"])


# Request / Response Schemas
class CreateSeriesRequest(BaseModel):
    series_id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    title: str = Field(..., min_length=1)
    full_script: str = Field(..., min_length=50)
    content_type: str = Field("psychological_horror")
    visual_profile: str = Field("psychological_horror")
    creator_name: Optional[str] = None
    creator_source: Optional[str] = None
    rights_status: str = Field("UNVERIFIED_EVALUATION_ONLY")
    target_duration: float = Field(48.0, ge=30.0, le=60.0)


class EditEpisodeRequest(BaseModel):
    episode_id: str
    title: Optional[str] = None
    adapted_narration: Optional[str] = None
    hook: Optional[str] = None
    cliffhanger: Optional[str] = None


class ReorderEpisodesRequest(BaseModel):
    ordered_episode_ids: List[str]


class ScheduleSeriesRequest(BaseModel):
    start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    schedule_type: str = "A"
    start_time: Optional[str] = Field("20:30", pattern=r"^\d{2}:\d{2}$")
    timezone: str = "Asia/Kolkata"
    cadence: str = "daily"
    custom_slots: Optional[List[str]] = None
    custom_days: Optional[List[str]] = None
    interval_days: int = Field(1, ge=1, le=365)

    class Config:
        extra = "forbid"


class SchedulePreviewRequest(BaseModel):
    series_id: Optional[str] = None
    episode_count: Optional[int] = None
    schedule_type: Optional[str] = "A"  # 'A', 'B', 'C'
    start_date: Optional[str] = None
    start_time: Optional[str] = None
    timezone: Optional[str] = "Asia/Kolkata"
    cadence: Optional[str] = "daily"  # 'daily', 'alternate', 'custom'
    custom_slots: Optional[List[str]] = None
    custom_days: Optional[List[str]] = None
    interval_days: Optional[int] = 1

    class Config:
        extra = "forbid"


class ScheduleCommitRequest(BaseModel):
    schedule_type: Optional[str] = "A"
    start_date: Optional[str] = None
    start_time: Optional[str] = None
    timezone: Optional[str] = "Asia/Kolkata"
    cadence: Optional[str] = "daily"
    custom_slots: Optional[List[str]] = None
    custom_days: Optional[List[str]] = None
    interval_days: int = Field(1, ge=1, le=365)

    class Config:
        extra = "forbid"


class ImportStoryRequest(BaseModel):
    text: Optional[str] = None
    filename: Optional[str] = "story.txt"
    author: Optional[str] = "Anonymous"
    source_url: Optional[str] = None
    permission_status: Optional[str] = "UNVERIFIED_EVALUATION_ONLY"
    attribution: Optional[str] = None


class IngestPasteRequest(BaseModel):
    raw_text: str = Field(..., min_length=1)
    title: Optional[str] = None
    author: Optional[str] = "Anonymous"
    source_url: Optional[str] = None
    permission_status: Optional[str] = "UNVERIFIED_EVALUATION_ONLY"
    attribution: Optional[str] = None


class IngestRedditRequest(BaseModel):
    url: str = Field(..., min_length=10)
    permission_status: Optional[str] = "UNVERIFIED_EVALUATION_ONLY"
    attribution: Optional[str] = None


class AnalyzeStoryRequest(BaseModel):
    raw_text: Optional[str] = None
    series_id: Optional[str] = None
    title: Optional[str] = None
    use_local_ai: Optional[bool] = True


class StoryBreakdownRequest(BaseModel):
    series_id: Optional[str] = None
    title: str = "Creator Series"
    raw_text: str = Field(..., min_length=20)
    duration_preset: str = Field("1m", description="1m (60s), 1.5m (90s), 3m (180s), or custom")
    custom_seconds: Optional[float] = Field(60.0, ge=20.0, le=180.0)
    author: Optional[str] = "Anonymous"
    source_url: Optional[str] = None
    permission_status: Optional[str] = "UNVERIFIED_EVALUATION_ONLY"
    attribution: Optional[str] = None


class RecommendPlansRequest(BaseModel):
    series_id: Optional[str] = None
    raw_text: Optional[str] = None
    analysis: Optional[Dict[str, Any]] = None
    title: Optional[str] = "Creator Story"
    custom_seconds: Optional[float] = Field(None, ge=20.0, le=180.0)


class GenerateBreakdownRequest(BaseModel):
    series_id: Optional[str] = None
    title: Optional[str] = "Creator Series"
    raw_text: Optional[str] = None
    selected_plan: Optional[Dict[str, Any]] = None
    duration_preset: Optional[str] = "1m"
    custom_seconds: Optional[float] = Field(None, ge=20.0, le=180.0)
    analysis: Optional[Dict[str, Any]] = None
    rights_status: Optional[str] = "UNVERIFIED_EVALUATION_ONLY"
    author: Optional[str] = "Anonymous"
    source_url: Optional[str] = None
    attribution: Optional[str] = None


class SingleEpisodeEditRequest(BaseModel):
    title: Optional[str] = None
    adapted_narration: Optional[str] = None
    text: Optional[str] = None
    hook: Optional[str] = None
    cliffhanger: Optional[str] = None
    visual_notes: Optional[str] = None


class ApproveStoryboardRequest(BaseModel):
    approved: bool = True
    reviewer: Optional[str] = "Creator"
    notes: Optional[str] = None


class ReviewRightsRequest(BaseModel):
    rights_status: RightsStatus
    evidence_note: str = Field(..., min_length=8, max_length=2000)


@router.post("/create", status_code=status.HTTP_201_CREATED)
def create_series(req: CreateSeriesRequest) -> Dict[str, Any]:
    """Create a new Creator Series in DRAFT state."""
    existing = series_db.get_series(req.series_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Series with ID '{req.series_id}' already exists.",
        )

    series = SeriesRecord(
        series_id=req.series_id,
        title=req.title,
        full_script=req.full_script,
        creator_info={"name": req.creator_name, "source": req.creator_source},
        content_type=req.content_type,
        visual_profile=req.visual_profile,
        rights_status=RightsStatus(req.rights_status),
        target_duration=req.target_duration,
        status=SeriesStatus.DRAFT,
    )
    series_db.save_series(series)
    return {"status": "success", "series": series.to_dict()}


@router.post("/import")
def import_story_document(req: ImportStoryRequest) -> Dict[str, Any]:
    """Ingest a story document (TXT, Markdown, raw text), analyze narrative structure and rights."""
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="Story text cannot be empty.")

    ingested = CreatorStudioEngine.ingest_document(req.text, filename=req.filename or "story.txt")
    clean_text = ingested["raw_text"] if isinstance(ingested, dict) else str(ingested)
    analysis = CreatorStudioEngine.analyze_story(clean_text)
    return {
        "status": "success",
        "clean_text": clean_text,
        "word_count": len(clean_text.split()),
        "analysis": analysis,
        "rights": {
            "author": req.author or "Anonymous",
            "source_url": req.source_url,
            "permission_status": req.permission_status,
            "attribution": req.attribution,
        },
    }


@router.post("/ingest/upload")
async def ingest_upload(
    file: UploadFile = File(...),
    author: Optional[str] = Form("Anonymous"),
    source_url: Optional[str] = Form(None),
    permission_status: Optional[str] = Form("UNVERIFIED_EVALUATION_ONLY"),
    attribution: Optional[str] = Form(None),
) -> Dict[str, Any]:
    """Multipart upload entry point for .txt, .md, and .docx documents."""
    filename = file.filename or "uploaded_story.txt"
    ext = Path(filename).suffix.lower()
    if ext not in [".txt", ".md", ".markdown", ".docx"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension '{ext}'. Only .txt, .md, and .docx files are supported.",
        )

    max_bytes = 8 * 1024 * 1024
    content_bytes = await file.read(max_bytes + 1)
    if len(content_bytes) > max_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Story uploads are limited to 8 MiB.")
    if not content_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    rights_data = {
        "source_type": "FILE_UPLOAD",
        "author": author or "Anonymous",
        "source_url": source_url or "",
        "rights_status": permission_status or "UNVERIFIED_EVALUATION_ONLY",
        "permission_verified": permission_status in ["VERIFIED", "LICENSED", "OWNED"],
        "attribution_statement": attribution or f"Story by {author or 'Creator'}",
    }

    try:
        result = CreatorStudioEngine.ingest_document(
            file_path_or_text=content_bytes,
            filename=filename,
            source_rights=rights_data,
            save_upload=True,
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error("Failed to parse uploaded document %s: %s", filename, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process file: {e}",
        )

    return {
        "status": "success",
        "title": result["title"],
        "raw_text": result["raw_text"],
        "word_count": result["word_count"],
        "estimated_spoken_duration_sec": result["estimated_spoken_duration_sec"],
        "average_wpm": result["average_wpm"],
        "file_type": result["file_type"],
        "original_filename": result["original_filename"],
        "preserved_path": result["preserved_path"],
        "rights": result["rights"],
    }


@router.post("/ingest/paste")
def ingest_paste(req: IngestPasteRequest) -> Dict[str, Any]:
    """Long-form editing workspace entry point with word count and duration estimation."""
    if not req.raw_text or not req.raw_text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pasted text cannot be empty.")

    rights_data = {
        "source_type": "PASTE",
        "author": req.author or "Anonymous",
        "source_url": req.source_url or "",
        "rights_status": req.permission_status or "UNVERIFIED_EVALUATION_ONLY",
        "permission_verified": req.permission_status in ["VERIFIED", "LICENSED", "OWNED"],
        "attribution_statement": req.attribution or f"Story by {req.author or 'Creator'}",
    }

    try:
        result = CreatorStudioEngine.ingest_paste(
            raw_text=req.raw_text,
            title=req.title,
            source_rights=rights_data,
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    return {
        "status": "success",
        "title": result["title"],
        "raw_text": result["raw_text"],
        "word_count": result["word_count"],
        "estimated_spoken_duration_sec": result["estimated_spoken_duration_sec"],
        "average_wpm": result["average_wpm"],
        "rights": result["rights"],
    }


@router.post("/ingest/reddit")
def ingest_reddit(req: IngestRedditRequest) -> Dict[str, Any]:
    """Fetch public Reddit post via official JSON API, validating against deleted/removed/404."""
    rights_data = {
        "rights_status": req.permission_status or "UNVERIFIED_EVALUATION_ONLY",
        "attribution": req.attribution,
    }
    try:
        result = CreatorStudioEngine.ingest_reddit(url=req.url, source_rights=rights_data)
        return {
            "status": "success",
            "title": result["title"],
            "raw_text": result["raw_text"],
            "word_count": result["word_count"],
            "estimated_spoken_duration_sec": result["estimated_spoken_duration_sec"],
            "average_wpm": result["average_wpm"],
            "author": result["author"],
            "subreddit": result["subreddit"],
            "permalink": result["permalink"],
            "score": result["score"],
            "num_comments": result["num_comments"],
            "over_18": result["over_18"],
            "rights": result["rights"],
        }
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error("Reddit ingestion failed for URL %s: %s", req.url, e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to fetch Reddit post: {e}")


@router.post("/analyze")
def analyze_story_endpoint(req: AnalyzeStoryRequest) -> Dict[str, Any]:
    """Accepts raw text or series_id and returns deep narrative analysis without episode splitting."""
    text_to_analyze = req.raw_text
    story_title = req.title

    if not text_to_analyze and req.series_id:
        series = series_db.get_series(req.series_id)
        if not series:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Series with ID '{req.series_id}' not found.",
            )
        text_to_analyze = series.full_script
        if not story_title:
            story_title = series.title

    if not text_to_analyze or not text_to_analyze.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'raw_text' or a valid 'series_id' containing story script must be provided.",
        )

    try:
        analysis = CreatorStudioEngine.analyze_story(
            raw_text_or_dict=text_to_analyze,
            title=story_title,
            use_local_ai=req.use_local_ai if req.use_local_ai is not None else True,
        )
    except Exception as e:
        logger.error("Story analysis failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Intelligent story analysis failed: {e}",
        )

    return {
        "status": "success",
        "title": analysis.get("title", story_title or "Creator Series"),
        "genre": analysis.get("genre", "Psychological Horror"),
        "word_count": analysis.get("word_count", len(text_to_analyze.split())),
        "estimated_spoken_duration_sec": analysis.get("estimated_spoken_duration_sec", 0.0),
        "analysis": analysis,
    }


@router.post("/breakdown")
def generate_series_breakdown(req: StoryBreakdownRequest) -> Dict[str, Any]:
    """Segment long-form story into organic episodes at sentence boundaries and persist to SeriesDatabase."""
    preset_durations = {
        "1m": 60.0,
        "1.5m": 90.0,
        "3m": 180.0,
    }
    target_sec = preset_durations.get(req.duration_preset, req.custom_seconds or 60.0)

    rights_data = {
        "author": req.author or "Anonymous",
        "source_url": req.source_url,
        "permission_status": req.permission_status or "UNVERIFIED_EVALUATION_ONLY",
        "attribution": req.attribution,
    }

    breakdown = CreatorStudioEngine.segment_into_episodes(
        raw_text=req.raw_text,
        target_duration_sec=target_sec,
        series_title=req.title,
        rights_data=rights_data,
    )

    series_id = req.series_id or f"series_{int(datetime.now().timestamp())}"
    episodes_data = breakdown.get("episodes", [])
    ep_records: List[EpisodeRecord] = []
    ep_ids: List[str] = []

    for ep in episodes_data:
        ep_num = ep.get("episode_index", 1)
        ep_id = f"{series_id}_ep{ep_num:02d}"
        ep_rec = EpisodeRecord(
            episode_id=ep_id,
            series_id=series_id,
            episode_num=ep_num,
            title=ep.get("title", f"Episode {ep_num}"),
            adapted_narration=ep.get("narration", ""),
            source_segment=ep.get("narration", ""),
            hook=ep.get("opening_hook", ""),
            cliffhanger=ep.get("cliffhanger", ""),
            estimated_duration=float(ep.get("estimated_duration_sec", target_sec)),
            status=EpisodeStatus.ADAPTED,
        )
        ep_records.append(ep_rec)
        ep_ids.append(ep_id)

    rights_status = RightsStatus.UNVERIFIED_EVALUATION_ONLY
    if req.permission_status in ["VERIFIED", "LICENSED"]:
        rights_status = RightsStatus.LICENSED
    elif req.permission_status == "PUBLIC_DOMAIN":
        rights_status = RightsStatus.PUBLIC_DOMAIN
    elif req.permission_status == "OWNED":
        rights_status = RightsStatus.OWNED

    series = SeriesRecord(
        series_id=series_id,
        title=req.title,
        full_script=req.raw_text,
        creator_info={
            "name": req.author,
            "source": req.source_url,
            "attribution": req.attribution or req.author or "Creator Series",
            "rights_status": rights_status.value,
            "source_type": "REDDIT" if req.source_url and "reddit.com" in req.source_url.lower() else "CREATOR_PROVIDED",
        },
        content_type="creator_story",
        visual_profile="psychological_horror",
        rights_status=rights_status,
        target_duration=target_sec,
        planned_episodes=len(ep_records),
        episode_ids=ep_ids,
        status=SeriesStatus.READY,
    )
    series_db.save_series_and_episodes(series, ep_records)

    return {
        "status": "success",
        "series": series.to_dict(),
        "breakdown": breakdown,
        "episodes": [e.to_dict() for e in ep_records],
    }


@router.get("")
def list_series() -> Dict[str, Any]:
    """List all creator series."""
    series_list = series_db.get_all_series()
    return {"total": len(series_list), "series": [s.to_dict() for s in series_list]}


@router.get("/{series_id}")
def get_series_detail(series_id: str) -> Dict[str, Any]:
    """Fetch complete metadata for a single series."""
    series = series_db.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")
    episodes = series_db.get_episodes_for_series(series_id)
    return {
        "series": series.to_dict(),
        "episodes": [ep.to_dict() for ep in episodes],
    }


@router.post("/{series_id}/analyze")
def analyze_series_story(series_id: str) -> Dict[str, Any]:
    """Perform Step 1 full-story narrative and character analysis."""
    series = series_db.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    analysis = story_adapter.analyze_story(series.title, series.full_script)
    rec_count = story_adapter.determine_episode_count(series.full_script)
    return {
        "analysis": analysis.to_dict(),
        "recommended_episode_count": rec_count,
        "estimated_total_duration_sec": story_adapter.estimate_narration_duration(series.full_script),
    }


@router.post("/{series_id}/segment")
def segment_series_episodes(series_id: str, episode_count: Optional[int] = None) -> Dict[str, Any]:
    """Segment story into discrete sequential episodes with hooks and cliffhangers."""
    series = series_db.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    analysis = story_adapter.analyze_story(series.title, series.full_script)
    outlines = story_adapter.create_narrative_outline(analysis, series.full_script, episode_count)

    created_episodes = []
    episode_ids = []
    for outline in outlines:
        ep_rec = story_adapter.adapt_episode_narration(series.series_id, outline, series.full_script, analysis)
        series_db.save_episode(ep_rec)
        created_episodes.append(ep_rec.to_dict())
        episode_ids.append(ep_rec.episode_id)

    series.planned_episodes = len(created_episodes)
    series.episode_ids = episode_ids
    series.status = SeriesStatus.READY
    series_db.save_series(series)

    return {
        "status": "success",
        "planned_episodes": len(created_episodes),
        "episodes": created_episodes,
    }


@router.post("/{series_id}/episodes/edit")
def edit_episode_script(series_id: str, req: EditEpisodeRequest) -> Dict[str, Any]:
    """Edit adapted narration or boundaries of a specific episode before activation."""
    ep = series_db.get_episode(req.episode_id)
    if not ep or ep.series_id != series_id:
        raise HTTPException(status_code=404, detail=f"Episode '{req.episode_id}' not found.")

    if req.title:
        ep.title = req.title
    if req.adapted_narration:
        ep.adapted_narration = req.adapted_narration
        ep.estimated_duration = story_adapter.estimate_narration_duration(req.adapted_narration)
        # Enforce cascading invalidation
        ep.status = EpisodeStatus.STALE_INVALIDATED
        ep.rendered_video_path = None
        ep.audio_path = None
        ep.visual_storyboard_path = None
        ep.qc_result = None
    if req.hook:
        ep.hook = req.hook
    if req.cliffhanger:
        ep.cliffhanger = req.cliffhanger

    series_db.save_episode(ep)
    return {"status": "success", "episode": ep.to_dict()}


@router.post("/{series_id}/episodes/reorder")
def reorder_episodes(series_id: str, req: ReorderEpisodesRequest) -> Dict[str, Any]:
    """Reorder episodes prior to series activation."""
    series = series_db.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")
    if series.status == SeriesStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Cannot reorder episodes of an ACTIVE series.")

    reordered = []
    for idx, ep_id in enumerate(req.ordered_episode_ids):
        ep = series_db.get_episode(ep_id)
        if ep and ep.series_id == series_id:
            ep.episode_num = idx + 1
            reordered.append(ep)

    series.episode_ids = req.ordered_episode_ids
    series_db.save_series_and_episodes(series, reordered)
    return {"status": "success", "new_order": req.ordered_episode_ids}


@router.post("/{series_id}/schedule")
def configure_schedule(series_id: str, req: ScheduleSeriesRequest) -> Dict[str, Any]:
    """Preview and persist the Creator cadence without claiming an Automatic slot."""
    series = series_db.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")
    config_payload = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    try:
        preview = series_scheduler.generate_calendar_preview(
            series_id=series_id,
            episode_count=len(series.episode_ids),
            schedule_type=req.schedule_type,
            start_date=req.start_date,
            start_time=req.start_time,
            timezone_name=req.timezone,
            cadence=req.cadence,
            custom_slots=req.custom_slots,
            custom_days=req.custom_days,
            interval_days=req.interval_days,
            s_db=series_db,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Creator schedule: {exc}")
    series.publication_schedule = {**config_payload, "calendar": preview["calendar"]}
    series_db.save_series(series)
    return {"status": "success", "schedule": series.publication_schedule, "calendar": preview["calendar"]}


@router.post("/{series_id}/activate")
def activate_series(series_id: str) -> Dict[str, Any]:
    """Activate a Creator series; Automatic Studio reservations remain separate."""
    series = series_db.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")
    if series.status == SeriesStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Completed series cannot be reactivated.")

    # Check rights safety
    if series.rights_status == RightsStatus.UNVERIFIED_EVALUATION_ONLY:
        logger.warning(f"Activating series '{series_id}' under UNVERIFIED_EVALUATION_ONLY mode.")

    series.status = SeriesStatus.ACTIVE
    series_db.save_series(series)
    return {"status": "success", "series_status": series.status}


@router.post("/{series_id}/rights")
def review_series_rights(series_id: str, req: ReviewRightsRequest) -> Dict[str, Any]:
    """Record the creator's rights decision and release any eligible rights-held jobs."""
    series = series_db.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")
    series.rights_status = req.rights_status
    series.creator_info = {**(series.creator_info or {}), "rights_review_note": req.evidence_note.strip(),
                           "rights_reviewed_at": datetime.now(timezone.utc).isoformat()}
    series_db.save_series(series)
    released = []
    if req.rights_status in (RightsStatus.OWNED, RightsStatus.LICENSED, RightsStatus.PUBLIC_DOMAIN):
        try:
            released = creator_queue_manager.enqueue_series(series_id)
        except ValueError:
            # A rights review may be recorded before the user commits a release calendar.
            pass
    return {"status": "success", "rights_status": req.rights_status.value, "released_jobs": len(released)}


@router.post("/{series_id}/pause")
def pause_series(series_id: str) -> Dict[str, Any]:
    """Pause series to yield execution while preserving Automatic Studio."""
    series = series_db.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")
    series.status = SeriesStatus.PAUSED
    series_db.save_series(series)
    paused_count = creator_queue_manager.set_series_paused(series_id, True)
    return {
        "status": "success",
        "series_status": series.status.value,
        "series_id": series_id,
        "paused_jobs": paused_count,
    }


@router.post("/{series_id}/resume")
def resume_series(series_id: str) -> Dict[str, Any]:
    """Resume previously paused series."""
    series = series_db.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")
    if series.status != SeriesStatus.PAUSED:
        raise HTTPException(status_code=400, detail=f"Series is '{series.status}', not PAUSED.")
    series.status = SeriesStatus.ACTIVE
    series_db.save_series(series)
    resumed_count = creator_queue_manager.set_series_paused(series_id, False)
    return {
        "status": "success",
        "series_status": series.status.value,
        "series_id": series_id,
        "resumed_jobs": resumed_count,
    }


@router.post("/{series_id}/cancel")
def cancel_series(series_id: str) -> Dict[str, Any]:
    """Cancel series execution and dequeue all pending episodes."""
    series = series_db.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")
    series.status = SeriesStatus.CANCELLED
    episodes = series_db.get_episodes_for_series(series_id)
    for episode in episodes:
        if episode.status not in (EpisodeStatus.PUBLISHED, EpisodeStatus.FAILED):
            episode.status = EpisodeStatus.CANCELLED
    series_db.save_series_and_episodes(series, episodes)
    counts = creator_queue_manager.cancel_series(series_id)
    return {
        "status": "success",
        "series_status": series.status.value,
        "series_id": series_id,
        "cancelled_jobs": counts["cancelled"],
        "running_jobs_cancellation_requested": counts["running"],
    }


@router.get("/{series_id}/queue-status")
def get_series_queue_status(series_id: str) -> Dict[str, Any]:
    """Return production lifecycle statuses across all episodes in the series."""
    try:
        result = queue_manager.get_series_queue_status(series_id, s_db=series_db)
        jobs = creator_queue_manager.get_series_jobs(series_id)
        result["creator_queue"] = {
            "queue_file": "creator_series_queue.json",
            "jobs": jobs,
            "pending": sum(j.get("status") in ("QUEUED", "RETRY_WAIT", "PAUSED") for j in jobs),
            "running": sum(j.get("status") == "RUNNING" for j in jobs),
            "failed": sum(j.get("status") == "FAILED" for j in jobs),
            "blocked_rights": sum(j.get("status") == "BLOCKED_RIGHTS" for j in jobs),
        }
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{series_id}/complete")
def complete_series_manually(series_id: str) -> Dict[str, Any]:
    """Mark a series manually as COMPLETED."""
    series = series_db.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")
    series.status = SeriesStatus.COMPLETED
    series_db.save_series(series)
    return {"status": "success", "series_status": series.status}
    return {"status": "success", "series_status": series.status}


# ──────────────────────────────────────────────────────────────────────────
# Step 3: Production-Plan Recommendations
# ──────────────────────────────────────────────────────────────────────────

@router.post("/recommend-plans")
def recommend_production_plans(req: RecommendPlansRequest) -> Dict[str, Any]:
    """Generates 2-3 dynamic production plans based on natural narrative stopping points with trade-off analysis."""
    raw_text = req.raw_text
    title = req.title or "Creator Story"

    if not raw_text and req.series_id:
        series = series_db.get_series(req.series_id)
        if not series:
            raise HTTPException(status_code=404, detail=f"Series '{req.series_id}' not found.")
        raw_text = series.full_script
        title = series.title

    if not raw_text or not raw_text.strip():
        raise HTTPException(status_code=400, detail="Either 'raw_text' or valid 'series_id' must be provided.")

    plans = production_planner.generate_production_plans(
        raw_text=raw_text,
        title=title,
        analysis=req.analysis,
        custom_seconds=req.custom_seconds,
    )

    return {
        "status": "success",
        "story_title": title,
        "total_words": len(raw_text.split()),
        "estimated_total_duration_sec": estimate_duration_seconds(raw_text),
        "recommended_plans": plans,
    }


# ──────────────────────────────────────────────────────────────────────────
# Step 4: Episode Breakdown & Three.js Storyboard Generation
# ──────────────────────────────────────────────────────────────────────────

@router.post("/generate-breakdown")
def generate_breakdown(req: GenerateBreakdownRequest) -> Dict[str, Any]:
    """Accepts selected plan and generates episode scripts and Three.js visual scene storyboards."""
    raw_text = req.raw_text
    title = req.title or "Creator Series"

    if not raw_text and req.series_id:
        series = series_db.get_series(req.series_id)
        if series:
            raw_text = series.full_script
            if not req.title or req.title == "Creator Series":
                title = series.title

    if not raw_text or not raw_text.strip():
        raise HTTPException(status_code=400, detail="Either 'raw_text' or valid 'series_id' must be provided.")

    series_rec, ep_records = production_planner.generate_episode_breakdown_and_storyboards(
        raw_text=raw_text,
        series_id=req.series_id,
        title=title,
        selected_plan=req.selected_plan,
        duration_preset=req.duration_preset or "1m",
        custom_seconds=req.custom_seconds,
        rights_status=req.rights_status or "UNVERIFIED_EVALUATION_ONLY",
        author=req.author or "Anonymous",
        source_url=req.source_url,
        attribution=req.attribution,
        analysis=req.analysis,
    )

    return {
        "status": "success",
        "series": series_rec.to_dict(),
        "episodes": [ep.to_dict() for ep in ep_records],
        "total_episodes": len(ep_records),
    }


# ──────────────────────────────────────────────────────────────────────────
# Step 4: Granular Episode Editing with Cascading Invalidation
# ──────────────────────────────────────────────────────────────────────────

@router.put("/episodes/{episode_id}")
@router.post("/episodes/{episode_id}")
def edit_single_episode(episode_id: str, req: SingleEpisodeEditRequest) -> Dict[str, Any]:
    """Granular edit of a single episode with cascading invalidation (STALE_INVALIDATED).
    Untouched episodes in the series remain completely unaffected.
    """
    try:
        narration = req.adapted_narration or req.text
        ep = production_planner.edit_single_episode_with_invalidation(
            episode_id=episode_id,
            title=req.title,
            adapted_narration=narration,
            hook=req.hook,
            cliffhanger=req.cliffhanger,
            visual_notes=req.visual_notes,
        )
        return {
            "status": "success",
            "message": f"Episode '{episode_id}' updated and marked STALE_INVALIDATED.",
            "episode": ep.to_dict(),
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Episode '{episode_id}' not found.")


# ──────────────────────────────────────────────────────────────────────────
# Step 4: Visual Storyboard Approval Gate
# ──────────────────────────────────────────────────────────────────────────

@router.post("/episodes/{episode_id}/approve")
def approve_episode_storyboard(episode_id: str, req: Optional[ApproveStoryboardRequest] = None) -> Dict[str, Any]:
    """Sets visual storyboard approval status on a single episode."""
    r = req or ApproveStoryboardRequest()
    try:
        ep = production_planner.set_storyboard_approval(
            episode_id=episode_id,
            approved=r.approved,
            reviewer=r.reviewer or "Creator",
            notes=r.notes,
        )
        return {
            "status": "success",
            "episode_id": episode_id,
            "is_approved": ep.is_approved,
            "episode_status": ep.status.value,
            "episode": ep.to_dict(),
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Episode '{episode_id}' not found.")


# ──────────────────────────────────────────────────────────────────────────
# Step 5: Scheduling Planner
# ──────────────────────────────────────────────────────────────────────────

@router.post("/schedule/preview")
def preview_series_schedule(req: SchedulePreviewRequest) -> Dict[str, Any]:
    """Generate calendar release preview and estimated completion date."""
    try:
        preview = series_scheduler.generate_calendar_preview(
            series_id=req.series_id,
            episode_count=req.episode_count,
            schedule_type=req.schedule_type or "A",
            start_date=req.start_date,
            start_time=req.start_time,
            timezone_name=req.timezone or "Asia/Kolkata",
            cadence=req.cadence or "daily",
            custom_slots=req.custom_slots,
            custom_days=req.custom_days,
            interval_days=req.interval_days or 1,
            s_db=series_db,
        )
        return preview
    except Exception as e:
        logger.error(f"Schedule preview generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Schedule preview failed: {e}")


@router.post("/{series_id}/schedule/commit")
def commit_series_schedule(series_id: str, req: ScheduleCommitRequest) -> Dict[str, Any]:
    """Lock in publication schedule and enqueue episodes into sequential queue."""
    series = series_db.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")
    try:
        config_payload = req.model_dump() if hasattr(req, "model_dump") else req.dict()
        res = series_scheduler.commit_series_schedule(
            series_id=series_id,
            schedule_config=config_payload,
            s_db=series_db,
        )
        enqueued = queue_manager.enqueue_series(series_id, s_db=series_db)
        res["enqueued_jobs"] = len(enqueued)
        res["queue_status"] = queue_manager.get_series_queue_status(series_id, s_db=series_db)
        try:
            creator_queue_manager.enqueue_series(series_id, episodes=series_db.get_episodes_for_series(series_id))
        except Exception:
            pass
        return res
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Schedule commit failed for series '{series_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to commit schedule: {e}")


