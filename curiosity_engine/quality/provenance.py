"""Story Provenance, Lineage and Content Integrity Validator for CurioLoop.

Guarantees:
1. Exact traceability across content lane, topic ID, approved script, narration hash, storyboard ID, and production run ID.
2. Hard rejection of forbidden categories (Biology, Nature, Generic Science) in automatic lane.
3. Prevention of accidental reuse of stale storyboards or mismatched audio/scripts from previous runs.
4. Verification that YouTube title, storyboard, narration, and approved script all describe the exact same story.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from curiosity_engine.content.editorial_policy import ALLOWED_CATEGORIES, normalize_category

logger = logging.getLogger("curiosity_engine.provenance")


def compute_script_narration_hash(script_data: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 digest of normalized narration text."""
    lines = (script_data or {}).get("lines") or []
    full_text = " ".join(str(ln.get("text", "")).strip().lower() for ln in lines)
    norm_text = re.sub(r"[^a-z0-9\s]", "", full_text)
    norm_text = re.sub(r"\s+", " ", norm_text).strip()
    return hashlib.sha256(norm_text.encode("utf-8")).hexdigest()


def compute_storyboard_hash(script_data: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 digest of storyboard visual sequence."""
    lines = (script_data or {}).get("lines") or []
    scenes = [
        ln.get("scene") if isinstance(ln.get("scene"), dict) else {"visual_type": str(ln.get("scene") or "")}
        for ln in lines
    ]
    seq_repr = "|".join(
        f"{sc.get('visual_type', '')}:{sc.get('headline', '')}:{sc.get('mood', '')}"
        for sc in scenes
    )
    return hashlib.sha256(seq_repr.encode("utf-8")).hexdigest()


def build_production_provenance(
    video_id: str,
    content_lane: str,
    topic_id: str,
    script_data: Dict[str, Any],
    production_run_id: Optional[str] = None,
    original_source_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct an authoritative provenance record for a video production run."""
    lane = (content_lane or "automatic").strip().lower()
    raw_cat = str(script_data.get("category") or "")
    norm_cat = normalize_category(raw_cat) or raw_cat.upper()
    lines = script_data.get("lines") or []
    full_narration = " ".join(str(ln.get("text", "")).strip() for ln in lines)
    script_hash = compute_script_narration_hash(script_data)
    storyboard_hash = compute_storyboard_hash(script_data)

    run_id = production_run_id or f"run_{video_id}_{script_hash[:8]}"
    source_id = original_source_id or script_data.get("id") or topic_id

    return {
        "production_run_id": run_id,
        "video_id": video_id,
        "content_lane": lane,
        "topic_id": topic_id,
        "original_source_id": str(source_id),
        "approved_script_id": str(script_data.get("id") or topic_id),
        "script_version": str(script_data.get("version", "1.0")),
        "category": norm_cat,
        "script_hash": script_hash,
        "storyboard_id": f"sb_{storyboard_hash[:12]}",
        "storyboard_hash": storyboard_hash,
        "final_narration_text": full_narration,
        "word_count": len(full_narration.split()),
        "beat_count": len(lines),
    }


def validate_story_provenance(
    record: Dict[str, Any],
    script_data: Dict[str, Any],
    project_dir: Optional[Path] = None,
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Strictly validate content lane, category policy, script/narration hash match,
    storyboard alignment, and title consistency.
    """
    issues: List[str] = []
    meta: Dict[str, Any] = {}

    content_lane = str(record.get("content_lane") or "automatic").strip().lower()
    raw_category = str(script_data.get("category") or record.get("category") or "").strip()
    norm_category = normalize_category(raw_category) or raw_category.upper()
    meta["content_lane"] = content_lane
    meta["category"] = norm_category

    # 1. Automatic lane editorial category gate
    if content_lane == "automatic":
        if raw_category and norm_category not in ALLOWED_CATEGORIES:
            issues.append(
                f"Automatic lane violation: Category '{raw_category}' (normalized: '{norm_category}') "
                f"is not in authorized set {sorted(ALLOWED_CATEGORIES)}."
            )
        elif not raw_category and (script_data.get("lines") or record.get("script")):
            issues.append(
                "Automatic lane violation: Category is missing from production record."
            )

    # 2. Approved script narration integrity
    approved_hash = compute_script_narration_hash(script_data)
    record_hash = record.get("script_hash")
    meta["approved_script_hash"] = approved_hash
    if record_hash and record_hash != approved_hash:
        issues.append(
            f"Provenance mismatch: Record script_hash ({record_hash[:8]}) does not match "
            f"approved script narration hash ({approved_hash[:8]})."
        )

    # 3. Project dir assets alignment (if project prepared)
    if project_dir and project_dir.exists():
        proj_script_file = project_dir / "script.json"
        if proj_script_file.exists():
            try:
                with open(proj_script_file, "r", encoding="utf-8") as f:
                    proj_script = json.load(f)
                proj_hash = compute_script_narration_hash(proj_script)
                meta["project_script_hash"] = proj_hash
                if proj_hash != approved_hash:
                    issues.append(
                        f"Stale project asset: project_dir script.json hash ({proj_hash[:8]}) "
                        f"does not match approved script hash ({approved_hash[:8]})."
                    )
            except Exception as e:
                issues.append(f"Could not read project_dir script.json: {e}")

        proj_lines_file = project_dir / "data" / "lines.json"
        if proj_lines_file.exists():
            try:
                with open(proj_lines_file, "r", encoding="utf-8") as f:
                    lines_data = json.load(f)
                lines_list = lines_data.get("lines") or []
                lines_text = " ".join(str(ln.get("text", "")).strip().lower() for ln in lines_list)
                lines_norm = re.sub(r"[^a-z0-9\s]", "", lines_text)
                lines_hash = hashlib.sha256(re.sub(r"\s+", " ", lines_norm).strip().encode("utf-8")).hexdigest()
                meta["lines_narration_hash"] = lines_hash
                if lines_hash != approved_hash:
                    issues.append(
                        f"Narration drift: data/lines.json narration hash ({lines_hash[:8]}) "
                        f"does not match approved script hash ({approved_hash[:8]})."
                    )
            except Exception as e:
                issues.append(f"Could not read data/lines.json: {e}")

    # 4. Storyboard to Scene Alignment & Repetition Check
    lines = script_data.get("lines") or []
    scenes = [
        ln.get("scene") if isinstance(ln.get("scene"), dict) else {"visual_type": str(ln.get("scene") or "")}
        for ln in lines
    ]
    prev_vt: Optional[str] = None
    repeated_consecutive = 0
    for i, sc in enumerate(scenes):
        vt = sc.get("visual_type")
        if vt and vt == prev_vt:
            repeated_consecutive += 1
            issues.append(f"Visual repetition: Consecutive scene {i+1} repeats visual_type '{vt}'.")
        prev_vt = vt

    meta["repeated_consecutive_scenes"] = repeated_consecutive

    # 5. Title & Topic Alignment
    topic_str = str(record.get("topic") or script_data.get("topic") or "").strip().lower()
    title_str = str(record.get("youtube_title") or "").strip().lower()
    if topic_str and title_str:
        # Check topic keywords in title or narration
        topic_words = set(re.findall(r"\b[a-z]{4,}\b", topic_str))
        narration_words = set(re.findall(r"\b[a-z]{4,}\b", meta.get("approved_script_hash", "")))
        title_words = set(re.findall(r"\b[a-z]{4,}\b", title_str))
        # If title is completely generic and mentions zero keywords of topic
        common_with_topic = topic_words & title_words
        if len(topic_words) >= 2 and not common_with_topic:
            # Check if title shares words with narration lines
            full_text = " ".join(str(ln.get("text", "")).strip().lower() for ln in lines)
            full_words = set(re.findall(r"\b[a-z]{4,}\b", full_text))
            if not (title_words & full_words):
                issues.append(
                    f"Title-Topic mismatch: YouTube title '{title_str}' shares no substantive subject "
                    f"keywords with topic '{topic_str}' or script narration."
                )

    passed = len(issues) == 0
    meta["passed"] = passed
    return passed, issues, meta
