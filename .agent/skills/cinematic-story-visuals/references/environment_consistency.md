# Environment Consistency

## Contents
1. Principle
2. Location record
3. Spatial map
4. Variants
5. Fixed elements and continuity locks
6. Establishing a place once, then trusting it
7. Reuse strategies by renderer capability
8. Validation

## 1. Principle
A location is a **space**, not a mood. Define its geometry, fixed objects and light so every scene in it feels like the same place, from any angle.

## 2. Location record
See `../templates/location_sheet_template.md`. Required: `location_id`, `name`, `description`, `architecture_and_layout`, `variants`, `continuity_locks`. Optional: `fixed_elements`, `recurring_objects`, `script_specified`.

## 3. Spatial map
Write the room as a map: where the door, window, table, light and key objects are (left/right/near/far relative to a stated camera position). Example: "Doorway is always on the **right** of the table when the camera faces the table from the kitchen entrance." Every shot must be derivable from this map.

## 4. Variants
A variant is a place at a specific time, weather and era (`afternoon_memory`, `present_night`). Variants change light, weather and atmosphere, **not geometry or fixed elements**. Add a variant instead of altering the base description.

## 5. Fixed elements and continuity locks
- Fixed elements: objects that never move (lamp, window, post).
- Continuity locks: one-line rules the validator and reviewer check (e.g., "Seats are always muted green vinyl.").
- Movable props must have a documented state per scene when they matter.

## 6. Establishing a place once, then trusting it
Show an `establishing` or `wide` shot the first time a location appears. Later shots may be tighter because the audience has the map. In every episode, reintroduce a location with one wide frame before close-ups if more than one scene has passed since it was last seen.

## 7. Reuse strategies by renderer capability
| Capability | Strategy |
|---|---|
| Supplied/generated stills | Create 1 master wide per variant and derive crops/pans from it |
| Layered images | Separate background / midground / foreground plates reused across shots |
| SVG / CSS | One reusable scene component per location; change camera transform, not layout |
| Procedural only | Define the location as a layout constant and render from camera parameters |

## 8. Validation
Fail if a scene's `location_id`/`variant_id` is unknown, if fixed elements switch sides, or if palette values leave the variant's range without a script reason.
