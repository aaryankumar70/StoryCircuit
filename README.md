# Project Curiosity Engine
## Autonomous Short-Form Video Production & Distribution Studio
### YouTube Shorts + Instagram Reels • Strict ₹0 / $0 Free-Tier Target

Curiosity Engine is an autonomous, local-first short-form video production studio designed to produce and publish exactly **two original educational videos daily** to **YouTube Shorts** with zero daily human intervention, zero cloud hosting costs, and a strict ₹0 budget on Windows.

---

### Key Specifications & Constraints
- **Daily Volume:** Exactly 2 original videos daily.
- **Duration:** 20–30 seconds per video.
- **Format:** Vertical 9:16 (1080 × 1920), 30 FPS, H.264 (MP4), AAC audio.
- **AI / Voice Costs:** 100% Free (Gemini Free Tier + Kokoro-82M ONNX local TTS + faster-whisper alignment).
- **Video Costs:** 100% Free (Procedural Canvas/HTML5 rendering in Headless Chrome + FFmpeg).
- **Architecture:** Local-first Windows native: Local Autonomous Scheduler (Asia/Kolkata), Local JSON Database, Direct YouTube Data API v3 MP4 upload.
- **Strict Budget Policy:** ₹0 / $0 local execution with zero cloud hosting, zero ingress/egress fees, and zero cloud run billing.

---

### Visual Style Kits
Curiosity Engine selects dynamic visual storytelling styles matched to content categories:

| Style Kit | Visual Identity | Content Pillars |
| :--- | :--- | :--- |
| **Inside Out** (`inside-out`) | Flat 2D vector x-ray cutaways, anatomy/internal views, punchy cuts | Biology, Psychology, Health/Body Mysteries, Neuroscience |
| **Paper Atlas** (`paper-atlas`) | Cut paper on aged parchment, crimson routes, gold date ribbons | History, Geography, Ancient Mysteries, Discoveries |
| **Stick Story** (`stick-story`) | Expressive stick figures (animated eyes), day/night room environments | Science experiments, Technology, Survival scenarios |

---

### Scheduled Jobs Architecture (Asia/Kolkata / IST)

| Local Job | IST Time | Execution | Action |
| :--- | :--- | :--- | :--- |
| `Job 1 (Generate)` | **05:30 AM IST** | Local Scheduler Daemon / Entrypoint | Discover topics, write scripts, synthesize Kokoro voice, render 2 videos, run QC, save to `output/`. |
| `Job 2 (Publish 1)` | **10:00 AM IST** | Local Scheduler Daemon / Entrypoint | Publish Video 1 to YouTube Shorts directly via resumable MP4 upload, record video ID in local DB. |
| `Job 3 (Publish 2)` | **06:00 PM IST** | Local Scheduler Daemon / Entrypoint | Publish Video 2 to YouTube Shorts directly via resumable MP4 upload, record video ID in local DB. |

---

### Project Structure
```
d:\yt/
├── curiosity_engine/
│   ├── config.py                  # Global settings, paths, and local runtime constraints
│   ├── content/                   # Topic discovery, Gemini free tier client, scriptwriting, descriptions
│   │   ├── gemini_client.py
│   │   ├── topic_discovery.py
│   │   ├── scriptwriter.py
│   │   ├── description_generator.py
│   │   └── curated_fallback.py
│   ├── production/                # Faceless Shorts video pipeline
│   │   ├── director.py
│   │   ├── tts_engine.py          # Kokoro-82M ONNX synthesis
│   │   ├── aligner.py             # Word-level timestamp alignment
│   │   └── renderer.py            # Headless Chrome + FFmpeg image2pipe
│   ├── quality/                   # Programmatic QC Gatekeeper
│   │   └── qc_gatekeeper.py
│   ├── distribution/              # YouTube Data API v3 direct upload & token manager
│   │   ├── youtube_publisher.py
│   │   ├── instagram_publisher.py
│   │   ├── token_manager.py
│   │   └── video_host.py
│   ├── state/                     # Local JSON database client (data/firestore_local.json)
│   │   └── db.py
│   ├── runner/                    # Pipeline, local scheduler & CLI entrypoint
│   │   ├── pipeline.py
│   │   ├── local_scheduler.py
│   │   └── entrypoint.py
│   └── dashboard/                 # Lightweight localhost FastAPI management dashboard
│       ├── app.py
│       └── templates/index.html
├── templates/                     # Inside Out, Paper Atlas, and Stick Story style kits
├── scripts/
│   ├── run_scheduler.py           # Local scheduler CLI runner
│   ├── start_scheduler.bat        # Windows batch launcher
│   ├── start_scheduler.ps1        # Windows PowerShell launcher
│   ├── auth_youtube.py            # YouTube OAuth Desktop Flow
│   └── upload_single_private_test.py
├── tests/                         # Pytest test suite (100% local-first)
├── requirements.txt
└── .env.example
```

---

### Local Quickstart

#### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

#### 2. Run Daily Video Generation (Job 1)
```bash
python -m curiosity_engine.runner.entrypoint --mode=generate
```

#### 3. Run Publishing (Job 2 & Job 3)
```bash
python -m curiosity_engine.runner.entrypoint --mode=publish-1
python -m curiosity_engine.runner.entrypoint --mode=publish-2
```

#### 4. Launch Management Dashboard
```bash
uvicorn curiosity_engine.dashboard.app:app --host 127.0.0.1 --port 8000
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000) to view today's videos, previews, quotas, and logs.

#### 5. Run Complete Acceptance Test Suite
```bash
python scripts/test_full_acceptance.py
```

---

### Cloud Deployment (Google Cloud Platform)

#### Prerequisites
- Google Cloud SDK (`gcloud`) installed and authenticated.
- A GCP project with Billing enabled (required to register Cloud Run, but operating costs remain $0 within free tier).

#### One-Click Deployment
```bash
bash cloud/deploy.sh <YOUR_GCP_PROJECT_ID>
```

#### Credential Configuration in Secret Manager
Store your API secrets securely in Google Secret Manager or Cloud Run Job environment variables:
- `GEMINI_API_KEY`: From Google AI Studio (Free Tier).
- `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`: From Google Cloud Console OAuth 2.0 Credentials with `youtube.upload` scope.
- `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_ACCOUNT_ID`: From Meta for Developers (Graph API v21.0 with `instagram_content_publish` permission).

---

### Quality Control (QC) Gatekeeper
Every render must automatically pass strict programmatic verification before being accepted:
1. **Duration Verification:** Exactly $\in [20.0, 30.0]$ seconds.
2. **Resolution & Aspect Ratio:** Strictly 1080 × 1920 (9:16 vertical).
3. **Codec Compliance:** H.264 video, AAC stereo audio.
4. **Audio Integrity:** Programmatic audio check (`astats` filter).
5. **Visual Health:** Frame sampling confirms non-zero variance (no black/blank frames).
6. **Safe Zones:** Text captions verified between y=1250 and y=1550 (below top overlay and above platform UI icons).
7. **Independence:** If Video 1 fails QC, it is rejected and logged; Video 2 proceeds unaffected.
