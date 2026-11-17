# Script framework (40-60 s Shorts)

## Word budget (calibrate, do not guess)
Measure real speech rate from 5-10 finished videos: `words_per_second = narration_words / narration_seconds`. Kokoro at default speed is usually about 2.4-2.8. Use that number in `validate_script.py --wps`.
Target audio length 42-58 s. Rough budget at 2.6 wps: **110-145 words**, 11-15 sentences. Hard limits 40 s and 60 s (the pipeline's existing 20-60 s check already allows this).

## Structure (beats = scenes for the existing visual system)
| Beat | Time | Job |
|---|---|---|
| 1 Hook | 0-3 s | One concrete, surprising claim, <= 14 words. No greeting, no setup. |
| 2 Stakes/context | 3-10 s | Who, where, when, and why it matters. Specific names and numbers. |
| 3-5 Escalation | 10-40 s | Each beat adds a new fact that raises tension or surprise. One idea per sentence. |
| 6 Turn | 40-50 s | The twist or consequence the viewer did not predict. |
| 7 Loop line | 50-58 s | Final sentence echoes the hook wording so the video replays smoothly. No CTA. |

Each beat is 1-2 sentences, <= 22 words per sentence, so every scene has one visual idea. Keep the existing scene/segment schema; map beats onto it.

## Retention rules
- Cut every sentence that does not add a new fact or raise tension. If removing it changes nothing, remove it.
- Concrete beats abstract: "fifty thousand dollars" not "a lot of money"; "Paris hotel" not "a location".
- Open a loop early (an unanswered question implied by the hook) and close it late, not at the midpoint.
- Short sentences. Read aloud: if you run out of breath, split it.
- Spoken English: contractions, no semicolons, no parentheses, numbers spelled the way they are said ("fifty thousand dollars"), no abbreviations Kokoro mispronounces.
- No "subscribe", "follow", "comment" asks. The loop is the call to action.
- One topic, one story. Never list-style "5 facts".

## Accuracy and safety (non-science niches still need facts)
- Reddit and web posts are not verified. Output a `claims` list (3-6 key factual claims) and a `confidence` per claim; drop or soften anything below "high".
- No invented quotes, no invented statistics. Use "reportedly" only when the source genuinely is disputed, and do not overuse it.
- Do not name private individuals in crime or abuse stories. Avoid graphic violence, self-harm detail, and anything likely to be limited-ads. Keep true crime non-graphic and about the story, not the gore.
- Real public figures: factual, documented events only. No defamation, no fabricated dialogue.

## Output contract
Keep every field the pipeline already consumes. Add (optional):
```json
{
  "niche": "cons_and_heists",
  "hook": "In 1925, a con man sold the Eiffel Tower.",
  "hook_pattern": "impossible_claim",
  "beats": ["..."],
  "loop_line": "...",
  "claims": [{"text": "...", "confidence": "high"}],
  "title": "<= 60 chars, curiosity + concrete noun, no clickbait lies",
  "est_seconds": 52
}
```
