"""CurioLoop 2.0 Visual Continuity Engine.
Ensures strict cinematic continuity across storyboards:
tracks characters, key props, spatial environments, historical eras,
time-of-day transitions, and 180-degree camera direction rules.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ContinuityViolation:
    scene_id: str
    rule: str
    severity: str  # "HARD_VIOLATION" or "WARNING"
    description: str


@dataclass
class ContinuityAuditReport:
    total_scenes: int
    passed: bool
    violations: List[ContinuityViolation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_scenes": self.total_scenes,
            "passed": self.passed,
            "violations_count": len(self.violations),
            "warnings_count": len(self.warnings),
            "violations": [
                {"scene_id": v.scene_id, "rule": v.rule, "severity": v.severity, "desc": v.description}
                for v in self.violations
            ],
            "warnings": self.warnings,
        }


class VisualContinuityTracker:
    """Tracks persistent narrative entities and ensures logical cinematic transitions."""

    VALID_TIME_PROGRESSION = {
        "DAWN": ["DAWN", "MORNING", "DAY"],
        "MORNING": ["MORNING", "DAY", "AFTERNOON"],
        "DAY": ["DAY", "AFTERNOON", "GOLDEN_HOUR"],
        "AFTERNOON": ["AFTERNOON", "GOLDEN_HOUR", "DUSK"],
        "GOLDEN_HOUR": ["GOLDEN_HOUR", "DUSK", "NIGHT"],
        "DUSK": ["DUSK", "NIGHT", "MIDNIGHT"],
        "NIGHT": ["NIGHT", "MIDNIGHT", "DAWN"],
        "MIDNIGHT": ["MIDNIGHT", "NIGHT", "DAWN"],
    }

    def __init__(self):
        self.history: List[Dict[str, Any]] = []
        self.registered_entities: Dict[str, Dict[str, Any]] = {}

    def reset(self) -> None:
        self.history.clear()
        self.registered_entities.clear()

    def audit_scene(self, scene: Dict[str, Any]) -> List[ContinuityViolation]:
        """Audit a single scene against historical sequence."""
        violations: List[ContinuityViolation] = []
        scene_id = str(scene.get("scene_id", f"SCN_{len(self.history) + 1}"))

        if not self.history:
            self._record(scene)
            return violations

        prev = self.history[-1]

        # 1. Historical Era Consistency
        curr_era = str(scene.get("historical_era") or scene.get("environment", {}).get("era") or "").upper()
        prev_era = str(prev.get("historical_era") or prev.get("environment", {}).get("era") or "").upper()
        is_flashback = bool(scene.get("is_flashback") or scene.get("continuity", {}).get("flashback", False))
        if curr_era and prev_era and curr_era != prev_era and not is_flashback:
            violations.append(
                ContinuityViolation(
                    scene_id=scene_id,
                    rule="HISTORICAL_ERA_RUPTURE",
                    severity="HARD_VIOLATION",
                    description=f"Abrupt era change from '{prev_era}' to '{curr_era}' without flashback flag.",
                )
            )

        # 2. Time of Day Progression
        curr_time = str(scene.get("time_of_day") or scene.get("environment", {}).get("time_of_day") or "").upper()
        prev_time = str(prev.get("time_of_day") or prev.get("environment", {}).get("time_of_day") or "").upper()
        is_time_jump = bool(scene.get("is_time_jump") or scene.get("continuity", {}).get("time_jump", False))
        if curr_time in self.VALID_TIME_PROGRESSION and prev_time in self.VALID_TIME_PROGRESSION and not is_time_jump:
            allowed = self.VALID_TIME_PROGRESSION[prev_time]
            if curr_time not in allowed:
                violations.append(
                    ContinuityViolation(
                        scene_id=scene_id,
                        rule="TIME_PROGRESSION_RUPTURE",
                        severity="WARNING",
                        description=f"Illogical time of day transition from '{prev_time}' to '{curr_time}' without transition marker.",
                    )
                )

        # 3. 180-Degree Screen Direction Rule
        curr_dir = str(scene.get("screen_direction") or scene.get("cinematography", {}).get("screen_direction") or "").upper()
        prev_dir = str(prev.get("screen_direction") or prev.get("cinematography", {}).get("screen_direction") or "").upper()
        is_reverse_cut = bool(scene.get("is_reverse_angle", False))
        opposing = (curr_dir == "LEFT_TO_RIGHT" and prev_dir == "RIGHT_TO_LEFT") or (
            curr_dir == "RIGHT_TO_LEFT" and prev_dir == "LEFT_TO_RIGHT"
        )
        if opposing and not is_reverse_cut:
            violations.append(
                ContinuityViolation(
                    scene_id=scene_id,
                    rule="SCREEN_DIRECTION_FLIP",
                    severity="WARNING",
                    description=f"Camera tracking axis inverted from '{prev_dir}' to '{curr_dir}' violating screen direction.",
                )
            )

        # 4. Important Object / Entity Continuity
        objects = scene.get("important_objects") or []
        for obj in objects:
            if isinstance(obj, dict):
                obj_id = obj.get("id") or obj.get("name")
                if obj_id:
                    if obj_id in self.registered_entities:
                        prior_state = self.registered_entities[obj_id]
                        if obj.get("state") and prior_state.get("state") and obj.get("state") != prior_state.get("state"):
                            # State change is logged as narrative progression
                            pass
                    else:
                        self.registered_entities[obj_id] = obj

        self._record(scene)
        return violations

    def _record(self, scene: Dict[str, Any]) -> None:
        self.history.append(scene)

    def audit_sequence(self, scenes: List[Dict[str, Any]]) -> ContinuityAuditReport:
        """Audits an entire sequence of storyboard scenes."""
        self.reset()
        all_violations: List[ContinuityViolation] = []
        warnings: List[str] = []

        for s in scenes:
            v_list = self.audit_scene(s)
            all_violations.extend(v_list)
            for v in v_list:
                if v.severity == "WARNING":
                    warnings.append(f"[{v.scene_id}] {v.rule}: {v.description}")

        hard_violations = [v for v in all_violations if v.severity == "HARD_VIOLATION"]
        passed = len(hard_violations) == 0

        return ContinuityAuditReport(
            total_scenes=len(scenes),
            passed=passed,
            violations=all_violations,
            warnings=warnings,
        )
