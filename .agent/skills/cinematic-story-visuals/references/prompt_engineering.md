# Visual Prompt Engineering

## Contents
1. When prompts are used
2. Prompt anatomy
3. Style rules
4. Templates
   1. Character reference
   2. Environment reference
   3. Cinematic scene
   4. Establishing shot
   5. Close-up shot
   6. Atmospheric transition shot
   7. Historical scene
   8. Psychological horror scene
5. Negative constraints library
6. Consistency tricks
7. Checklist

## 1. When prompts are used
Only when the pipeline has an image generator, a text-to-image provider already in use, or when a human/agent will create plates by hand. If the renderer is purely procedural, treat these as **art-direction specs** for building SVG/CSS layers. Never make image generation mandatory.

## 2. Prompt anatomy
Order (most important first): **Subject -> Action/state -> Environment -> Composition -> Camera/lens -> Lighting -> Colour -> Atmosphere -> Texture -> Time/era -> Consistency anchors -> Negative constraints.**

## 3. Style rules
- Concrete nouns and verbs; one sentence per idea.
- Avoid adjective stacking ("dark eerie spooky haunting creepy"); choose the single most informative descriptor.
- Name sources of light and the direction of shadow.
- State what is **not** visible when relevant (hidden faces).
- Do not name living artists, copyrighted characters or specific films.
- Paste canonical `reference_description` text for characters; paste location `description` + `fixed_elements` for places.

## 4. Templates
Placeholders in `<angle brackets>`.

### 4.1 Character reference
```
Character reference sheet of <reference_description>, <pose: neutral standing / three-quarter back / profile>, plain muted charcoal background, soft even studio-like light for readability, full body and upper body views, consistent proportions, <palette colours for clothing>, realistic, fine detail on <locked_traits>.
Negative: extra people, text, logos, exaggerated features, glamour lighting, changed clothing, red lighting.
```

### 4.2 Environment reference
```
Empty <location name>, <description>, <fixed_elements>, camera at <position> facing <direction>, <time of day> light from <source>, <weather/atmosphere>, palette <HEX list>, wide establishing view, no people, realistic, high detail on <key objects>.
Negative: people, text, brand logos, anachronistic objects, bright saturated colours.
```

### 4.3 Cinematic scene
```
<Subject and action>, in <location + variant>, <composition: negative space / foreground framing / leading lines>, <shot type> at <angle>, <lens feel>, lit by <motivated key light> with <cool/warm fill>, palette <HEX>, <atmosphere>, <texture: subtle film grain>, <era>, <consistency anchors>.
Negative: <library below>
```

### 4.4 Establishing shot
```
Wide establishing view of <location + variant>, <time/weather>, <depth layers: foreground / midground / background>, <leading line>, subject small in frame or absent, <light source>, palette <HEX>, subtle atmospheric depth, realistic, calm and still.
Negative: close-ups, extra characters, text, dramatic lens flare.
```

### 4.5 Close-up shot
```
Close-up of <object or body part>, <specific detail: wood grain / taped crack / wristwatch>, shallow depth of field, single motivated light from <direction>, deep shadow surround, palette <HEX>, subtle grain, nothing else in frame.
Negative: faces (unless required), blood, gore, text, bright colours.
```

### 4.6 Atmospheric transition shot
```
<Fog / rain on glass / empty corridor / slow light on a wall>, abstract-leaning but realistic, no characters, <motion implied: drifting / dripping>, soft focus, palette <HEX>, designed as a quiet breath between scenes.
Negative: characters, text, creatures, bright highlights.
```

### 4.7 Historical scene
```
<Subject> in <place, year>, <period clothing and objects per research list>, <architecture>, <period light source: candle / oil lamp / daylight>, documentary composition, <shot type>, palette <era HEX>, soft grain, historically accurate, no modern objects.
Negative: anachronisms, modern buildings, plastic, zippers, wires, fantasy armour, neon, text overlays.
```

### 4.8 Psychological horror scene
```
<Ordinary place made wrong by one detail>, <subject small or turned away>, large negative space, <doorway/window frame>, low-key lighting from <single motivated source>, desaturated blue-grey and charcoal with muted green, one dim warm practical light, subtle film grain, <fog or dust if justified>, still and quiet, withholding: <hidden element>.
Negative: monsters, ghosts, glowing eyes, blood, gore, red lighting, jump scare, cartoon style, bright colours, text.
```

## 5. Negative constraints library
- Universal: `text, watermark, logo, extra fingers, distorted face, duplicate person, cartoon style, overexposed`
- Horror: `monster, ghost, glowing eyes, blood, gore, red lighting, jump scare, haunted-house cliche, bright saturated colours`
- Mystery: `gibberish text, fake logos, conspiracy-wall cliche, trench coat cliche`
- Historical: `anachronism, modern objects, plastic, neon, wires, fantasy costume`
- Character consistency: `different hairstyle, different clothing, glasses (if not locked), age change`

## 6. Consistency tricks
- Reuse the same seed and reference image when supported.
- Generate a **master wide** per location variant, then derive close-ups via crops or image-to-image.
- Keep a prompt prefix per character and per location (`reference_description`, `description`).
- Keep palette HEX in every prompt.
- For identical framing across episodes, reuse the same composition line.

## 7. Checklist
- [ ] Subject, environment, composition, camera, lighting, colour, atmosphere, texture, time, consistency, negatives all present
- [ ] No adjective stacking
- [ ] No unapproved characters or events
- [ ] Hidden elements stated
- [ ] Prompt matches the scene's narration
