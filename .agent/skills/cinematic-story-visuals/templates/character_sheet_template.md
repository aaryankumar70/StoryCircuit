# Character Sheet: <Name>

> One identity record, one or more age/era **states**. Convert to the `characters[]` block of `visual_bible.json`.

- **Character ID:** `char_<snake_case>`
- **Name:** <name> (placeholder? yes/no)
- **Narrative role:**
- **Default presentation:** on_screen | mostly_unseen | silhouette_only | group | remembered_only
- **Never show face?** yes/no (reason)
- **Source:** script-stated | ASSUMPTION

## Identity Check (answer before creating a record)
| Situation | Treatment |
|---|---|
| New character | New `character_id` |
| Existing character, same era | Reuse `character_id` and `state_id` |
| Same character, different age | Same `character_id`, new `state_id` |
| Remembered through narration only | `presence: remembered` or no depiction |
| Flashback | Use the era-appropriate state |

## State: `<state_id>`
- **Label / era / age:**
- **Build and height impression:**
- **Face:**
- **Hair:**
- **Skin tone:**
- **Distinguishing features:**
- **Clothing:**
- **Emotional baseline:**
- **Reference description (canonical sentence pasted into every prompt):**
- **Locked traits (never change):**
- **Allowed changes (and what justifies them):**

(Repeat the State block for each age/era.)
