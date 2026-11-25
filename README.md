# StoryCircuit — Zero-Cost Scene-Matched YouTube Shorts Studio

A lean, CPU-friendly (`1080×1920`, FFmpeg + Python) studio built to produce **2 original Shorts per day** at **₹0 / $0 cost** without repetitive templates or dialogue–visual mismatches.

## Key Features
- **3 Workflow Modes:**
  1. **Auto / Random Topics:** Pulls fresh topics (Wikipedia + curated seeds + local Ollama `qwen2.5:3b-instruct` or optional Gemini free tier) with **SQLite n-gram & keyword deduplication** so stories never repeat.
  2. **Custom Multi-Day Plan:** Schedule topics, visual styles, and optional scripts into `(date, slot 1|2)` ahead of time.
  3. **Custom Scripts:** Paste your own narration or `[Alex]:` / `[Maya]:` two-voice dialogue; your exact words are preserved and matched beat-by-beat with visuals.
- **Dialogue-Matched Visuals (Anti-Template):**
  - Rotates 5 distinct cohesive art styles (`editorial_dark`, `vintage_archival`, `graphic_noir`, `cinematic_painterly`, `blueprint_tech`).
  - Resolves every beat individually via **Pollinations AI** (no key), **Wikimedia Commons / NASA archival photos** (no key), or **pure-Python Pillow editorial/stat cards** (offline fallback).
- **Fast CPU Rendering + Deterministic QC:**
  - Native FFmpeg Ken Burns motion (`zoompan`), ducked copyright-free ambient underscore, and word-synced `.ass` captions in the Shorts safe zone (`Edge-TTS` WordBoundary timestamps).
  - Verifies 1080×1920, H.264/AAC, `ebur128` loudness, no black gaps, and no frozen scenes before queuing for upload.
- **Direct YouTube Upload & 2/Day Scheduler:**
  - Safe defaults: `YOUTUBE_PUBLISHING_MODE=simulation`, `YOUTUBE_PRIVACY_STATUS=private`.

## Quick Start
```bash
cd /home/ryu/Projects/storycircuit
cp .env.example .env

# Start Web Dashboard (http://127.0.0.1:8080)
./start_dashboard.sh
# or: .venv/bin/python -m reelforge web

# Or generate one Short directly from CLI
.venv/bin/python -m reelforge generate --mode random

# Authorize YouTube OAuth when ready for live uploads
.venv/bin/python scripts/auth_youtube.py
```

## OAuth Branding Website (`docs/`)
Static public pages for the Google OAuth consent screen (`GitHub Pages` branch `main`, folder `/docs`):
- **Homepage:** `docs/index.html` ([https://aaryankumar70.github.io/StoryCircuit/](https://aaryankumar70.github.io/StoryCircuit/))
- **Privacy Policy:** `docs/privacy.html` ([https://aaryankumar70.github.io/StoryCircuit/privacy.html](https://aaryankumar70.github.io/StoryCircuit/privacy.html))
