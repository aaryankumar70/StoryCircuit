"""Data models and type definitions for CurioLoop Creator Series & Cinematic Visuals.

Provides strongly typed schemas for:
- Series and Episode persistence
- Story analysis, outline, and episode segmentation
- Character, location, and story continuity bibles
- Visual quality rubric scoring
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class SeriesStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EpisodeStatus(str, Enum):
    # Step 6 Production Lifecycle statuses
    PLANNED = "PLANNED"
    SCRIPT_READY = "SCRIPT_READY"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    IN_PRODUCTION = "IN_PRODUCTION"
    QC_FAILED = "QC_FAILED"
    READY_FOR_PUBLISHING = "READY_FOR_PUBLISHING"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"

    # Additional pipeline and backward-compatible states
    DRAFT = "DRAFT"
    ADAPTED = "ADAPTED"
    STORYBOARDED = "STORYBOARDED"
    AUDIO_READY = "AUDIO_READY"
    RENDERED = "RENDERED"
    QC_PASSED = "QC_PASSED"
    READY = "READY"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    STALE_INVALIDATED = "STALE_INVALIDATED"


EPISODE_STATUS_DISPLAY_MAP: Dict[EpisodeStatus, str] = {
    EpisodeStatus.PLANNED: "Planned",
    EpisodeStatus.DRAFT: "Planned",
    EpisodeStatus.SCRIPT_READY: "Script ready",
    EpisodeStatus.ADAPTED: "Script ready",
    EpisodeStatus.AWAITING_APPROVAL: "Awaiting approval",
    EpisodeStatus.STORYBOARDED: "Awaiting approval",
    EpisodeStatus.IN_PRODUCTION: "In production",
    EpisodeStatus.AUDIO_READY: "In production",
    EpisodeStatus.RENDERED: "In production",
    EpisodeStatus.QC_FAILED: "QC failed",
    EpisodeStatus.FAILED: "QC failed",
    EpisodeStatus.READY_FOR_PUBLISHING: "Ready for publishing",
    EpisodeStatus.QC_PASSED: "Ready for publishing",
    EpisodeStatus.READY: "Ready for publishing",
    EpisodeStatus.SCHEDULED: "Scheduled",
    EpisodeStatus.PUBLISHED: "Published",
    EpisodeStatus.CANCELLED: "Cancelled",
    EpisodeStatus.STALE_INVALIDATED: "Planned",
}


def normalize_episode_status(val: Any) -> EpisodeStatus:
    """Normalize any string or enum value to valid EpisodeStatus enum."""
    if isinstance(val, EpisodeStatus):
        return val
    s = str(val or "").strip().upper().replace(" ", "_")
    alias_map = {
        "PLANNED": EpisodeStatus.PLANNED,
        "DRAFT": EpisodeStatus.DRAFT,
        "SCRIPT_READY": EpisodeStatus.SCRIPT_READY,
        "ADAPTED": EpisodeStatus.ADAPTED,
        "AWAITING_APPROVAL": EpisodeStatus.AWAITING_APPROVAL,
        "STORYBOARDED": EpisodeStatus.STORYBOARDED,
        "IN_PRODUCTION": EpisodeStatus.IN_PRODUCTION,
        "AUDIO_READY": EpisodeStatus.AUDIO_READY,
        "RENDERED": EpisodeStatus.RENDERED,
        "QC_FAILED": EpisodeStatus.QC_FAILED,
        "FAILED": EpisodeStatus.FAILED,
        "READY_FOR_PUBLISHING": EpisodeStatus.READY_FOR_PUBLISHING,
        "QC_PASSED": EpisodeStatus.QC_PASSED,
        "READY": EpisodeStatus.READY,
        "SCHEDULED": EpisodeStatus.SCHEDULED,
        "PUBLISHED": EpisodeStatus.PUBLISHED,
        "CANCELLED": EpisodeStatus.CANCELLED,
        "STALE_INVALIDATED": EpisodeStatus.STALE_INVALIDATED,
    }
    return alias_map.get(s, EpisodeStatus.PLANNED)


def normalize_series_status(val: Any) -> SeriesStatus:
    """Normalize any string or enum value to valid SeriesStatus enum."""
    if isinstance(val, SeriesStatus):
        return val
    s = str(val or "").strip().upper().replace(" ", "_")
    try:
        return SeriesStatus(s)
    except ValueError:
        return SeriesStatus.DRAFT


class VisualProfileType(str, Enum):
    PSYCHOLOGICAL_HORROR = "psychological_horror"
    MYSTERY_INVESTIGATIVE = "mystery_investigative"
    HISTORICAL = "historical"
    CUSTOM = "custom"


class RightsStatus(str, Enum):
    OWNED = "OWNED"
    LICENSED = "LICENSED"
    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
    UNVERIFIED_EVALUATION_ONLY = "UNVERIFIED_EVALUATION_ONLY"


@dataclass
class SeriesRecord:
    series_id: str
    title: str
    full_script: str
    creator_info: Dict[str, Any] = field(default_factory=dict)
    content_type: str = "psychological_horror"
    language: str = "en"
    target_duration: float = 48.0
    planned_episodes: int = 0
    episode_ids: List[str] = field(default_factory=list)
    status: SeriesStatus = SeriesStatus.DRAFT
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    next_episode_num: int = 1
    publication_schedule: Dict[str, Any] = field(default_factory=lambda: {
        "slot": 2,
        "time_ist": "20:30",
        "cadence": "daily",
        "max_episodes_per_day": 1,
    })
    published_episode_ids: List[str] = field(default_factory=list)
    failed_episode_ids: List[str] = field(default_factory=list)
    completion_state: Dict[str, Any] = field(default_factory=dict)
    rights_status: RightsStatus = RightsStatus.UNVERIFIED_EVALUATION_ONLY
    visual_profile: str = VisualProfileType.PSYCHOLOGICAL_HORROR.value
    visual_bible_path: Optional[str] = None
    bible_version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, SeriesStatus) else str(self.status)
        d["rights_status"] = self.rights_status.value if isinstance(self.rights_status, RightsStatus) else str(self.rights_status)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SeriesRecord":
        copied = dict(data)
        if "status" in copied:
            copied["status"] = normalize_series_status(copied["status"])
        if "rights_status" in copied and isinstance(copied["rights_status"], str):
            copied["rights_status"] = RightsStatus(copied["rights_status"])
        # filter unexpected keys
        valid_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in copied.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class EpisodeRecord:
    episode_id: str
    series_id: str
    episode_num: int
    title: str
    adapted_narration: str
    source_segment: Dict[str, Any] = field(default_factory=dict)
    hook: str = ""
    beats: List[str] = field(default_factory=list)
    cliffhanger: str = ""
    estimated_duration: float = 48.0
    actual_duration: Optional[float] = None
    audio_path: Optional[str] = None
    visual_storyboard_path: Optional[str] = None
    rendered_video_path: Optional[str] = None
    status: EpisodeStatus = EpisodeStatus.DRAFT
    upload_status: str = "PENDING"
    youtube_id: Optional[str] = None
    scheduled_publication_time: Optional[str] = None
    actual_publication_time: Optional[str] = None
    retry_count: int = 0
    qc_result: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_approved: bool = False
    approval_date: Optional[str] = None
    version: int = 1
    storyboard: Optional[Dict[str, Any]] = None

    @property
    def lifecycle_status(self) -> str:
        status_enum = self.status if isinstance(self.status, EpisodeStatus) else normalize_episode_status(self.status)
        return EPISODE_STATUS_DISPLAY_MAP.get(status_enum, str(status_enum.value))

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, EpisodeStatus) else str(self.status)
        d["lifecycle_status"] = self.lifecycle_status
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EpisodeRecord":
        copied = dict(data)
        if "status" in copied:
            copied["status"] = normalize_episode_status(copied["status"])
        valid_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in copied.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class VisualQualityScore:
    """10-criterion rubric evaluation from cinematic-story-visuals/references/visual_quality_rubric.md."""
    narrative_relevance: float
    cinematic_composition: float
    atmosphere: float
    lighting: float
    colour_consistency: float
    character_consistency: float
    environment_consistency: float
    motion_quality: float
    visual_pacing: float
    episode_continuity: float
    notes: List[str] = field(default_factory=list)
    automatic_failures: List[str] = field(default_factory=list)

    @property
    def average_score(self) -> float:
        scores = [
            self.narrative_relevance,
            self.cinematic_composition,
            self.atmosphere,
            self.lighting,
            self.colour_consistency,
            self.character_consistency,
            self.environment_consistency,
            self.motion_quality,
            self.visual_pacing,
            self.episode_continuity,
        ]
        return round(sum(scores) / len(scores), 2)

    @property
    def min_score(self) -> float:
        return min([
            self.narrative_relevance,
            self.cinematic_composition,
            self.atmosphere,
            self.lighting,
            self.colour_consistency,
            self.character_consistency,
            self.environment_consistency,
            self.motion_quality,
            self.visual_pacing,
            self.episode_continuity,
        ])

    @property
    def serialized_score_min(self) -> float:
        return min(self.character_consistency, self.environment_consistency, self.episode_continuity)

    @property
    def verdict(self) -> str:
        if self.automatic_failures or self.average_score < 6.5 or self.min_score <= 4.0:
            return "REJECT"
        if self.average_score >= 8.0 and self.min_score >= 7.0 and self.serialized_score_min >= 8.0:
            return "SHIP"
        return "REVISE"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "narrative_relevance": self.narrative_relevance,
            "cinematic_composition": self.cinematic_composition,
            "atmosphere": self.atmosphere,
            "lighting": self.lighting,
            "colour_consistency": self.colour_consistency,
            "character_consistency": self.character_consistency,
            "environment_consistency": self.environment_consistency,
            "motion_quality": self.motion_quality,
            "visual_pacing": self.visual_pacing,
            "episode_continuity": self.episode_continuity,
            "average_score": self.average_score,
            "min_score": self.min_score,
            "serialized_score_min": self.serialized_score_min,
            "verdict": self.verdict,
            "notes": self.notes,
            "automatic_failures": self.automatic_failures,
        }
