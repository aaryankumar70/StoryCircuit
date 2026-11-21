"""CurioLoop 2.0 Storyboard Approval Engine.
Enforces pre-render visual review, scene modifications, and explicit storyboard approval
before executing expensive full Chromium CDP + FFmpeg rendering.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from curiosity_engine.quality.visual_semantic_qc import SemanticVisualQC

logger = logging.getLogger(__name__)


class StoryboardApprovalManager:
    """Manages storyboard generation, interactive review, and approval gating."""

    @classmethod
    def generate_review_dossier(cls, storyboard: Dict[str, Any]) -> str:
        """Formats the storyboard into an interactive human-readable Markdown review dossier."""
        title = storyboard.get("title", "Untitled Storyboard")
        total_scenes = storyboard.get("total_scenes", len(storyboard.get("scenes", [])))
        duration = storyboard.get("total_duration_sec", 0.0)
        era = storyboard.get("historical_era", "Historical Era")
        setting = storyboard.get("setting", "Story Setting")

        md = []
        md.append(f"# Visual Storyboard Review: {title}")
        md.append(f"**Historical Era:** {era} | **Setting:** {setting} | **Total Scenes:** {total_scenes} | **Target Duration:** {duration:.1f}s\n")
        md.append("---")
        md.append("### Scene-by-Scene Narrative Visual Plan\n")

        for s in storyboard.get("scenes", []):
            sc_id = s.get("scene_id")
            idx = s.get("beat_index")
            narr = s.get("narration", {})
            text = narr.get("text", "")
            t_start = narr.get("start_s", 0.0)
            t_end = narr.get("end_s", 0.0)
            dur = narr.get("duration_sec", 0.0)

            sub = s.get("primary_subject", {})
            env = s.get("environment", {})
            cam = s.get("camera", {})
            method = s.get("rendering_method", "CINEMATIC_2_5D")
            explanation = s.get("visual_match_explanation", "")

            md.append(f"#### Scene {idx} [{sc_id}] ({t_start:.1f}s – {t_end:.1f}s, {dur:.1f}s)")
            md.append(f"- **Spoken Narration:** *\"{text}\"*")
            md.append(f"- **Primary Subject:** **{sub.get('name', 'Subject')}** (Action: *{sub.get('action', 'none')}*)")
            md.append(f"- **Environment & Era:** {env.get('name', 'Setting')} ({env.get('era', era)}, {env.get('time_of_day', 'Day')})")
            md.append(f"- **Production Method:** `{method}` | **Shot Type:** `{cam.get('shot_type', 'MEDIUM')}` ({cam.get('motivation', 'REVEAL')})")
            md.append(f"- **Visual Correspondence Rationale:** {explanation}")
            md.append("")

        return "\n".join(md)

    @classmethod
    def save_storyboard(cls, project_dir: Path, storyboard: Dict[str, Any], auto_approve: bool = False) -> Path:
        """Saves storyboard.json, runs semantic QC, and sets initial approval state."""
        sb_path = project_dir / "storyboard.json"
        
        # Run Semantic Visual QC
        qc_report = SemanticVisualQC.evaluate_storyboard(storyboard)
        storyboard["semantic_qc"] = qc_report.to_dict()
        
        status = "PENDING_REVIEW"
        if auto_approve and qc_report.passed:
            status = "APPROVED"

        storyboard["approval_status"] = status
        sb_path.write_text(json.dumps(storyboard, indent=2), encoding="utf-8")

        # Also write review markdown
        review_md = cls.generate_review_dossier(storyboard)
        (project_dir / "STORYBOARD_REVIEW.md").write_text(review_md, encoding="utf-8")

        logger.info("Saved storyboard and review dossier at %s (Status: %s)", sb_path, status)
        return sb_path

    @classmethod
    def approve_storyboard(cls, project_dir: Path, reviewer: str = "Creator") -> Dict[str, Any]:
        """Approve the storyboard so that rendering is unlocked."""
        sb_path = project_dir / "storyboard.json"
        if not sb_path.exists():
            raise FileNotFoundError(f"Missing storyboard.json in {project_dir}")

        storyboard = json.loads(sb_path.read_text(encoding="utf-8"))
        storyboard["approval_status"] = "APPROVED"
        storyboard["approved_by"] = reviewer
        sb_path.write_text(json.dumps(storyboard, indent=2), encoding="utf-8")
        logger.info("Storyboard approved by %s at %s", reviewer, project_dir)
        return storyboard

    @classmethod
    def is_approved(cls, project_dir: Path) -> Tuple[bool, str]:
        """Check if storyboard exists and is approved for rendering."""
        sb_path = project_dir / "storyboard.json"
        if not sb_path.exists():
            return False, "Missing storyboard.json. Storyboard must be generated first."

        storyboard = json.loads(sb_path.read_text(encoding="utf-8"))
        status = storyboard.get("approval_status", "PENDING_REVIEW")
        if status == "APPROVED":
            return True, "Storyboard approved."
        return False, f"Storyboard status is '{status}'. Requires approval before full render."
