"""Rendering Orchestrator for Curiosity Engine.
Drives Headless Chrome via DevTools Protocol, mixes procedural audio,
streams frames directly to FFmpeg with reliable unbuffered pipes, and
validates rendered MP4 container/stream integrity before completion.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any, Dict, Optional

from curiosity_engine.config import get_chrome_executable

logger = logging.getLogger("curiosity_engine.renderer")

CHECK_TIMEOUT_SEC = 600
CUES_TIMEOUT_SEC = 180
MIX_TIMEOUT_SEC = 180
RENDER_TIMEOUT_SEC = 1800
MIN_VALID_MP4_BYTES = 100_000


def _win_creation_flags() -> int:
    """Return Windows CREATE_NO_WINDOW flag so background pythonw runs don't pop consoles."""
    if sys.platform == "win32":
        return 0x08000000
    return 0


def validate_rendered_mp4(
    mp4_path: Path,
    expected_duration: Optional[float] = None,
    min_bytes: int = MIN_VALID_MP4_BYTES,
) -> Dict[str, Any]:
    """Validate that a rendered MP4 exists, meets minimum size, has valid moov container,
    and contains readable video & audio streams matching expected duration.
    Raises RuntimeError / FileNotFoundError on any validation failure.
    """
    if not mp4_path.exists() or not mp4_path.is_file():
        raise FileNotFoundError(f"Rendered MP4 missing: {mp4_path}")

    size_bytes = mp4_path.stat().st_size
    if size_bytes < min_bytes:
        raise RuntimeError(
            f"Rendered MP4 '{mp4_path.name}' is partial/corrupt ({size_bytes} bytes < {min_bytes} min bytes)."
        )

    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration,size",
        "-show_entries", "stream=codec_name,codec_type,width,height",
        "-of", "json",
        str(mp4_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
            creationflags=_win_creation_flags(),
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"ffprobe timed out inspecting '{mp4_path.name}'") from e
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        raise RuntimeError(
            f"ffprobe rejected '{mp4_path.name}' (corrupt container or missing moov atom): {stderr}"
        ) from e

    try:
        probe = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid ffprobe JSON output for '{mp4_path.name}': {e}") from e

    streams = probe.get("streams", [])
    fmt = probe.get("format", {})
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if not video_stream or not int(video_stream.get("width", 0)) or not int(video_stream.get("height", 0)):
        raise RuntimeError(f"Rendered MP4 '{mp4_path.name}' has no valid video stream.")
    if not audio_stream:
        raise RuntimeError(f"Rendered MP4 '{mp4_path.name}' has no valid audio stream.")

    duration = float(fmt.get("duration", 0.0) or 0.0)
    if duration <= 1.0:
        raise RuntimeError(f"Rendered MP4 '{mp4_path.name}' has invalid duration ({duration:.2f}s).")

    if expected_duration and expected_duration > 1.0:
        diff = abs(duration - expected_duration)
        tol = max(2.0, expected_duration * 0.15)
        if diff > tol:
            raise RuntimeError(
                f"Rendered MP4 '{mp4_path.name}' duration {duration:.2f}s does not match expected {expected_duration:.2f}s (diff {diff:.2f}s)."
            )

    return {
        "size_bytes": size_bytes,
        "duration": duration,
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "video_codec": video_stream.get("codec_name"),
        "audio_codec": audio_stream.get("codec_name"),
    }


def _cleanup_partial_renders(project_dir: Path, output_mp4: Path, target_name: str) -> None:
    """Remove partial or corrupt temporary render files."""
    renders_dir = project_dir / "renders"
    candidates = [
        renders_dir / f".part_{target_name}",
        output_mp4.with_suffix(".tmp.mp4"),
    ]
    # Also check if existing renders/<name>.mp4 is corrupt; remove it if invalid so re-render starts clean
    render_target = renders_dir / target_name
    if render_target.exists():
        try:
            validate_rendered_mp4(render_target)
        except Exception:
            candidates.append(render_target)

    for cand in candidates:
        if cand.exists():
            try:
                cand.unlink()
                logger.info(f"Cleaned partial/corrupt render artifact: {cand}")
            except Exception as e:
                logger.warning(f"Could not delete partial render {cand}: {e}")


def _is_valid_mix_wav(mix_path: Path, expected_dur: float) -> bool:
    """Return True if data/mix.wav exists, parses cleanly, and matches expected duration."""
    if not mix_path.exists() or mix_path.stat().st_size < 10_000:
        return False
    try:
        with wave.open(str(mix_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate <= 0:
                return False
            wav_dur = frames / float(rate)
            return abs(wav_dur - expected_dur) <= max(1.5, expected_dur * 0.1)
    except Exception:
        return False


def _run_subprocess_logged(
    cmd: list[str],
    cwd: Path,
    env: Dict[str, str],
    log_path: Path,
    timeout_sec: int,
    step_name: str,
) -> None:
    """Execute a subprocess writing combined stdout/stderr to log_path, enforcing timeout and non-zero exit handling."""
    try:
        with open(log_path, "w", encoding="utf-8") as lf:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=lf,
                stderr=subprocess.STDOUT,
                timeout=timeout_sec,
                creationflags=_win_creation_flags(),
            )
    except subprocess.TimeoutExpired as e:
        tail = ""
        if log_path.exists():
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-1000:]
        logger.error(f"{step_name} timed out after {timeout_sec}s.\n{tail}")
        raise RuntimeError(f"{step_name} timed out after {timeout_sec}s: {tail}") from e

    if proc.returncode != 0:
        err_text = ""
        if log_path.exists():
            err_text = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        logger.error(f"{step_name} failed (exit={proc.returncode}):\n{err_text}")
        raise RuntimeError(f"{step_name} failed (exit={proc.returncode}): {err_text}")


def render_project_video(
    project_dir: Path,
    output_mp4: Path,
    resume: bool = True,
    force_rebuild: bool = False,
) -> Path:
    """Execute render pipeline: check -> cues -> mix -> video MP4 -> validate -> atomic copy.
    When resume=True and not force_rebuild, safely reuses verified pre-render artifacts
    (CHECK OK, valid cues.json, valid mix.wav, or already-valid renders/<name>.mp4).
    """
    env = os.environ.copy()
    chrome_bin = get_chrome_executable()
    env["CHROME"] = chrome_bin
    env["SOFTWARE_GL"] = "1"

    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    relative_render_dest = f"renders/{output_mp4.name}"
    rendered_file = project_dir / relative_render_dest
    log_dir = project_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Read duration from data/lines.json
    lines_json_path = project_dir / "data" / "lines.json"
    if not lines_json_path.exists():
        raise FileNotFoundError(f"Missing lines.json in {project_dir}")
    with open(lines_json_path, "r", encoding="utf-8") as f:
        dur = float(json.load(f)["duration"])

    # Clean partial staging/corrupt files before proceeding
    _cleanup_partial_renders(project_dir, output_mp4, output_mp4.name)

    # Fast-path resume if rendered_file already exists AND passes strict MP4 validation
    if resume and not force_rebuild and rendered_file.exists():
        try:
            meta = validate_rendered_mp4(rendered_file, expected_duration=dur)
            logger.info(
                f"Reusing already-valid rendered MP4 at {rendered_file} "
                f"({meta['size_bytes']:,} bytes, {meta['duration']:.2f}s)."
            )
            staging_mp4 = output_mp4.with_suffix(".tmp.mp4")
            if rendered_file.resolve() != output_mp4.resolve():
                shutil.copy2(rendered_file, staging_mp4)
                validate_rendered_mp4(staging_mp4, expected_duration=dur)
                staging_mp4.replace(output_mp4)
            return output_mp4
        except Exception as e:
            logger.info(f"Existing rendered file not reusable ({e}); re-rendering.")

    # 1. Capture Check (reuse only if log confirms CHECK OK)
    check_log = log_dir / "check.log"
    check_reusable = (
        resume
        and not force_rebuild
        and check_log.exists()
        and "CHECK OK" in check_log.read_text(encoding="utf-8", errors="replace")
        and "CHECK FAILED" not in check_log.read_text(encoding="utf-8", errors="replace")
    )
    if check_reusable:
        logger.info(f"Visual timeline previously verified (CHECK OK in {check_log}); reusing.")
    else:
        logger.info(f"Checking visual timeline in {project_dir}...")
        _run_subprocess_logged(
            ["node", "tools/capture.mjs", "check"],
            cwd=project_dir,
            env=env,
            log_path=check_log,
            timeout_sec=CHECK_TIMEOUT_SEC,
            step_name="Visual check",
        )
        check_out = check_log.read_text(encoding="utf-8", errors="replace")
        if "CHECK FAILED" in check_out or "CHECK OK" not in check_out:
            raise RuntimeError(f"Visual check failed:\n{check_out[-1500:]}")
        logger.info("Visual timeline verified (CHECK OK).")

    # 2. Extract sound cues
    cues_json_path = project_dir / "data" / "cues.json"
    cues_reusable = False
    if resume and not force_rebuild and cues_json_path.exists():
        try:
            cues_data = json.loads(cues_json_path.read_text(encoding="utf-8"))
            if isinstance(cues_data.get("cues"), list) and abs(float(cues_data.get("duration", 0)) - dur) < 1.0:
                cues_reusable = True
        except Exception:
            cues_reusable = False

    if cues_reusable:
        logger.info("Valid data/cues.json already exists; reusing.")
    else:
        logger.info("Extracting procedural audio cues...")
        _run_subprocess_logged(
            ["node", "tools/capture.mjs", "cues"],
            cwd=project_dir,
            env=env,
            log_path=log_dir / "cues.log",
            timeout_sec=CUES_TIMEOUT_SEC,
            step_name="Cue extraction",
        )

    # 3. Procedural audio mix
    mix_wav_path = project_dir / "data" / "mix.wav"
    if resume and not force_rebuild and _is_valid_mix_wav(mix_wav_path, dur):
        logger.info("Valid data/mix.wav already exists; reusing.")
    else:
        logger.info("Mixing audio bed, sound cues, and narration...")
        _run_subprocess_logged(
            [sys.executable, "tools/mix.py", "."],
            cwd=project_dir,
            env=env,
            log_path=log_dir / "mix.log",
            timeout_sec=MIX_TIMEOUT_SEC,
            step_name="Audio mix",
        )
        if not _is_valid_mix_wav(mix_wav_path, dur):
            raise RuntimeError(f"Audio mix completed without producing a valid mix.wav at {mix_wav_path}")

    # 4. Stream frames to FFmpeg
    logger.info(f"Rendering {dur:.2f}s video ({output_mp4.name})...")
    staging_mp4 = output_mp4.with_suffix(".tmp.mp4")
    try:
        _run_subprocess_logged(
            ["node", "tools/capture.mjs", "video", relative_render_dest, "0", str(dur)],
            cwd=project_dir,
            env=env,
            log_path=log_dir / "render.log",
            timeout_sec=RENDER_TIMEOUT_SEC,
            step_name="Video render",
        )

        # Strict MP4 validation before copying/replacing destination
        meta = validate_rendered_mp4(rendered_file, expected_duration=dur)
        if rendered_file.resolve() != output_mp4.resolve():
            shutil.copy2(rendered_file, staging_mp4)
            validate_rendered_mp4(staging_mp4, expected_duration=dur)
            staging_mp4.replace(output_mp4)
    except Exception:
        if staging_mp4.exists():
            try:
                staging_mp4.unlink()
            except Exception:
                pass
        _cleanup_partial_renders(project_dir, output_mp4, output_mp4.name)
        raise

    logger.info(
        f"Video successfully rendered & validated: {output_mp4} "
        f"({meta['size_bytes']:,} bytes, {meta['duration']:.2f}s, {meta['width']}x{meta['height']})."
    )
    return output_mp4
