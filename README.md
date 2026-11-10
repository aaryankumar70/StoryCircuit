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

### Autonomous Schedule Architecture (`Asia/Kolkata` / IST)

| Stage | Timing / Trigger | Execution | Action |
| :--- | :--- | :--- | :--- |
| `Daily Batch` | **First Windows Login / Rollover** | [`LocalScheduler`](curiosity_engine/runner/local_scheduler.py) (`--daemon`) | Reconcile state, generate missing slots only, synthesize Kokoro audio + Whisper alignment, render MP4s, run QC, and upload/schedule privately on YouTube. |
| `Slot 1 Publish` | **12:30 PM IST** | YouTube Data API `status.publishAt` | Automatically transitions Slot 1 from `private` to `public` at 12:30 PM IST (or next eligible day if started after 12:15 PM IST). |
| `Slot 2 Publish` | **08:30 PM IST** | YouTube Data API `status.publishAt` | Automatically transitions Slot 2 from `private` to `public` at 08:30 PM IST (or next eligible day if started after 08:15 PM IST). |

Once YouTube confirms `status.publishAt`, YouTube handles publication independently—the local PC does not need to stay powered on at publication time.

---

### Project Structure
```text
.
├── curiosity_engine/
│   ├── config.py                  # Global settings, paths, and safe local defaults
│   ├── content/                   # Topic discovery, Gemini client, scriptwriter, descriptions, curated fallback
│   ├── production/                # Director, Kokoro-82M ONNX TTS, Whisper word alignment, Chrome/FFmpeg renderer
│   ├── quality/                   # Programmatic QC Gatekeeper (duration, geometry, codecs, LUFS, visual checks)
│   ├── distribution/              # YouTube Data API v3 upload/schedule client & OAuth TokenManager
│   ├── notifications/             # Persistent, retry-safe Telegram Bot API operational notifier
│   ├── state/                     # Atomic local JSON store (data/firestore_local.json, excluded from Git)
│   ├── runner/                    # Slot-independent pipeline, local scheduler daemon, automation state
│   └── dashboard/                 # Localhost FastAPI management dashboard (127.0.0.1:8000)
├── templates/                     # Reusable HTML/JS visual style kits (inside-out, paper-atlas, stick-story)
├── scripts/
│   ├── auth_youtube.py            # Desktop Google OAuth 2.0 wizard & tokeninfo scope verifier
│   ├── run_scheduler.py           # Safe CLI runner (--status, --dry-run, --validate, --once --confirm, --daemon)
│   ├── manage_windows_task.py     # Dual Windows Startup VBS registration & scheduler/dashboard boot manager
│   ├── start_scheduler.bat        # Windows batch launcher
│   └── start_scheduler.ps1        # Windows PowerShell launcher
├── reauthorize_youtube.bat        # One-click full-scope OAuth reauthorization & validation helper
├── docs/                          # Static GitHub Pages OAuth branding homepage & privacy policy
├── tests/                         # Pytest unit and integration test suite
├── requirements.txt
└── .env.example
```

---

### Installation & Local Setup

#### 1. System Prerequisites
- **Python 3.10+** (verified on Python 3.14 Windows)
- **Node.js 18+** (used by `templates/*/tools/capture.mjs` for headless frame capture)
- **FFmpeg & FFprobe** on `PATH`
- **Google Chrome or Microsoft Edge** (configured via `CHROME` in `.env`)
- **Local Model Weights** (excluded from Git; place in `./models`):
  - `./models/kokoro/kokoro-v1.0.onnx` and `./models/kokoro/voices-v1.0.bin`
  - `./models/whisper-small/` (optional `faster-whisper` weights; falls back cleanly to inline timing if absent)

#### 2. Install Python Dependencies
```bash
pip install -r requirements.txt
# Optional for running the test suite:
pip install pytest httpx
```

#### 3. Configure Environment Variables (`.env`)
Copy `.env.example` to `.env` and fill in your own credentials locally (**never commit `.env`**):
```bash
cp .env.example .env
```
Key safety defaults in `curiosity_engine/config.py`:
- `YOUTUBE_PUBLISHING_MODE=simulation` (set to `live` only when ready to upload to YouTube)
- `YOUTUBE_PRIVACY_STATUS=private` (always kept `private` by default; scheduled videos auto-publish at `publishAt`)
- `INSTAGRAM_PUBLISHING_MODE=disabled` (strict ₹0 default; zero Instagram network calls)

#### 4. Configure Google OAuth & YouTube Data API v3
1. In Google Cloud Console, enable **YouTube Data API v3** and configure an **OAuth consent screen**.
   > **Note on Google OAuth Testing Mode:** If the consent screen remains in `Testing` status, Google expires refresh tokens roughly every **7 days**. CurioLoop tracks the authorization timestamp in `data/token_state.json`, alerts Telegram 24 hours before expiry, safely pauses new publishing if revoked, and provides 1-click recovery below.
2. Create an OAuth 2.0 Client ID of type **Desktop app** and set `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET` in `.env`.
3. Authorize locally with full upload + scheduling scopes (`youtube.upload`, `youtube.readonly`, `youtube.force-ssl`):
   ```bash
   python scripts/auth_youtube.py --force --scope-mode full --yes
   ```
4. Verify credentials, binaries, models, and OAuth scopes (read-only):
   ```bash
   python scripts/run_scheduler.py --validate
   ```

**7-Day OAuth Reauthorization (2 One-Step Options):**
- **From Dashboard:** Open `http://127.0.0.1:8000` and click **Reconnect YouTube Account**. Complete browser sign-in; the running scheduler and dashboard automatically hot-reload `.env`, verify `can_upload` + `can_update_schedule`, send a Telegram confirmation, and resume automation if it was paused due to OAuth expiration.
- **Standalone Fallback:** Double-click `reauthorize_youtube.bat` in the project root (`D:\yt`).

#### 5. Telegram Operational Notifications (Optional, Free Bot API)
Add your Telegram bot credentials to `.env` (**never commit `.env`**):
```dotenv
TELEGRAM_BOT_TOKEN=123456789:your-bot-token-here
TELEGRAM_CHAT_ID=your-chat-id
TELEGRAM_DAILY_SUMMARY_HOUR_IST=21
```
CurioLoop automatically dispatches deduplicated, locally persisted notifications with bounded retries and outage recovery (`data/notifications_state.json`):
- **Public Publication Confirmed:** Triggered **only** after the YouTube API confirms `privacyStatus == "public"` (never merely on private upload or scheduling).
- **OAuth Lifecycle:** Proactive warning ~24 hours before the 7-day Testing expiration, plus an urgent alert if a refresh token is revoked/rejected.
- **Operational Failures:** Alerts on upload, scheduling, processing, YouTube rejection, authentication, or missed-publication delays.
- **Daily IST Summary:** One summary per day summarizing produced count vs daily limit, next scheduled video, OAuth reauth estimate, and any errors.
Telegram errors are strictly isolated and logged cleanly without tokens so notification outages never interrupt publishing.

#### 6. Safe Scheduler Usage & Automatic Windows Dual Startup
Always run read-only diagnostics before live execution:
```bash
python scripts/run_scheduler.py --status      # Read-only telemetry & Windows startup state
python scripts/run_scheduler.py --dry-run     # Read-only evaluation (zero side effects)
python scripts/run_scheduler.py --validate    # Dependency & OAuth check
```
Single-shot execution requires explicit confirmation (`--confirm`), and daily unattended automation is gated by `automation_state` (`enabled`) plus `YOUTUBE_PUBLISHING_MODE`:
```bash
python scripts/run_scheduler.py --once --confirm
python scripts/manage_windows_task.py register   # Registers single non-admin Startup VBS launcher
python scripts/manage_windows_task.py boot       # Starts BOTH scheduler daemon & dashboard (idempotent)
python scripts/manage_windows_task.py status     # Checks scheduler PID, dashboard port 8000, & VBS startup
python scripts/manage_windows_task.py stop-all   # Cleanly stops both daemon and dashboard
```
Upon Windows login, the single non-admin Startup launcher (`CurioLoopScheduler.vbs`) invokes `scripts/manage_windows_task.py boot` via `pythonw.exe` (hidden, detached):
- **Scheduler Daemon:** `scripts/run_scheduler.py --daemon --interval 15` guarded by `data/.scheduler.lock` -> logs to `data/scheduler.log`.
- **Dashboard Server:** `uvicorn curiosity_engine.dashboard.app:app --host 127.0.0.1 --port 8000` guarded by `data/.dashboard.lock` and TCP port check -> logs to `data/dashboard.log`.
- Startup events are logged to `data/startup.log`. Duplicate launches are skipped automatically, and if either service fails to boot, the other still starts cleanly.

#### 7. Local Management Dashboard
Open [http://127.0.0.1:8000](http://127.0.0.1:8000) (auto-started on Windows login via `boot`, or start manually with `python scripts/manage_windows_task.py start-dashboard`).
Features:
- **Operational Status Overview:** Scheduler PID/status, dashboard health, YouTube OAuth health & 7-day estimated reauth date, next scheduled video, today's production count, Telegram status & queue count, last confirmed public publish, and last failure.
- **Safe Controls:** `Reconnect YouTube Account`, `View Scheduler Status`, `Notifications` history viewer, `Dashboard Logs` sanitized tail viewer, confirmation-gated `Pause / Resume Automation`, `Validate Config`, and `Dry-Run Preview`.
- **Security:** Bound strictly to `127.0.0.1`, mutating actions protected via `X-Studio-Auth`, all credentials redacted automatically.

#### 8. Run Automated Tests
```bash
python -m pytest tests/ -v
```
The unit/integration tests run fully locally with mocked external APIs and never upload real videos or touch production credentials.

#### 9. Troubleshooting
- **OAuth Expired / Automation Paused:** New publishing pauses automatically while already-scheduled YouTube videos remain untouched. Click **Reconnect YouTube Account** in the dashboard or run `reauthorize_youtube.bat`.
- **Dashboard Unavailable on `127.0.0.1:8000`:** Run `python scripts/manage_windows_task.py start-dashboard` and inspect `data/dashboard.log` + `data/startup.log`.
- **Telegram Alerts Not Arriving:** Ensure both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set in `.env` and send `/start` to your bot first. Queued messages retry automatically on scheduler startup/poll.
- **Scheduler Duplicate Prevention:** If `.scheduler.lock` or `.dashboard.lock` contains a stale PID after an unexpected reboot, `manage_windows_task.py boot` verifies PID liveness + port `8000` before starting cleanly.

---

### OAuth Branding Website (`docs/`)
Static public pages for the Google OAuth consent screen (`GitHub Pages` branch `main`, folder `/docs`):
- **Homepage:** `docs/index.html` ([https://aaryankumar70.github.io/StoryCircuit/](https://aaryankumar70.github.io/StoryCircuit/))
- **Privacy Policy:** `docs/privacy.html` ([https://aaryankumar70.github.io/StoryCircuit/privacy.html](https://aaryankumar70.github.io/StoryCircuit/privacy.html))

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
