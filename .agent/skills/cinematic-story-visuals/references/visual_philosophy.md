# Visual Philosophy

## Contents
1. The governing principle
2. Seven rules
3. The three questions every scene must answer
4. Showing vs withholding
5. Restraint budget for Shorts
6. Renderer realism

## 1. The governing principle
**A scene exists because it contributes to story, atmosphere, character, suspense or emotional impact.** If a scene can be deleted and the narration still lands, it was decoration. Replace it or merge it.

## 2. Seven rules
1. **Narration leads, picture deepens.** The image never contradicts the narration and never depicts events the script did not state.
2. **Specific beats generic.** "A cracked green vinyl seat with taped repairs" beats "an old bus." Specific objects make a place feel lived in and make consistency checkable.
3. **Consistency is a feature.** The same character, place and palette recurring is what makes a series feel produced rather than generated.
4. **Withhold deliberately.** Decide what the audience must not see (a face, the story's content, the monster) and write it down in `hidden_or_withheld`.
5. **One idea per frame.** One subject, one source of tension, one focal point.
6. **Movement is a verb.** Camera movement is an action with a reason (approach, retreat, realise, search). If you cannot state the reason, use a static frame.
7. **Escalate by tightening, not by adding.** Raise tension by narrowing the frame, lengthening stillness or removing light, not by adding effects.

## 3. The three questions every scene must answer
1. **What does the audience need to feel right now?** (curiosity, unease, dread, grief, relief)
2. **What single image delivers that feeling?** (an empty seat, a dark doorway, a hand on a table)
3. **What is the cheapest way to render it in the available renderer?** (layered CSS, SVG silhouette, supplied still, canvas particles)

If question 3 contradicts question 2, change the image, not the feeling.

## 4. Showing vs withholding
| Show | Withhold |
|---|---|
| Spaces, objects, reactions, consequences | The thing itself (entity, story content, culprit) |
| Evidence the audience can inspect | Faces of key unknowns until the reveal |
| Partial views and silhouettes | Complete explanations |

Dread lives in the gap between what is implied and what is confirmed.

## 5. Restraint budget for Shorts
Vertical Shorts run 30-60 s. A reasonable budget is 6-12 scenes for 45 s (3-7 s each). Per scene: one camera move or none, at most two atmospheric layers, at most one hero effect (a lighting shift, a rack focus, a reveal). If a scene needs more than that, it is probably two scenes.

## 6. Renderer realism
Prefer techniques that work in HTML/CSS/JS, canvas or SVG with FFmpeg assembly: layered images with parallax, CSS filters (blur, contrast, brightness), gradient light cones, animated noise for grain, particle systems for dust and rain, slow `transform: scale()` zooms. Never assume image-generation, video-generation or paid APIs. See `transitions_and_motion.md` for the capability ladder.
