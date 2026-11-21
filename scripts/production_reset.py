"""
Production Reset Script for CurioLoop 2.0
Establishes a clean baseline dated 21 November 2026 (Asia/Kolkata).

Protects:
- .env and credentials
- OAuth tokens and client secrets
- Telegram bot tokens & chat IDs
- Kokoro ONNX model weights and voice embeddings
- Whisper model caches
- Published and scheduled YouTube videos (preserved in published_history archive)
- User source materials

Archives:
- Pre-2026-11-21 output artifacts and test runs into D:\\yt_archive_20261121_baseline\\
- Pre-reset database snapshot with SHA-256 checksums
"""

import os
import sys
import json
import shutil
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

IST = ZoneInfo("Asia/Kolkata")
RESET_BASELINE_DATE = "2026-11-21"
ARCHIVE_BASE_DIR = Path("D:/yt_archive_20261121_baseline")
WORKSPACE_DIR = Path("D:/yt")

def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def plan_reset(execute: bool = False):
    print("=" * 60)
    print(f"CurioLoop 2.0 Production Reset Planner")
    print(f"Target Baseline: {RESET_BASELINE_DATE} (Asia/Kolkata)")
    print(f"Archive Target:  {ARCHIVE_BASE_DIR}")
    print(f"Execution Mode:  {'LIVE EXECUTION' if execute else 'DRY RUN'}")
    print("=" * 60)

    manifest = {
        "reset_timestamp": datetime.now(IST).isoformat(),
        "baseline_date": RESET_BASELINE_DATE,
        "archived_files": [],
        "preserved_youtube_records": [],
        "preserved_config_files": []
    }

    # 1. Verify protected paths
    protected_rel_paths = [
        ".env",
        "data/token_state.json",
        "models/kokoro",
        "models/whisper-small"
    ]
    for p in protected_rel_paths:
        full_p = WORKSPACE_DIR / p
        if full_p.exists():
            manifest["preserved_config_files"].append(str(p))
            print(f"[PROTECTED] Verified safe: {p}")

    # 2. Archive output folder
    output_dir = WORKSPACE_DIR / "output"
    archive_output_dir = ARCHIVE_BASE_DIR / "output"
    
    dirs_to_archive = []
    files_to_archive = []
    
    if output_dir.exists():
        for item in output_dir.iterdir():
            # If it's an old test folder or prior video run
            if item.is_dir():
                dirs_to_archive.append(item)
            elif item.is_file():
                files_to_archive.append(item)

    print(f"\n[OUTPUT] Found {len(dirs_to_archive)} directories and {len(files_to_archive)} files to archive from output/")

    # 3. Database snapshot and clean baseline
    db_path = WORKSPACE_DIR / "data/firestore_local.json"
    preserved_videos = {}
    archived_video_count = 0

    if db_path.exists():
        with open(db_path, "r", encoding="utf-8") as f:
            raw_db = json.load(f)

        videos = raw_db.get("videos", {})
        for vid_id, vid_data in videos.items():
            yt_url = vid_data.get("youtube_url")
            yt_id = vid_data.get("youtube_id")
            # Preserve all uploaded/scheduled YouTube videos
            if yt_url or yt_id or vid_id.startswith(f"video_{RESET_BASELINE_DATE.replace('-', '')}"):
                preserved_videos[vid_id] = vid_data
                manifest["preserved_youtube_records"].append({
                    "video_id": vid_id,
                    "youtube_url": yt_url,
                    "youtube_id": yt_id,
                    "status": vid_data.get("status")
                })
            else:
                archived_video_count += 1

        print(f"[DATABASE] Preserved {len(preserved_videos)} published/current records, archiving {archived_video_count} test/scratch records")

    # 4. Automation state
    auto_state_path = WORKSPACE_DIR / "data/automation_state.json"
    cleaned_auto_state = None
    if auto_state_path.exists():
        with open(auto_state_path, "r", encoding="utf-8") as f:
            raw_auto = json.load(f)
        daily_records = raw_auto.get("daily_records", {})
        # Keep records from 2026-11-21 onwards, and preserve previous published records in a history archive
        preserved_daily = {}
        for d, rec in daily_records.items():
            if d >= RESET_BASELINE_DATE:
                preserved_daily[d] = rec
        cleaned_auto_state = dict(raw_auto)
        cleaned_auto_state["daily_records"] = preserved_daily
        cleaned_auto_state["published_archive"] = {d: rec for d, rec in daily_records.items() if d < RESET_BASELINE_DATE}
        print(f"[AUTOMATION] Retained {len(preserved_daily)} active daily records for baseline >= {RESET_BASELINE_DATE}, archived {len(daily_records) - len(preserved_daily)} into published_archive")

    if not execute:
        print("\n[DRY RUN COMPLETE] No files were moved or altered. Pass --execute to perform reset.")
        return

    # Perform Backup & Reset
    print("\n[EXECUTING RESET] Creating archive directory at:", ARCHIVE_BASE_DIR)
    ARCHIVE_BASE_DIR.mkdir(parents=True, exist_ok=True)
    archive_output_dir.mkdir(parents=True, exist_ok=True)
    archive_data_dir = ARCHIVE_BASE_DIR / "data"
    archive_data_dir.mkdir(parents=True, exist_ok=True)

    # Backup data/
    data_dir = WORKSPACE_DIR / "data"
    for item in data_dir.iterdir():
        if item.is_file():
            dest = archive_data_dir / item.name
            shutil.copy2(item, dest)
            manifest["archived_files"].append({
                "source": str(item.relative_to(WORKSPACE_DIR)),
                "archive_path": str(dest),
                "size_bytes": dest.stat().st_size,
                "sha256": sha256_file(dest)
            })

    # Move output directories to archive
    for item in dirs_to_archive:
        dest = archive_output_dir / item.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(item, dest)
        shutil.rmtree(item)
        print(f"Archived output folder: {item.name}")

    for item in files_to_archive:
        dest = archive_output_dir / item.name
        shutil.copy2(item, dest)
        item.unlink()
        print(f"Archived output file: {item.name}")

    # Write reset database
    if db_path.exists():
        raw_db["videos"] = preserved_videos
        raw_db["logs"] = [l for l in raw_db.get("logs", []) if isinstance(l, dict) and l.get("timestamp", "").startswith(RESET_BASELINE_DATE)]
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(raw_db, f, indent=2)
        print(f"Updated {db_path} to clean baseline.")

    # Write reset automation state
    if cleaned_auto_state and auto_state_path.exists():
        with open(auto_state_path, "w", encoding="utf-8") as f:
            json.dump(cleaned_auto_state, f, indent=2)
        print(f"Updated {auto_state_path} to clean baseline.")

    # Save manifest
    manifest_path = ARCHIVE_BASE_DIR / "reset_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"\n[RESET COMPLETE] Saved archive manifest to {manifest_path}")

if __name__ == "__main__":
    exec_mode = "--execute" in sys.argv
    plan_reset(execute=exec_mode)
