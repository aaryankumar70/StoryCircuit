"""CurioLoop 2.0 Pydantic v2 Contracts.
Authoritative data models derived from JSON Schema Draft-07 contracts.
Enforces zero-cost local-first architectural standards across all pipeline stages.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class StoryBeat(BaseModel):
    """Atomic narrative beat binding voice text, emotional register, and visual intention."""
    beat_id: str
    beat_index: int
    act: int = 1
    timestamp_start_estimate_sec: float
    timestamp_end_estimate_sec: float
    narrative_intent: str
    emotional_register: Literal[
        "NEUTRAL",
        "CURIOUS",
        "SUSPENSEFUL",
        "URGENT",
        "SOMBER",
        "AWE",
        "REVELATORY",
    ]
    narration_script: str
    visual_prompt_intent: str
    key_revelation: Optional[str] = None


class ScriptDocument(BaseModel):
    """Curated script document structured into atomic story beats."""
    script_id: str
    topic_id: str
    title: str
    category: Literal[
        "MYSTERY",
        "HISTORY",
        "SPACE_EXTRATERRESTRIAL",
        "CREATOR_SERIES",
    ]
    version: int = 1
    estimated_duration_sec: float
    word_count: int
    average_wpm: float = 145.0
    beats: List[StoryBeat]
    fact_check_status: Literal["PASSED", "WARNINGS_REVIEWED", "REJECTED"] = "PASSED"
    viral_critic_score: float = Field(default=8.5, ge=0.0, le=10.0)


class TopicRecord(BaseModel):
    """Standard discovery and editorial intake record for CurioLoop 2.0."""
    topic_id: str
    category: Literal[
        "MYSTERY",
        "HISTORY",
        "SPACE_EXTRATERRESTRIAL",
        "CREATOR_SERIES",
    ]
    title: str
    premise: str
    narrative_hook: str
    novelty_score: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence_strength: Literal["STRONG", "MODERATE", "SPECULATIVE", "MIXED"] = "STRONG"
    core_conflict: str
    primary_entity: str
    tags: List[str] = Field(default_factory=list)
    status: Literal["PROPOSED", "APPROVED", "REJECTED", "IN_RESEARCH", "PRODUCED"] = "PROPOSED"
    rejection_reason: Optional[str] = None
    editorial_notes: str = ""


class SceneLayer(BaseModel):
    """Individual graphic or atmospheric plane in a 2.5D visual composition."""
    layer_id: str
    plane: Literal["FOREGROUND", "MIDGROUND", "BACKGROUND", "ATMOSPHERE", "OVERLAY"]
    asset_path: str
    depth_z: float
    parallax_factor: float
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    blend_mode: Literal[
        "normal",
        "screen",
        "multiply",
        "overlay",
        "soft-light",
        "additive",
    ] = "normal"


class SceneLighting(BaseModel):
    """Volumetric and key lighting configuration for 2.5D canvas."""
    key_light_direction: List[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0])
    color_temperature_k: int = 5600
    intensity: float = 1.0
    volumetric_haze: float = 0.2


class SceneAtmosphere(BaseModel):
    """Particle and atmospheric effect parameters."""
    fog_density: float = 0.1
    dust_particle_count: int = 40
    rain_intensity: float = 0.0
    turbulence: float = 0.5


class SceneSpecification(BaseModel):
    """Multi-layer 2.5D visual composition specification for continuous rendering."""
    scene_id: str
    beat_id: str
    duration_sec: float
    composition_type: Literal[
        "ESTABLISHING",
        "ENVIRONMENTAL",
        "OBJECT_MACRO",
        "EVIDENCE_CALLOUT",
        "DRAMATIC_REVEAL",
        "DUAL_PERSPECTIVE",
        "TIMELINE_OVERLAY",
    ]
    visual_style: Literal[
        "DIMENSIONAL_2_5D",
        "ARCHIVAL_CHRONICLE",
        "SPECULATIVE_ANOMALY",
        "SCIENTIFIC_TELEMETRY",
    ]
    layers: List[SceneLayer] = Field(default_factory=list)
    lighting: SceneLighting = Field(default_factory=SceneLighting)
    atmosphere: SceneAtmosphere = Field(default_factory=SceneAtmosphere)
    camera_path_ref: str = "SLOW_DRIFT"


class EpisodeItem(BaseModel):
    """Individual serialized episode specification within an EpisodePlan."""
    episode_number: int
    title: str
    duration_sec: float
    opening_hook: str
    core_event: str
    cliffhanger_ending: str
    dependencies: List[int] = Field(default_factory=list)
    word_count: int = 0
    script_text: str = ""
    status: Literal["DRAFT", "SCRIPTED", "AUDIO_READY", "RENDERED", "APPROVED", "STALE_INVALIDATED"] = "DRAFT"


class EpisodePlan(BaseModel):
    """Multi-episode serialization and duration-architecting plan for Creator Studio."""
    series_id: str
    series_title: str
    total_episodes: int = Field(ge=1)
    target_episode_duration_sec: float = 60.0
    episodes: List[EpisodeItem] = Field(default_factory=list)
    chronology_check: bool = True
    continuity_character_set: List[str] = Field(default_factory=list)
    source_rights: Optional[Dict[str, Any]] = None


class VoiceProfile(BaseModel):
    """Local Kokoro ONNX voice synthesizer parameters."""
    voice_id: str
    voice_code: str = "bm_george"  # Deep, warm, resonant, authoritative
    speed: float = 1.05
    pitch_semitones: float = -1.2
    target_integrated_lufs: float = -16.0
    max_true_peak_db: float = -0.5
    prosody_emphasis_tags: bool = True


class RenderJob(BaseModel):
    """Headless 30fps video compositing job specification."""
    job_id: str
    script_id: str
    audio_path: str
    word_timestamps_path: str
    output_path: str
    width: int = 1080
    height: int = 1920
    fps: int = 30
    scenes: List[SceneSpecification]
    watermark_enabled: bool = True
    watermark_opacity: float = 0.55
