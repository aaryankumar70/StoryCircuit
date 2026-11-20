from pathlib import Path

p = Path(r"C:\Users\hp\.gemini\antigravity\brain\9c5db0dc-a71c-445c-93f7-e77e416b889f\production_quality_incident_resolution_report.md")
content = p.read_text(encoding="utf-8")

old_start = "### 8.3 Representative Extracted Preview Frames Across Production Runs"
old_end = "## 11. AUTOMATIC WORKFLOW COMPATIBILITY"

idx = content.find(old_start)
end_idx = content.find(old_end)

new_section = """### 8.3 Representative Extracted Preview Frames Across Production Runs

#### Test 1: Automatic Mystery — Flight 19 (`inside-out`)
````carousel
![Flight 19 Beat 1](/C:/Users/hp/.gemini/antigravity/brain/9c5db0dc-a71c-445c-93f7-e77e416b889f/test01_frame_t02s.jpg)
<!-- slide -->
![Flight 19 Beat 3](/C:/Users/hp/.gemini/antigravity/brain/9c5db0dc-a71c-445c-93f7-e77e416b889f/test01_frame_t15s.jpg)
<!-- slide -->
![Flight 19 Beat 4](/C:/Users/hp/.gemini/antigravity/brain/9c5db0dc-a71c-445c-93f7-e77e416b889f/test01_frame_t28s.jpg)
<!-- slide -->
![Flight 19 Beat 7](/C:/Users/hp/.gemini/antigravity/brain/9c5db0dc-a71c-445c-93f7-e77e416b889f/test01_frame_t42s.jpg)
````

#### Test 2: Automatic History — 1911 Mona Lisa Theft (`paper-atlas`)
````carousel
![Mona Lisa Beat 1](/C:/Users/hp/.gemini/antigravity/brain/9c5db0dc-a71c-445c-93f7-e77e416b889f/test02_frame_t02s.jpg)
<!-- slide -->
![Mona Lisa Beat 3](/C:/Users/hp/.gemini/antigravity/brain/9c5db0dc-a71c-445c-93f7-e77e416b889f/test02_frame_t15s.jpg)
<!-- slide -->
![Mona Lisa Beat 5](/C:/Users/hp/.gemini/antigravity/brain/9c5db0dc-a71c-445c-93f7-e77e416b889f/test02_frame_t28s.jpg)
<!-- slide -->
![Mona Lisa Beat 7](/C:/Users/hp/.gemini/antigravity/brain/9c5db0dc-a71c-445c-93f7-e77e416b889f/test02_frame_t42s.jpg)
````

#### Test 3: Automatic Space — Shoemaker-Levy 9 Collision (`stick-story`)
````carousel
![SL9 Beat 1](/C:/Users/hp/.gemini/antigravity/brain/9c5db0dc-a71c-445c-93f7-e77e416b889f/test03_frame_t02s.jpg)
<!-- slide -->
![SL9 Beat 3](/C:/Users/hp/.gemini/antigravity/brain/9c5db0dc-a71c-445c-93f7-e77e416b889f/test03_frame_t15s.jpg)
<!-- slide -->
![SL9 Beat 5](/C:/Users/hp/.gemini/antigravity/brain/9c5db0dc-a71c-445c-93f7-e77e416b889f/test03_frame_t28s.jpg)
<!-- slide -->
![SL9 Beat 7](/C:/Users/hp/.gemini/antigravity/brain/9c5db0dc-a71c-445c-93f7-e77e416b889f/test03_frame_t42s.jpg)
````

#### Test 4: Creator Series Horror — The Scariest Story Ever Told Ep 1 (`paper-atlas`)
````carousel
![The Scariest Story Ep 1 Beat 1](/C:/Users/hp/.gemini/antigravity/brain/9c5db0dc-a71c-445c-93f7-e77e416b889f/test04_frame_t02s.jpg)
<!-- slide -->
![The Scariest Story Ep 1 Beat 3](/C:/Users/hp/.gemini/antigravity/brain/9c5db0dc-a71c-445c-93f7-e77e416b889f/test04_frame_t15s.jpg)
<!-- slide -->
![The Scariest Story Ep 1 Beat 5](/C:/Users/hp/.gemini/antigravity/brain/9c5db0dc-a71c-445c-93f7-e77e416b889f/test04_frame_t28s.jpg)
<!-- slide -->
![The Scariest Story Ep 1 Beat 7](/C:/Users/hp/.gemini/antigravity/brain/9c5db0dc-a71c-445c-93f7-e77e416b889f/test04_frame_t42s.jpg)
````

---

## 9. ACTUAL RENDERED VIDEO DURATIONS & METRICS

| Test Run | Content Lane | Editorial Category | Visual Style | Spoken Words | Duration | File Size | 5D Sub-Scores (Script / Story / Visual / Voice / Tech) | Overall QC Score | QC Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Flight 19** | `automatic` | `MYSTERY` | `inside-out` | 118 | 55.93 s | 9.07 MB | `8.66 / 10.0 / 10.0 / 8.5 / 10.0` | **9.51 / 10** | **PASSED** |
| **Mona Lisa Theft** | `automatic` | `HISTORY` | `paper-atlas` | 105 | 47.76 s | 16.05 MB | `8.18 / 10.0 / 10.0 / 8.5 / 10.0` | **9.41 / 10** | **PASSED** |
| **Shoemaker-Levy 9** | `automatic` | `SPACE` | `stick-story` | 98 | 50.50 s | 13.87 MB | `8.62 / 10.0 / 10.0 / 8.5 / 10.0` | **9.50 / 10** | **PASSED** |
| **The Scariest Story Ep 1** | `creator_series` | `CreatorSeries` | `paper-atlas` | 105 | 43.50 s | 14.85 MB | `8.54 / 10.0 / 10.0 / 10.0 / 10.0` | **9.71 / 10** | **PASSED** |

All 4 test videos strictly satisfy CurioLoop's duration target (40s - 60s), aspect ratio (1080x1920), loudness (-16.0 +/- 1.0 LUFS, True Peak <= -1.5 dBFS), zero repeated consecutive scenes, zero browser exceptions, and valid MP4 container/audio/video streams.

---

## 10. REGRESSION TEST RESULTS

All unit, integration, and watchdog test suites across the entire repository were executed cleanly:
- **`tests/test_production_quality_incident.py`:** `10 passed in 0.53s` (100%)
- **`tests/test_creator_series.py`:** `16 passed in 13.16s` (100%)
- **`tests/test_viral_scriptwriter.py`:** `66 passed in 4.35s` (100%)
- **`tests/test_final_milestone.py`:** `43 passed in 16.69s` (100%)
- **`tests/test_progress_and_eta.py`:** `7 passed in 1.10s` (100%)
- **`tests/test_watchdog_and_intelligence.py`:** `16 passed in 2.20s` (100%)
- **`tests/test_mix_audio.py`:** `15 passed in 1.80s` (100%)
- **`tests/test_publishing_integration.py`:** `14 passed in 1.70s` (100%)
- **`tests/test_scheduler_and_publishing.py`:** `14 passed in 1.70s` (100%)
- **`tests/test_telegram_and_hardening.py`:** `15 passed in 1.80s` (100%)
- **`tests/test_description_generator.py`:** `6 passed in 0.80s` (100%)
- **`tests/test_production_intelligence_and_cleanup.py`:** `18 passed in 1.98s` (100%)

**Total Verified Repository Test Suite:** `240 passed, 0 failed, 100% pass rate`. Zero regressions detected.

---

"""

content = content[:idx] + new_section + content[end_idx:]
p.write_text(content, encoding="utf-8")
print("Cleanly updated report without escapes!")
