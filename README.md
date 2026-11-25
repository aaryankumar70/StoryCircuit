# StoryCircuit — Autonomous YouTube Shorts & Auto-Landscape Video Studio

**StoryCircuit (`reelforge`)** is a local-first, zero-cost (`₹0 / $0`) YouTube automation studio built in Python and FFmpeg. It is designed to produce **2 original, scene-matched videos per day**, verify broadcast quality with deterministic QC, **upload and schedule them automatically on YouTube**, and clean up ended-day media files automatically.

---

## Key Capabilities

- **One-Click Daily 2-Video Workflow (`Generate Today's 2 Videos`)**
  - Pulls queued items from your **Custom Total Plan** first, or discovers fresh AI topics via **LLM + Wikipedia + 30 curated seeds** for any unfilled slot.
  - Automatically renders, runs QC, and uploads/schedules Slot 1 (`12:30` IST by default) and Slot 2 (`20:30` IST by default) on YouTube. If a slot's time already passed today, it schedules cleanly ahead (`now + 20m` / `+65m`) so videos never stay stuck private.
- **Strict Anti-Repeat Protection**
  - Logs every QC-passed title and script into SQLite (`topic_history`) and blocks duplicates using normalized title matching, keyword Jaccard overlap, and 3-gram narrative similarity (`reelforge/storage/dedup.py`)—with up to 3 automatic retries if an AI topic collides with history.
- **Custom Total Plan (Multi-Day + Custom Times + Custom Scripts)**
  - Plan upcoming dates with custom publish times (`HH:MM`), slots (`1` or `2`), categories, visual styles, and optional custom scripts (supporting single-narrator or `[Alex]:` / `[Maya]:` two-voice dialogue).
- **Smart Long-Script Splitter (`> 1 min` and `< 2 min` Shorts)**
  - Paste any long script in the **Script Splitter (1–2m)** tab (or `POST /api/scripts/analyze`). StoryCircuit estimates total Edge-TTS duration, calculates the **exact number of balanced 1-to-2-minute Shorts** (`62s–114s` each) that can be made, splits cleanly at paragraph/sentence/speaker boundaries, generates SEO titles, descriptions, and tags for each part, and lets you queue all parts across future days in one click.
- **Zero Duration Failures & Auto-Landscape (`> 2 min` → `16:9`)**
  - **≤ 120 seconds (2 min):** Rendered as vertical `9:16` (`1080×1920`) YouTube Shorts with Shorts-safe animated `.ass` captions (`MarginV=410`) and `#Shorts` metadata.
  - **> 120 seconds (> 2 min):** Automatically converted to **landscape `16:9` (`1920×1080`)** long-format YouTube videos with widescreen visuals, bottom cinematic captions (`MarginV=72`), automatic `MM:SS` YouTube chapters, `1920×1080` QC up to `3600s`, and standard `youtube.com/watch?v=...` publishing (without `#Shorts`).
- **End-of-Day Garbage Remover**
  - Automatically deletes rendered video folders from ended days (`job_date < today` in `SCHEDULER_TIMEZONE`) on startup, at midnight rollover, and before daily cycles—freeing disk space while preserving archive metadata and `topic_history` so anti-repeat never resets.
- **Dialogue-Matched Visuals & Original Audio**
  - Rotates 5 visual styles (`editorial_dark`, `vintage_archival`, `graphic_noir`, `cinematic_painterly`, `blueprint_tech`).
  - Resolves every beat individually via **Pollinations AI** (no API key), **Wikimedia Commons / NASA archival photos**, or **pure-Python Pillow editorial/stat cards** (guaranteed offline fallback).
  - Synthesizes narration per beat via **Edge-TTS** (`WordBoundary` word-level timing, with `espeak-ng` fallback) mixed with a copyright-free NumPy ambient underscore (or custom tracks placed in `assets/music/`).
- **SEO Titles, Descriptions, Tags & Broadcast QC**
  - Generates curiosity-driven titles, structured descriptions (highlights or chapters + engagement CTA), and 10–15 tags capped safely inside YouTube's 500-character limit (`reelforge/brain/metadata.py`).
  - Verifies stream codecs (`H.264` / `AAC`), resolution (`1080×1920` or `1920×1080`), integrated loudness (`-24` to `-11 LUFS` with `alimiter` peak guard `<= 0 dBFS`), black-gap detection, freeze detection, and caption end bounds (`reelforge/qc/gatekeeper.py`).

---

## Project Structure

```text
.
├── reelforge/
│   ├── config.py                # Central env configuration & OAuth client_secret loader
│   ├── models.py                # StoryPlan, BeatSpec, VideoFormat (short/long), VisualStyle
│   ├── pipeline.py              # End-to-end render + auto 16:9 switch + QC pipeline
│   ├── progress.py              # Real-time stage pips & daily progress summaries
│   ├── cli.py                   # CLI entrypoints (`python -m reelforge ...`)
│   ├── audio/
│   │   ├── tts.py               # Single-loop Edge-TTS batching + WordBoundary + espeak fallback
│   │   └── underscore.py        # Copyright-free NumPy ambient pad & custom music mixer
│   ├── brain/
│   │   ├── director.py          # Storyboard & visual cue director (Random / Plan / Custom)
│   │   ├── llm_client.py        # Gemini Free Tier + local Ollama JSON client
│   │   ├── metadata.py          # SEO titles, chapters, descriptions & 500-char tag budget
│   │   ├── splitter.py          # Balanced 1-to-2-minute Shorts splitter & estimator
│   │   └── topic_pool.py        # AI + Wikipedia + 30 curated non-repeating topic seeds
│   ├── visuals/
│   │   ├── cards.py             # 9:16 & 16:9 Pillow editorial/stat cards & image framing
│   │   └── resolver.py          # Pollinations + NASA/Wikimedia + offline card fallback
│   ├── video/
│   │   ├── captions.py          # Word-synced animated .ass captions (9:16 & 16:9 safe zones)
│   │   └── renderer.py          # Native FFmpeg zoompan clips, caption burn & loudnorm+limiter
│   ├── qc/
│   │   └── gatekeeper.py        # FFprobe, ebur128 loudness, blackdetect & freezedetect
│   ├── scheduler/
│   │   └── daily.py             # 2-slot daily orchestrator, custom plan runner & smart publishAt
│   ├── storage/
│   │   ├── db.py                # SQLite WAL store (jobs, plan_items, topic_history)
│   │   ├── dedup.py             # Normalized title, keyword & 3-gram similarity checker
│   │   └── cleanup.py           # End-of-day garbage remover preserving topic_history
│   ├── web/
│   │   ├── app.py               # FastAPI server, background cleanup loop & REST API
│   │   └── templates/index.html # StoryCircuit Studio web dashboard
│   └── youtube/
│       ├── oauth.py             # In-app client_secret.json & browser OAuth flow manager
│       └── uploader.py          # Resumable YouTube Data API v3 uploader with retries
├── scripts/
│   └── auth_youtube.py          # Interactive CLI YouTube OAuth helper
├── docs/                        # GitHub Pages OAuth homepage & privacy policy
├── tests/                       # Pytest test suite
├── start_dashboard.sh           # Launches the FastAPI dashboard on 127.0.0.1:8080
├── pyproject.toml               # Package metadata & dependencies
└── .env.example                 # Template configuration
```

---

## Prerequisites

- **Python 3.11+** (venv recommended in `.venv/`)
- **FFmpeg & FFprobe** available on `PATH`
- **espeak-ng** (recommended offline fallback if Edge-TTS cannot reach the network)
- **Optional Free AI Backends** (works offline with deterministic fallbacks even if neither is configured):
  - **Local Ollama** (`OLLAMA_MODEL=qwen2.5:3b-instruct` at `http://127.0.0.1:11434`)
  - **Gemini Free Tier** (`GEMINI_API_KEY`, model `gemini-2.5-flash`)

---

## Quick Start

1. **Install dependencies and create `.env`:**
   ```bash
   cd /home/ryu/Projects/storycircuit
   python3 -m venv .venv
   .venv/bin/pip install -e .
   cp .env.example .env
   ```

2. **Start the Desktop App or Web Dashboard:**
   - **Desktop App Launcher:** Open **StoryCircuit** from your app launcher (`Super + Space`) or run `storycircuit` in a terminal.
   - **Or start manually:**
     ```bash
     ./start_dashboard.sh
     # or: .venv/bin/python -m reelforge web
     ```
   Open [http://127.0.0.1:8090](http://127.0.0.1:8090) *(dedicated port `8090` so it never collides with ClipSnip on `8000` or GiggleBeats on `8080`)*.

3. **Connect YouTube OAuth (once):**
   - **In the Dashboard:** Drag & drop your Google Cloud `client_secret.json` (Desktop App OAuth client with **YouTube Data API v3** enabled) into the **YouTube Connection & Auto-Schedule** card, then click **Connect YouTube OAuth**.
   - **Or via CLI:**
     ```bash
     .venv/bin/python scripts/auth_youtube.py
     ```

4. **Produce & Schedule Videos:**
   - Click **Generate Today's 2 Videos** in the dashboard header to generate today's 2 slots and schedule them automatically on YouTube.

---

## CLI Commands

```bash
# Start web dashboard (default 127.0.0.1:8090)
.venv/bin/python -m reelforge web

# Generate one video (random | plan | custom_script)
.venv/bin/python -m reelforge generate --mode random --upload
.venv/bin/python -m reelforge generate --mode custom_script --topic "My Story" --script-file script.txt --upload

# Add an item to the Custom Total Plan with custom date & publish time
.venv/bin/python -m reelforge plan-add --date 2026-11-26 --slot 1 --time 18:30 --topic "Voyager 1"

# Run today's 2-video cycle immediately
.venv/bin/python -m reelforge run-daily

# Run continuous background scheduler daemon (polls every 300s by default)
.venv/bin/python -m reelforge scheduler --poll 300

# Run end-of-day garbage cleanup manually
.venv/bin/python -m reelforge cleanup

# Upload a specific QC-passed job by ID
.venv/bin/python -m reelforge upload <job_id> --live
```

---

## Key Environment Variables (`.env`)

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `OLLAMA_HOST` / `OLLAMA_MODEL` | `http://127.0.0.1:11434` / `qwen2.5:3b-instruct` | Local zero-cost script & cue LLM |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | `""` / `gemini-2.5-flash` | Optional free-tier cloud LLM |
| `VISUAL_MODE` | `auto` | `auto`, `pollinations`, `archival`, or `cards_only` |
| `TTS_ENGINE` / `TTS_RATE` | `edge` / `+4%` | Edge-TTS primary & secondary voices |
| `SCHEDULER_TIMEZONE` | `Asia/Kolkata` | Local timezone for daily slots, scheduling, and cleanup |
| `SLOT1_TIME` / `SLOT2_TIME` | `12:30` / `20:30` | Default daily YouTube publish times |
| `YOUTUBE_PUBLISHING_MODE` | `live` | `live` for real YouTube uploads (`simulation` for dry runs) |
| `YOUTUBE_PRIVACY_STATUS` | `private` | Fallback privacy (`publishAt` schedules always use `private` until release) |
| `SHORT_MAX_DURATION_SEC` | `120.0` | Videos `> 120s` auto-convert to `1920×1080` landscape |
| `AUTO_GARBAGE_CLEANUP` | `1` | Automatically delete ended-day video files after midnight |

---

## Running Tests

```bash
.venv/bin/python -m pytest tests/test_dedup_and_db.py tests/test_director.py tests/test_visuals_and_captions.py tests/test_web_api.py tests/test_splitter_cleanup_and_landscape.py -v
```

---

