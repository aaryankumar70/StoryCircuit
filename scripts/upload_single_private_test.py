"""CurioLoop Studio - Isolated Single-Video Private YouTube Upload Test.

Targets ONLY Slot 1 (video_20261109_slot1).
Guarantees:
1. Resolves actual video MP4 path from project structure and database record.
2. Verified QC-passed content only.
3. YouTube upload is strictly PRIVATE (privacyStatus='private').
4. Instagram is NEVER invoked (zero imports or calls).
5. Global publishing mode remains untouched.
6. Does not confuse simulated IDs ('yt_sim_...') with real YouTube IDs.
7. Checks for existing real YouTube IDs or duplicate titles on channel.
8. Requires explicit confirmation before live network upload.
9. Reconciles channel state if network drops.
10. Preserves existing simulated history separately.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from curiosity_engine.config import OUTPUT_DIR, PUBLISHING_MODE
from curiosity_engine.distribution.token_manager import token_manager
from curiosity_engine.distribution.youtube_publisher import (
    YouTubeAuthError,
    YouTubePublisher,
    youtube_publisher,
)
from curiosity_engine.state.db import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("curiosity_engine.upload_single_test")

SLOT_1_ID = "video_20261109_slot1"


def print_banner(title: str) -> None:
    print(f"\n{'='*75}\n{title}\n{'='*75}")


def resolve_slot1_video(record: Dict[str, Any]) -> Path:
    """Resolve actual video file from record and known output locations."""
    candidates = []

    # 1. Path recorded in database
    db_path = record.get("local_video_path")
    if db_path:
        candidates.append(Path(db_path))

    # 2. Top-level output directory
    candidates.append(OUTPUT_DIR / f"{SLOT_1_ID}.mp4")

    # 3. Subfolder render directory
    candidates.append(OUTPUT_DIR / SLOT_1_ID / "renders" / f"{SLOT_1_ID}.mp4")

    for cand in candidates:
        if cand.exists() and cand.is_file() and cand.stat().st_size > 1024 * 1024:
            return cand.resolve()

    raise FileNotFoundError(
        f"Could not resolve valid MP4 video for {SLOT_1_ID}. Checked paths:\n"
        + "\n".join(f" - {c}" for c in candidates)
    )


def run_preflight_checks() -> Dict[str, Any]:
    """Execute rigorous pre-upload validation gates."""
    print_banner("PREFLIGHT AUDIT: CurioLoop Slot 1 Private YouTube Upload")

    # 1. Fetch DB Record
    record = db.get_video_record(SLOT_1_ID)
    if not record:
        raise RuntimeError(f"Database record for '{SLOT_1_ID}' not found in firestore_local.json.")

    print(f"[OK] Database Record Loaded: {SLOT_1_ID}")
    print(f"     Topic: {record.get('topic')}")
    print(f"     Category: {record.get('category')} | Style: {record.get('style')}")

    # 2. Resolve & Inspect MP4 File
    video_path = resolve_slot1_video(record)
    size_mb = round(video_path.stat().st_size / (1024 * 1024), 2)
    print(f"[OK] Video File Resolved: {video_path}")
    print(f"     File Size: {size_mb} MB")

    # 3. Verify QC Status
    qc_passed = record.get("qc_passed", False)
    qc_results = record.get("qc_results", {}).get("checks", {})
    if not qc_passed:
        raise RuntimeError(f"Slot 1 video has not passed programmatic QC gate! Issues: {record.get('error')}")

    print(f"[OK] Programmatic QC Status: PASSED")
    print(f"     Duration: {qc_results.get('duration_sec')}s | Resolution: {qc_results.get('resolution')}")
    print(f"     Loudness: {qc_results.get('audio_loudness', {}).get('integrated_lufs')} LUFS, "
          f"Peak: {qc_results.get('audio_loudness', {}).get('true_peak_db')} dBFS")

    # 4. Check for Existing Real YouTube ID vs Simulated ID
    current_yt_id = record.get("youtube_upload_id")
    is_simulated = bool(current_yt_id and current_yt_id.startswith("yt_sim_"))
    print(f"[OK] Current Database Upload State:")
    print(f"     Recorded ID: {current_yt_id} (Simulated: {is_simulated})")

    if current_yt_id and not is_simulated:
        raise RuntimeError(
            f"SAFETY ABORT: Video already has a real YouTube upload ID ({current_yt_id})! "
            f"Refusing to duplicate or overwrite."
        )

    # 5. Check YouTube OAuth Health
    print("[OK] Checking YouTube OAuth 2.0 Token Health...")
    health = token_manager.check_youtube_health()
    if not health.get("healthy"):
        raise YouTubeAuthError(
            f"YouTube OAuth token is not healthy! Status: {health.get('status')}. "
            f"Alert: {health.get('alert')}"
        )
    print(f"     OAuth Status: HEALTHY (Token exchange validated with Google)")

    # 6. Verify Metadata & Strict Privacy
    script = record.get("script", {})
    title = script.get("title", record.get("topic", "Fascinating Fact"))
    if "#Shorts" not in title and "#shorts" not in title:
        yt_title = f"{title[:80]} #Shorts"
    else:
        yt_title = title[:100]

    sources = record.get("sources", [])
    claims = record.get("claims", [])
    description = record.get("youtube_description")
    if not description:
        from curiosity_engine.content.description_generator import description_generator
        desc_data = description_generator.generate(
            topic=record.get("topic", title),
            category=record.get("category", "Biology"),
            script_data=script,
            sources=sources,
            claims=claims,
        )
        description = desc_data["full_description"]
        record["youtube_description"] = description
        db.save_video_record(SLOT_1_ID, record)

    tags = ["Shorts", "Curiosity", "Biology", "Science", "DidYouKnow", "Education"]
    category_id = "27"  # Education
    privacy_status = "private"  # STRICTLY PRIVATE

    print(f"[OK] Upload Metadata Prepared:")
    print(f"     Title: {yt_title}")
    print(f"     Privacy Status: {privacy_status.upper()} (Zero public visibility)")
    print(f"     Category ID: {category_id} (Education)")
    print(f"     Tags: {', '.join(tags)}")

    # 7. Check Channel Reconciliation (Duplicate Prevention on YouTube)
    print("[OK] Checking YouTube Channel for existing video with matching title...")
    reconciled = youtube_publisher.reconcile_existing_upload(yt_title)
    if reconciled:
        raise RuntimeError(
            f"SAFETY ABORT: Video with title '{yt_title}' was already found on your YouTube channel "
            f"(ID: {reconciled.get('video_id')}). Aborting to prevent duplicate upload."
        )
    print("     Channel Check: No duplicate found on YouTube channel.")

    # 8. Instagram Exclusion Assertion
    assert "curiosity_engine.distribution.instagram_publisher" not in sys.modules, (
        "Security Error: Instagram publisher was imported! Instagram must remain excluded."
    )
    print("[OK] Platform Isolation: Instagram is 100% EXCLUDED (zero imports, zero calls).")

    # 9. Global Publishing Mode Check
    print(f"[OK] Global Publishing Mode: {PUBLISHING_MODE.upper()} (Remains unchanged)")

    return {
        "record": record,
        "video_path": video_path,
        "yt_title": yt_title,
        "description": description,
        "tags": tags,
        "category_id": category_id,
        "privacy_status": privacy_status,
        "current_sim_id": current_yt_id if is_simulated else None,
    }


def execute_upload(preflight_data: Dict[str, Any]) -> None:
    """Execute live upload with interactive confirmation and durable DB update."""
    print_banner("READY FOR LIVE UPLOAD TO YOUTUBE")
    print("Target Video:  ", preflight_data["video_path"])
    print("Upload Title:  ", preflight_data["yt_title"])
    print("Privacy Mode:   PRIVATE (Only visible to you in YouTube Studio)")
    print("Simulated ID:  ", preflight_data.get("current_sim_id"))
    print("-" * 75)

    confirm = input("\nType 'CONFIRM' to perform the private YouTube upload: ").strip()
    if confirm != "CONFIRM":
        print("\n[CANCELLED] Confirmation not received. Aborting upload.")
        sys.exit(0)

    print("\nInitiating live upload to YouTube Data API v3 (chunked resumable)...")
    try:
        res = youtube_publisher.upload_short(
            video_path=preflight_data["video_path"],
            title=preflight_data["yt_title"],
            description=preflight_data["description"],
            tags=preflight_data["tags"],
            category_id=preflight_data["category_id"],
            privacy_status="private",
            force_mode="live",
        )
    except Exception as e:
        logger.error(f"Upload encountered an exception: {e}")
        print("\nAttempting channel state reconciliation...")
        reconciled = youtube_publisher.reconcile_existing_upload(preflight_data["yt_title"])
        if reconciled:
            print("[RECONCILED] Upload succeeded despite exception!")
            res = reconciled
        else:
            print(f"[FAILED] Upload did not complete. Error: {e}")
            raise

    real_video_id = res.get("video_id")
    real_url = res.get("url")
    now_iso = datetime.now(timezone.utc).isoformat()

    # Update database record
    record = preflight_data["record"]
    # Preserve simulation history
    record["simulated_youtube_upload_id"] = preflight_data.get("current_sim_id")
    # Record real upload metadata
    record["youtube_upload_id"] = real_video_id
    record["youtube_url"] = real_url
    record["youtube_privacy_status"] = "private"
    record["youtube_simulated"] = False
    record["youtube_published_at"] = now_iso
    record["publishing_status"] = "PUBLISHED"
    db.save_video_record(SLOT_1_ID, record)

    print_banner("UPLOAD SUCCESSFUL: YouTube Short (PRIVATE)")
    print(f"Video ID:        {real_video_id}")
    print(f"Privacy Status:  PRIVATE")
    print(f"Watch URL:       {real_url}")
    print(f"Studio Link:     https://studio.youtube.com/video/{real_video_id}/edit")
    print(f"Database Record: Updated (youtube_simulated=False, Slot 2 preserved)")
    print("=" * 75)


def main():
    parser = argparse.ArgumentParser(description="CurioLoop Slot 1 Private YouTube Upload Test")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute the live private upload (requires interactive 'CONFIRM' input).",
    )
    args = parser.parse_args()

    preflight = run_preflight_checks()

    if args.execute:
        execute_upload(preflight)
    else:
        print_banner("DRY-RUN / PREFLIGHT COMPLETED SUCCESSFULLY")
        print("All 9 validation gates passed without error.")
        print("Zero uploads were performed.")
        print("To execute the live private upload, run with: --execute")


if __name__ == "__main__":
    main()
