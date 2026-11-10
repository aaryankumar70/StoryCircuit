"""Phase 2 Production Script: Generate Both Sample Videos Locally.
Topic 1: Why do your ears ring in absolute silence? (Inside Out, Biology)
Topic 2: The sunken Egyptian port city of Thonis-Heracleion (Paper Atlas, History)

Outputs:
- Pristine 1080x1920 30fps H.264 / AAC MP4 files
- CurioLoop brand badge in safe zone
- EBU R128 loudness measured and checked
- Complete QC reports, scripts, source references, and topic scores
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curiosity_engine.config import OUTPUT_DIR
from curiosity_engine.content.curated_fallback import CURATED_TOPICS
from curiosity_engine.quality.qc_gatekeeper import measure_audio_loudness, verify_video
from curiosity_engine.runner.pipeline import produce_single_video
from curiosity_engine.state.db import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("phase2_production")


def main():
    target_date = "2026-11-09"
    clean_date = target_date.replace("-", "")

    # Retrieve Topic 1 (Ear Ringing) and Topic 2 (Thonis-Heracleion)
    topic_1 = next(t for t in CURATED_TOPICS if t["id"] == "bio_silence_ringing")
    topic_2 = next(t for t in CURATED_TOPICS if t["id"] == "hist_thonis_heracleion")

    video_1_id = f"video_{clean_date}_slot1"
    video_2_id = f"video_{clean_date}_slot2"

    print("=" * 70)
    print("PHASE 2: CURIOLOOP LOCAL PRODUCTION QUALITY RUN")
    print(f"Date: {target_date}")
    print(f"Slot 1: {topic_1['topic']} [{topic_1['category']}] -> {topic_1['style']}")
    print(f"Slot 2: {topic_2['topic']} [{topic_2['category']}] -> {topic_2['style']}")
    print("=" * 70)

    # 1. Video 1 (already rendered and passed QC, reuse if completed)
    logger.info(">>> Checking / Producing Slot 1 Video...")
    v1_rec = produce_single_video(
        video_id=video_1_id,
        topic_info=topic_1,
        slot_index=1,
        target_date=target_date,
        force_rebuild=False,
    )
    v1_path = Path(v1_rec["local_video_path"])
    v1_qc = verify_video(v1_path, v1_rec["script"])
    v1_loudness = measure_audio_loudness(v1_path)

    # 2. Produce Video 2
    logger.info(">>> Producing Slot 2 Video...")
    v2_rec = produce_single_video(
        video_id=video_2_id,
        topic_info=topic_2,
        slot_index=2,
        target_date=target_date,
        force_rebuild=True,
    )
    v2_path = Path(v2_rec["local_video_path"])
    v2_qc = verify_video(v2_path, v2_rec["script"])
    v2_loudness = measure_audio_loudness(v2_path)

    # Summary Report
    summary = {
        "production_date": target_date,
        "video_1": {
            "id": video_1_id,
            "topic": topic_1["topic"],
            "category": topic_1["category"],
            "style": topic_1["style"],
            "file": str(v1_path),
            "size_bytes": v1_path.stat().st_size,
            "scores": topic_1["scores"],
            "sources": topic_1["sources"],
            "claims": topic_1["claims"],
            "script": v1_rec["script"],
            "qc_passed": v1_qc.passed,
            "qc_checks": v1_qc.checks,
            "qc_issues": v1_qc.issues,
            "loudness": v1_loudness,
        },
        "video_2": {
            "id": video_2_id,
            "topic": topic_2["topic"],
            "category": topic_2["category"],
            "style": topic_2["style"],
            "file": str(v2_path),
            "size_bytes": v2_path.stat().st_size,
            "scores": topic_2["scores"],
            "sources": topic_2["sources"],
            "claims": topic_2["claims"],
            "script": v2_rec["script"],
            "qc_passed": v2_qc.passed,
            "qc_checks": v2_qc.checks,
            "qc_issues": v2_qc.issues,
            "loudness": v2_loudness,
        },
    }

    report_path = OUTPUT_DIR / f"phase2_qc_report_{clean_date}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 70)
    print("PHASE 2 PRODUCTION EXECUTION SUMMARY")
    print("=" * 70)
    print(f"Video 1: {v1_path.name}")
    print(f"  Duration  : {v1_qc.checks.get('duration_sec', 0):.2f}s")
    print(f"  Resolution: {v1_qc.checks.get('resolution')}")
    print(f"  Loudness  : {v1_loudness['integrated_lufs']:.1f} LUFS (Target: [-21, -13] LUFS)")
    print(f"  True Peak : {v1_loudness['true_peak_db']:.1f} dBFS (Target: <= -0.5 dBFS)")
    print(f"  QC Status : {'PASSED' if v1_qc.passed else 'FAILED'}")

    print(f"\nVideo 2: {v2_path.name}")
    print(f"  Duration  : {v2_qc.checks.get('duration_sec', 0):.2f}s")
    print(f"  Resolution: {v2_qc.checks.get('resolution')}")
    print(f"  Loudness  : {v2_loudness['integrated_lufs']:.1f} LUFS (Target: [-21, -13] LUFS)")
    print(f"  True Peak : {v2_loudness['true_peak_db']:.1f} dBFS (Target: <= -0.5 dBFS)")
    print(f"  QC Status : {'PASSED' if v2_qc.passed else 'FAILED'}")
    print("=" * 70)

    return v1_qc.passed and v2_qc.passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
