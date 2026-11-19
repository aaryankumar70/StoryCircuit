# Camera and Composition

## Contents
1. How to use this file
2. Shot types: what, when, why
3. Angles
4. Composition techniques
5. Camera movement
6. Vertical (9:16) framing rules
7. Choosing a shot: decision table

## 1. How to use this file
Pick the shot from the **narrative purpose**, not from habit. Every movement must serve the narration. If a shot or movement cannot be justified in one sentence (`camera_movement.rationale`), simplify.

## 2. Shot types
| Shot (`shot.type`) | What it is | Use when | Avoid when |
|---|---|---|---|
| `extreme_wide` | Subject tiny in a vast setting | Isolation, scale, dread of space | You need emotion from a face |
| `wide` | Full figure plus environment | Relationship between character and place | Close emotional beat |
| `establishing` | Orients the viewer in a new location/time | First scene in a location; time jumps | Repeated within one location |
| `medium` | Waist-up | Dialogue-like exchange, posture | Details that need clarity |
| `medium_close` | Chest-up | Emotional state without intimacy overload | Large environmental storytelling |
| `close_up` | Face or key object | Strong emotion, key object | Anonymous or withheld faces |
| `extreme_close_up` | Detail (eyes, hands, object) | Peak tension, evidence, a trigger | Overuse; once or twice per episode |
| `over_the_shoulder` | Over one subject toward another | Confrontation, listening, withholding a face | Single-character scenes |
| `pov` | Viewer sees through a character's eyes | First-person narration, discovery | Scenes where the narrator should be seen |
| `silhouette` | Dark figure against light | Anonymity, threat, withholding identity | Scenes needing readable expression |
| `insert` | Close view of an object or document | Clues, objects, motifs | Pacing needs to be fast and wide |

## 3. Angles
- `eye_level`: neutral, documentary, ordinary-made-wrong.
- `low`: power, threat, looming architecture. Use sparingly; do not make normal people monstrous.
- `high` / `overhead`: vulnerability, mapping, desk evidence, isolation.
- `ground_level`: unease, insects-eye, objects on floors.
- `dutch_subtle`: <= 3 degrees, only for brief disorientation; never sustained.

## 4. Composition techniques
- **Negative space**: empty frame area that makes the subject feel isolated or watched. Put the subject in the lower third or to one side.
- **Leading lines**: roads, aisles, hallways point toward the story's destination or the unknown.
- **Foreground framing**: doorway edges, seat backs, branches that create depth and voyeuristic tension.
- **Rule of thirds / off-centre subjects**: use for unease; centred subjects for confrontation and symmetry.
- **Symmetry**: use for ritual, institutions, inevitability; break it once for impact.
- **Depth layering**: foreground / midground / background with distinct values for parallax.
- **Visual hierarchy**: one brightest area, one highest-contrast edge, one sharp plane. The audience looks where those coincide.
- **Focus**: shallow focus isolates; deep focus lets a threat hide in the background.

## 5. Camera movement (`camera_movement.type`)
| Movement | Meaning | Typical range |
|---|---|---|
| `static` | Stillness, weight, dread | Dread beats, key lines |
| `slow_push_in` | Approach, realisation, fixation | scale 1.00 -> 1.04-1.08 over scene |
| `slow_pull_out` | Release, isolation, reveal of scale | scale 1.06 -> 1.00 |
| `pan_left/right` | Following, searching, reading a map | <= 8% of frame width |
| `tilt_up/down` | Revealing height, depth | <= 6% of frame height |
| `parallax_drift` | Depth and life in a still image | layer offsets 1-3% |
| `rack_focus` | Redirects attention, reveals | 0.6-1.2 s |
| `handheld_micro` | Instability, panic | Rare; <= 0.3% jitter; never constant |

Intensity vocabulary: `none`, `barely_perceptible` (<= 0.06 scale), `subtle` (0.06-0.12), `moderate` (0.12-0.2), `strong` (>0.2; reserve for climactic moments).

## 6. Vertical (9:16) framing rules
- Place key subjects in the central 70% of height; keep a safe margin (~12% top, ~20% bottom) free of key detail for platform UI and captions.
- Vertical frames favour vertical lines (doorways, trees, hallways); use them as dominant lines.
- Wide shots work if the subject is small and the environment is tall; use depth (near/far) rather than width.
- Captions usually occupy the lower third; do not place faces or key objects there.
- Keep the focal point stable across a scene so the viewer does not need to search.

## 7. Choosing a shot: decision table
| Narration beat | Recommended |
|---|---|
| Introduces a place | `establishing` / `wide`, slow push-in |
| States a rule or fact calmly | `medium`, static |
| Admits something terrible | `extreme_close_up` or `wide` static |
| Describes a memory | `wide` with foreground motif, soft contrast |
| Describes a decision | `medium_close` or back-to-camera, slow push-in |
| A reveal | focus/light change, not a new object |
| Ends the story | held wide, dip to black |
