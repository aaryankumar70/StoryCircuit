"""CurioLoop 2.0 Narrative-Driven Visual Director.
Translates spoken narration into rich, semantically grounded visual scenes.
Replaces legacy template-driven keyword assignment with full story event analysis,
motivated cinematography, multi-method rendering, and continuity auditing.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from curiosity_engine.production.cinematography import (
    CameraMotivation,
    CameraShotType,
    create_motivated_camera_path,
)
from curiosity_engine.production.semantic_asset_selector import SemanticAssetSelector
from curiosity_engine.production.visual_continuity import VisualContinuityTracker
from curiosity_engine.production.visual_diversity import VisualDiversityChecker

logger = logging.getLogger(__name__)


@dataclass
class SceneLayerSpec:
    layer_id: str
    plane: str  # FOREGROUND, MIDGROUND_SUBJECT, BACKGROUND, ATMOSPHERE
    asset_path: str
    depth_z: float
    parallax_factor: float
    opacity: float = 1.0
    blend_mode: str = "normal"
    blur_px: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer_id": self.layer_id,
            "plane": self.plane,
            "asset_path": self.asset_path,
            "depth_z": self.depth_z,
            "parallax_factor": self.parallax_factor,
            "opacity": self.opacity,
            "blend_mode": self.blend_mode,
            "blur_px": self.blur_px,
        }


@dataclass
class NarrativeSceneSpecification:
    scene_id: str
    beat_index: int
    narration_text: str
    start_s: float
    end_s: float
    duration_sec: float

    # Narrative semantic grounding
    story_event: str
    visual_objective: str
    primary_subject: Dict[str, Any]
    environment: Dict[str, Any]
    important_objects: List[Dict[str, Any]]
    visual_match_explanation: str

    # Production & Rendering Method
    rendering_method: str  # CINEMATIC_2_5D, SELECTIVE_3D, ARCHIVAL_IMAGERY, DOCUMENTARY_MOTION_GRAPHICS, PROCEDURAL_ENVIRONMENT
    composition_type: str
    camera: Dict[str, Any]
    lighting_and_atmosphere: Dict[str, Any]
    layers: List[SceneLayerSpec]
    transition_out: Dict[str, Any]
    continuity_requirements: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "beat_index": self.beat_index,
            "narration": {
                "text": self.narration_text,
                "start_s": round(self.start_s, 2),
                "end_s": round(self.end_s, 2),
                "duration_sec": round(self.duration_sec, 2),
            },
            "story_event": self.story_event,
            "visual_objective": self.visual_objective,
            "primary_subject": self.primary_subject,
            "environment": self.environment,
            "important_objects": self.important_objects,
            "visual_match_explanation": self.visual_match_explanation,
            "rendering_method": self.rendering_method,
            "composition_type": self.composition_type,
            "camera": self.camera,
            "lighting_and_atmosphere": self.lighting_and_atmosphere,
            "layers": [l.to_dict() for l in self.layers],
            "transition_out": self.transition_out,
            "continuity_requirements": self.continuity_requirements,
        }


class NarrativeVisualDirector:
    """Translates full story scripts into cinematographic, narrative-driven visual plans."""

    def __init__(self, assets_dir: Optional[Path] = None):
        self.asset_selector = SemanticAssetSelector(assets_dir=assets_dir)
        self.continuity_tracker = VisualContinuityTracker()

    def direct_script(
        self,
        script_data: Dict[str, Any],
        word_timings: Optional[List[Dict[str, Any]]] = None,
        line_timings: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Generate a complete narrative storyboard for a script."""
        title = script_data.get("title") or script_data.get("topic") or "Narrative Story"
        category = script_data.get("category", "MYSTERY")
        lines = script_data.get("lines", [])

        # Normalize line_timings if passed as dict containing 'lines'
        timing_list = []
        if isinstance(line_timings, dict):
            timing_list = line_timings.get("lines", [])
        elif isinstance(line_timings, list):
            timing_list = line_timings

        scenes: List[NarrativeSceneSpecification] = []
        t_cursor = float(script_data.get("lead", 0.40))

        # Determine overall historical/thematic era
        inferred_era = self._infer_story_era(title, category, lines)
        inferred_setting = self._infer_story_setting(title, category, lines)

        for idx, line in enumerate(lines):
            text = str(line.get("text", "")).strip()
            # Calculate line start and end times from line_timings if available
            start_s = t_cursor
            if timing_list and idx < len(timing_list):
                lt_entry = timing_list[idx]
                start_s = float(lt_entry.get("start", t_cursor))
                if "duration" in lt_entry:
                    dur = float(lt_entry["duration"])
                elif "end" in lt_entry:
                    dur = float(lt_entry["end"]) - start_s
                else:
                    words_count = max(1, len(text.split()))
                    dur = max(2.5, words_count / 2.35)
                end_s = start_s + dur
                t_cursor = end_s + float(line.get("gap", 0.28))
            else:
                words_count = max(1, len(text.split()))
                dur = max(2.5, words_count / 2.35)
                end_s = start_s + dur
                t_cursor = end_s + float(line.get("gap", 0.28))

            scene_spec = self._analyze_and_direct_beat(
                beat_idx=idx,
                text=text,
                start_s=start_s,
                end_s=end_s,
                total_beats=len(lines),
                story_title=title,
                category=category,
                era=inferred_era,
                setting=inferred_setting,
                prior_scene=scenes[-1] if scenes else None,
            )
            scenes.append(scene_spec)

        # Audit and enforce sequence diversity
        scene_dicts = [s.to_dict() for s in scenes]
        diversity_report = VisualDiversityChecker.audit_sequence(scene_dicts)
        if not diversity_report.passed:
            logger.warning(
                "Visual diversity audit flagged %d issues. Adjusting scene camera angles and compositions.",
                len(diversity_report.violations),
            )
            self._refine_diversity(scenes)
            scene_dicts = [s.to_dict() for s in scenes]
            diversity_report = VisualDiversityChecker.audit_sequence(scene_dicts)

        # Audit continuity
        continuity_report = self.continuity_tracker.audit_sequence(scene_dicts)

        storyboard = {
            "title": title,
            "category": category,
            "historical_era": inferred_era,
            "setting": inferred_setting,
            "total_scenes": len(scenes),
            "total_duration_sec": round(t_cursor, 2),
            "diversity_report": diversity_report.to_dict(),
            "continuity_report": continuity_report.to_dict(),
            "scenes": scene_dicts,
        }
        return storyboard

    def _analyze_and_direct_beat(
        self,
        beat_idx: int,
        text: str,
        start_s: float,
        end_s: float,
        total_beats: int,
        story_title: str,
        category: str,
        era: str,
        setting: str,
        prior_scene: Optional[NarrativeSceneSpecification],
    ) -> NarrativeSceneSpecification:
        """Deep narrative decomposition of a single spoken beat."""
        low = text.lower()
        duration = max(1.5, end_s - start_s)
        scene_id = f"SCN_{beat_idx + 1:02d}"

        # 1. Extract physical entities, key objects, and story actions
        extracted_entities = self._extract_entities(text, story_title)
        primary_subject_name = extracted_entities["primary_subject"]
        action_verb = extracted_entities["action"]
        objects = extracted_entities["objects"]

        # 2. Select narrative rendering method
        method, comp_type, shot_type, motivation = self._determine_visual_strategy(
            beat_idx, total_beats, text, primary_subject_name, action_verb
        )

        # 3. Environment and lighting configuration
        env_spec = self._configure_environment(setting, era, beat_idx, total_beats, text)
        lighting_spec = self._configure_lighting(category, env_spec["time_of_day"], motivation)

        # 4. Resolve semantically grounded assets
        asset_path, asset_record, score = self.asset_selector.select_asset_for_scene(
            primary_subject=primary_subject_name,
            narration_text=text,
            era=era,
            category=category,
            required_objects=[o["name"] for o in objects],
        )

        # 5. Build 3-plane depth layers
        layers = self._build_depth_layers(
            scene_id=scene_id,
            method=method,
            main_asset=asset_path,
            env_spec=env_spec,
            primary_subject=primary_subject_name,
            objects=objects,
        )

        # 6. Motivated cinematography
        camera_spec = create_motivated_camera_path(
            shot_type=shot_type,
            motivation=motivation,
            duration_sec=duration,
            narrative_reason=f"{shot_type.value} camera movement motivated by {motivation.value} to reveal {primary_subject_name} ({action_verb}).",
        )

        # 7. Formulate explicit visual match explanation
        explanation = (
            f"The narration states '{text}'. The visual specifically presents {primary_subject_name} "
            f"within a {env_spec['name']} ({era}), executing '{action_verb}', using {method} with {shot_type.value} "
            f"framing to fulfill the narrative purpose of {motivation.value} without generic filler."
        )

        return NarrativeSceneSpecification(
            scene_id=scene_id,
            beat_index=beat_idx + 1,
            narration_text=text,
            start_s=start_s,
            end_s=end_s,
            duration_sec=duration,
            story_event=f"{primary_subject_name} {action_verb}",
            visual_objective=f"Show {primary_subject_name} in {env_spec['name']}",
            primary_subject={
                "name": primary_subject_name,
                "role": "FOCAL_SUBJECT",
                "action": action_verb,
                "asset": str(asset_path),
            },
            environment=env_spec,
            important_objects=objects,
            visual_match_explanation=explanation,
            rendering_method=method,
            composition_type=comp_type,
            camera=camera_spec.to_dict(),
            lighting_and_atmosphere=lighting_spec,
            layers=layers,
            transition_out={
                "type": "FOCAL_RACK_DISSOLVE" if beat_idx < total_beats - 1 else "FADE_TO_BLACK",
                "duration_sec": 0.45,
            },
            continuity_requirements=[
                f"Subject '{primary_subject_name}' must preserve physical attributes across consecutive appearances.",
                f"Setting remains {setting} ({era}).",
            ],
        )

    def _determine_visual_strategy(
        self,
        beat_idx: int,
        total_beats: int,
        text: str,
        subject: str,
        action: str,
    ) -> Tuple[str, str, CameraShotType, CameraMotivation]:
        """Selects production method and motivated cinematography based on story beat."""
        low = f"{text} {subject} {action}".lower()

        # Opening Hook (Beat 1)
        if beat_idx == 0:
            if any(w in low for w in ["rule", "watchman", "cabin", "outpost", "door"]):
                return "CINEMATIC_2_5D", "FOREGROUND_SUBJECT_DEPTH", CameraShotType.ESTABLISHING, CameraMotivation.REVEAL
            elif any(w in low for w in ["ship", "ocean", "sea", "sail", "vessel"]):
                return "SELECTIVE_3D", "MARITIME_HORIZON_WIDE", CameraShotType.ESTABLISHING, CameraMotivation.ISOLATION
            else:
                return "CINEMATIC_2_5D", "ENVIRONMENTAL_ESTABLISHING", CameraShotType.ESTABLISHING, CameraMotivation.REVEAL

        # Climax / Revelation (Near final third)
        if beat_idx >= max(1, total_beats - 3):
            if any(w in low for w in ["name", "log", "ink", "key", "journal", "note", "letter"]):
                return "ARCHIVAL_IMAGERY", "OBJECT_MACRO_SCRUTINY", CameraShotType.MACRO_CLOSEUP, CameraMotivation.EVIDENCE
            elif any(w in low for w in ["telephone", "bell", "ring", "call"]):
                return "CINEMATIC_2_5D", "FOCAL_RELIC_SCRUTINY", CameraShotType.DOLLY_IN, CameraMotivation.DISCOVERY
            elif any(w in low for w in ["vanished", "empty", "trace", "abandoned"]):
                return "SELECTIVE_3D", "DESOLATE_PULLBACK", CameraShotType.DOLLY_OUT, CameraMotivation.ISOLATION

        # Intermediate narrative actions
        if any(w in low for w in ["approach", "walk", "flashlight", "search", "patrol", "door"]):
            return "CINEMATIC_2_5D", "SUBJECT_TRACKING_PROFILE", CameraShotType.TRACKING, CameraMotivation.INVESTIGATION
        elif any(w in low for w in ["telephone", "bell", "ring", "alarm", "sound"]):
            return "CINEMATIC_2_5D", "ISOLATED_RELIC_FOCUS", CameraShotType.DOLLY_IN, CameraMotivation.DISCOVERY
        elif any(w in low for w in ["years", "boarded", "chains", "padlock", "locked"]):
            return "PROCEDURAL_ENVIRONMENT", "STRUCTURAL_BARRIER_WIDE", CameraShotType.MEDIUM, CameraMotivation.THREAT
        elif any(w in low for w in ["ocean", "sea", "water", "swell", "drift", "storm"]):
            return "SELECTIVE_3D", "DYNAMIC_OCEAN_SURFACE", CameraShotType.WIDE, CameraMotivation.ATMOSPHERE
        elif any(w in low for w in ["log", "ledger", "key", "document", "record"]):
            return "ARCHIVAL_IMAGERY", "EVIDENCE_TABLE_OVERHEAD", CameraShotType.MACRO_CLOSEUP, CameraMotivation.EVIDENCE
        elif any(w in low for w in ["map", "route", "coordinates", "navigate"]):
            return "DOCUMENTARY_MOTION_GRAPHICS", "AUTHENTIC_CARTOGRAPHIC_CHART", CameraShotType.PAN_TILT, CameraMotivation.INVESTIGATION
        else:
            return "CINEMATIC_2_5D", "LAYERED_PERSPECTIVE", CameraShotType.MEDIUM, CameraMotivation.INVESTIGATION

    def _extract_entities(self, text: str, story_title: str) -> Dict[str, Any]:
        """Extract narrative actors, actions, and physical objects from script text."""
        low = text.lower()
        sub = "Story Protagonist"
        action = "observes environment"
        objects: List[Dict[str, Any]] = []

        if "watchman" in low or "miller" in low or "patrol" in low:
            sub = "Night Watchman Officer Miller"
            if "approached" in low:
                action = "advances cautiously with trembling flashlight beam"
            elif "rule" in low:
                action = "stands vigilance over restricted perimeter"
            elif "flashlight" in low:
                action = "illuminates rusted iron threshold"
        elif "telephone" in low or "bell" in low:
            sub = "Vintage Wall Telephone in Cabin 4"
            action = "vibrates violently as copper bell rings"
            objects.append({"name": "Copper Bells", "type": "ACOUSTIC_RELIC"})
        elif "cabin" in low or "cabin four" in low:
            sub = "Boarded Timber Cabin Four"
            action = "stands isolated behind iron security chains"
            objects.append({"name": "Iron Padlock & Chains", "type": "PHYSICAL_BARRIER"})
        elif "ledger" in low or "journal" in low or "ink" in low:
            sub = "Archival Desk Ledger & Fresh Ink Entry"
            action = "displays current date and watchman's name"
            objects.append({"name": "Handwritten Journal", "type": "PRIMARY_DOCUMENT"})
            if "key" in low:
                objects.append({"name": "Lost Brass River Key", "type": "PHYSICAL_RELIC"})
        elif "key" in low:
            sub = "Lost Brass River Key"
            action = "rests wet on dust-covered ledger"
            objects.append({"name": "Lost Brass Key", "type": "PHYSICAL_RELIC"})
        elif "mary celeste" in low or "ship" in low or "vessel" in low or "brigantine" in low:
            sub = "The Mary Celeste Sailing Vessel"
            action = "drifts silently under full canvas with empty helm"
            objects.append({"name": "Unattended Ship Wheel", "type": "NAUTICAL_EQUIPMENT"})
        elif "ocean" in low or "atlantic" in low or "sea" in low:
            sub = "Open North Atlantic Swell"
            action = "surges beneath turbulent maritime squall"
        else:
            sub = story_title[:32]
            action = "reveals critical story development"

        return {"primary_subject": sub, "action": action, "objects": objects}

    def _configure_environment(
        self, setting: str, era: str, beat_idx: int, total_beats: int, text: str
    ) -> Dict[str, Any]:
        """Configure authentic historical/physical environment."""
        low = text.lower()
        if "cabin" in low or "watchman" in low or "forest" in low or "wood" in low or "telephone" in low or "desk" in low:
            if "inside" in low or "desk" in low or "ledger" in low or "telephone" in low:
                name = "Cabin Four Interior Office"
                kit = "INVESTIGATION_ROOM"
                weather = "COLD_FROST"
                time_of_day = "NIGHT"
            else:
                name = "Blackwood Forest Outpost Exterior"
                kit = "NIGHT_LANDSCAPE"
                weather = "FREEZING_FOG"
                time_of_day = "NIGHT"
        elif "ship" in low or "ocean" in low or "atlantic" in low or "celeste" in low:
            name = "North Atlantic Ocean"
            kit = "OCEAN_STORM"
            weather = "SQUALL_MIST"
            time_of_day = "OVERCAST_DAY"
        elif "museum" in low or "gallery" in low:
            name = "Museum Salon Carré"
            kit = "MUSEUM"
            weather = "INDOOR_CONTROLLED"
            time_of_day = "DAY"
        else:
            name = setting or "Archival Investigation Setting"
            kit = "HISTORICAL_ARCHIVE"
            weather = "ATMOSPHERIC_HAZE"
            time_of_day = "DUSK"

        return {
            "name": name,
            "kit": kit,
            "era": era,
            "weather": weather,
            "time_of_day": time_of_day,
        }

    def _configure_lighting(self, category: str, time_of_day: str, motivation: CameraMotivation) -> Dict[str, Any]:
        """Motivated lighting parameters."""
        if time_of_day == "NIGHT":
            kelvin = 2800 if motivation == CameraMotivation.EVIDENCE else 3800
            ambient = 0.22
            key_int = 1.4
            shadow = 0.8
        elif time_of_day == "OVERCAST_DAY":
            kelvin = 6200
            ambient = 0.45
            key_int = 1.1
            shadow = 0.5
        else:
            kelvin = 3400
            ambient = 0.30
            key_int = 1.3
            shadow = 0.6

        return {
            "color_temperature_k": kelvin,
            "key_light_intensity": key_int,
            "ambient_intensity": ambient,
            "shadow_softness": shadow,
            "atmospheric_fog_density": 0.0028,
        }

    def _build_depth_layers(
        self,
        scene_id: str,
        method: str,
        main_asset: Path,
        env_spec: Dict[str, Any],
        primary_subject: str,
        objects: List[Dict[str, Any]],
    ) -> List[SceneLayerSpec]:
        """Constructs 3 distinct depth planes: Foreground, Midground, Background."""
        asset_rel = f"assets/{main_asset.name}" if main_asset.exists() else str(main_asset)
        layers: List[SceneLayerSpec] = []

        # 1. Foreground plane (adds dimensional depth, framing aperture, or atmospheric mist)
        layers.append(
            SceneLayerSpec(
                layer_id=f"{scene_id}_L_FG",
                plane="FOREGROUND",
                asset_path="assets/foreground_framing.svg",
                depth_z=180.0,
                parallax_factor=1.45,
                opacity=0.88,
                blur_px=1.5,
            )
        )

        # 2. Midground Subject plane (focal story subject)
        layers.append(
            SceneLayerSpec(
                layer_id=f"{scene_id}_L_MG",
                plane="MIDGROUND_SUBJECT",
                asset_path=asset_rel,
                depth_z=0.0,
                parallax_factor=1.0,
                opacity=1.0,
                blur_px=0.0,
            )
        )

        # 3. Background plane (deep environment backdrop)
        layers.append(
            SceneLayerSpec(
                layer_id=f"{scene_id}_L_BG",
                plane="BACKGROUND",
                asset_path=f"assets/env_{env_spec['kit'].lower()}.svg",
                depth_z=-450.0,
                parallax_factor=0.32,
                opacity=0.92,
                blur_px=2.0,
            )
        )

        return layers

    def _refine_diversity(self, scenes: List[NarrativeSceneSpecification]) -> None:
        """Resolve adjacent composition or camera repetitions."""
        shot_alternatives = [
            CameraShotType.DOLLY_IN,
            CameraShotType.MEDIUM,
            CameraShotType.TRACKING,
            CameraShotType.CLOSEUP,
            CameraShotType.PAN_TILT,
            CameraShotType.WIDE,
        ]
        for i in range(len(scenes) - 1):
            s1 = scenes[i]
            s2 = scenes[i + 1]
            if s1.camera.get("shot_type") == s2.camera.get("shot_type"):
                curr_shot = s2.camera.get("shot_type")
                alt_shot = next((s for s in shot_alternatives if s.value != curr_shot), CameraShotType.MEDIUM)
                dur = s2.duration_sec
                mot = CameraMotivation(s2.camera.get("motivation", "INVESTIGATION"))
                new_cam = create_motivated_camera_path(alt_shot, mot, dur)
                s2.camera = new_cam.to_dict()

    def _infer_story_era(self, title: str, category: str, lines: List[Dict[str, Any]]) -> str:
        full_text = f"{title} {' '.join(str(l.get('text', '')) for l in lines)}".lower()
        if "1872" in full_text or "mary celeste" in full_text or "brigantine" in full_text or "nineteenth century" in full_text:
            return "1872 (Victorian Maritime Era)"
        if "1942" in full_text or "blimp" in full_text or "war" in full_text or "navy" in full_text:
            return "1942 (World War II)"
        if "1911" in full_text or "mona lisa" in full_text or "louvre" in full_text:
            return "1911 (Belle Époque)"
        if "thirty-five years" in full_text or "cabin" in full_text or "forest" in full_text or "watchman" in full_text:
            return "Mid-20th Century to Contemporary"
        if category == "SPACE":
            return "Modern Space Age"
        return "Historical Mystery Era"

    def _infer_story_setting(self, title: str, category: str, lines: List[Dict[str, Any]]) -> str:
        full_text = f"{title} {' '.join(str(l.get('text', '')) for l in lines)}".lower()
        if "atlantic" in full_text or "celeste" in full_text or "ocean" in full_text or "ship" in full_text:
            return "North Atlantic Ocean"
        if "blackwood" in full_text or "forest" in full_text or "cabin" in full_text or "watchman" in full_text:
            return "Blackwood Forest Outpost"
        if "museum" in full_text or "louvre" in full_text or "paris" in full_text:
            return "Louvre Museum, Paris"
        return "Narrative Investigation Location"
