"""Render representative sample episodes for 'The Scariest Story Ever Told' pilot.
Renders Episode 1 (Early), Episode 3 (Middle), and Episode 6 (Late/Final).
Extracts representative frames and validates MP4 containers.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

from curiosity_engine.creator_series.renderer_adapter import renderer_adapter
from curiosity_engine.production.aligner import align_narration_words
from curiosity_engine.production.renderer import render_project_video, validate_rendered_mp4
from curiosity_engine.production.tts_engine import synthesize_narration

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("render_pilot_samples")

PILOT_DIR = Path("output/creator_series_eval/the_scariest_story_ever_told")
RENDERS_DIR = PILOT_DIR / "renders"
RENDERS_DIR.mkdir(parents=True, exist_ok=True)
FRAMES_DIR = PILOT_DIR / "frames"
FRAMES_DIR.mkdir(parents=True, exist_ok=True)

bible = json.loads((PILOT_DIR / "visual_bible.json").read_text("utf-8"))

sample_episodes = [1, 3, 6]
render_results = []

for ep_num in sample_episodes:
    sb_path = PILOT_DIR / "storyboards" / f"ep{ep_num:02d}_storyboard.json"
    storyboard = json.loads(sb_path.read_text("utf-8"))
    ep_id = f"the_scariest_story_ever_told_ep{ep_num:02d}"

    print(f"\n==========================================")
    print(f"Staging & Rendering Episode {ep_num} ({storyboard['title']})...")
    print(f"==========================================")

    proj_dir, downgrades = renderer_adapter.prepare_creator_project(
        project_id=ep_id,
        storyboard=storyboard,
        bible=bible,
        output_dir=RENDERS_DIR / "staging",
    )

    # 1. Kokoro TTS
    t0 = time.time()
    wav_path = synthesize_narration(proj_dir)
    print(f"TTS synthesis done in {time.time() - t0:.2f}s")

    # 2. Whisper alignment
    t0 = time.time()
    words_path = align_narration_words(proj_dir)
    print(f"Whisper alignment done in {time.time() - t0:.2f}s")

    # 3. Canvas rendering & FFmpeg muxing
    out_mp4 = RENDERS_DIR / f"{ep_id}.mp4"
    t0 = time.time()
    render_project_video(proj_dir, out_mp4, resume=False, force_rebuild=True)
    print(f"Video rendered in {time.time() - t0:.2f}s -> {out_mp4}")

    # 4. Strict MP4 validation
    meta = validate_rendered_mp4(out_mp4)
    print(f"Episode {ep_num} validated: {meta['size_bytes']:,} bytes, {meta['duration']:.2f}s, {meta['width']}x{meta['height']}")

    # 5. Extract representative frames (t=2s, mid, end-3s)
    mid_t = str(int(meta["duration"] / 2))
    end_t = str(int(meta["duration"] - 3))
    extracted = []
    for ts in ["2", mid_t, end_t]:
        frame_file = FRAMES_DIR / f"ep{ep_num:02d}_t{ts}s.jpg"
        cmd = ["ffmpeg", "-y", "-ss", ts, "-i", str(out_mp4), "-vframes", "1", "-q:v", "2", str(frame_file)]
        subprocess.run(cmd, capture_output=True, check=True)
        print(f"Extracted frame: {frame_file.name} ({frame_file.stat().st_size:,} bytes)")
        extracted.append(str(frame_file))

    render_results.append({
        "episode_num": ep_num,
        "title": storyboard["title"],
        "actual_duration_sec": meta["duration"],
        "size_bytes": meta["size_bytes"],
        "resolution": f"{meta['width']}x{meta['height']}",
        "mp4_path": str(out_mp4),
        "frames": extracted,
    })

with open(PILOT_DIR / "rendered_samples_inspection.json", "w", encoding="utf-8") as f:
    json.dump(render_results, f, indent=2)

print("\nRepresentative sample episodes (1, 3, 6) rendered, inspected, and saved!")
