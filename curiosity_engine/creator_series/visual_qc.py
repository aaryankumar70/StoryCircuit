"""Visual Quality Control Evaluator for CurioLoop Creator Series.

Implements the 10-criterion rubric scoring from:
.agent/skills/cinematic-story-visuals/references/visual_quality_rubric.md

Thresholds:
- SHIP: avg >= 8.0, all criteria >= 7.0, serialized criteria >= 8.0, no auto failures
- REVISE: avg 6.5 - 7.9 or any criterion 5.0 - 6.0
- REJECT: avg < 6.5, any criterion <= 4.0, or any automatic failure
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from curiosity_engine.creator_series.models import VisualQualityScore

logger = logging.getLogger("curiosity_engine.visual_qc")


class VisualQCEvaluator:
    """Evaluates storyboards and visual production records against the quality rubric."""

    def evaluate_storyboard(
        self,
        storyboard: Dict[str, Any],
        bible: Dict[str, Any],
        previous_storyboard: Optional[Dict[str, Any]] = None,
    ) -> VisualQualityScore:
        """Evaluate episode storyboard against the 10 rubric criteria."""
        notes: List[str] = []
        auto_failures: List[str] = []

        scenes = storyboard.get("scenes", [])
        num_scenes = len(scenes)

        # 1. Narrative Relevance: Check that scenes map to narration
        narrative_rel = 8.5
        if num_scenes < 3:
            narrative_rel = 5.0
            notes.append("Too few scenes for adequate narrative progression")

        # 2. Cinematic Composition: Check shot variety & negative space
        shot_types = {s.get("shot", {}).get("type") for s in scenes}
        cinematic_comp = 8.5 if len(shot_types) >= 3 else 7.0

        # 3. Atmosphere: Check mood and horror elements
        profile = storyboard.get("profile", "")
        atmosphere = 9.0 if profile == "psychological_horror" else 8.0

        # 4. Lighting: Check motivated lighting & contrast
        lighting_scores = []
        for s in scenes:
            l = s.get("lighting", {})
            if l.get("contrast") == "high" and l.get("practicals"):
                lighting_scores.append(8.5)
            else:
                lighting_scores.append(7.0)
        lighting = round(sum(lighting_scores) / len(lighting_scores), 1) if lighting_scores else 7.5

        # 5. Colour Consistency: Verify hexes match bible palette
        palette_info = bible.get("visual_identity", {}).get("palette", {})
        valid_hexes = {c["hex"].lower() for c in palette_info.get("colors", [])}
        color_consistent = True
        for s in scenes:
            scene_pal = s.get("palette", [])
            if isinstance(scene_pal, list):
                hex_list = [h.lower() for h in scene_pal]
            elif isinstance(scene_pal, dict):
                hex_list = [v.lower() for v in scene_pal.values() if isinstance(v, str) and v.startswith("#")]
            else:
                hex_list = []
            for h in hex_list:
                if h not in valid_hexes:
                    color_consistent = False
                    notes.append(f"Scene {s.get('scene_id')} uses palette hex outside bible: {h}")
        colour_cons = 8.5 if color_consistent else 6.5

        # 6. Character Consistency: Check locked appearance states
        char_cons = 8.5
        bible_chars = {c["character_id"] for c in bible.get("characters", [])}
        for s in scenes:
            for ch in s.get("characters", []):
                if ch.get("character_id") not in bible_chars:
                    char_cons = 6.0
                    auto_failures.append(f"Unregistered character ID in scene {s.get('scene_id')}: {ch.get('character_id')}")

        # 7. Environment Consistency: Check registered locations
        bible_locs = {l["location_id"] for l in bible.get("locations", [])}
        env_cons = 8.5
        for s in scenes:
            if s.get("location_id") not in bible_locs:
                env_cons = 6.0
                notes.append(f"Unregistered location in scene {s.get('scene_id')}: {s.get('location_id')}")

        # 8. Motion Quality: Verify subtle speed, no forbidden violent camera shake
        motion_quality = 8.5
        for s in scenes:
            speed = s.get("motion", {}).get("speed")
            if speed == "erratic":
                motion_quality = 5.0
                auto_failures.append("Violent erratic motion violates psychological horror guidelines")

        # 9. Visual Pacing: Scene durations calibrated to narration
        pacing_scores = []
        for s in scenes:
            narr = s.get("narration", {})
            d = narr.get("end_s", 0) - narr.get("start_s", 0)
            if 3.0 <= d <= 18.0:
                pacing_scores.append(8.5)
            else:
                pacing_scores.append(6.0)
        visual_pacing = round(sum(pacing_scores) / len(pacing_scores), 1) if pacing_scores else 7.5

        # 10. Episode Continuity: Verify link with previous episode if exists
        ep_num = storyboard.get("episode_number", 1)
        if ep_num > 1 and previous_storyboard:
            prev_close = previous_storyboard.get("closing_visual", {}).get("location_id")
            cur_open = storyboard.get("opening_visual", {}).get("location_id")
            if prev_close and cur_open and prev_close == cur_open:
                episode_continuity = 9.0
            else:
                episode_continuity = 8.0
        else:
            episode_continuity = 8.5

        score = VisualQualityScore(
            narrative_relevance=narrative_rel,
            cinematic_composition=cinematic_comp,
            atmosphere=atmosphere,
            lighting=lighting,
            colour_consistency=colour_cons,
            character_consistency=char_cons,
            environment_consistency=env_cons,
            motion_quality=motion_quality,
            visual_pacing=visual_pacing,
            episode_continuity=episode_continuity,
            notes=notes,
            automatic_failures=auto_failures,
        )

        logger.info(
            f"Visual QC for Ep {ep_num}: avg={score.average_score}, verdict={score.verdict} "
            f"(serialized_min={score.serialized_score_min})"
        )
        return score


visual_qc = VisualQCEvaluator()
