---
name: viral-shorts-scriptwriter
description: Retention-first script engine for the CurioLoop/StoryCircuit YouTube Shorts pipeline. Use this skill whenever the task involves choosing topics, writing, rewriting, scoring, validating or debugging narration scripts for 40-60 second Shorts, removing biology/science content, fixing weak hooks or "AI-sounding" scripts, tuning Gemini script prompts, or changing the script-quality gate. Use it even if the user only says "improve the scripts", "make shorts get more views", or "remove science topics".
---

# Viral Shorts Scriptwriter (CurioLoop)

Goal: make every Short a **40-60 second, story-driven, non-science** video whose script earns its watch time. Visuals (Inside-Out, Paper Atlas, Stick Story), Kokoro TTS, Whisper alignment, FFmpeg, QC, scheduler and uploader already work. **Do not touch them.** This skill only changes: topic policy, script generation prompts, script validation, and the script-quality gate.

No skill can guarantee views. This one raises the floor (no weak hooks, no filler, no slop) and adds a feedback loop so the system learns what works.

## Hard rules

1. **Production safety first.** Live system. Never delete the DB, reset state, touch OAuth tokens, delete/reschedule existing scheduled videos, or upload anything while testing. Test in a separate evaluation directory with publishing mocked or disabled. Instagram stays disabled.
2. **Audit before editing.** Read the repo, produce a file-level map (`docs/SCRIPT_ENGINE_AUDIT.md`), and only then change code. Never invent filenames; the handover doc says they must be verified.
3. **Additive changes.** Keep the existing script JSON schema the downstream stages consume. Add optional fields; never rename or remove fields without updating every consumer and tests.
4. **No biology / science topics.** Policy lives in `resources/niche_policy.json`. Enforce it at discovery, topic scoring, prompt, validator and fallback list. Already-produced or scheduled videos stay untouched.
5. **Duration 40-60 s.** Target 42-58 s of spoken audio. Word budget comes from the measured speech rate (see `references/script_framework.md`), not a guess.
6. **LLM calls are scarce** (Gemini rate limits). Max 3 calls per video: (1) ideate + draft, (2) critique + rewrite, (3) one emergency repair. Deterministic validation costs zero calls.

## Workflow

1. **Audit** (read-only). Locate: topic discovery, curated topic data, topic scoring/novelty, Gemini prompt code, script schema, duration validation, QC gate, fallback topics, tests. Note every place biology/science can enter (subreddit lists, curated data, prompt text, scoring keywords, fallbacks).
2. **Calibrate speech rate.** From 5-10 existing finished videos compute `words / narration_seconds`. Store as `words_per_second` in config. Use it in `scripts/validate_script.py --wps`.
3. **Apply topic policy** (`references/integration_guide.md` section 1).
4. **Replace the script prompt** with the two-call flow in `references/gemini_prompts.md`; keep the existing JSON output keys, add the new optional ones.
5. **Wire the validator** (`scripts/validate_script.py`) as a hard gate between script generation and TTS. Errors trigger a rewrite with the error list fed back to Gemini; warnings are logged.
6. **Add tests** (copy/adapt `scripts/test_validate_script.py`) and run the full existing test suite.
7. **Dry run** in an evaluation directory: generate 10 scripts with publishing mocked, run the validator, read them as a viewer, report pass rate and the weakest ones.
8. **Report** what is implemented, partial, disabled, planned. Stop for approval before anything that touches production state or scheduling.

## What a good script is

Read `references/script_framework.md` (structure, word budgets, pacing), `references/hook_playbook.md` (first 3 seconds), `references/banned_patterns.md` (AI-slop and weak-writing rules), `references/quality_rubric.md` (scoring used by the critique call) and `references/examples.md` (a model script and before/after rewrites) before writing or editing any prompt.

One-line version: concrete hook in under 14 words, one escalating story with a specific person/place/number every few sentences, a turn the viewer did not predict, and a last line that echoes the hook so the Short loops.

## Niches that fit (default policy)

Strange-but-true history, cons and heists, unsolved or bizarre mysteries (non-graphic), business and money stories, internet and pop-culture moments, geography and "places that shouldn't exist" (fits Paper Atlas), human-interest, workplace and relationship stories (fits Stick Story), mythology and folklore, survival and disaster stories told as human stories. Edit `resources/niche_policy.json` to change this; the validator reads it.

If a visual style was built mainly for biology/science content (check Inside-Out), do **not** delete it. Just stop routing topics to it unless a non-science niche maps to it. Report this in the audit.

## Feedback loop (optional, needs approval)

Log per video: niche, hook pattern id, word count, validator score, and later YouTube's viewed-vs-swiped-away % and average percentage viewed. Reading analytics may need an extra OAuth scope. **Do not modify or overwrite existing tokens**; ask the owner to authorise it. Use results to weight niches and hook patterns after 30+ videos, not before.

## Bundled files

- `scripts/validate_script.py`: deterministic gate (duration estimate, hook, slop, topic policy, pacing, loop ending). Stdlib only.
- `scripts/test_validate_script.py`: unit tests.
- `resources/niche_policy.json`, `resources/banned_phrases.json`: editable policy.
- `references/*.md`: writing guidance, Gemini prompts, rubric, integration guide, examples.
- `ANTIGRAVITY_PROMPT.md`: the prompt to paste into Antigravity.
