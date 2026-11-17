# Integration guide (adapt to the real repo; verify every path)

## 1. Remove biology/science at every entry point
Search the repo (case-insensitive) for: science, biology, anatomy, neuro, medicine, health, space, nature, animal, and the lists in `resources/niche_policy.json`.
- **Discovery**: remove science/biology subreddits and keywords from the Reddit source list; add `discovery_keyword_denylist` as a filter on titles/bodies.
- **Curated data**: tag or move science/biology entries to an archive file (do not delete data); exclude them from selection.
- **Scoring/novelty**: add a niche allow-list check; zero score for denied niches. Keep novelty logic as is.
- **Fallback topics**: replace with allowed-niche fallbacks (at least 30 hand-verified ones).
- **Prompts**: remove science framing and examples.
- **Visual style routing**: topic -> style mapping must still work for non-science niches (Paper Atlas for places/geography, Stick Story for human stories). Do not delete any style.
- **Existing production data**: never modify already-produced or scheduled videos or DB records. Policy applies to new topics only.

## 2. Script generation
Replace prompt construction with `gemini_prompts.md`. Keep client code, retries, JSON parsing, and output keys. Add config values: `words_per_second`, `word_min`, `word_max`, `target_seconds_min=42`, `target_seconds_max=58`.

## 3. Validation gate
Call `validate(script, wps)` (import from `scripts/validate_script.py`, or copy it into the project's own package) after script generation and before TTS. On errors: feed `errors` into critique/repair (max 2 more calls), else mark the topic failed and select the next topic. Persist the validator result in the job record. Classify failures with the existing recoverable / permanent / waiting taxonomy; never reprocess an unchanged failed script.

## 4. Tests
Unit tests for validator and topic filter; a test that no denied-niche topic can be selected; a test with Gemini mocked; run existing pytest suite and report any pre-existing failures separately.

## 5. Evaluation
Use a separate eval output dir and a mocked publisher. Generate 10 scripts, report: pass rate, avg estimated seconds, avg score, number of Gemini calls per video, top 3 weakest scripts with reasons.
