# Example: Psychological Horror - "The Story on the Bus"

## Contents
1. Premise (as given, nothing added)
2. Profile and bible summary
3. Character reference records
4. Location reference records
5. Three-episode arc and continuity ledger
6. Scene breakdown for Episode 2 (summary)
7. Camera and lighting instructions
8. Example visual prompts
9. Continuity across episodes
10. Notes on what is withheld

Full machine-readable files: [`visual_bible_example.json`](visual_bible_example.json) and [`episode_storyboard_example.json`](episode_storyboard_example.json) (validated by `../scripts/validate.py skill`).

## 1. Premise
A first-person psychological horror story about a man who, as a child, misses a terrifying story told on a school bus. Years later, he discovers that the children who heard it believed the story predicted their deaths. His childhood friend refuses to reveal it, even decades later, because he believes telling the man would cause his death. Eventually the protagonist overhears the story and discovers that the prediction was about him. The ending preserves dread and inevitability.

No other events, characters or twists are added. Names ("Daniel", "Marcus"), clothing, and room layouts are **assumptions** used for visual coherence and must be replaced by script facts when available.

## 2. Profile and bible summary
- Profile A: Psychological Horror; palette "Bus-Window Grey" (`#0B0F12`, `#1B2429`, `#3A4A4F`, `#6F7F84`, `#A9B4B0`, green `#5B6B58`, practical `#C9B27A`).
- Narrator is first-person and **never shown face-on**.
- The story itself is **never visualised**.
- Motifs: empty seat, backs of heads, threshold.

## 3. Character reference records
| ID / state | Reference description (canonical) |
|---|---|
| `char_narrator` / `narrator_adult` | A man of about 41, average height and lean, short dark hair greying at the temples, steel wristwatch on his left wrist, charcoal wool overcoat over a dark grey sweater; shown from behind, in profile shadow, or as a silhouette. |
| `char_narrator` / `narrator_child` | A thin boy of about nine with short, slightly uneven dark hair, navy hooded jacket, worn backpack hanging from one strap; seen from behind or at a distance. |
| `char_friend` / `friend_child` | A slightly stocky boy of about nine with short sandy-brown hair, serious round face, green knitted scarf, grey zip-up jacket. |
| `char_friend` / `friend_adult` | A solid man of about 41 with short receding sandy-brown hair, lined round face, dark muted-green scarf (echo of the childhood scarf), grey wool cardigan. |
| `char_bus_children` / `bus_children_child` | Anonymous cluster of school children, backs of heads and silhouettes only. |

Echo traits: the green scarf links friend child and adult; the narrator's hair colour and jacket/coat darkness link his states.

## 4. Location reference records
| ID | Variants | Fixed elements |
|---|---|---|
| `loc_school_bus` | `afternoon_memory`, `dusk_memory` | muted-green vinyl seats with taped cracks, central aisle toward rear, tall dusty windows |
| `loc_bus_route_road` | `childhood_dusk_fog`, `present_overcast` | road bends away; bus-stop post left; tree line right |
| `loc_friend_home` | `present_evening_lamp` | small wooden table, one hanging lamp, doorway to dark hallway **on the right** |
| `loc_overhearing_space` | `present_night` | narrow hallway ending in a partly open door with a vertical light strip |

## 5. Three-episode arc and continuity ledger
| Ep | Title | Content (premise only) | Opening visual | Closing visual |
|---|---|---|---|---|
| 1 | The Missed Story | The child misses the story; years later he learns the children believed it predicted their deaths | Cold open: the empty bus seat (`motif_empty_seat`) | Narrator, back to camera, on the empty road in overcast mist |
| 2 | The Refusal | The friend refuses to tell him, believing telling would cause his death | Same road, same posture (match to Ep 1 close) | Friend motionless under the lamp; dark doorway at right |
| 3 | What the Doorway Heard | He overhears the story and learns it concerned him | The dark doorway becomes the narrow light strip | Held wide of the narrator at the threshold; dip to black; consequence never shown |

Ledger entries for episodes 1 and 2 are stored in the bible JSON.

## 6. Scene breakdown for Episode 2 (summary)
| Scene | Time | Narration (abridged) | Purpose | Shot / movement | Tension |
|---|---|---|---|---|---|
| s01 | 0-5 | I went back to the one person... | Continue from Ep 1 | Wide, barely perceptible push-in | 3 |
| s02 | 5-11 | Marcus never mentioned that day... | Introduce silence | OTS, static | 4 |
| s03 | 11-17 | He was there. I wasn't. | Exclusion memory | Wide, empty seat foreground | 4 |
| s04 | 17-24 | I asked him. He said no. | First refusal | Medium close, slow push | 5 |
| s05 | 24-31 | It would kill me. | Central statement | ECU hands, static | 7 |
| s06 | 31-38 | Decades later... | Distance between men | Wide, slow pull-out | 6 |
| s07 | 38-46 | He kept his silence... | Hold dread; hand off | Wide, static, lamp dims | 8 |

Seven scenes for 46 s: scene boundaries follow idea changes (road, kitchen, memory, refusal), not sentences.

## 7. Camera and lighting instructions
- Kitchen: one warm lamp (3000K practical), cool ambient (6500K), high contrast, deep shadows, no fill light on faces.
- Bus memory: lower contrast, warmer-neutral window light, dust in light shafts, long lens compression.
- Road: flat overcast, low contrast, mist as the only motion.
- Movement: static or barely perceptible push; no shake; the strongest moment (s05) is **fully static**.

## 8. Example visual prompts
**Bus memory (cinematic scene):**
`View down a school bus aisle from the front, green vinyl seats with taped cracks, an empty seat in soft foreground, several rows back a huddle of children seen only from behind in muted dark jackets, one child in a green knitted scarf, low afternoon sunlight through dusty windows, desaturated blue-grey and charcoal with muted green, subtle film grain, long-lens compression, still and quiet.`
Negative: `faces, visible eyes, text, gore, ghosts, monsters, red lighting, bright colours, cartoon style, extra adults`

**Kitchen close-up (hands):**
`Extreme close-up of a middle-aged man's hands resting on a worn wooden kitchen table, fingers pressed together, single warm overhead lamp, deep black surround, shallow depth of field, muted desaturated colours, fine film grain.`
Negative: `face, blood, gore, red lighting, bright colours, text, extra hands`

**Threshold (Ep 3 reference):**
`Narrow hallway at night seen from behind a man in a charcoal overcoat, ending at a partly open door with a thin vertical strip of warm light, cold dark walls, large empty space, desaturated blue-grey palette, subtle grain, silent and still.`
Negative: `face, monsters, ghosts, red lighting, text, bright light`

## 9. Continuity across episodes
- The **same** muted green appears in bus seats, friend's scarf and foliage.
- The doorway is always on the **right** of the table; it becomes the light-strip threshold in Ep 3 (`obj_doorway_light`).
- The road has the same bend, post and tree line in Ep 1 and Ep 2.
- The narrator's face is never shown in any episode; his coat and watch remain constant.
- Ledger: Ep 1 closes on the road; Ep 2 opens on the identical frame.

## 10. Notes on what is withheld
The story's words and the prediction are never visualised. In Ep 3 the audience sees the narrator's stillness at the threshold, never the consequence. Dread and inevitability come from the held composition and the dark.
