# Prompt to paste into Antigravity

Install first: unzip so the folder `viral-shorts-scriptwriter/` sits in `<your CurioLoop repo>/.agent/skills/` (workspace skill) or in Antigravity's global skills folder. If your Antigravity version uses a different skills path, check its docs and place the folder there.

---

You are a senior Python engineer working on CurioLoop/StoryCircuit, a LIVE local-first YouTube Shorts production system. Use the skill `viral-shorts-scriptwriter` (read its SKILL.md and every file in references/ first).

OBJECTIVE
1. Completely remove biology and science content from topic discovery, topic selection, fallbacks, prompts and validation for all NEW videos.
2. Make scripts good enough to gain views: 40-60 second Shorts (target 42-58 s of narration), retention-first, non-science niches only (see resources/niche_policy.json).
3. Keep visuals, Kokoro TTS, Whisper alignment, FFmpeg, QC, scheduler, watchdog, dashboard, YouTube upload and Telegram untouched except where a minimal, tested interface change is unavoidable.

ABSOLUTE SAFETY RULES
- Never delete or reset the local database or production state. Never touch OAuth tokens or credentials. Never delete or reschedule existing scheduled videos. Never upload or publish anything while testing. Instagram stays disabled.
- Do not run destructive cleanup on production output. Use a separate evaluation directory and a mocked/disabled publisher for every test run.
- Do not invent filenames, modules or functions. Verify everything in the repo.
- Preserve the existing script JSON schema; only add optional fields.
- Existing produced/scheduled videos and records must stay as they are.

PHASE 0: AUDIT (read-only, then STOP and wait for my approval)
Inspect the whole repo. Write `docs/SCRIPT_ENGINE_AUDIT.md` containing: file-level map of discovery, curated topic data, topic scoring/novelty, Gemini prompt/script code, script schema consumed downstream, duration validation, QC gate, fallback topics, visual-style routing, and tests. List every place biology/science can enter. Report measured `words_per_second` from at least 5 existing finished narrations. Mark each item implemented / partial / disabled / planned / missing. Note whether any visual style (e.g. Inside-Out) depends on science topics, and DO NOT delete any style.

PHASE 1: IMPLEMENT (after I approve the audit; work on a new git branch)
1. Topic policy: filter denied niches/keywords in discovery, scoring and selection; remove science/biology subreddits and curated entries from selection (archive, do not delete data); replace fallbacks with at least 30 hand-verified allowed-niche topics; map allowed niches to existing visual styles.
2. Script generation: replace prompts using references/gemini_prompts.md (two-call flow, max 3 Gemini calls per video, existing backoff for 429s). Keep existing output keys; add niche, hook, hook_pattern, beats, loop_line, claims, est_seconds.
3. Validation gate: integrate scripts/validate_script.py (copy into the project's package) between script generation and TTS. Errors trigger a targeted rewrite using the error list; after the retry budget, fail the topic using the existing recoverable/permanent/waiting classification and move to the next topic. Never reprocess an unchanged failed script. Store the validator result in the job record.
4. Config: add words_per_second, word_min, word_max, target_seconds 42-58, keeping the existing 20-60 technical limit.
5. Tests: unit tests for the validator and topic filter, a test proving no denied-niche topic can be selected, a Gemini-mocked script test. Run the full existing pytest suite and report pre-existing failures separately.

PHASE 2: EVALUATE (isolated)
Generate 10 scripts in an evaluation directory with publishing mocked. Report pass rate, average estimated seconds, validator warnings, Gemini calls per video, and the 3 weakest scripts with reasons. Do not render or upload unless I ask, and if you render, only into the evaluation directory.

DELIVERABLES
Git diff summary, SCRIPT_ENGINE_AUDIT.md, test results, evaluation report, and a final table of implemented / partial / disabled / planned / missing items. Stop and ask before any change that touches production state, scheduling, credentials or the live database.
