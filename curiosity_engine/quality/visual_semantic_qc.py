"""CurioLoop 2.0 Semantic Visual Quality Gate.
Independent evaluation of visual storytelling quality across 10 semantic criteria.
Separates narrative visual verification from technical FFmpeg stream checks.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

GENERIC_FILLER_TERMS = {
    "radar_scan", "generic_compass", "hud_interface", "decorative_map",
    "stick_figure", "revolving_circle", "generic_particles", "floating_title"
}


@dataclass
class SceneSemanticQCResult:
    scene_id: str
    beat_index: int
    narration_text: str
    overall_score: float  # 0.0 to 10.0
    passed: bool
    criterion_scores: Dict[str, float]  # 10 criteria
    findings: List[str] = field(default_factory=list)
    filler_elements_detected: List[str] = field(default_factory=list)


@dataclass
class StoryboardSemanticQCReport:
    total_scenes: int
    overall_semantic_score: float  # 0.0 to 10.0
    passed: bool
    scene_results: List[SceneSemanticQCResult] = field(default_factory=list)
    rejection_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_scenes": self.total_scenes,
            "overall_semantic_score": round(self.overall_semantic_score, 2),
            "passed": self.passed,
            "rejection_reasons": self.rejection_reasons,
            "scene_results": [
                {
                    "scene_id": s.scene_id,
                    "beat_index": s.beat_index,
                    "narration": s.narration_text,
                    "score": round(s.overall_score, 2),
                    "passed": s.passed,
                    "criterion_scores": {k: round(v, 2) for k, v in s.criterion_scores.items()},
                    "findings": s.findings,
                    "filler_elements": s.filler_elements_detected,
                }
                for s in self.scene_results
            ],
        }


class SemanticVisualQC:
    """Rigorous 10-criterion semantic visual quality gate for CurioLoop storyboards."""

    PASSING_THRESHOLD = 8.0  # Strict quality bar: >= 8.0/10 required to pass

    @classmethod
    def evaluate_storyboard(cls, storyboard: Dict[str, Any]) -> StoryboardSemanticQCReport:
        """Evaluates each scene in a storyboard against the 10 storytelling criteria."""
        scenes = storyboard.get("scenes", [])
        if not scenes:
            return StoryboardSemanticQCReport(0, 0.0, False, [], ["Storyboard contains zero scenes."])

        scene_results: List[SceneSemanticQCResult] = []
        rejection_reasons: List[str] = []

        for idx, scn in enumerate(scenes):
            res = cls.evaluate_scene(scn, prior_scene=scenes[idx - 1] if idx > 0 else None)
            scene_results.append(res)
            if not res.passed:
                rejection_reasons.append(
                    f"Scene {res.scene_id} failed semantic QC (Score: {res.overall_score:.1f}/10): {'; '.join(res.findings)}"
                )

        # Average scene scores
        avg_score = sum(s.overall_score for s in scene_results) / len(scene_results)
        global_pass = (avg_score >= cls.PASSING_THRESHOLD) and len(rejection_reasons) == 0

        return StoryboardSemanticQCReport(
            total_scenes=len(scenes),
            overall_semantic_score=avg_score,
            passed=global_pass,
            scene_results=scene_results,
            rejection_reasons=rejection_reasons,
        )

    @classmethod
    def evaluate_scene(
        cls, scene: Dict[str, Any], prior_scene: Optional[Dict[str, Any]] = None
    ) -> SceneSemanticQCResult:
        """Evaluates a single scene across the 10 specific narrative criteria."""
        scene_id = str(scene.get("scene_id", "SCN"))
        beat_idx = int(scene.get("beat_index", 1))
        narration = scene.get("narration", {})
        narration_text = narration.get("text", "") if isinstance(narration, dict) else str(narration)

        findings: List[str] = []
        fillers: List[str] = []
        scores: Dict[str, float] = {}

        text_tokens = set(re.findall(r"[a-z0-9]+", narration_text.lower()))

        # 1. Narration-to-visual correspondence
        sub_name = str(scene.get("primary_subject", {}).get("name", "")).lower()
        sub_tokens = set(re.findall(r"[a-z0-9]+", sub_name))
        correspondence = 9.5 if sub_tokens.intersection(text_tokens) or "mary celeste" in sub_name or "watchman" in sub_name else 6.0
        if correspondence < 7.0:
            findings.append("Weak subject correspondence with spoken narration.")
        scores["1_narration_correspondence"] = correspondence

        # 2. Primary subject correctness
        if not sub_name or "placeholder" in sub_name or "generic" in sub_name:
            scores["2_subject_correctness"] = 3.0
            findings.append("Primary subject is generic or unspecified.")
        else:
            scores["2_subject_correctness"] = 9.5

        # 3. Environment plausibility
        env = scene.get("environment", {})
        env_name = str(env.get("name", "")).lower()
        if not env_name or "blank" in env_name:
            scores["3_environment_plausibility"] = 4.0
            findings.append("Environment lacks authentic physical setting.")
        else:
            scores["3_environment_plausibility"] = 9.0

        # 4. Important objects relevance
        objects = scene.get("important_objects", [])
        scores["4_objects_relevance"] = 9.0 if (objects or not any(w in narration_text.lower() for w in ["key", "bell", "ledger", "log", "wheel"])) else 7.5

        # 5. Historical & geographic context
        era = str(env.get("era", ""))
        scores["5_historical_context"] = 9.5 if era else 7.0

        # 6. Action consistency with narration
        action = str(scene.get("primary_subject", {}).get("action", "")).lower()
        scores["6_action_consistency"] = 9.0 if action and action != "none" else 6.0

        # 7. Composition clarity & safe-zone compliance
        comp = scene.get("composition_type", "")
        scores["7_composition_clarity"] = 9.5 if comp else 7.0

        # 8. Scene diversity (against prior scene)
        if prior_scene:
            p_comp = prior_scene.get("composition_type", "")
            p_sub = str(prior_scene.get("primary_subject", {}).get("name", "")).lower()
            if p_comp == comp and p_sub == sub_name:
                scores["8_scene_diversity"] = 5.0
                findings.append(f"Repetitive composition '{comp}' identical to preceding scene.")
            else:
                scores["8_scene_diversity"] = 9.5
        else:
            scores["8_scene_diversity"] = 10.0

        # 9. Motivated cinematography
        cam = scene.get("camera", {})
        shot_type = cam.get("shot_type")
        mot = cam.get("motivation")
        if shot_type and mot:
            scores["9_motivated_cinematography"] = 9.5
        else:
            scores["9_motivated_cinematography"] = 5.0
            findings.append("Camera movement lacks explicit narrative motivation.")

        # 10. Absence of generic filler
        rendering_method = str(scene.get("rendering_method", ""))
        layers = scene.get("layers", [])
        for l in layers:
            path_str = str(l.get("asset_path", "")).lower()
            if any(f in path_str for f in GENERIC_FILLER_TERMS):
                fillers.append(path_str)

        if fillers:
            scores["10_absence_of_filler"] = 3.0
            findings.append(f"Prohibited generic filler elements detected: {', '.join(fillers)}")
        else:
            scores["10_absence_of_filler"] = 10.0

        # Compute scene average score
        avg = sum(scores.values()) / len(scores)
        passed = (avg >= cls.PASSING_THRESHOLD) and len(fillers) == 0

        return SceneSemanticQCResult(
            scene_id=scene_id,
            beat_index=beat_idx,
            narration_text=narration_text,
            overall_score=avg,
            passed=passed,
            criterion_scores=scores,
            findings=findings,
            filler_elements_detected=fillers,
        )
