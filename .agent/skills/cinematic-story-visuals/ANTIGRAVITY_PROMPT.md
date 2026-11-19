# ANTIGRAVITY_PROMPT: Integrate `cinematic-story-visuals` into CurioLoop

You are a senior engineer working inside the real CurioLoop repository. Integrate the `cinematic-story-visuals` skill (this package) as an **optional, additive visual-direction layer**. The skill is renderer-independent; the repository is the source of truth about what can actually be rendered.

## 0. Non-negotiable rules
1. **Inspect first, change later.** Do not write code until Phase 1 is complete and summarised.
2. **Preserve all existing rendering capabilities.** Every current template, topic type and output must render exactly as before when the new feature is off (default off or behind a per-series setting).
3. **Add visual profiles without globally replacing existing templates.** Profiles are selectable additions.
4. **Keep automatic content and Creator Series visually independent.** Automatic daily content must not pick up Creator Series profiles, bibles or ledgers, and vice versa. Keep storage, IDs and config separate.
5. **Reuse existing production infrastructure** (script pipeline, Kokoro TTS output, faster-whisper alignment, HTML/CSS/JS templates, headless browser rendering, FFmpeg assembly, QC).
6. **No unnecessary dependencies and no new external API costs.** Do not add paid APIs, cloud services or heavy libraries. If an optional free local generator already exists in the repo, you may use it; do not make generation mandatory.
7. **Never modify publishing, OAuth, scheduler or database state** as part of this integration. No schema migrations on production tables, no edits to upload logic, tokens, scheduling slots or queued/published records. If persistence is needed, use new files or a clearly separate new store, and only if the repository already has such a pattern.
8. **Validate with local rendering before any production deployment.** Do not deploy, schedule or publish as part of this task.
9. Work on a branch or working copy; keep commits small and reversible.

## 1. Phase 1: Inspect (read-only)
Produce a written findings report before coding:
- Rendering architecture: entry points, how a script becomes frames/video, where HTML/CSS/JS templates live, how scenes/segments are represented, how audio timing (faster-whisper) maps to visuals, how FFmpeg assembles the output, resolution/fps/duration constraints.
- **Currently active visual templates** and where each is used (by topic type, by content type, automatic vs Creator Series). List which are live, which are legacy.
- Existing capabilities: image generation or stock fetching (if any), parallax/zoom/pan, particles, overlays, transitions, grain/vignette, caption rendering, safe areas.
- Configuration mechanism (settings files, env, dashboard) and how series/topic types are chosen.
- Persistence patterns for per-series data (files, folders, DB) and whether a safe new location exists.
- QC step(s): what is checked today.
- Test or dry-run tooling for local rendering.
Summarise the report to the user and wait for confirmation if anything is ambiguous.

## 2. Phase 2: Design the integration (small, additive)
Based on the findings, propose a minimal design covering:
1. **Profile registry:** a simple mapping from profile ID (`psychological_horror`, `mystery_investigative`, `historical`) to a style preset the *existing* renderer can apply (palette variables, grain/vignette strength, motion defaults, transition set). Existing templates remain the default.
2. **Storyboard adapter:** a function that reads an `episode_storyboard.json` (see `schemas/`) and maps each scene to the repository's existing scene/segment structure: duration from narration timing, camera movement -> zoom/pan params, motion layers -> available layers/overlays, transition -> existing transition set, palette -> CSS variables. Where a feature is unsupported, **degrade gracefully** (e.g. parallax -> slow zoom; particles -> none) and log the downgrade.
3. **Series store:** where `visual_bible.json` and episode storyboards live for Creator Series only (separate from automatic content). Include read/write helpers with schema validation.
4. **Skill invocation point:** where in the pipeline the visual plan is generated (after the script and audio alignment, before rendering). The plan may come from an LLM call that already exists in the pipeline (reuse the same provider and budget; no new paid calls), guided by `SKILL.md` and references.
5. **Fallback:** if storyboard generation or validation fails, the pipeline falls back to the current visual path with no user-visible failure.
6. **QC hook:** add the rubric's automatic-failure checks that can be automated (unknown IDs, palette drift, tension/motion mismatches via `scripts/validate.py` logic). Do not remove existing QC.
7. **Feature flag/config:** profile selection per series; default off.
Present the design briefly, then implement.

## 3. Phase 3: Implement
- Copy or vendor the skill into the repository's skills location used by Antigravity (see README installation). Keep `scripts/validate.py` runnable with plain Python.
- Implement the profile registry, adapter, series store and QC hook per the design, touching as few existing files as possible.
- Keep Creator Series and automatic content code paths separate (separate config keys, folders, and function entry points).
- Add small unit tests or dry-run scripts consistent with the repository's testing style.
- Update documentation (README or docs folder) with how to enable a profile, where bibles live, and how to validate.

## 4. Phase 4: Validate locally (required)
1. Run `python scripts/validate.py skill .` in the skill folder.
2. Render the bundled example storyboard (`examples/episode_storyboard_example.json`) locally through the adapter with the real renderer, vertical 9:16, with existing audio-timing inputs or placeholder silence.
3. Render one existing automatic-content video with the feature off and confirm output is unchanged (visual comparison and, if possible, frame hashes).
4. Check: faces/key objects in safe areas, no flashing > 3 Hz, scene durations match narration, transitions work, no console/render errors, render time within budget.
5. Score the rendered sample with `references/visual_quality_rubric.md`.
6. Produce a report: files changed, features degraded, assumptions, rubric score, screenshots or sample frames.

## 5. Phase 5: Hand-off
Deliver: summary of changes; list of files; how to turn the feature on/off; known limitations; a checklist confirming rules 0.1-0.9. **Do not deploy, schedule or publish.** Stop for human approval.

## 6. Things to ask the user only if inspection cannot answer
- Which Creator Series (if any) should be used as the first pilot.
- Whether free local image generation exists in the repository and may be used.
- Preferred location for series bibles.

## 7. Acceptance criteria
- Existing outputs unchanged with feature off.
- A Creator Series episode can be rendered from a validated storyboard with a chosen profile.
- Automatic content is unaffected by Creator Series assets.
- No new paid services, no publishing/OAuth/scheduler/DB changes.
- Fallback to existing visuals on any failure.
