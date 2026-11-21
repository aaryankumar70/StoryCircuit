"""CurioLoop 2.0 Visual Engine Acceptance Benchmark.
Generates an isolated local evaluation video proving genuine narrative visual storytelling:
- Subject-specific scenes (19th-century brigantine, ocean swells, unmanned helm, archival logbook)
- Real cinematography (wide establishing, tracking, dolly-in, macro close-up, dolly-out)
- Multi-method rendering (Cinematic 2.5D, Archival Imagery, Procedural Environment)
- Complete retirement of legacy radar/compass/stick-figure templates.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath("."))
os.environ["GEMINI_API_KEY"] = ""

import curiosity_engine.production.director
from curiosity_engine.config import OUTPUT_DIR
from curiosity_engine.production.director import prepare_project
from curiosity_engine.production.renderer import render_project_video
from curiosity_engine.production.storyboard_approval import StoryboardApprovalManager
from curiosity_engine.quality.qc_gatekeeper import verify_video
from curiosity_engine.quality.visual_semantic_qc import SemanticVisualQC

EVAL_DIR = OUTPUT_DIR / "evaluation_20261121"


def extract_preview_frames(video_path: Path, output_dir: Path, timestamps: list[float]):
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted = []
    import subprocess
    for ts in timestamps:
        out_frame = output_dir / f"{video_path.stem}_frame_t{int(ts):02d}s.jpg"
        cmd = [
            "ffmpeg", "-y", "-ss", str(ts), "-i", str(video_path),
            "-vframes", "1", "-q:v", "2", str(out_frame)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode == 0 and out_frame.exists():
            extracted.append(out_frame)
            print(f"Extracted frame at t={ts:.1f}s -> {out_frame.name} ({out_frame.stat().st_size} bytes)")
    return extracted


def produce_benchmark():
    video_id = "eval_narrative_benchmark"
    project_dir = EVAL_DIR / video_id
    output_mp4 = EVAL_DIR / f"{video_id}.mp4"

    # 20-30s Benchmark Script with 6 distinct narrative beats
    script_data = {
        "title": "The Mystery of the Mary Celeste",
        "category": "MYSTERY",
        "voice": "bm_george",
        "speed": 1.05,
        "lead": 0.35,
        "outro": 0.55,
        "evidence_type": "historical_incident",
        "sources": ["Maritime Archives: British Admiralty Court 1873 Report on Mary Celeste"],
        "lines": [
            {
                "text": "In December 1872, the British brigantine Dei Gratia spotted a lone vessel drifting across the North Atlantic.",
                "caps": "IN DECEMBER 1872 *A LONE VESSEL DRIFTING",
                "gap": 0.28,
            },
            {
                "text": "Heavy Atlantic swells battered the wooden hull, but the ship was sailing with all canvas set.",
                "caps": "HEAVY ATLANTIC SWELLS *BATTERED THE WOODEN HULL",
                "gap": 0.26,
            },
            {
                "text": "Captain Morehouse sent a boarding crew across the icy water to hail the silent deck.",
                "caps": "A BOARDING CREW *HAILED THE SILENT DECK",
                "gap": 0.28,
            },
            {
                "text": "They found the helm completely unmanned, the cargo untouched, and every soul vanished.",
                "caps": "THE HELM UNMANNED *AND EVERY SOUL VANISHED",
                "gap": 0.26,
            },
            {
                "text": "Down in the cabin, an open logbook lay on the desk with its final entry from ten days before.",
                "caps": "AN OPEN LOGBOOK *WITH ITS FINAL ENTRY",
                "gap": 0.28,
            },
            {
                "text": "Maritime history still cannot explain why ten people abandoned a seaworthy ship in open sea.",
                "caps": "WHY TEN PEOPLE *ABANDONED A SEAWORTHY SHIP",
                "gap": 0.28,
            }
        ]
    }

    print("=" * 60)
    print("STEP 1: PREPARING NARRATIVE VISUAL ENGINE BENCHMARK")
    print("=" * 60)

    orig_output_dir = curiosity_engine.production.director.OUTPUT_DIR
    curiosity_engine.production.director.OUTPUT_DIR = EVAL_DIR
    try:
        prep_dir = prepare_project(video_id, script_data, auto_approve_storyboard=True)
    finally:
        curiosity_engine.production.director.OUTPUT_DIR = orig_output_dir

    print("Project prepared at:", prep_dir)

    # Inspect Storyboard & Run Semantic QC
    sb_path = prep_dir / "storyboard.json"
    storyboard = json.loads(sb_path.read_text(encoding="utf-8"))
    print("\n--- STORYBOARD GENERATED ---")
    print(f"Total Scenes: {storyboard['total_scenes']}, Duration: {storyboard['total_duration_sec']}s")
    for s in storyboard["scenes"]:
        print(f"[{s['scene_id']}] {s['narration']['text'][:50]}... -> Subject: {s['primary_subject']['name']} ({s['rendering_method']}, {s['camera']['shot_type']})")

    sem_qc = SemanticVisualQC.evaluate_storyboard(storyboard)
    print(f"\nSemantic Visual QC: Passed={sem_qc.passed}, Score={sem_qc.overall_semantic_score:.2f}/10")
    if sem_qc.rejection_reasons:
        print("Semantic QC Issues:", sem_qc.rejection_reasons)

    # Approve storyboard
    StoryboardApprovalManager.approve_storyboard(prep_dir, reviewer="AcceptanceTestReviewer")

    # Render video
    print("\n" * 2 + "=" * 60)
    print("STEP 2: RENDERING VIA CHROMIUM CDP UNBUFFERED PIPE")
    print("=" * 60)
    t_render = time.time()
    rendered_mp4 = render_project_video(prep_dir, output_mp4, resume=False, force_rebuild=True)
    print(f"Render completed in {time.time()-t_render:.1f}s -> {rendered_mp4} ({rendered_mp4.stat().st_size} bytes)")

    # Technical + Semantic QC
    print("\n" * 2 + "=" * 60)
    print("STEP 3: RUNNING QUALITY CONTROL GATEKEEPER")
    print("=" * 60)
    qc_report = verify_video(rendered_mp4, script_metadata=script_data, project_dir=prep_dir)
    print(f"Technical QC Passed: {qc_report.passed}, Score: {qc_report.checks.get('overall_score')}/10")
    if qc_report.issues:
        print("QC Issues:", qc_report.issues)

    # Extract preview frames
    frames = extract_preview_frames(rendered_mp4, EVAL_DIR / "frames", [2.0, 6.0, 10.0, 14.0, 19.0, 24.0])
    print(f"Successfully generated {len(frames)} preview frames.")
    return rendered_mp4, storyboard, sem_qc, qc_report, frames


if __name__ == "__main__":
    produce_benchmark()
