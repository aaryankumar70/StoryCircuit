# CurioLoop Script Engine & Editorial System Audit

**Date:** 2026-11-17  
**System:** CurioLoop / StoryCircuit Autonomous Production Studio  
**Branch:** `feature/editorial-transformation`  
**Purpose:** Pre-implementation architectural audit for Viral Shorts Scriptwriter integration and three-category editorial transformation (`MYSTERY`, `HISTORY`, `SPACE`).

---

## 1. Executive Summary & Calibration

CurioLoop's production engine (Kokoro-82M ONNX TTS, faster-whisper word alignment, HTML/CSS/Canvas/WebGL visual scenes, headless Chrome capture, FFmpeg assembly, QC gate, local database, and Windows watchdog) is operating reliably.

However, the editorial layer currently suffers from:
1. **Unfocused / Disallowed Categories:** Topic discovery and fallback catalogs contain generic biology, animal trivia, and science-facts (e.g. `bio_silence_ringing`, `bio_greenland_shark`, `psych_invisible_gorilla`).
2. **Global Space Bans in Original Skill:** The standalone `viral-shorts-scriptwriter` skill included `space_and_astronomy`, `galaxy`, `black hole`, `neutron star`, and `planet` in its deny lists, directly contradicting CurioLoop's editorial mandate.
3. **Missing Pre-Script Research Layer:** Generation was previously relying directly on LLM knowledge or raw Reddit prompts without a structured, verifiable research dossier.
4. **Lack of Independent Story Critique:** Scripts were directly scored on heuristic heuristics rather than through an adversarial, multi-dimensional story critic with bounded targeted revisions.

### Empirical Speech Rate Calibration
From 8 actual finished production videos in `output/`:
| Production Video | Spoken Words | Audio Duration (s) | Measured Rate (WPS) |
|---|---|---|---|
| `video_20261109_slot1` | 68 | 29.92s | 2.273 |
| `video_20261112_slot1` | 132 | 49.34s | 2.676 |
| `video_20261112_slot2` | 114 | 47.28s | 2.411 |
| `video_20261114_slot1` | 115 | 47.61s | 2.415 |
| `video_20261114_slot2` | 122 | 50.78s | 2.402 |
| `video_20261116_slot1` | 114 | 45.00s | 2.533 |
| `video_20261117_slot1` | 114 | 45.00s | 2.533 |
| `video_20261117_slot2` | 119 | 49.35s | 2.411 |

- **Empirical Average:** **2.457 words per second** (Calibrated standard: `2.46 WPS`).
- **Target Duration (42s–58s):** **103 to 142 spoken words**.
- **Technical Range (40s–60s):** **98 to 147 spoken words** (accounting for sentence pauses: ~90–145 words).

---

## 2. File-Level Component Map

| Component / Subsystem | Current File(s) | Role & Downstream Interface | Current Status | Planned Action |
|---|---|---|---|---|
| **Topic Discovery** | `curiosity_engine/content/topic_discovery.py` | Discovers daily topics across pillars; checks recent topic collisions. | **Partial** (allows Science, Biology, Psychology, Nature) | Restrict discovery strictly to `MYSTERY`, `HISTORY`, `SPACE`. Implement 10-dimension story potential scoring. |
| **Reddit Seed Discovery** | `curiosity_engine/content/reddit_discovery.py` | Pulls public Reddit discussion angles (r/science, r/psychology, etc.). | **Partial** (includes biology/science subs) | Remove science/biology subreddits; retain r/UnresolvedMysteries, r/AskHistorians, r/space. Enforce non-evidence signal rule. |
| **Curated Fallback Catalog** | `curiosity_engine/content/curated_fallback.py` | 12 hardcoded stories used when offline or Gemini API unconfigured. | **Partial** (contains biology/nature entries) | Archive biology/nature stories to `curated_archive.py`. Replace with 30+ verified story dossiers (10+ Mystery, 10+ History, 10+ Space). |
| **Central Editorial Policy** | *None* (scattered in `config.py`) | Defines category boundaries, banned terms, allowed niches. | **Missing** | Create `curiosity_engine/content/editorial_policy.py` with contextual validation for `MYSTERY`, `HISTORY`, `SPACE`. |
| **Research Dossier** | *None* | Constructs verified claim hierarchies, sources, uncertainties before writing. | **Missing** | Create `curiosity_engine/content/research_dossier.py` establishing structured research dossiers. |
| **Narrative Engine & Hooks** | *Embedded in `scriptwriter.py`* | Generates hooks, outlines, and beat sequences. | **Partial** (only 1 hook generated) | Create `curiosity_engine/content/narrative_engine.py` with 8 candidate hooks, hook playbook evaluation, and 5-beat documentary arc. |
| **Story Critic** | *None* (only basic regex scoring) | Evaluates drafts on 10 criteria (1-10) and orders targeted rewrites. | **Missing** | Create `curiosity_engine/content/story_critic.py` (strict thresholds: factual >= 8, overall >= 8, max 3 Gemini calls). |
| **Deterministic Validator** | Skill's `validate_script.py` | Evaluates duration, hook length, banned openers, pacing, loop ending. | **Partial** (original skill banned Space/Astronomy) | Create `curiosity_engine/quality/script_validator.py` adapting skill validator with contextual space support and dossier verification. |
| **Scriptwriting Orchestration** | `curiosity_engine/content/scriptwriter.py` | Top-level script generator and QC duration reviser. | **Implemented** | Upgrade to drive the new editorial pipeline: Discovery -> Category Check -> Dossier -> Hooks -> Outline -> Draft -> Critic -> Validator. |
| **Downstream TTS Engine** | `curiosity_engine/production/tts_engine.py` | Consumes `script.json` (`lines[].text`, `lines[].gap`, `voice`, `speed`). | **Implemented** | **Preserve exactly.** Ensure script output preserves existing schema with additive metadata. |
| **Visual Alignment** | `curiosity_engine/production/aligner.py` | Runs faster-whisper on `narration.wav` to create `words.json`. | **Implemented** | **Preserve exactly.** |
| **Visual Scene Choreography** | `curiosity_engine/production/director.py` | Copies style template, writes `script.json`, launches TTS/aligner. | **Implemented** | **Preserve exactly.** |
| **Visual Templates** | `templates/{inside-out, paper-atlas, stick-story}` | Web templates rendered via Chrome and FFmpeg. | **Implemented** | **Preserve all 3 styles.** Route `MYSTERY`, `HISTORY`, `SPACE` appropriately across all three styles. |
| **Video QC Gatekeeper** | `curiosity_engine/quality/qc_gatekeeper.py` | Validates rendered MP4, duration (20-60s), visual checks, audio LUFS. | **Implemented** | **Preserve exactly.** |
| **Production Pipeline** | `curiosity_engine/runner/pipeline.py` | Orchestrates single video production and QC recovery. | **Implemented** | Integrate deterministic script validator check before TTS stage. |

---

## 3. Biology & Science Leak Audit

We audited every entry point where forbidden biology, animal trivia, or generic science facts could leak into production:

1. **`curiosity_engine/config.py`**:
   - `CONTENT_PILLARS`: Currently includes `"Science"`, `"Biology"`, `"Nature"`, `"Psychology"`, `"Human behavior"`.
   - *Fix:* Restrict to `"Mysteries"`, `"History"`, `"Space"`.
2. **`curiosity_engine/content/reddit_discovery.py`**:
   - `CURATED_SUBREDDITS`: Currently queries `r/science`, `r/psychology`, `r/Damnthatsinteresting`.
   - *Fix:* Remove these subreddits; retain only `r/UnresolvedMysteries`, `r/AskHistorians`, `r/space`. Filter titles against `discovery_keyword_denylist`.
3. **`curiosity_engine/content/curated_fallback.py`**:
   - Items 0, 7, 10 (`bio_silence_ringing`, `bio_greenland_shark`, `psych_invisible_gorilla`) are pure biology/animal trivia.
   - *Fix:* Move these to `curated_archive.py`. Build 30+ new verified story dossiers strictly within Mystery, History, Space.
4. **`curiosity_engine/content/topic_discovery.py`**:
   - `generate_candidate_topics` prompt currently mentions "psychological/behavioral phenomena" and "breakthroughs in science".
   - *Fix:* Reword prompt to mandate `MYSTERY`, `HISTORY`, or `SPACE` only. Add pre-production category validation gate.
5. **`curiosity_engine/content/scriptwriter.py`**:
   - Scene keyword inference currently looks for "brain", "neuron", "blood", "cell".
   - *Fix:* Clean up to prioritize historical, cosmic, and mysterious scene mapping without removing visual rendering capabilities.

---

## 4. Visual Style Mapping Preservation

The project contains three visual styles:
- `inside-out`: High-tech schematic / conceptual visualizer with radar scans, meter surges, and neural/cosmic pulses.
- `paper-atlas`: Archival parchment, vintage expedition maps, historical documents, and navigational lines.
- `stick-story`: Dynamic character-driven vignettes, situational storytelling, and tension rooms.

**Preservation Strategy:**
- Do NOT delete any visual style.
- Route categories appropriately:
  - `MYSTERY`: `paper-atlas` (unresolved expeditions, lost cities), `stick-story` (survivors, witnesses), or `inside-out` (cryptographic anomalies, enigmatic artifacts).
  - `HISTORY`: `paper-atlas` (empires, ancient technology), `stick-story` (historical personalities, turning points).
  - `SPACE`: `inside-out` (black holes, cosmic bursts, exoplanet telemetry), `stick-story` (astronaut experiences, mission control), `paper-atlas` (astronomical discovery history).

---

## 5. Implementation Roadmap

1. **Phase 1: Editorial Policy & Configuration**
   - Create `curiosity_engine/content/editorial_policy.py`.
   - Implement contextual category classification (allowing narrative Space; rejecting biology/trivia).
   - Calibrate speech rate to 2.46 WPS.
2. **Phase 2: Research Dossier Engine**
   - Create `curiosity_engine/content/research_dossier.py` with structured claims, source hierarchy, and verification rules.
3. **Phase 3: Narrative Engine & Hooks**
   - Create `curiosity_engine/content/narrative_engine.py` with 8 candidate hook generator and 5-beat documentary arc.
4. **Phase 4: Story Critic & Deterministic Validator**
   - Create `curiosity_engine/content/story_critic.py` (10 dimensions, strict thresholds, max 3 Gemini calls).
   - Create `curiosity_engine/quality/script_validator.py` with contextual category validation and claim verification.
5. **Phase 5: Catalog Overhaul & Pipeline Integration**
   - Archive old biology topics to `curiosity_engine/content/curated_archive.py`.
   - Expand `curiosity_engine/content/curated_fallback.py` to 30+ verified story dossiers (10 Mystery, 10 History, 10 Space).
   - Update `topic_discovery.py`, `reddit_discovery.py`, and `scriptwriter.py`.
   - Wire deterministic validator gate into `pipeline.py`.
6. **Phase 6: Verification & Isolated Evaluation Set**
   - Add unit and integration tests in `tests/test_viral_scriptwriter.py`.
   - Run full 154+ pytest suite.
   - Generate 10 evaluation scripts in `output/editorial_eval/` (3 Mystery, 3 History, 4 Space).
   - Compile Final Engineering Report.
