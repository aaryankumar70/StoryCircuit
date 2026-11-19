"""Staging, TTS, Whisper alignment, Canvas rendering, and verification for an episode."""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from pathlib import Path

from curiosity_engine.creator_series.renderer_adapter import renderer_adapter
from curiosity_engine.production.aligner import align_narration_words
from curiosity_engine.production.renderer import render_project_video, validate_rendered_mp4
from curiosity_engine.production.tts_engine import synthesize_narration

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_single_render")

PILOT_DIR = Path("output/creator_series_eval/the_scariest_story_ever_told")
RENDERS_DIR = PILOT_DIR / "renders"
RENDERS_DIR.mkdir(parents=True, exist_ok=True)
FRAMES_DIR = PILOT_DIR / "frames"
FRAMES_DIR.mkdir(parents=True, exist_ok=True)

bible = json.loads((PILOT_DIR / "visual_bible.json").read_text("utf-8"))


def render_episode(ep_num: int) -> dict:
    sb_path = PILOT_DIR / "storyboards" / f"ep{ep_num:02d}_storyboard.json"
    storyboard = json.loads(sb_path.read_text("utf-8"))
    ep_id = f"the_scariest_story_ever_told_ep{ep_num:02d}"

    logger.info(f"=== Staging Episode {ep_num}: {storyboard['title']} ===")
    proj_dir, downgrades = renderer_adapter.prepare_creator_project(
        project_id=ep_id,
        storyboard=storyboard,
        bible=bible,
        output_dir=RENDERS_DIR / "staging",
    )

    logger.info("Step 1: Kokoro TTS synthesis...")
    t0 = time.time()
    wav_path = synthesize_narration(proj_dir)
    logger.info(f"Kokoro synthesis completed in {time.time() - t0:.2f}s -> {wav_path}")

    logger.info("Step 2: faster-whisper alignment...")
    t0 = time.time()
    words_path = align_narration_words(proj_dir)
    logger.info(f"Whisper alignment completed in {time.time() - t0:.2f}s -> {words_path}")

    lines_meta = json.loads((proj_dir / "data" / "lines.json").read_text("utf-8"))
    actual_audio_dur = lines_meta.get("duration", 0.0)
    logger.info(f"Audio duration from lines.json: {actual_audio_dur:.2f}s ({len(lines_meta.get('lines', []))} lines)")

    logger.info("Step 3: Headless Chrome Canvas rendering & FFmpeg muxing...")
    out_mp4 = RENDERS_DIR / f"{ep_id}.mp4"
    t0 = time.time()
    render_project_video(proj_dir, out_mp4, resume=False, force_rebuild=True)
    logger.info(f"Video render completed in {time.time() - t0:.2f}s -> {out_mp4}")

    logger.info("Step 4: Strict MP4 validation...")
    meta = validate_rendered_mp4(out_mp4)
    logger.info(f"Validated MP4: {meta['size_bytes']:,} bytes, {meta['duration']:.2f}s, {meta['width']}x{meta['height']}")

    logger.info("Step 5: Extract representative frames...")
    mid_t = str(int(meta["duration"] / 2))
    end_t = str(int(meta["duration"] - 3))
    extracted = []
    for ts in ["2", mid_t, end_t]:
        frame_file = FRAMES_DIR / f"ep{ep_num:02d}_t{ts}s.jpg"
        cmd = ["ffmpeg", "-y", "-ss", ts, "-i", str(out_mp4), "-vframes", "1", "-q:v", "2", str(frame_file)]
        subprocess.run(cmd, capture_output=True, check=True)
        logger.info(f"Extracted frame: {frame_file.name} ({frame_file.stat().st_size:,} bytes)")
        extracted.append(str(frame_file))

    return {
        "episode_num": ep_num,
        "title": storyboard["title"],
        "actual_duration_sec": meta["duration"],
        "size_bytes": meta["size_bytes"],
        "resolution": f"{meta['width']}x{meta['height']}",
        "mp4_path": str(out_mp4),
        "frames": extracted,
    }


if __name__ == "__main__":
    ep_to_render = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    res = render_episode(ep_to_render)
    print(json.dumps(res, indent=2))
