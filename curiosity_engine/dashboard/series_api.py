"""FastAPI Router for CurioLoop Creator Series Management.

Defines RESTful API contracts and business logic for series authoring,
story analysis, episode segmentation, scheduling, and QC inspection.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from curiosity_engine.creator_series.models import (
    EpisodeRecord,
    EpisodeStatus,
    RightsStatus,
    SeriesRecord,
    SeriesStatus,
    VisualProfileType,
)
from curiosity_engine.creator_series.series_db import series_db
from curiosity_engine.creator_series.story_adapter import story_adapter
from curiosity_engine.creator_series.visual_director import visual_director
from curiosity_engine.creator_series.visual_qc import visual_qc

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
    time_ist: str = Field("20:30", pattern=r"^\d{2}:\d{2}$")
    slot: int = Field(2, ge=1, le=2)


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

    for idx, ep_id in enumerate(req.ordered_episode_ids):
        ep = series_db.get_episode(ep_id)
        if ep and ep.series_id == series_id:
            ep.episode_num = idx + 1
            series_db.save_episode(ep)

    series.episode_ids = req.ordered_episode_ids
    series_db.save_series(series)
    return {"status": "success", "new_order": req.ordered_episode_ids}


@router.post("/{series_id}/schedule")
def configure_schedule(series_id: str, req: ScheduleSeriesRequest) -> Dict[str, Any]:
    """Set publication slot, target time, and first release date."""
    series = series_db.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    series.publication_schedule = {
        "start_date": req.start_date,
        "time_ist": req.time_ist,
        "slot": req.slot,
        "cadence": "daily",
        "max_episodes_per_day": 1,
    }
    series_db.save_series(series)
    return {"status": "success", "schedule": series.publication_schedule}


@router.post("/{series_id}/activate")
def activate_series(series_id: str) -> Dict[str, Any]:
    """Activate series to claim the 8:30 PM Slot 2 priority."""
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


@router.post("/{series_id}/pause")
def pause_series(series_id: str) -> Dict[str, Any]:
    """Pause series to yield Slot 2 back to automatic Lane A content."""
    series = series_db.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")
    series.status = SeriesStatus.PAUSED
    series_db.save_series(series)
    return {"status": "success", "series_status": series.status}


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
    return {"status": "success", "series_status": series.status}


@router.post("/{series_id}/complete")
def complete_series_manually(series_id: str) -> Dict[str, Any]:
    """Mark a series manually as COMPLETED."""
    series = series_db.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")
    series.status = SeriesStatus.COMPLETED
    series_db.save_series(series)
    return {"status": "success", "series_status": series.status}
