---
name: cinematic-story-visuals
description: Visual direction system that turns a written script into a cinematic, visually consistent short-form video plan (visual bible, character and location records, scene breakdown, episode storyboard, prompts, camera/lighting/motion instructions). Use whenever a task involves planning or improving visuals for narrated stories, YouTube Shorts, horror, mystery or historical storytelling, multi-part series continuity, character or location consistency, storyboards, shot lists, or visual quality review, even if the user does not say "cinematic". Do NOT use for writing scripts, TTS, captions-only work, publishing, scheduling, or non-narrative graphics.
---

# Cinematic Story Visuals

A renderer-independent **visual direction** skill. It decides *what the audience sees, what stays hidden, and how the picture serves the narration*; it does not render anything itself and does not assume any image/video API.

## 1. What it produces
1. **Visual bible** (JSON, per series) - identity, palette, lighting, camera language, characters (with age/era states), locations (with variants), objects, motifs, constraints, continuity ledger.
2. **Episode storyboard** (JSON, per episode) - scenes with narration timing, shot, movement, lighting, palette, motion layers, transitions, continuity requirements, optional prompts.
3. **Quality review** - 10-criterion rubric score with ship / revise / reject.
4. **Implementation notes** for the engineering agent (Antigravity) describing what the renderer must support.

Schemas: `schemas/visual_bible.schema.json`, `schemas/episode_storyboard.schema.json`. Validator: `scripts/validate.py` (no dependencies).

## 2. When to activate
Activate when the task is any of: storyboarding a narrated story; defining or reusing a series' look; keeping characters/locations consistent; planning camera, lighting, motion or transitions for Shorts; generating image prompts or art-direction specs; reviewing visual quality; adding a new visual profile.

Do **not** activate for: script writing/topic selection, TTS/audio, subtitle styling alone, thumbnail text, publishing/scheduling/OAuth/database work, or pure code refactors unrelated to visuals.

## 3. Hard rules (always)
1. **Never invent** characters, events or plot twists. Unknown details are marked ASSUMPTION and then frozen.
2. **Narration leads.** Visuals never contradict it and never depict unstated events.
3. **Withhold deliberately.** Record `hidden_or_withheld`; do not visualise forbidden/unknown content (a story's words, an entity, a culprit).
4. **Consistency over novelty.** Reuse IDs, palette and states. Identity changes only when the narrative justifies it and is logged.
5. **Do not assume** a renderer, image generator, video generator or paid API. Inspect first; downgrade scenes to what exists.
6. **Every camera movement needs a one-line reason**; static is valid.
7. **Do not touch** publishing, OAuth, scheduling or database state.

## 4. Workflow
### Step 0 - Gather
Inputs: the script (with narration timing if available), series ID, existing bible (if any), previous episode's closing state, and renderer capabilities (if known).

### Step 1 - Select profile
| Signal in script | Profile | Read |
|---|---|---|
| Fear, dread, unease, unexplained, personal haunting | `psychological_horror` | `references/horror_visual_language.md` |
| Investigation, evidence, documents, "what happened", unsolved | `mystery_investigative` | `references/mystery_visual_language.md` |
| Real past events, a named era, dates, historical figures | `historical` | `references/historical_visual_language.md` |
| Space/cosmology or anything else | `custom` | Create a new profile using `references/visual_philosophy.md` + `references/lighting_and_color.md` (see section 8) |
If two profiles fit, pick the dominant one for the bible and note the secondary in `implementation_notes`. Profiles are independent: never blend palettes.

### Step 2 - Understand the script
Extract characters, descriptions, locations, time periods, timeline, objects, events, emotional progression, suspense points, revelations, motifs, transitions (full checklist: `references/scene_breakdown.md`). Resolve character identity cases (new / existing / different age / remembered / flashback) using `references/character_consistency.md`.

### Step 3 - Create or load the visual bible
- New series: fill `templates/visual_bible_template.md`, then emit `visual_bible.json`.
- Existing series: load it, add only genuinely new characters/locations/objects, keep IDs stable. See `references/serialized_visual_continuity.md`.
- Locations: `references/environment_consistency.md`. Colour/light: `references/lighting_and_color.md`.

### Step 4 - Break the script into scenes
Boundaries come from changes in location, time, emotional beat, information, or required camera idea, not from sentences. Targets: 30 s = 5-8 scenes, 45 s = 7-10, 60 s = 9-13; 2-9 s per scene. Fill `templates/scene_specification_template.json`. Camera and composition: `references/camera_and_composition.md`. Motion and transitions: `references/transitions_and_motion.md`.

### Step 5 - Write the episode storyboard
Use `templates/episode_storyboard_template.md` and emit `episode_storyboard.json`: opening visual (continues from previous closing), visual progression with tension levels, scenes, closing visual and hand-off, continuity notes. Append the episode's closing state to `continuity_ledger`.

### Step 6 - Prompts / art-direction specs (only if useful)
Use `references/prompt_engineering.md`. If the renderer is procedural, treat prompts as specs for building layers. Paste canonical `reference_description` text for characters and `description`/`fixed_elements` for locations.

### Step 7 - Validate
```
python scripts/validate.py bible   visual_bible.json
python scripts/validate.py episode episode_storyboard.json --bible visual_bible.json [--previous prev_episode.json]
python scripts/validate.py skill   .     # self-check of bundled examples and doc links
```
Fix all FAIL lines; review WARN lines. Then score with `references/visual_quality_rubric.md` (ship needs avg >= 8.0, no criterion < 7, no automatic failure; serialised episodes need criteria 6, 7, 10 >= 8).

### Step 8 - Communicate implementation requirements
Produce a short list for the engineering agent: which scene features need which renderer capability (layers, parallax, particles, light-dimming overlay, grain, transitions), what was downgraded, and any assumptions. Point it to `ANTIGRAVITY_PROMPT.md`. Never ask for new paid services.

## 5. Output contract (summary)
- IDs: `char_*`, `loc_*`, `obj_*`, `motif_*`, scene IDs `epNN_sNN`; state IDs and variant IDs are lowercase snake_case.
- Required per scene: `scene_id`, `narration{text,start_s,end_s}`, `narrative_purpose`, `narrative_mode`, `visual_description`, `characters[]`, `location_id`, `variant_id`, `shot`, `camera_movement`, `lighting`, `palette[3-6 HEX]`, `motion.layers[]`, `tension_level`, `transition_out`, `continuity_requirements[]`.
- Optional: `hidden_or_withheld`, `prompt`, `implementation_hints`.
- Continuity rules enforced by the validator: all IDs resolve to the bible; profile/series match; static camera has intensity `none`; narration times ascend without overlap; opening matches previous closing or is explained.

## 6. Pacing and motion defaults (vertical Shorts)
Static or barely perceptible push-in (<= 0.06 scale) by default; stillness for dread beats; short cuts or one long hold at climax, never both; non-cut transitions in <= 40% of scenes; hook image in first 1-3 s; keep faces/key objects out of the bottom ~20% (captions) and top ~12% (platform UI).

## 7. Reference map (load only what you need)
| Need | File |
|---|---|
| Principles | `references/visual_philosophy.md` |
| Profile A/B/C | `references/horror_visual_language.md`, `references/mystery_visual_language.md`, `references/historical_visual_language.md` |
| Shots and composition | `references/camera_and_composition.md` |
| Light and colour | `references/lighting_and_color.md` |
| Characters / places | `references/character_consistency.md`, `references/environment_consistency.md` |
| Scenes / motion | `references/scene_breakdown.md`, `references/transitions_and_motion.md` |
| Series continuity | `references/serialized_visual_continuity.md` |
| Prompts | `references/prompt_engineering.md` |
| QC | `references/visual_quality_rubric.md` |
| Full worked example | `examples/psychological_horror_example.md` (+ JSON files) |

## 8. Adding a new profile (e.g. Space / Cosmology)
Create `references/<profile>_visual_language.md` following the section layout of the existing profile files (identity, palette HEX, lighting, composition, motion, anti-patterns, recipes); add the enum value to both schemas (or use `custom` + `custom_profile_name`); add a palette entry in `references/lighting_and_color.md`; add a row to the profile table above. Do not modify existing profiles.

## 9. Integration
For repository integration, follow `ANTIGRAVITY_PROMPT.md`. This skill never edits a repository by itself.
