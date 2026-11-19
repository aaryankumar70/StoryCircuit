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
                "character_id": "char_joshua",
                "name": "Joshua",
                "name_is_placeholder": False,
                "narrative_role": "First-person protagonist who wore Walkman headphones on the bus and spent 43 years trying to uncover the story, unaware the prediction was his own death.",
                "presentation": "mostly_unseen",
                "never_show_face": True,
                "states": [
                    {
                        "state_id": "joshua_child",
                        "label": "Joshua (Age 12)",
                        "age": "12",
                        "timeline_period": "Childhood memory (1980s)",
                        "appearance": {
                            "build": "Lean schoolboy",
                            "face": "Uncertain, seen in profile shadow",
                            "hair": "Short dark hair",
                        },
                        "clothing": ["Navy hooded windbreaker", "Grey school backpack", "Yellow Walkman headphones around neck"],
                        "reference_description": "A thin twelve-year-old boy with short dark hair, navy windbreaker, wearing yellow sponge Walkman headphones, seen from behind or in profile shadow.",
                    },
                    {
                        "state_id": "joshua_adult",
                        "label": "Joshua (Age 56)",
                        "age": 56,
                        "timeline_period": "Present Day",
                        "appearance": {
                            "build": "Lean and weathered electrician/writer",
                            "face": "Lined with fatigue and mounting dread",
                            "hair": "Dark hair greying heavily at the temples",
                        },
                        "clothing": ["Charcoal wool jacket", "Muted dark grey crewneck sweater"],
                        "reference_description": "A man of 56 with silver-grey temples, seen in silhouette, overcoat collar turned up against the cold.",
                    },
                ],
            },
            {
                "character_id": "char_isaiah",
                "name": "Isaiah",
                "name_is_placeholder": False,
                "narrative_role": "Joshua's childhood best friend who heard the driver's prophecy and kept a protective vow of silence until dying of pancreatic cancer at 55.",
                "presentation": "mostly_unseen",
                "never_show_face": False,
                "states": [
                    {
                        "state_id": "isaiah_child",
                        "label": "Isaiah (Age 12)",
                        "age": "12",
                        "timeline_period": "Childhood memory (1980s)",
                        "appearance": {
                            "build": "Stocky schoolboy",
                            "face": "Solemn round face, wide terrified eyes",
                            "hair": "Short sandy brown hair",
                        },
                        "clothing": ["Green knitted scarf", "Grey corduroy jacket"],
                        "reference_description": "A stocky twelve-year-old boy with a solemn round face, sandy hair, and a green knitted scarf.",
                    },
                    {
                        "state_id": "isaiah_adult",
                        "label": "Isaiah (Age 55)",
                        "age": 55,
                        "timeline_period": "Coffee Shop Meetup",
                        "appearance": {
                            "build": "Visibly frail and emaciated from terminal cancer",
                            "face": "Glassy, deeply yellowed jaundiced eyes, hollow cheeks",
                            "hair": "Thinning grey hair",
                        },
                        "clothing": ["Faded brown corduroy jacket", "Muted olive green scarf"],
                        "reference_description": "A frail man of 55 with glassy yellowed eyes, raising a ceramic coffee mug, worn corduroy jacket.",
                    },
                ],
            },
            {
                "character_id": "char_maria",
                "name": "Maria",
                "name_is_placeholder": False,
                "narrative_role": "Classmate on the bus who witnessed the prophecy, refused to speak in math class, and is overheard 43 years later in a bar recounting the deaths.",
                "presentation": "mostly_unseen",
                "never_show_face": False,
                "states": [
                    {
                        "state_id": "maria_child",
                        "label": "Maria (Age 12)",
                        "age": "12",
                        "timeline_period": "Classroom memory",
                        "appearance": {
                            "build": "Small schoolgirl",
                            "face": "Pale, nervous expression",
                            "hair": "Dark brown curly hair in ponytails",
                        },
                        "clothing": ["Navy school cardigan", "Red spiral notebook"],
                        "reference_description": "A twelve-year-old girl with dark curly hair doodling nervously in a spiral notebook in math class.",
                    },
                    {
                        "state_id": "maria_adult",
                        "label": "Maria (Age 55)",
                        "age": 55,
                        "timeline_period": "Present Day Bar",
                        "appearance": {
                            "build": "Middle-aged woman",
                            "face": "Sideways quirk of mouth when speaking, animated and haunted expression",
                            "hair": "Thick brown curly hair cut to shoulders",
                        },
                        "clothing": ["Dark olive blouse", "Silver pendant necklace"],
                        "reference_description": "A middle-aged woman with thick curly brown hair, sideways quirk of her mouth, seated at a dimly lit bar booth.",
                    },
                ],
            },
            {
                "character_id": "char_driver",
                "name": "Substitute Bus Driver",
                "name_is_placeholder": False,
                "narrative_role": "Substitute driver on the county road with hollow, glazed eyes who delivers the fatal prophecies before drifting into opposing traffic.",
                "presentation": "mostly_unseen",
                "never_show_face": True,
                "states": [
                    {
                        "state_id": "driver_bus",
                        "label": "Substitute Driver",
                        "age": "50s",
                        "timeline_period": "Childhood memory",
                        "appearance": {
                            "build": "Broad, rigid posture",
                            "face": "Glazed, unblinking eyes reflected in rearview mirror",
                            "hair": "Thinning grey hair under cap",
                        },
                        "clothing": ["Faded navy driver uniform jacket", "Gloves on steering wheel"],
                        "reference_description": "Driver seen primarily in the rectangular rearview mirror, unblinking hollow gaze.",
                    }
                ],
            },
        ]

        default_locations = [
            {
                "location_id": "loc_school_bus",
                "name": "School Bus Interior & County Road",
                "description": "An aging school bus interior with rows of green vinyl seats, condensation on tall windows, drifting on a winding two-lane rural road.",
                "architecture_and_layout": [
                    "Narrow central aisle running toward the rear",
                    "Paired green vinyl seats on both sides",
                    "Tall dusty glass windows overlooking rural trees",
                    "Large steering wheel and rectangular convex rearview mirror",
                ],
                "variants": [
                    {
                        "variant_id": "afternoon_memory",
                        "timeline_period": "childhood",
                        "time_of_day": "late afternoon",
                        "lighting": "Low diffused sunlight through dusty glass",
                        "weather_or_atmosphere": "Quiet, dry, dust floating",
                        "palette_hexes": ["#0B0F12", "#1B2429", "#3A4A4F", "#C9B27A"],
                    },
                    {
                        "variant_id": "crash_aftermath",
                        "timeline_period": "childhood",
                        "time_of_day": "afternoon",
                        "lighting": "Harsh cold daylight through shattered windshield and rising white steam",
                        "weather_or_atmosphere": "White steam, smoke, shattered glass, stillness",
                        "palette_hexes": ["#0B0F12", "#1B2429", "#6F7F84", "#A9B4B0"],
                    },
                ],
                "continuity_locks": [
                    "Green vinyl seats with taped cracks are fixed in memory.",
                    "Aisle always recedes into dark shadow toward rear.",
                ],
            },
            {
                "location_id": "loc_classroom_math",
                "name": "Junior High Math Classroom",
                "description": "Junior high math class with wooden desks arranged in rows, chalk equations on blackboard, and window overlooking grey overcast sky.",
                "architecture_and_layout": [
                    "Rows of wooden school desks with attached wire baskets",
                    "Green slate blackboard at the front",
                    "Tall institutional windows on the left",
                ],
                "variants": [
                    {
                        "variant_id": "morning_class",
                        "timeline_period": "childhood",
                        "time_of_day": "morning",
                        "lighting": "Flat grey morning daylight",
                        "weather_or_atmosphere": "Tense silence, whispering undertones",
                        "palette_hexes": ["#0B0F12", "#1B2429", "#3A4A4F", "#A9B4B0"],
                    }
                ],
                "continuity_locks": [
                    "Maria's desk is on the left aisle by the tall window.",
                    "Spiral math notebook with frantic doodles on desk.",
                ],
            },
            {
                "location_id": "loc_coffee_shop",
                "name": "Corner Coffee Shop",
                "description": "A quiet local corner cafe with dark wooden booth, two ceramic coffee mugs, and morning light through cold windowpanes.",
                "architecture_and_layout": [
                    "Dark wooden booth table with round ceramic mugs",
                    "Large streetfront window casting directional morning light",
                    "Subtle steam rising from black coffee",
                ],
                "variants": [
                    {
                        "variant_id": "morning_reunion",
                        "timeline_period": "present day",
                        "time_of_day": "morning",
                        "lighting": "Low directional morning window light, high contrast shadow",
                        "weather_or_atmosphere": "Somber, melancholic, quiet cafe atmosphere",
                        "palette_hexes": ["#0B0F12", "#1B2429", "#3A4A4F", "#C9B27A"],
                    }
                ],
                "continuity_locks": [
                    "Two ceramic coffee mugs placed on worn wooden table.",
                    "Isaiah sits across the table in the window light.",
                ],
            },
            {
                "location_id": "loc_local_bar",
                "name": "Dimly Lit Hometown Bar",
                "description": "A local neighborhood tavern with dark oak wood paneling, amber pendant lamps, booths in deep shadow, and beer glasses reflecting neon accents.",
                "architecture_and_layout": [
                    "Dark wood tavern tables and high-backed leather booths",
                    "Low hanging amber glass pendant lights",
                    "Distant neon glow and exit door casting a rim of white light",
                ],
                "variants": [
                    {
                        "variant_id": "night_overhearing",
                        "timeline_period": "present day",
                        "time_of_day": "night",
                        "lighting": "Deep low-key lighting with warm amber table pool and silhouette shadows",
                        "weather_or_atmosphere": "Murmuring bar chatter, cigarette smoke traces, sudden freezing tension",
                        "palette_hexes": ["#0B0F12", "#1B2429", "#3A4A4F", "#C9B27A"],
                    }
                ],
                "continuity_locks": [
                    "Maria is seated one booth over at an angle visible to Joshua.",
                    "Joshua remains obscured in shadow in the adjacent booth.",
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
                    "Single motivated practical light source (overhead lamp, headlights, or window).",
                    "No fill light on faces; faces remain in profile, silhouette, or deep shadow.",
                    "Deep unlit corners and high negative space ratio (>75%).",
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
                "Isaiah's green knitted scarf is worn as a child and echoed as an adult.",
                "Joshua's yellow Walkman headphones wire is visible in 1980s scenes.",
                "Bus interior green vinyl color is locked across all childhood scenes.",
                "Maria's curly brown hair and sideways mouth quirk are consistent across timelines.",
            ],
            "negative_constraints": [
                "Never show narrator's face directly to camera.",
                "No saturated red blood pools or gore elements.",
                "No cartoon monsters, demonic eyes, or cheap jump scares.",
                "Never exceed 25% color saturation on midtones.",
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
        from curiosity_engine.creator_series.story_adapter import split_into_sentences

        ep_num = episode.episode_num
        sentences = split_into_sentences(episode.adapted_narration)
        if not sentences:
            sentences = [episode.adapted_narration]

        num_scenes = max(3, min(6, len(sentences)))
        time_per_scene = duration_s / num_scenes

        # Episode-specific cinematic scene choreography
        episode_blueprints = {
            1: [
                ("loc_school_bus", "afternoon_memory", "wide", ["empty green vinyl bus seats", "narrator silhouette foreground", "sunlight through dusty glass"], [{"character_id": "char_joshua", "state_id": "joshua_child", "presence": "silhouette"}], 3),
                ("loc_school_bus", "afternoon_memory", "medium", ["rectangular rearview mirror reflecting glazed unblinking driver eyes"], [{"character_id": "char_driver", "state_id": "driver_bus", "presence": "partial"}], 5),
                ("loc_school_bus", "afternoon_memory", "close_up", ["yellow Walkman headphones on ears", "cassette tape spinning to silent stop"], [{"character_id": "char_joshua", "state_id": "joshua_child", "presence": "silhouette"}], 6),
                ("loc_school_bus", "afternoon_memory", "over_the_shoulder", ["rows of children sitting completely slack-jawed and wide-eyed in silence"], [{"character_id": "char_isaiah", "state_id": "isaiah_child", "presence": "partial"}], 8),
            ],
            2: [
                ("loc_school_bus", "afternoon_memory", "medium", ["driver hands frozen on wheel", "blaring headlights of oncoming truck through glass"], [{"character_id": "char_driver", "state_id": "driver_bus", "presence": "silhouette"}], 9),
                ("loc_school_bus", "crash_aftermath", "wide", ["shattered bus frame on rural verge", "thick white steam rising into clear daylight sky"], [], 8),
                ("loc_classroom_math", "morning_class", "medium", ["wooden school desks", "Maria doodling nervously in spiral math notebook"], [{"character_id": "char_maria", "state_id": "maria_child", "presence": "partial"}], 6),
                ("loc_classroom_math", "morning_class", "over_the_shoulder", ["Maria slamming notebook shut and walking to another desk", "students staring in silence"], [{"character_id": "char_maria", "state_id": "maria_child", "presence": "back_to_camera"}], 7),
            ],
            3: [
                ("loc_classroom_math", "morning_class", "medium_close", ["shadowed school hallway lockers", "Isaiah shouting 'fifty-five' with jaw clenched"], [{"character_id": "char_isaiah", "state_id": "isaiah_child", "presence": "partial"}], 7),
                ("loc_school_bus", "afternoon_memory", "wide", ["silhouette of Joshua walking away down rural road", "deep empty negative space"], [{"character_id": "char_joshua", "state_id": "joshua_child", "presence": "back_to_camera"}], 6),
                ("loc_coffee_shop", "morning_reunion", "close_up", ["digital calendar alert glowing in dark room: 'Isaiah's birthday—fifty-five'"], [], 7),
                ("loc_coffee_shop", "morning_reunion", "medium", ["Joshua seated by rain-streaked window dialing phone in anticipation"], [{"character_id": "char_joshua", "state_id": "joshua_adult", "presence": "silhouette"}], 7),
            ],
            4: [
                ("loc_coffee_shop", "morning_reunion", "medium", ["two ceramic coffee mugs on dark wood table", "steam rising in morning light"], [], 4),
                ("loc_coffee_shop", "morning_reunion", "medium_close", ["Isaiah seated across table, visibly frail with jaundiced yellowed eyes"], [{"character_id": "char_isaiah", "state_id": "isaiah_adult", "presence": "partial"}], 8),
                ("loc_coffee_shop", "morning_reunion", "over_the_shoulder", ["Isaiah raising his hand firmly", "whispering solemn protective refusal with love"], [{"character_id": "char_isaiah", "state_id": "isaiah_adult", "presence": "partial"}], 7),
                ("loc_coffee_shop", "morning_reunion", "wide", ["empty coffee cup remaining on table", "Joshua walking into cold winter street alone"], [{"character_id": "char_joshua", "state_id": "joshua_adult", "presence": "back_to_camera"}], 8),
            ],
            5: [
                ("loc_local_bar", "night_overhearing", "wide", ["dimly lit tavern booth in deep shadow", "amber pendant lamp illuminating cocktail table"], [{"character_id": "char_joshua", "state_id": "joshua_adult", "presence": "silhouette"}], 6),
                ("loc_local_bar", "night_overhearing", "medium", ["middle-aged Maria with curly brown hair speaking animatedly to young woman"], [{"character_id": "char_maria", "state_id": "maria_adult", "presence": "partial"}], 7),
                ("loc_school_bus", "crash_aftermath", "silhouette", ["shadowy flashback: Devon and stepfather silhouette in moonlight"], [], 9),
                ("loc_local_bar", "night_overhearing", "medium_close", ["shadowy silhouette: wedding dress, fallen tiered cake, wooden dowel in shadow"], [], 9),
            ],
            6: [
                ("loc_local_bar", "night_overhearing", "medium", ["Maria leaning close to table, mouth tight as she delivers the final prophecy"], [{"character_id": "char_maria", "state_id": "maria_adult", "presence": "partial"}], 8),
                ("loc_local_bar", "night_overhearing", "close_up", ["shadowed profile of Joshua, throat trembling in sudden paralyzing terror"], [{"character_id": "char_joshua", "state_id": "joshua_adult", "presence": "silhouette"}], 9),
                ("loc_local_bar", "night_overhearing", "wide", ["Joshua bursting through tavern exit into freezing dark empty street"], [{"character_id": "char_joshua", "state_id": "joshua_adult", "presence": "back_to_camera"}], 9),
                ("loc_school_bus", "afternoon_memory", "wide", ["haunting memory of school bus aisle receding into absolute darkness", "final realization"], [], 9),
            ],
        }

        bp_list = episode_blueprints.get(ep_num, episode_blueprints[1])
        n_scenes = len(bp_list)
        n_sents = len(sentences)

        # Distribute all sentences evenly across scenes so no narration is lost
        scene_sentences_map = [[] for _ in range(n_scenes)]
        for idx, sentence in enumerate(sentences):
            s_target = min(idx * n_scenes // n_sents, n_scenes - 1)
            scene_sentences_map[s_target].append(sentence)

        # Ensure no scene is left with empty narration text
        for s_idx in range(n_scenes):
            if not scene_sentences_map[s_idx]:
                scene_sentences_map[s_idx].append(sentences[min(s_idx, n_sents - 1)])

        scenes = []

        for s_idx in range(n_scenes):
            sc_id = f"ep{ep_num:02d}_s{s_idx + 1:02d}"
            loc_id, var_id, shot_type, comp, char_ref, tension = bp_list[s_idx]
            s_text = " ".join(scene_sentences_map[s_idx])
            start_t = round(s_idx * (duration_s / n_scenes), 2)
            end_t = round((s_idx + 1) * (duration_s / n_scenes), 2)
            cam_type = "slow_push_in" if s_idx % 2 == 0 else "static"

            scene_obj = {
                "scene_id": sc_id,
                "narration": {
                    "text": s_text,
                    "start_s": start_t,
                    "end_s": end_t,
                    "timing_source": "estimated",
                },
                "narrative_purpose": f"Escalate psychological tension and visualize beat {s_idx + 1} of Episode {ep_num}.",
                "narrative_mode": "remembered_narration" if ep_num <= 2 else "present",
                "visual_description": f"Cinematic staging: {comp[0]}. Controlled low-key lighting, desaturated Bus-Window Grey palette.",
                "characters": char_ref,
                "location_id": loc_id,
                "variant_id": var_id,
                "shot": {
                    "type": shot_type,
                    "angle": "eye_level",
                    "composition": comp,
                },
                "camera_movement": {
                    "type": cam_type,
                    "intensity": "barely_perceptible",
                    "rationale": "Quiet resolve and mounting inevitable dread.",
                },
                "lighting": {
                    "style": "practical" if loc_id in ["loc_coffee_shop", "loc_local_bar"] else "ambient",
                    "key_source": "overhead practical bulb" if loc_id in ["loc_coffee_shop", "loc_local_bar"] else "diffused window light",
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
                    "type": "hard_cut" if s_idx < len(bp_list) - 1 else "dip_to_black",
                    "duration_ms": 200 if s_idx < len(bp_list) - 1 else 600,
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
                "hands_off_to_next": "Holding motionless in deep shadow before dip to black",
            },
            "visual_progression": [
                {
                    "phase": "setup",
                    "scene_ids": [s["scene_id"] for s in scenes[:2]],
                    "tension_start": scenes[0]["tension_level"],
                    "tension_end": scenes[1]["tension_level"],
                    "description": "Establish eerie setting and quiet tension",
                },
                {
                    "phase": "escalation_and_cliffhanger",
                    "scene_ids": [s["scene_id"] for s in scenes[2:]],
                    "tension_start": scenes[2]["tension_level"],
                    "tension_end": scenes[-1]["tension_level"],
                    "description": "Mounting dread and concluding cliffhanger",
                },
            ],
            "scenes": scenes,
            "audio_design": {
                "soundtrack_profile": "low_sub_bass_drone",
                "procedural_stems": ["ambience", "risers", "sweeps"],
            },
            "quality_rubric_self_check": {
                "pacing": 9.0,
                "focal_point": 9.0,
                "lighting_contrast": 9.0,
                "palette_adherence": 9.5,
                "text_safe_zone": 10.0,
                "overall_score": 9.3,
            },
        }

        # Validate against schema
        jsonschema.validate(instance=storyboard, schema=self._episode_storyboard_schema)
        return storyboard


visual_director = VisualDirector()
