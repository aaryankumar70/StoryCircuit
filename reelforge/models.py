"""Typed domain models for ReelForge (StoryCircuit)."""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SourceMode(str, Enum):
    RANDOM = "random"
    PLAN = "plan"
    CUSTOM_SCRIPT = "custom_script"


class VideoFormat(str, Enum):
    SHORT = "short"  # 1080x1920 vertical 9:16 (<= 120s)
    LONG = "long"    # 1920x1080 landscape 16:9 (> 120s)


class VisualStyle(str, Enum):
    EDITORIAL_DARK = "editorial_dark"
    VINTAGE_ARCHIVAL = "vintage_archival"
    GRAPHIC_NOIR = "graphic_noir"
    CINEMATIC_PAINTERLY = "cinematic_painterly"
    BLUEPRINT_TECH = "blueprint_tech"


STYLE_PROMPTS: Dict[str, str] = {
    VisualStyle.EDITORIAL_DARK.value: (
        "dramatic editorial documentary illustration, deep charcoal shadows, warm amber rim lighting, "
        "crisp detail, moody atmosphere, vertical 9:16 composition, no text, no watermark"
    ),
    VisualStyle.VINTAGE_ARCHIVAL.value: (
        "aged archival documentary photograph aesthetic, muted sepia and slate tones, subtle film grain, "
        "authentic historical mood, vertical 9:16 composition, no text, no watermark"
    ),
    VisualStyle.GRAPHIC_NOIR.value: (
        "high-contrast graphic novel ink illustration, bold cel shading, crimson and teal accents, "
        "expressive storytelling framing, vertical 9:16 composition, no text, no watermark"
    ),
    VisualStyle.CINEMATIC_PAINTERLY.value: (
        "rich cinematic concept art painting, volumetric light rays, atmospheric depth, "
        "vivid storytelling scene, vertical 9:16 composition, no text, no watermark"
    ),
    VisualStyle.BLUEPRINT_TECH.value: (
        "sleek isometric technical illustration on midnight navy background, glowing cyan accents, "
        "clean visual metaphor, vertical 9:16 composition, no text, no watermark"
    ),
}


def get_style_prompt(style: VisualStyle, video_format: VideoFormat = VideoFormat.SHORT) -> str:
    """Return style prompt adapted to vertical 9:16 Shorts or widescreen 16:9 landscape."""
    base = STYLE_PROMPTS.get(style.value, STYLE_PROMPTS[VisualStyle.EDITORIAL_DARK.value])
    if video_format == VideoFormat.LONG:
        return base.replace("vertical 9:16 composition", "widescreen 16:9 cinematic composition")
    return base


class MotionType(str, Enum):
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    PULSE = "pulse"


class MediaPreference(str, Enum):
    AI_IMAGE = "ai_image"
    ARCHIVAL = "archival"
    GRAPHIC_CARD = "graphic_card"


class BeatSpec(BaseModel):
    index: int
    speaker: str = "narrator"  # "narrator" | "primary" | "secondary"
    text: str
    visual_prompt: str
    archival_query: str = ""
    media_preference: MediaPreference = MediaPreference.AI_IMAGE
    motion: MotionType = MotionType.ZOOM_IN
    callout_title: str = ""
    callout_stat: str = ""
    resolved_image_path: Optional[str] = None
    resolved_source: Optional[str] = None
    start_sec: float = 0.0
    end_sec: float = 0.0


class StoryPlan(BaseModel):
    title: str
    hook: str
    category: str = "story"
    style: VisualStyle = VisualStyle.EDITORIAL_DARK
    beats: List[BeatSpec] = Field(default_factory=list)
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    source_mode: SourceMode = SourceMode.RANDOM
    source_ref: str = ""
    video_format: VideoFormat = VideoFormat.SHORT
    target_width: int = 1080
    target_height: int = 1920

    @property
    def full_script(self) -> str:
        return " ".join(b.text.strip() for b in self.beats if b.text.strip())


class WordTiming(BaseModel):
    word: str
    start_sec: float
    end_sec: float
    speaker: str = "narrator"


class QCReport(BaseModel):
    passed: bool
    checks: Dict[str, Any] = Field(default_factory=dict)
    issues: List[str] = Field(default_factory=list)
