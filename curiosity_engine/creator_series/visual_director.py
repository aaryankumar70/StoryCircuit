"""Cinematic Visual Director & Storyboard Generator for CurioLoop Creator Series.

Integrates the cinematic-story-visuals skill:
- Profiles: psychological_horror, mystery_investigative, historical, custom
- Generates Series Visual Bible matching schemas/visual_bible.schema.json
- Generates Episode Storyboards matching schemas/episode_storyboard.schema.json
- Validates all visual artifacts strictly against skill JSON schemas
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import jsonschema

from curiosity_engine.config import PROJECT_ROOT
from curiosity_engine.creator_series.models import EpisodeRecord

logger = logging.getLogger("curiosity_engine.visual_director")

SKILL_DIR = PROJECT_ROOT / ".agent" / "skills" / "cinematic-story-visuals"
SCHEMAS_DIR = SKILL_DIR / "schemas"


def load_schema(schema_name: str) -> Dict[str, Any]:
    """Load JSON schema from the installed skill."""
    schema_path = SCHEMAS_DIR / schema_name
    if not schema_path.exists():
        raise FileNotFoundError(f"Missing schema: {schema_path}")
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


class VisualDirector:
    """Creates and validates visual bibles and episode storyboards."""

    def __init__(self):
        self._visual_bible_schema = load_schema("visual_bible.schema.json")
        self._episode_storyboard_schema = load_schema("episode_storyboard.schema.json")

    def create_horror_visual_bible(
        self,
        series_id: str,
        title: str,
        logline: str,
        characters: Optional[List[Dict[str, Any]]] = None,
        locations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Construct a psychological_horror visual bible strictly conforming to schema."""
        default_characters = [
            {
                "character_id": "char_narrator",
                "name": "Daniel",
                "name_is_placeholder": True,
                "narrative_role": "First-person protagonist who missed the story and later discovers it was about him.",
                "presentation": "mostly_unseen",
                "never_show_face": True,
                "states": [
                    {
                        "state_id": "narrator_adult",
                        "label": "Adult Narrator",
                        "age": 41,
                        "timeline_period": "Present Day",
                        "appearance": {
                            "build": "Lean and tense",
                            "face": "Lined with fatigue, never shown directly",
                            "hair": "Dark hair greying at the temples",
                        },
                        "clothing": ["Charcoal wool overcoat", "Dark grey sweater"],
                        "reference_description": "A man of about 41, seen only from behind or in profile shadow, charcoal wool overcoat.",
                    },
                    {
                        "state_id": "narrator_child",
                        "label": "Child Narrator",
                        "age": "about 9",
                        "timeline_period": "Childhood memory",
                        "appearance": {
                            "build": "Thin schoolboy",
                            "face": "Uncertain, seen from distance",
                            "hair": "Slightly uneven dark hair",
                        },
                        "clothing": ["Navy hooded jacket", "Worn backpack"],
                        "reference_description": "A thin boy of about nine with short dark hair, navy hooded jacket, seen from behind.",
                    },
                ],
            },
            {
                "character_id": "char_friend",
                "name": "Isaiah",
                "name_is_placeholder": False,
                "narrative_role": "Childhood friend who heard the prophecy and maintained silence to protect the narrator.",
                "presentation": "mostly_unseen",
                "never_show_face": False,
                "states": [
                    {
                        "state_id": "friend_adult",
                        "label": "Adult Friend",
                        "age": 41,
                        "timeline_period": "Present Day",
                        "appearance": {
                            "build": "Solid, weary build",
                            "face": "Heavy brow and tight jaw",
                            "hair": "Receding sandy hair",
                        },
                        "clothing": ["Grey wool cardigan", "Muted dark green scarf"],
                        "reference_description": "A solid man in his forties with receding hair, heavy jaw, dark muted-green scarf.",
                    },
                    {
                        "state_id": "friend_child",
                        "label": "Child Friend",
                        "age": "about 9",
                        "timeline_period": "Childhood memory",
                        "appearance": {
                            "build": "Stocky boy",
                            "face": "Solemn round face",
                            "hair": "Short sandy brown hair",
                        },
                        "clothing": ["Green knitted scarf", "Grey jacket"],
                        "reference_description": "A stocky boy of about nine with solemn expression and green knitted scarf.",
                    },
                ],
            },
        ]

        default_locations = [
            {
                "location_id": "loc_school_bus",
                "name": "School Bus Interior",
                "description": "An aging school bus interior with rows of green vinyl seats and condensation on tall windows.",
                "architecture_and_layout": [
                    "Narrow central aisle running toward the rear",
                    "Paired vinyl seats on both sides",
                    "Tall dusty glass windows",
                ],
                "variants": [
                    {
                        "variant_id": "afternoon_memory",
                        "timeline_period": "childhood",
                        "time_of_day": "late afternoon",
                        "lighting": "Low diffused sunlight through dusty glass",
                        "weather_or_atmosphere": "Quiet, dry, dust floating",
                        "palette_hexes": ["#0B0F12", "#1B2429", "#3A4A4F", "#C9B27A"],
                    }
                ],
                "continuity_locks": [
                    "Green vinyl seats with taped cracks are fixed in memory.",
                    "Aisle always recedes into dark shadow toward rear.",
                ],
            },
            {
                "location_id": "loc_friend_home",
                "name": "Friend's Kitchen",
                "description": "A small dim kitchen with a worn wooden table and a doorway leading into darkness.",
                "architecture_and_layout": [
                    "Small wooden table center left",
                    "Single hanging overhead practical lamp",
                    "Doorway to dark hallway on the right",
                ],
                "variants": [
                    {
                        "variant_id": "present_evening_lamp",
                        "timeline_period": "present day",
                        "time_of_day": "evening",
                        "lighting": "Single warm overhead lamp, deep shadows",
                        "weather_or_atmosphere": "Cold and quiet stillness",
                        "palette_hexes": ["#0B0F12", "#1B2429", "#3A4A4F", "#C9B27A"],
                    }
                ],
                "continuity_locks": [
                    "The doorway to the dark hallway is always on the right side.",
                    "Single overhead bulb is the only illuminated source.",
                ],
            },
            {
                "location_id": "loc_threshold",
                "name": "Threshold Corridor",
                "description": "A narrow dark hallway leading to a door cracked open with a vertical sliver of amber light.",
                "architecture_and_layout": [
                    "Narrow corridor with bare walls",
                    "Door cracked open at the far end",
                    "Vertical strip of light spilling onto floor",
                ],
                "variants": [
                    {
                        "variant_id": "present_night",
                        "timeline_period": "present day",
                        "time_of_day": "night",
                        "lighting": "High contrast sliver of light against absolute black",
                        "weather_or_atmosphere": "Stifling silence and claustrophobia",
                        "palette_hexes": ["#0B0F12", "#1B2429", "#6F7F84", "#C9B27A"],
                    }
                ],
                "continuity_locks": [
                    "Doorway remains cracked open with thin amber strip.",
                    "Narrator remains outside the illuminated room.",
                ],
            },
        ]

        bible = {
            "schema_version": "1.0",
            "series_id": series_id,
            "title": title,
            "bible_version": 1,
            "profile": "psychological_horror",
            "visual_identity": {
                "logline": logline,
                "mood_keywords": ["unsettling", "dread", "claustrophobic", "inevitable", "desaturated"],
                "palette": {
                    "name": "Bus-Window Grey",
                    "colors": [
                        {"role": "shadow", "hex": "#0B0F12", "usage": "Deep background blacks and floor shadows"},
                        {"role": "base", "hex": "#1B2429", "usage": "Wall and seat foundation tone"},
                        {"role": "midtone", "hex": "#3A4A4F", "usage": "Midground fabric and mist"},
                        {"role": "highlight", "hex": "#6F7F84", "usage": "Rim lighting and cold window edges"},
                        {"role": "accent", "hex": "#A9B4B0", "usage": "Pale skin highlights and dust specs"},
                        {"role": "practical_light", "hex": "#C9B27A", "usage": "Single warm lamp filament and door strip"},
                    ],
                    "max_saturation_note": "Keep all chroma below 25% except the single warm tungsten filament.",
                },
                "lighting_rules": [
                    "Strict low-key lighting with high contrast ratio (>= 8:1).",
                    "Single motivated practical light source (overhead lamp or distant window).",
                    "No fill light on faces; faces remain in profile or deep shadow.",
                    "Deep unlit corners and high negative space ratio.",
                ],
                "camera_language": {
                    "preferred_shots": ["over_the_shoulder", "wide", "close_up", "silhouette"],
                    "movement_rules": [
                        "Camera remains static or uses barely perceptible slow push-in (<= 0.05 speed).",
                        "No sudden camera shake, whip pans, or dutch tilt gimmicks.",
                    ],
                    "forbidden": [
                        "No cartoon monsters or cheap jump scares.",
                        "No saturated red blood filters or glowing eyes.",
                        "Never show narrator's face directly to camera.",
                    ],
                },
                "texture": {
                    "film_grain": "subtle",
                    "vignette": "subtle",
                    "notes": "Fine organic 35mm grain and dark edge vignette.",
                },
            },
            "characters": characters or default_characters,
            "locations": locations or default_locations,
            "continuity_constraints": [
                "Narrator is never shown face-on; always from behind, profile, or silhouette.",
                "The green scarf echoes between childhood and adult friend states.",
                "The doorway to the dark hallway is always on the right side of the kitchen table.",
                "The original story itself is never directly visualised; only the stillness and dread.",
            ],
            "negative_constraints": [
                "No bright cheerful lighting or saturated primaries.",
                "No visual jump scares, monsters, or gore.",
                "No visible text floating in the 3D scene (captions strictly in UI safe zone).",
            ],
            "implementation_notes": [
                "Optimized for 1080x1920 9:16 vertical video with captions bounded at y=1400..1600.",
                "Main action visual staging kept strictly in y=250..1160.",
            ],
        }

        # Validate against schema
        jsonschema.validate(instance=bible, schema=self._visual_bible_schema)
        return bible

    def create_episode_storyboard(
        self,
        series_id: str,
        episode: EpisodeRecord,
        bible: Dict[str, Any],
        duration_s: float = 48.0,
    ) -> Dict[str, Any]:
        """Generate a scene-by-scene storyboard conforming strictly to episode_storyboard.schema.json."""
        scenes = []
        sentences = [s.strip() for s in episode.adapted_narration.split(". ") if s.strip()]
        if not sentences:
            sentences = [episode.adapted_narration]

        num_scenes = max(3, min(7, len(sentences)))
        time_per_scene = duration_s / num_scenes

        for s_idx in range(num_scenes):
            sc_id = f"ep{episode.episode_num:02d}_s{s_idx + 1:02d}"
            s_text = sentences[min(s_idx, len(sentences) - 1)]
            start_t = round(s_idx * time_per_scene, 2)
            end_t = round((s_idx + 1) * time_per_scene, 2)

            if s_idx == 0:
                loc_id = "loc_school_bus"
                var_id = "afternoon_memory"
                shot_type = "wide"
                angle = "eye_level"
                comp = ["empty bus seat foreground left", "dark aisle receding center", "high negative space above"]
                char_ref = [{"character_id": "char_narrator", "state_id": "narrator_child", "presence": "silhouette"}]
                tension = 3
                cam_type = "slow_push_in"
            elif s_idx == num_scenes - 1:
                loc_id = "loc_threshold"
                var_id = "present_night"
                shot_type = "medium"
                angle = "eye_level"
                comp = ["figure centered back-to-camera", "cracked door with light strip", "deep black surrounding frame"]
                char_ref = [{"character_id": "char_narrator", "state_id": "narrator_adult", "presence": "back_to_camera"}]
                tension = 8
                cam_type = "static"
            else:
                loc_id = "loc_friend_home"
                var_id = "present_evening_lamp"
                shot_type = "medium_close" if s_idx % 2 == 1 else "over_the_shoulder"
                angle = "eye_level"
                comp = ["worn wooden table in lower half", "practical lamp overhead", "shadowed doorway on right"]
                char_ref = [{"character_id": "char_friend", "state_id": "friend_adult", "presence": "partial"}]
                tension = 4 + s_idx
                cam_type = "static" if s_idx % 2 == 0 else "slow_push_in"

            scene_obj = {
                "scene_id": sc_id,
                "narration": {
                    "text": s_text,
                    "start_s": start_t,
                    "end_s": end_t,
                    "timing_source": "estimated",
                },
                "narrative_purpose": f"Establish narrative beat {s_idx + 1} and escalate psychological tension.",
                "narrative_mode": "present" if s_idx > 0 else "remembered_narration",
                "visual_description": f"Atmospheric scene: {comp[0]}. Deep shadows, cold muted tones, single practical light.",
                "characters": char_ref,
                "location_id": loc_id,
                "variant_id": var_id,
                "shot": {
                    "type": shot_type,
                    "angle": angle,
                    "composition": comp,
                },
                "camera_movement": {
                    "type": cam_type,
                    "intensity": "barely_perceptible",
                    "rationale": "Quiet resolve and sustained dread.",
                },
                "lighting": {
                    "style": "practical" if loc_id != "loc_school_bus" else "ambient",
                    "key_source": "overhead practical bulb" if loc_id != "loc_school_bus" else "diffused window light",
                    "contrast": "high",
                },
                "palette": ["#0B0F12", "#1B2429", "#3A4A4F", "#C9B27A"],
                "motion": {
                    "layers": [
                        {"layer": "background", "role": "environment", "motion": "static"},
                        {"layer": "subject", "role": "character silhouette", "motion": "static"},
                    ],
                },
                "tension_level": tension,
                "transition_out": {
                    "type": "hard_cut" if s_idx < num_scenes - 1 else "dip_to_black",
                    "duration_ms": 200 if s_idx < num_scenes - 1 else 600,
                    "rationale": "Direct narrative progression.",
                },
                "continuity_requirements": [
                    "Match tone and character silhouette with previous scene",
                    "Keep lighting motivated from established practicals",
                ],
            }
            scenes.append(scene_obj)

        storyboard = {
            "schema_version": "1.0",
            "series_id": series_id,
            "bible_version": 1,
            "episode_number": episode.episode_num,
            "title": episode.title,
            "narrative_summary": f"Serialized episode {episode.episode_num} of {series_id}: {episode.hook[:60]}...",
            "profile": "psychological_horror",
            "target_duration_seconds": duration_s,
            "aspect_ratio": "9:16",
            "opening_visual": {
                "description": scenes[0]["visual_description"],
                "location_id": scenes[0]["location_id"],
                "variant_id": scenes[0]["variant_id"],
                "continues_from_episode": episode.episode_num - 1 if episode.episode_num > 1 else None,
                "continuity_link": "Visual match with closing frame of preceding episode" if episode.episode_num > 1 else "",
            },
            "closing_visual": {
                "description": scenes[-1]["visual_description"],
                "location_id": scenes[-1]["location_id"],
                "variant_id": scenes[-1]["variant_id"],
                "hands_off_to_next": "Holding motionless in deep shadow at threshold before dip to black",
            },
            "visual_progression": [
                {
                    "phase": "setup",
                    "scene_ids": [s["scene_id"] for s in scenes[:2]],
                    "tension_start": 3,
                    "tension_end": 5,
                    "description": "Establish eerie setting and quiet tension",
                },
                {
                    "phase": "escalation_and_cliffhanger",
                    "scene_ids": [s["scene_id"] for s in scenes[2:]],
                    "tension_start": 5,
                    "tension_end": 8,
                    "description": "Mounting dread and concluding cliffhanger",
                },
            ],
            "scenes": scenes,
        }

        # Validate against schema
        jsonschema.validate(instance=storyboard, schema=self._episode_storyboard_schema)
        return storyboard


visual_director = VisualDirector()
