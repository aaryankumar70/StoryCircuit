"""Generate improved YouTube Shorts descriptions for existing CurioLoop videos.
Updates database records and prints before/after comparisons.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from curiosity_engine.content.description_generator import description_generator
from curiosity_engine.state.db import db


def upgrade_existing_descriptions():
    video_ids = ["video_20261109_slot1", "video_20261109_slot2"]
    results = {}

    for vid in video_ids:
        record = db.get_video_record(vid)
        if not record:
            print(f"[WARNING] Video {vid} not found in database.")
            continue

        topic = record.get("topic", "")
        category = record.get("category", "")
        script_data = record.get("script", {})
        sources = record.get("sources", [])
        claims = record.get("claims", [])

        # Previous (before) description
        old_desc = record.get("youtube_description") or (
            f"{script_data.get('title', topic)}\n\nSources & Verification:\n"
            + "\n".join(sources)
            + "\n\n#Shorts #Curiosity #Education"
        )

        # Generate enhanced intelligent description
        enhanced_data = description_generator.generate(
            topic=topic,
            category=category,
            script_data=script_data,
            sources=sources,
            claims=claims,
        )

        new_desc = enhanced_data["full_description"]

        # Persist to database record
        record["youtube_description"] = new_desc
        record["description_data"] = enhanced_data
        record["description_edited"] = False
        db.save_video_record(vid, record)

        results[vid] = {
            "title": script_data.get("title", topic),
            "category": category,
            "old_desc": old_desc,
            "new_desc": new_desc,
            "char_count": enhanced_data["char_count"],
            "hook": enhanced_data["hook"],
            "engagement_question": enhanced_data["engagement_question"],
            "hashtags": enhanced_data["hashtags"],
            "sources": sources,
        }

    return results


if __name__ == "__main__":
    upgrades = upgrade_existing_descriptions()
    for vid, data in upgrades.items():
        print(f"\n{'='*75}\nVIDEO: {vid} ({data['title']})\n{'='*75}")
        print("--- BEFORE (Old Simple Placeholder) ---")
        print(data["old_desc"])
        print("\n--- AFTER (Enhanced Intelligent Description) ---")
        print(data["new_desc"])
        print(f"\nLength: {data['char_count']} chars (Limit: 5,000)")
        print(f"Hashtags: {' '.join(data['hashtags'])}")
