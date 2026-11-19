# Visual Quality Rubric

## Contents
1. How to score
2. The ten criteria
3. Automatic failure conditions
4. Thresholds
5. Corrections by criterion
6. Review report format

## 1. How to score
Score each criterion **1-10** (10 = excellent). Score the storyboard first (planning stage), then the rendered episode (output stage). Two passes catch different failures. Be strict: 10 means "nothing to improve", 7 means "good and shippable".

## 2. The ten criteria
| # | Criterion | 9-10 | 7-8 | 4-6 | 1-3 |
|---|---|---|---|---|---|
| 1 | **Narrative relevance** | Every scene shows or deepens something stated in the script | One or two scenes are filler | Several scenes decorative | Visuals mostly unrelated |
| 2 | **Cinematic composition** | Intentional framing, depth, hierarchy in every scene | Mostly intentional | Centred, flat, repetitive | Random/stock-like |
| 3 | **Atmosphere** | Consistent, unmistakable mood matching profile | Mood mostly present | Mood intermittent | Mood absent or wrong |
| 4 | **Lighting** | Motivated, directional, supports tension | Mostly motivated | Flat or inconsistent | Unmotivated/blown/unreadable |
| 5 | **Colour consistency** | Palette held; one accent per frame | Minor drift | Noticeable drift | Palette ignored |
| 6 | **Character consistency** | Locked traits intact across all scenes/episodes | One minor deviation | Visible changes | Characters unrecognisable between scenes |
| 7 | **Environment consistency** | Geometry and fixed elements stable | Minor drift | Layout changes | Same place looks different |
| 8 | **Motion quality** | Motion purposeful, smooth, restrained | Mostly purposeful | Gratuitous or jerky | Distracting/nauseating |
| 9 | **Visual pacing** | Scene lengths and tension respond to narration | Mostly fitting | Monotonous or rushed | Pacing contradicts narration |
| 10 | **Episode continuity** | Seamless with previous/next; ledger respected | Small gaps | Noticeable identity drift | Episodes look unrelated |

For a standalone (non-serialised) video, score #10 as "continuity within the video" (opening/closing coherence).

## 3. Automatic failure conditions
Any one fails the output regardless of score:
1. Character appearance changes without narrative justification.
2. A scene depicts an event that never happened in the script.
3. Visuals contradict the narration.
4. Horror atmosphere becomes cartoonish (monsters, glowing eyes, gore, red filter, jump-scare zooms).
5. Effects overwhelm the story (constant shake, heavy glitch, particles on every layer).
6. Consecutive episodes have inconsistent visual identities.
7. Generic imagery replaces meaningful scenes (stock-style backgrounds, unrelated B-roll).
8. A character or location appears that is not in the script or bible.
9. Anachronism in a historical profile output.
10. Text in visuals is illegible gibberish presented as evidence.
11. Flashing > 3 per second.
12. Existing renderer capabilities broken by the integration (regression).

## 4. Thresholds
- **Ship:** average >= 8.0, no criterion < 7, no automatic failure.
- **Revise:** average 6.5-7.9 or any criterion 5-6; fix and re-score.
- **Reject:** average < 6.5, any criterion <= 4, or any automatic failure; return to the stage that caused it (bible, breakdown or production).
- **Serialised episodes:** criteria 6, 7 and 10 must each be >= 8.

## 5. Corrections by criterion
| Criterion | Typical fix |
|---|---|
| Narrative relevance | Merge or delete filler scenes; re-read the narration; map every scene to a script line |
| Composition | Re-pick shot from `camera_and_composition.md`; add negative space/foreground; shift subject off centre |
| Atmosphere | Reapply profile palette and grain; remove conflicting effects; add one atmosphere layer only |
| Lighting | Define the motivated source; reduce fill; add temperature contrast |
| Colour consistency | Replace scene palette with bible HEX; reduce saturation; remove extra accents |
| Character consistency | Paste `reference_description`; restore locked traits; reduce face exposure |
| Environment consistency | Redraw from the spatial map; correct left/right of fixed elements |
| Motion quality | Reduce scale delta; remove shake; match ease curves; slow down |
| Visual pacing | Re-time scene lengths to narration; slow tense beats; shorten hooks |
| Episode continuity | Match opening to the previous closing; log changes in the ledger |

## 6. Review report format
```
Episode: <series> #<n>   Stage: storyboard | render
Scores: 1:<> 2:<> 3:<> 4:<> 5:<> 6:<> 7:<> 8:<> 9:<> 10:<>   Average: <>
Automatic failures: none | <list>
Decision: ship | revise | reject
Fixes (ordered): 1) ... 2) ...
```
