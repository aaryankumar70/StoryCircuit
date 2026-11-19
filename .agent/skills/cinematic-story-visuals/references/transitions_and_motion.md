# Transitions and Motion

## Contents
1. Principles for vertical Shorts
2. Capability ladder (what the renderer can probably do)
3. Motion toolkit
4. Transition catalogue
5. Pacing responding to narration and suspense
6. Stillness
7. Implementation recipes (HTML/CSS/JS + FFmpeg)
8. Performance and safety

## 1. Principles
- Movement is a verb with a reason. Static is a valid, often stronger choice.
- Escalate pacing with narration: slower and stiller as dread rises; faster only for realisation or release.
- Keep motion legible on a phone: subtle changes must still read at small size.
- Avoid constant motion; the eye needs rest.

## 2. Capability ladder
Inspect the repository and choose the highest rung that is already available. Never add a rung that needs new paid APIs.
1. **Static stills** (given or generated) with `transform` zoom/pan.
2. **Layered plates** (background/mid/foreground) with parallax.
3. **CSS/SVG overlays**: gradients, vignette, grain, light cones, fog layers.
4. **Canvas particles**: dust, rain, snow, embers.
5. **Procedural scenes**: SVG/CSS-drawn silhouettes and environments.
6. **Video clips / generated video** (only if already supported; never assume).
If a scene calls for something above the ladder, simplify the scene.

## 3. Motion toolkit
| Effect | Parameters | Typical use |
|---|---|---|
| Slow zoom (push/pull) | scale delta 0.03-0.08 over 4-7 s, ease-in-out | Default life in a still |
| Pan | <= 8% width, linear or ease | Following, reading maps |
| Parallax | factors: bg 0.1, mid 0.4, fg 1.0 (relative offsets) | Depth for layered plates |
| Fog/mist | slow lateral drift 0.5-2 px/s at 1080 width, 10-30% opacity | Depth, mood |
| Rain | angled streaks, 2-3 density levels, low opacity | Only when scripted |
| Dust | slow floating specks in light cones, 5-15 particles | Light shafts, memory scenes |
| Light flicker/dim | opacity change 5-15% over 2-5 s | Dread, failing practical |
| Focus change | blur radius 0 <-> 6px over 0.6-1.2 s | Reveals |
| Micro-drift | <= 0.3% jitter | Final panic only |

## 4. Transition catalogue (`transition_out.type`)
| Type | Duration | Use |
|---|---|---|
| `hard_cut` | 0 ms | Default; impact, rhythm, return from memory |
| `slow_dissolve` | 800-1500 ms | Time passage, place change, softness |
| `dip_to_black` | 1000-1800 ms | Episode end, shock beat, breath |
| `match_cut` | 0 ms | Shapes/positions echo across scenes (doorway to light strip) |
| `fog_wipe` | 600-1200 ms | Atmospheric transitions where fog is established |
| `focus_pull` | 600-1000 ms | Reveals, shifting attention |
| `light_shift` | 500-1200 ms | A lamp dims or turns on, linking scenes |
| `sound_bridge_cut` | 0 ms | Cut mid-line so audio carries across; visual shifts |
Do not use wipes, spins or flashy transitions. Limit non-cut transitions to <= 40% of scenes.

## 5. Pacing responding to narration and suspense
| Tension 0-3 | 4-6 | 7-8 | 9-10 |
|---|---|---|---|
| 4-7 s scenes, gentle push-ins | 3.5-6 s, tighter shots | 4-8 s holds, static or barely perceptible | Very short cuts **or** one long hold; never a mix of both |
Rule: **a disturbing line is often best on a static frame**; save movement for before and after it.

## 6. Stillness
Intentional stillness is expressed with `camera_movement.type: static` and `motion.stillness_is_intentional: true`. Use it at the worst moment, at the reveal, and at the ending. Minimal environmental motion (dust) is acceptable to keep the image alive.

## 7. Implementation recipes
- **Zoom:** `transform: scale(var(--s0)) -> scale(var(--s1))` with `transition` or Web Animations API; `transform-origin` at focal point.
- **Parallax:** each plate translated by `camera_offset * factor`.
- **Grain:** noise tile with stepped animation (e.g. 12 fps) at 4-8% opacity.
- **Dimming lamp:** animate `opacity` of a warm radial gradient overlay.
- **Dip to black:** a full-frame black layer animating opacity 0 -> 1.
- **Deterministic frames:** drive animations from a timeline (frame number or time) rather than real time so headless capture is reproducible. Avoid `Math.random()` without a fixed seed.
- **FFmpeg:** assemble captured frames at 30 fps; if the pipeline composites clips, use `xfade=transition=fade` for dissolves and `fade=t=out` for dip-to-black.
These are guidance only; adapt to the actual repository.

## 8. Performance and safety
- Respect the repository's rendering budget (resolution, fps, per-scene render time).
- No flashing > 3 times per second (photosensitivity).
- Keep file sizes within upload constraints; avoid heavy blur on full-frame at high resolution.
