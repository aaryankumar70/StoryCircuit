# Lighting and Color

## Contents
1. Principles
2. Lighting styles
3. Colour temperature and contrast
4. Exposure, shadow density and atmospheric depth
5. Palettes by profile (HEX)
6. Consistency rules
7. Implementation notes for web renderers

## 1. Principles
1. Light is motivated: the viewer should be able to point to its source.
2. Contrast directs attention; colour sets mood; both must stay consistent across a series.
3. Restraint: two to four main colours plus one accent per frame.
4. Lighting can carry story: a dimming lamp, a growing shadow, a narrowing light strip.

## 2. Lighting styles (`lighting.style`)
| Style | Look | Use |
|---|---|---|
| `low_key` | Mostly shadow, few highlights | Horror, dread, secrecy |
| `high_key` | Bright, low contrast | Rare; ironic contrast, calm before dread, history daylight |
| `practical` | Light visible in-frame (lamps, windows) | Natural, grounded scenes; warm islands |
| `rim` | Edge light separating subject from background | Silhouettes with shape, depth separation |
| `backlit` | Light behind subject, face dark | Anonymity, threat, memory |
| `volumetric` | Visible light shafts in dust/fog | Atmosphere, depth, reverence; use sparingly |
| `silhouette` | Subject as dark shape against light | Withheld identity, inevitability |
| `ambient` | Soft environmental light | Overcast exteriors, neutral scenes |
| `mixed` | Combination with a declared primary | Complex interiors |

## 3. Colour temperature and contrast
- Cool (6000-7500K, blue-grey): outdoors, institutional, unease. Warm (2700-3200K, amber): lamps, refuge, memory.
- **Temperature contrast** (warm island in cool frame) is the strongest cheap separator.
- Contrast levels: `low` (fog, overcast), `medium` (documentary), `high` (low-key dramatics).
- Avoid complementary extremes (teal vs orange blockbuster look) unless the profile requires it.

## 4. Exposure, shadow density and atmospheric depth
- **Shadow density**: `light` (detail everywhere), `moderate`, `deep` (detail only near light), `crushed` (near-black surround; reserve for peak beats).
- Never crush to pure black (`#000000`); use the profile's deep shadow value.
- **Exposure**: keep highlights below bone-grey in horror; avoid blown whites.
- **Atmospheric depth**: distant elements lighter, lower contrast and slightly bluer (fog colour); foreground darker and sharper.

## 5. Palettes by profile (HEX)
### Psychological Horror - "Bus-Window Grey"
`#0B0F12` shadow, `#1B2429` base, `#3A4A4F` mid, `#6F7F84` fog, `#A9B4B0` highlight, `#5B6B58` green, `#C9B27A` practical.
### Psychological Horror - alternative "Wet Asphalt Night"
`#07090B`, `#151B1F`, `#2B3A40`, `#5A6A70`, `#8FA0A0`, accent `#6E7E5C`, practical `#B8A36B`.
### Mystery / Investigative
`#10151A` ink, `#26323A` slate, `#4B6270` steel, `#CFC6AE` paper, `#B8873B` amber clue, `#3F6B68` teal, `#B9C4C6` highlight.
### Historical (generic, adjust by era; see `historical_visual_language.md`)
`#1D2024` base, `#43494B` mid, `#C8B98E` warm highlight, `#7A5C2E` accent, `#8A8F8C` neutral mid.
### Space / Cosmology (future profile, example)
`#05070D` void, `#101B33` deep blue, `#2E4A7A` nebula blue, `#9DB4D9` starlight, `#E4C98A` warm star, `#5B3F7A` violet accent.

## 6. Consistency rules
- Each location variant lists palette HEX values; scenes use a subset.
- Do not introduce a new accent colour without a script reason; record it in the ledger.
- Match colour temperature across consecutive scenes in the same location and time of day.
- Memory/flashback scenes shift **contrast and softness**, not hue family.

## 7. Implementation notes for web renderers
- Light cones: CSS `radial-gradient` / `conic-gradient` layers with `mix-blend-mode: screen` or `soft-light`.
- Vignette: radial gradient overlay, 15-35% opacity.
- Grain: tiled noise PNG or SVG `feTurbulence`, 4-8% opacity, animated by stepped offset (12 fps) rather than smooth movement.
- Colour grade: CSS `filter: saturate() contrast() brightness()` plus an overlay with `mix-blend-mode: multiply` in the palette base colour.
- Dimming practicals: animate the opacity of the warm gradient layer, not the whole image.
- Respect what the actual renderer supports; see `transitions_and_motion.md`.
