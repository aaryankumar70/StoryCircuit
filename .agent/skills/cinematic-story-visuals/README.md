# cinematic-story-visuals

Renderer-independent **visual direction skill** for narrated short-form video. It converts a written script into a persistent **visual bible**, **episode storyboards**, shot/lighting/motion instructions and QC scores, with first-class support for **serialized stories** (consistent characters, locations and palette across daily episodes).

Built for CurioLoop (Kokoro TTS, faster-whisper, HTML/CSS/JS rendering, headless browser, FFmpeg), but it assumes none of it: the future implementation agent inspects the real repository and adapts the skill.

## Architecture
```
SKILL.md                 entry point: when to use, workflow, rules (loads fast)
ANTIGRAVITY_PROMPT.md    instructions for the coding agent integrating it into CurioLoop
references/              deep knowledge, loaded on demand
  profiles: horror (A, primary), mystery (B), historical (C)
  craft: camera, lighting/colour, motion/transitions, prompts
  continuity: characters, environments, serialized series, scene breakdown
  QC: 10-criterion rubric with automatic failures
templates/               fill-in templates (bible, character, location, episode, scene JSON)
schemas/                 JSON Schema for the visual bible and episode storyboard
examples/                worked examples (horror full, mystery, historical) + validated JSON
scripts/validate.py      dependency-free schema + continuity + link validator
```
Pipeline concept: **Script -> Understanding -> Visual Bible -> Scene Breakdown -> Storyboard JSON -> Validate -> (renderer adapter built by Antigravity) -> Local render -> Rubric QC**.

## Files
- `SKILL.md`, `ANTIGRAVITY_PROMPT.md`, `README.md`
- `references/`: `visual_philosophy.md`, `horror_visual_language.md`, `mystery_visual_language.md`, `historical_visual_language.md`, `camera_and_composition.md`, `lighting_and_color.md`, `character_consistency.md`, `environment_consistency.md`, `scene_breakdown.md`, `transitions_and_motion.md`, `serialized_visual_continuity.md`, `prompt_engineering.md`, `visual_quality_rubric.md`
- `templates/`: `visual_bible_template.md`, `character_sheet_template.md`, `location_sheet_template.md`, `episode_storyboard_template.md`, `scene_specification_template.json`
- `examples/`: `psychological_horror_example.md`, `mystery_example.md`, `historical_example.md`, `visual_bible_example.json`, `episode_storyboard_example.json`
- `schemas/`: `visual_bible.schema.json`, `episode_storyboard.schema.json`
- `scripts/`: `validate.py` (supporting file)

## Quick start
```
python scripts/validate.py skill .
python scripts/validate.py bible examples/visual_bible_example.json
python scripts/validate.py episode examples/episode_storyboard_example.json --bible examples/visual_bible_example.json
```
Requires Python 3.8+. Uses `jsonschema` automatically if installed; otherwise a built-in Draft-07 subset validator.

## Installation in Google Antigravity
Antigravity's skill folder locations and UI can change between versions; check its current documentation if the paths below differ.
1. Unzip `cinematic-story-visuals.zip` so you have a folder `cinematic-story-visuals/` that contains `SKILL.md` at its top level.
2. Place the folder where Antigravity discovers skills:
   - **Workspace (project) skills:** `<your-repo>/.agent/skills/cinematic-story-visuals/`
   - **Global (all projects) skills:** `~/.gemini/antigravity/skills/cinematic-story-visuals/` (on Windows: `%USERPROFILE%\.gemini\antigravity\skills\cinematic-story-visuals\`)
3. Restart or reload the agent session so it re-scans skills.
4. In the agent chat, paste the contents of `ANTIGRAVITY_PROMPT.md` (or tell the agent: "Read `.agent/skills/cinematic-story-visuals/ANTIGRAVITY_PROMPT.md` and follow it").
5. Ask the agent to run `python scripts/validate.py skill .` inside the skill folder to confirm the install.

## How it will integrate with CurioLoop
1. After the script and Kokoro/faster-whisper timing exist, the pipeline asks the existing LLM provider (no new paid calls) to produce a storyboard JSON guided by `SKILL.md`.
2. The JSON is validated (schema + continuity). On failure, CurioLoop falls back to its current visuals.
3. A small adapter maps scenes to existing HTML/CSS/JS template parameters (zoom/pan, overlays, transitions, palette variables); unsupported features degrade gracefully.
4. For Creator Series, the bible and ledger persist per series so each daily episode continues the previous episode's closing state; automatic content stays on its own independent path.
5. Local render -> rubric QC -> human approval before anything is scheduled.

## Limitations the implementation agent must account for
- The skill is stateless: **persistence of bibles/ledgers must be implemented by the repository** (separate for Creator Series vs automatic content).
- **Character consistency without image generation is limited**: with procedural or stock visuals, rely on silhouettes, back-of-head shots, reusable SVG/CSS assets and locked colours. True face consistency needs a generator that supports reference images or seeds, which may not exist locally.
- Shot types and camera angles are *specifications*; the renderer can only approximate them with 2D layers, crops and transforms.
- Storyboards are generated by an LLM and may drift; the validator catches structural and ID errors but not artistic quality (use the rubric and human review).
- Narration timing in examples is estimated; replace with faster-whisper alignment when available.
- The examples contain **assumed** names and details for visual coherence; real scripts override them.
- Palette HEX values are starting points; verify legibility with the pipeline's caption styling and platform safe areas.
- Antigravity skill paths and invocation behaviour may change; verify against current documentation.
- The skill defines no Space/Cosmology profile yet (extension steps in `SKILL.md` section 8).
