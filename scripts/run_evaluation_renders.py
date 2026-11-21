"""CurioLoop 2.0 Evaluation Video Producer.
Generates 2 evaluation videos in an isolated directory (output/evaluation_20261121/):
1. Automatic Studio Shorts Video (Pillar: MYSTERY)
2. Creator Studio Episode Video (Pillar: CREATOR STORY)

Enforces:
- Strict ₹0 local-first operation
- Sequential execution: LLM -> unload -> Kokoro ONNX -> Whisper -> Chromium -> FFmpeg
- Contact sheet frame extraction (t=2s, 15s, 28s, 42s)
- Comprehensive QC gatekeeper verification
- Zero live publishing / zero external API calls
"""

import os
import sys
import json
import time
import shutil
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.abspath("."))

# Guarantee ₹0 operation
os.environ["GEMINI_API_KEY"] = ""

import curiosity_engine.production.director
from curiosity_engine.config import OUTPUT_DIR, get_chrome_executable
from curiosity_engine.intelligence.local_model import local_model
from curiosity_engine.content.scriptwriter import write_video_script
from curiosity_engine.production.director import prepare_project
from curiosity_engine.production.renderer import render_project_video
from curiosity_engine.quality.qc_gatekeeper import verify_video

EVAL_DIR = OUTPUT_DIR / "evaluation_20261121"

def extract_preview_frames(video_path: Path, output_dir: Path, timestamps: list[float]):
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted = []
    for ts in timestamps:
        frame_name = f"{video_path.stem}_frame_t{int(ts):02d}s.jpg"
        out_frame = output_dir / frame_name
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{ts:.2f}",
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",
            str(out_frame)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if out_frame.exists() and out_frame.stat().st_size > 5000:
            extracted.append(out_frame)
            print(f"Extracted frame at t={ts:.1f}s -> {out_frame.name} ({out_frame.stat().st_size} bytes)")
    return extracted

def produce_automatic_evaluation_video():
    print("\n" + "=" * 60)
    print("STEP 1: PRODUCING AUTOMATIC STUDIO EVALUATION VIDEO")
    print("=" * 60)
    
    video_id = "eval_auto_mystery"
    project_dir = EVAL_DIR / video_id
    output_mp4 = EVAL_DIR / f"{video_id}.mp4"
    
    if output_mp4.exists() and output_mp4.stat().st_size > 1000000 and project_dir.exists():
        print(f"Video already rendered at: {output_mp4} ({output_mp4.stat().st_size} bytes). Skipping render.")
        rendered_mp4 = output_mp4
        prep_dir = project_dir
    else:
        topic_info = {
            "topic": "The Ghost Blimp of 1942: L-8 Returns with No Crew",
            "category": "MYSTERY",
            "niche": "unsolved_mysteries",
            "discovery_origin": "local_qwen",
            "source_mode": "local_model"
        }

        t0 = time.time()
        print(f"Generating script locally via Ollama for topic: '{topic_info['topic']}'...")
        script_data = write_video_script(topic_info)
        print(f"Script generated in {time.time()-t0:.1f}s. Word count: {sum(len(l['text'].split()) for l in script_data['lines'])}")

        # Unload LLM from RAM immediately
        local_model.unload_model()
        print("Ollama model unloaded from RAM.")

        # Prepare project (Kokoro ONNX audio + faster-whisper alignment)
        print("Synthesizing narration & aligning timestamps...")
        # Overwrite director project dir to isolated evaluation folder
        if project_dir.exists():
            shutil.rmtree(project_dir)
        
        # Temporarily redirect prepare_project to EVAL_DIR
        orig_output_dir = curiosity_engine.production.director.OUTPUT_DIR
        curiosity_engine.production.director.OUTPUT_DIR = EVAL_DIR
        try:
            prep_dir = prepare_project(video_id, script_data)
        finally:
            curiosity_engine.production.director.OUTPUT_DIR = orig_output_dir

        print("Project prepared at:", prep_dir)
        
        # Render video via Chromium CDP + FFmpeg
        print("Rendering video via Chromium CDP unbuffered pipe (30fps 1080x1920)...")
        t_render = time.time()
        rendered_mp4 = render_project_video(prep_dir, output_mp4, resume=False, force_rebuild=True)
        print(f"Render completed in {time.time()-t_render:.1f}s -> {rendered_mp4} ({rendered_mp4.stat().st_size} bytes)")

    # Run QC
    print("Running Quality Control Gatekeeper...")
    script_meta = json.loads((prep_dir / "script.json").read_text(encoding="utf-8"))
    qc_report = verify_video(rendered_mp4, script_metadata=script_meta, project_dir=prep_dir)
    print(f"QC Passed: {qc_report.passed}, Overall Score: {qc_report.checks.get('overall_score')}/10")
    if qc_report.issues:
        print("QC Issues:", qc_report.issues)

    # Extract preview frames
    frames = extract_preview_frames(rendered_mp4, EVAL_DIR / "frames", [2.0, 15.0, 28.0, 42.0])
    return rendered_mp4, qc_report, frames

def produce_creator_evaluation_video():
    print("\n" + "=" * 60)
    print("STEP 2: PRODUCING CREATOR STUDIO EVALUATION VIDEO")
    print("=" * 60)

    video_id = "eval_creator_cabin4"
    project_dir = EVAL_DIR / video_id
    output_mp4 = EVAL_DIR / f"{video_id}.mp4"

    # Creator Studio manuscript
    script_data = {
        "title": "The Cabin Four Mystery: Episode 1",
        "category": "MYSTERY",
        "evidence_type": "personal_account",
        "sources": ["Creator Manuscript - Blackwood Forest Series"],
        "style": "inside-out",
        "lead": 0.35,
        "outro": 0.55,
        "voice": "bm_george",
        "lines": [
            {
                "text": "The night watchman at Blackwood Forest had one single rule.",
                "caps": "THE NIGHT WATCHMAN HAD *ONE SINGLE RULE",
                "gap": 0.28,
                "scene": {"visual_type": "tension_room", "headline": "BLACKWOOD OUTPOST", "sublabel": "RESTRICTED ACCESS", "mood": "mystery", "accent": "cyan", "cue": "tock"}
            },
            {
                "text": "Never answer the telephone in cabin four.",
                "caps": "NEVER *ANSWER THE TELEPHONE IN CABIN FOUR",
                "gap": 0.28,
                "scene": {"visual_type": "archive_map", "headline": "FOREST GRID", "sublabel": "CABIN FOUR OUTLINE", "mood": "mystery", "accent": "crimson", "cue": "whoosh"}
            },
            {
                "text": "For thirty-five years, that cabin stood boarded up with iron chains.",
                "caps": "FOR THIRTY-FIVE YEARS *BOARDED WITH IRON CHAINS",
                "gap": 0.26,
                "scene": {"visual_type": "vault_mystery", "headline": "BOARDED FACADE", "sublabel": "HEAVY IRON PADLOCK", "mood": "dark", "accent": "cyan", "cue": "slide"}
            },
            {
                "text": "Yet on a freezing Tuesday in November, the vintage copper bell began to ring.",
                "caps": "THE VINTAGE COPPER BELL *BEGAN TO RING",
                "gap": 0.28,
                "scene": {"visual_type": "radar_scan", "headline": "AUDIO TELEMETRY", "sublabel": "ACOUSTIC SPIKE DETECTED", "mood": "urgent", "accent": "yellow", "cue": "tock"}
            },
            {
                "text": "Officer Miller approached the rusted door with his flashlight trembling in his grip.",
                "caps": "OFFICER MILLER APPROACHED WITH *TREMBLING FLASHLIGHT",
                "gap": 0.26,
                "scene": {"visual_type": "tension_room", "headline": "NIGHT PATROL", "sublabel": "SINGLE FLASHLIGHT BEAM", "mood": "tense", "accent": "yellow", "cue": "slide"}
            },
            {
                "text": "Inside, on a dust-covered desk, sat a handwritten log with today's date and his own name in fresh ink.",
                "caps": "HIS OWN NAME IN *FRESH BLACK INK",
                "gap": 0.28,
                "scene": {"visual_type": "payoff_reveal", "headline": "DESK LEDGER", "sublabel": "FRESH INK ENTRY", "mood": "shock", "accent": "crimson", "cue": "sparkle"}
            },
            {
                "text": "Beside the open journal lay a brass key he had dropped into the river twelve years ago.",
                "caps": "BESIDE IT LAY A *LOST BRASS KEY",
                "gap": 0.26,
                "scene": {"visual_type": "vault_mystery", "headline": "LOST RELIC", "sublabel": "RIVER BED DISCOVERY", "mood": "mystery", "accent": "cyan", "cue": "whoosh"}
            },
            {
                "text": "And that is why the night watchman at Blackwood Forest never answers the telephone in cabin four.",
                "caps": "WHY THE WATCHMAN *NEVER ANSWERS CABIN FOUR",
                "gap": 0.28,
                "scene": {"visual_type": "payoff_reveal", "headline": "THE UNBROKEN RULE", "sublabel": "ECHO RESOLUTION", "mood": "mystery", "accent": "cyan", "cue": "pop"}
            }
        ]
    }

    # Prepare project
    if project_dir.exists():
        shutil.rmtree(project_dir)

    import curiosity_engine.production.director
    orig_output_dir = curiosity_engine.production.director.OUTPUT_DIR
    curiosity_engine.production.director.OUTPUT_DIR = EVAL_DIR
    try:
        prep_dir = prepare_project(video_id, script_data)
    finally:
        curiosity_engine.production.director.OUTPUT_DIR = orig_output_dir

    print("Project prepared at:", prep_dir)

    # Render video
    print("Rendering video via Chromium CDP unbuffered pipe (30fps 1080x1920)...")
    t_render = time.time()
    rendered_mp4 = render_project_video(prep_dir, output_mp4, resume=False, force_rebuild=True)
    print(f"Render completed in {time.time()-t_render:.1f}s -> {rendered_mp4} ({rendered_mp4.stat().st_size} bytes)")

    # Run QC
    print("Running Quality Control Gatekeeper...")
    script_meta = json.loads((prep_dir / "script.json").read_text(encoding="utf-8"))
    qc_report = verify_video(rendered_mp4, script_metadata=script_meta, project_dir=prep_dir)
    print(f"QC Passed: {qc_report.passed}, Overall Score: {qc_report.checks.get('overall_score')}/10")
    if qc_report.issues:
        print("QC Issues:", qc_report.issues)

    # Extract preview frames
    frames = extract_preview_frames(rendered_mp4, EVAL_DIR / "frames", [2.0, 15.0, 28.0, 42.0])
    return rendered_mp4, qc_report, frames

if __name__ == "__main__":
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    import curiosity_engine.production.director
    
    t_start = time.time()
    auto_mp4, auto_qc, auto_frames = produce_automatic_evaluation_video()
    creator_mp4, creator_qc, creator_frames = produce_creator_evaluation_video()
    
    total_time = time.time() - t_start
    print("\n" + "=" * 60)
    print(f"ALL EVALUATION RENDERS COMPLETE IN {total_time:.1f}s")
    print(f"Auto Video:    {auto_mp4} (Passed={auto_qc.passed})")
    print(f"Creator Video: {creator_mp4} (Passed={creator_qc.passed})")
    print("=" * 60)
