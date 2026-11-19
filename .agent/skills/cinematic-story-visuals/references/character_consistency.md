# Character Consistency

## Contents
1. Principle
2. Identity record
3. States for ages and eras
4. Identity decision table
5. Locked traits and allowed changes
6. Presentation modes (when faces are withheld)
7. Consistency in prompts and rendering
8. Validation

## 1. Principle
A character must not change appearance between scenes or episodes without narrative justification. **Never invent additional characters or alter established identities.** If the script does not supply a detail, mark it ASSUMPTION and keep it fixed once chosen.

## 2. Identity record
Fields (see `../templates/character_sheet_template.md`): `character_id`, `name`, `narrative_role`, `presentation`, then per state: `state_id`, `label`, `age`, `timeline_period`, `appearance` (build, face, hair, skin tone, distinguishing), `clothing`, `emotional_baseline`, `reference_description`, `locked_traits`, `allowed_changes`.

## 3. States for ages and eras
Same person at a different age = **same `character_id`, new `state_id`**. Keep **echo traits** between states so the audience can connect them (the same scarf colour, hair colour family, a distinctive posture). Document echoes in `locked_traits`.

## 4. Identity decision table
| Case | Treatment |
|---|---|
| New character | New `character_id` and at least one state |
| Existing character, same era | Reuse same `character_id` + `state_id` |
| Same character at a different age | Same `character_id`, new `state_id`, echo traits retained |
| Character remembered through narration only | `presence: remembered`: silhouette, object, or none; never invent a face |
| Flashback | Use the state matching the flashback's era |
| Unnamed group | One `group` character with anonymous cluster rules |
| Unclear whether two mentions are the same person | Treat as one character unless the script says otherwise; flag for review |

## 5. Locked traits and allowed changes
- **Locked**: traits that never change within a state (hair colour, signature garment, build).
- **Allowed**: situational changes (collar up, hood down, scarf loosened, posture, expression). Each allowed change needs a story or environmental reason.
- **Forbidden**: new tattoos, glasses, injuries, hairstyles, outfit swaps without a time or scene reason.

## 6. Presentation modes
`on_screen`, `mostly_unseen`, `silhouette_only`, `group`, `remembered_only`. First-person narrators are often `mostly_unseen`: show back, hands, profile shadow or POV; do not show a face unless the script requires it. Withholding the face also removes the largest consistency risk in AI-generated imagery.

## 7. Consistency in prompts and rendering
- Paste the state's `reference_description` verbatim into every prompt that includes the character.
- Reuse the same seed, reference image or asset when the renderer supports it.
- If the renderer uses supplied or generated stills, maintain a **character reference sheet** (front, side, back, key props) and reuse crops.
- For SVG/CSS silhouettes, build one reusable silhouette asset per state and reuse it everywhere; vary only pose/scale.
- Use identical colours for signature clothing (HEX in the bible).

## 8. Validation
Fail a storyboard if any scene references an unknown `character_id`/`state_id`, mixes eras (adult and child states in the same frame without a justified overlay), or violates `locked_traits`. `scripts/validate.py` enforces the ID checks; the rest are manual rubric items (see `visual_quality_rubric.md`).
