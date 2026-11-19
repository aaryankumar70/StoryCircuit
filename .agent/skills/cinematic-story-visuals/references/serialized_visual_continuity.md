# Serialized Visual Continuity

## Contents
1. Principle
2. Series-level assets
3. Continuity ledger
4. Opening and closing states
5. When the visual identity may change
6. Procedure: starting episode N
7. Procedure: finishing episode N
8. Validation rules
9. Failure and recovery

## 1. Principle
Episodes must feel like **chapters of one production**. Palette, lighting logic, camera language, character looks and locations persist across days of publishing. Visual identity **evolves only when the narrative justifies it**, and every change is logged.

## 2. Series-level assets
Stored per series (persist in the pipeline's own series storage; the skill itself is stateless):
- `visual_bible.json` (identity, palette, lighting, camera language, characters, locations, objects, motifs, constraints)
- Episode storyboards (`episode_storyboard.json` per episode)
- Continuity ledger inside the bible (`continuity_ledger[]`)
- Reference assets if the renderer uses images (character sheets, master location plates)

## 3. Continuity ledger
One entry per episode with `closing_visual_state` (location, variant, description, palette, character states), `next_opening_state` and `bible_changes`. Append the entry **when the episode storyboard is finalised**, not after publishing; update if the render changes it.

## 4. Opening and closing states
- Episode N opening = episode N-1 closing state, **or** a motivated transition recorded in `continuity_notes`.
- Common links: same frame (resume), match cut (doorway -> light strip), time-jump (dissolve + variant change), recap-free cold open on a motif.
- The closing frame should leave a visual question (a dark doorway, an unlit room), not just a fade.

## 5. When the visual identity may change
Allowed (with narrative justification and a `bible_changes` entry):
- A story turn (a revelation shifts palette temperature slightly).
- A location change (new location record).
- A time jump (new character state).
- Escalation (tighter framing, longer stillness, darker shadows within the existing palette).
Not allowed: changing palette family, grain, camera language, or character looks for novelty, or because a different renderer path was easier.
When a change is justified, bump `bible_version` and keep the old entries documented.

## 6. Procedure: starting episode N
1. Load `visual_bible.json` and the ledger.
2. Read the closing state of episode N-1.
3. Read episode N's script; extract new characters, locations, objects.
4. Add records for genuinely new elements only; reuse existing IDs for old ones.
5. Choose the opening visual (see section 4).
6. Draft the storyboard (see `scene_breakdown.md`).
7. Run `python scripts/validate.py episode ... --bible ... --previous ...`.

## 7. Procedure: finishing episode N
1. Confirm final frame matches `closing_visual`.
2. Append a ledger entry (closing state, next opening state, bible changes).
3. If new characters/locations/objects appeared, they are now in the bible.
4. Save both files.

## 8. Validation rules (continuity)
- Every `character_id`, `state_id`, `location_id`, `variant_id` in an episode exists in the bible.
- `profile` and `series_id` equal the bible's.
- Episode opening location/variant equals previous closing, or `continuity_notes` explain the break.
- Scenes never mix eras of one character in a frame.
- Palette HEX values come from the bible or are documented additions.
- No new characters not in the script.

## 9. Failure and recovery
If an earlier episode was rendered with an inconsistency: do not retroactively re-render published episodes; fix the bible so future episodes follow a single canonical look, and document the divergence in the ledger (`bible_changes`).
