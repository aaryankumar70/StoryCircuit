"""CurioLoop 2.0 Cinematography Engine.
Provides motivated camera direction, shot archetypes, trajectory evaluation,
and biological handheld drift for cinematic visual storytelling.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class CameraShotType(str, Enum):
    ESTABLISHING = "ESTABLISHING"
    WIDE = "WIDE"
    MEDIUM = "MEDIUM"
    CLOSEUP = "CLOSEUP"
    MACRO_CLOSEUP = "MACRO_CLOSEUP"
    TRACKING = "TRACKING"
    DOLLY_IN = "DOLLY_IN"
    DOLLY_OUT = "DOLLY_OUT"
    ORBIT = "ORBIT"
    AERIAL_SURVEY = "AERIAL_SURVEY"
    PAN_TILT = "PAN_TILT"
    RACK_FOCUS = "RACK_FOCUS"
    DRAMATIC_REVEAL = "DRAMATIC_REVEAL"


class CameraMotivation(str, Enum):
    REVEAL = "REVEAL"
    INVESTIGATION = "INVESTIGATION"
    DISCOVERY = "DISCOVERY"
    ISOLATION = "ISOLATION"
    THREAT = "THREAT"
    EVIDENCE = "EVIDENCE"
    ATMOSPHERE = "ATMOSPHERE"
    PURSUIT = "PURSUIT"


@dataclass
class CameraKeyframe:
    position: Tuple[float, float, float]
    look_at: Tuple[float, float, float]
    roll: float = 0.0
    fov: float = 45.0
    focal_distance: float = 400.0


@dataclass
class CameraShotSpec:
    shot_type: CameraShotType
    motivation: CameraMotivation
    duration_sec: float
    screen_direction: str = "LEFT_TO_RIGHT"
    shake_intensity: float = 0.25
    keyframes: List[CameraKeyframe] = field(default_factory=list)
    narrative_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_type": self.shot_type.value,
            "motivation": self.motivation.value,
            "duration_sec": self.duration_sec,
            "screen_direction": self.screen_direction,
            "shake_intensity": self.shake_intensity,
            "narrative_reason": self.narrative_reason,
            "keyframes": [
                {
                    "position": list(k.position),
                    "look_at": list(k.look_at),
                    "roll": k.roll,
                    "fov": k.fov,
                    "focal_distance": k.focal_distance,
                }
                for k in self.keyframes
            ],
        }


def quintic_in_out(t: float) -> float:
    """Quintic easing for smooth, natural camera drift without mechanical snaps."""
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 16.0 * (t**5)
    return 1.0 - ((-2.0 * t + 2.0) ** 5) / 2.0


def create_motivated_camera_path(
    shot_type: CameraShotType,
    motivation: CameraMotivation,
    duration_sec: float,
    target: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    narrative_reason: str = "",
) -> CameraShotSpec:
    """Generate a pair of camera keyframes motivated by the narrative event."""
    tx, ty, tz = target
    k0: CameraKeyframe
    k1: CameraKeyframe
    shake = 0.25
    direction = "LEFT_TO_RIGHT"

    if shot_type == CameraShotType.DOLLY_IN:
        # Pushes in from wide perspective to intimate subject scrutiny
        k0 = CameraKeyframe(
            position=(tx, ty + 40.0, tz + 700.0),
            look_at=(tx, ty, tz),
            roll=0.0,
            fov=50.0,
            focal_distance=650.0,
        )
        k1 = CameraKeyframe(
            position=(tx, ty + 10.0, tz + 280.0),
            look_at=(tx, ty, tz),
            roll=0.0,
            fov=45.0,
            focal_distance=280.0,
        )
        direction = "PUSH_IN"
    elif shot_type == CameraShotType.DOLLY_OUT:
        # Pulls back to reveal vastness, abandonment, or isolation
        k0 = CameraKeyframe(
            position=(tx, ty + 10.0, tz + 240.0),
            look_at=(tx, ty, tz),
            roll=0.0,
            fov=45.0,
            focal_distance=240.0,
        )
        k1 = CameraKeyframe(
            position=(tx, ty + 100.0, tz + 850.0),
            look_at=(tx, ty, tz),
            roll=0.0,
            fov=52.0,
            focal_distance=800.0,
        )
        direction = "PULL_BACK"
    elif shot_type == CameraShotType.TRACKING:
        # Lateral movement following a subject across horizontal space
        k0 = CameraKeyframe(
            position=(tx - 260.0, ty + 20.0, tz + 480.0),
            look_at=(tx - 40.0, ty, tz),
            roll=-0.015,
            fov=46.0,
            focal_distance=460.0,
        )
        k1 = CameraKeyframe(
            position=(tx + 260.0, ty + 20.0, tz + 440.0),
            look_at=(tx + 40.0, ty, tz),
            roll=0.015,
            fov=46.0,
            focal_distance=440.0,
        )
        direction = "LEFT_TO_RIGHT"
    elif shot_type == CameraShotType.ORBIT:
        # Controlled investigative arc around a mysterious subject or relic
        k0 = CameraKeyframe(
            position=(tx - 240.0, ty + 60.0, tz + 460.0),
            look_at=(tx, ty, tz),
            roll=-0.01,
            fov=45.0,
            focal_distance=450.0,
        )
        k1 = CameraKeyframe(
            position=(tx + 240.0, ty + 80.0, tz + 430.0),
            look_at=(tx, ty, tz),
            roll=0.01,
            fov=45.0,
            focal_distance=430.0,
        )
        direction = "ARC_SURROUND"
    elif shot_type == CameraShotType.MACRO_CLOSEUP:
        # Ultra-shallow focal depth scrutiny of handwritten log, relic, or key prop
        k0 = CameraKeyframe(
            position=(tx - 25.0, ty + 20.0, tz + 170.0),
            look_at=(tx, ty, tz),
            roll=0.0,
            fov=40.0,
            focal_distance=170.0,
        )
        k1 = CameraKeyframe(
            position=(tx + 15.0, ty + 8.0, tz + 115.0),
            look_at=(tx, ty, tz),
            roll=0.008,
            fov=38.0,
            focal_distance=115.0,
        )
        shake = 0.15
        direction = "MACRO_SCRUTINY"
    elif shot_type == CameraShotType.AERIAL_SURVEY:
        # High-angle downward perspective observing maritime transit, ruins, or outpost
        k0 = CameraKeyframe(
            position=(tx, ty + 620.0, tz + 320.0),
            look_at=(tx, ty, tz),
            roll=0.0,
            fov=55.0,
            focal_distance=600.0,
        )
        k1 = CameraKeyframe(
            position=(tx + 80.0, ty + 480.0, tz + 210.0),
            look_at=(tx, ty, tz),
            roll=0.012,
            fov=52.0,
            focal_distance=480.0,
        )
        direction = "AERIAL_GLIDE"
    elif shot_type == CameraShotType.PAN_TILT:
        # Controlled vertical or diagonal reveal
        k0 = CameraKeyframe(
            position=(tx - 120.0, ty - 80.0, tz + 520.0),
            look_at=(tx - 120.0, ty - 80.0, tz),
            roll=0.0,
            fov=48.0,
            focal_distance=520.0,
        )
        k1 = CameraKeyframe(
            position=(tx + 120.0, ty + 90.0, tz + 500.0),
            look_at=(tx + 120.0, ty + 90.0, tz),
            roll=0.0,
            fov=48.0,
            focal_distance=500.0,
        )
        direction = "TILT_UP"
    elif shot_type == CameraShotType.RACK_FOCUS:
        # Shift in optical clarity from foreground clue to background truth
        k0 = CameraKeyframe(
            position=(tx, ty + 25.0, tz + 410.0),
            look_at=(tx, ty, tz),
            roll=0.0,
            fov=45.0,
            focal_distance=180.0,  # Focus on near object
        )
        k1 = CameraKeyframe(
            position=(tx, ty + 25.0, tz + 390.0),
            look_at=(tx, ty, tz),
            roll=0.0,
            fov=45.0,
            focal_distance=550.0,  # Rack to deep background
        )
        direction = "RACK_FOCUS"
    else:  # ESTABLISHING or WIDE
        k0 = CameraKeyframe(
            position=(tx, ty + 60.0, tz + 680.0),
            look_at=(tx, ty, tz),
            roll=0.0,
            fov=52.0,
            focal_distance=680.0,
        )
        k1 = CameraKeyframe(
            position=(tx, ty + 40.0, tz + 540.0),
            look_at=(tx, ty, tz),
            roll=0.0,
            fov=48.0,
            focal_distance=540.0,
        )
        direction = "ESTABLISHING_DRIFT"

    return CameraShotSpec(
        shot_type=shot_type,
        motivation=motivation,
        duration_sec=duration_sec,
        screen_direction=direction,
        shake_intensity=shake,
        keyframes=[k0, k1],
        narrative_reason=narrative_reason
        or f"{shot_type.value} motivated by {motivation.value} to direct viewer attention.",
    )
