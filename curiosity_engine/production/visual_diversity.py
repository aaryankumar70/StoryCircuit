"""CurioLoop 2.0 Visual Diversity Checker.
Evaluates storyboard sequences to prevent visual repetition:
detects cloned compositions, repeated camera paths, identical color palettes,
and overused visual effects.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DiversityComparison:
    scene_a_id: str
    scene_b_id: str
    composition_similarity: float
    subject_similarity: float
    camera_similarity: float
    palette_similarity: float
    overall_similarity: float
    is_duplicate: bool
    issues: List[str] = field(default_factory=list)


@dataclass
class SequenceDiversityReport:
    total_scenes: int
    diversity_score: float  # 0.0 to 10.0 scale (10.0 = completely rich, diverse storytelling)
    passed: bool
    max_adjacent_similarity: float
    violations: List[str] = field(default_factory=list)
    comparisons: List[DiversityComparison] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_scenes": self.total_scenes,
            "diversity_score": round(self.diversity_score, 2),
            "passed": self.passed,
            "max_adjacent_similarity": round(self.max_adjacent_similarity, 3),
            "violations": self.violations,
        }


class VisualDiversityChecker:
    """Audits scene sequences to ensure high narrative variety and eliminate generic repetition."""

    REPETITION_THRESHOLD = 0.70  # Pairwise similarity above 70% is flagged

    @classmethod
    def compare_scenes(
        cls, scene_a: Dict[str, Any], scene_b: Dict[str, Any]
    ) -> DiversityComparison:
        """Compare two scenes across 4 key visual dimensions."""
        issues: List[str] = []

        # 1. Composition similarity
        comp_a = str(scene_a.get("composition_type") or scene_a.get("composition", {}).get("type") or "")
        comp_b = str(scene_b.get("composition_type") or scene_b.get("composition", {}).get("type") or "")
        comp_sim = 1.0 if (comp_a and comp_a == comp_b) else 0.0
        if comp_sim == 1.0:
            issues.append(f"Identical composition archetype: '{comp_a}'")

        # 2. Subject similarity
        sub_a = str(scene_a.get("primary_subject") or scene_a.get("main_subject", {}).get("name") or "").lower()
        sub_b = str(scene_b.get("primary_subject") or scene_b.get("main_subject", {}).get("name") or "").lower()
        sub_sim = 1.0 if (sub_a and sub_a == sub_b) else (0.5 if (sub_a and sub_b and (sub_a in sub_b or sub_b in sub_a)) else 0.0)
        if sub_sim >= 0.8:
            issues.append(f"Identical focal subject: '{sub_a}'")

        # 3. Camera shot similarity
        cam_a = str(scene_a.get("camera_shot") or scene_a.get("camera_behavior", {}).get("shot_type") or "")
        cam_b = str(scene_b.get("camera_shot") or scene_b.get("camera_behavior", {}).get("shot_type") or "")
        cam_sim = 1.0 if (cam_a and cam_a == cam_b) else 0.0
        if cam_sim == 1.0:
            issues.append(f"Identical camera shot: '{cam_a}'")

        # 4. Environment & Lighting Palette similarity
        env_a = str(scene_a.get("environment_kit") or scene_a.get("environment", {}).get("kit") or "")
        env_b = str(scene_b.get("environment_kit") or scene_b.get("environment", {}).get("kit") or "")
        env_sim = 1.0 if (env_a and env_a == env_b) else 0.0

        # Weighted composite similarity:
        # Repetitive composition (35%) + Repeated camera (25%) + Overlapping subject (25%) + Same env (15%)
        overall = (
            comp_sim * 0.35
            + cam_sim * 0.25
            + sub_sim * 0.25
            + env_sim * 0.15
        )

        is_dup = overall >= cls.REPETITION_THRESHOLD

        return DiversityComparison(
            scene_a_id=scene_a.get("scene_id", "A"),
            scene_b_id=scene_b.get("scene_id", "B"),
            composition_similarity=comp_sim,
            subject_similarity=sub_sim,
            camera_similarity=cam_sim,
            palette_similarity=env_sim,
            overall_similarity=overall,
            is_duplicate=is_dup,
            issues=issues,
        )

    @classmethod
    def audit_sequence(cls, scenes: List[Dict[str, Any]]) -> SequenceDiversityReport:
        """Audits an entire storyboard sequence of scenes."""
        if not scenes:
            return SequenceDiversityReport(0, 10.0, True, 0.0)

        if len(scenes) == 1:
            return SequenceDiversityReport(1, 10.0, True, 0.0)

        comparisons: List[DiversityComparison] = []
        violations: List[str] = []
        max_adj_sim = 0.0

        for i in range(len(scenes) - 1):
            comp = cls.compare_scenes(scenes[i], scenes[i + 1])
            comparisons.append(comp)
            if comp.overall_similarity > max_adj_sim:
                max_adj_sim = comp.overall_similarity

            if comp.is_duplicate:
                msg = (
                    f"Adjacent scenes [{comp.scene_a_id} -> {comp.scene_b_id}] violate diversity "
                    f"({comp.overall_similarity:.0%} similarity): {', '.join(comp.issues)}"
                )
                violations.append(msg)

        # Global variety checks
        compositions = [s.get("composition_type") or s.get("composition", {}).get("type") for s in scenes if s]
        unique_comps = len(set(filter(None, compositions)))
        comp_ratio = unique_comps / max(1, len(scenes))
        if comp_ratio < 0.5:
            violations.append(
                f"Low composition variety: only {unique_comps} unique archetypes across {len(scenes)} scenes."
            )

        # Compute 0-10 score
        penalty = len(violations) * 2.0
        score = max(0.0, min(10.0, 10.0 - penalty))

        return SequenceDiversityReport(
            total_scenes=len(scenes),
            diversity_score=score,
            passed=len(violations) == 0,
            max_adjacent_similarity=max_adj_sim,
            violations=violations,
            comparisons=comparisons,
        )
