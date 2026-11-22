"""Rendering Orchestrator for Curiosity Engine.
Drives Headless Chrome via DevTools Protocol, mixes procedural audio,
streams frames directly to FFmpeg with reliable unbuffered pipes, and
validates rendered MP4 container/stream integrity before completion.
"""
from __future__ import annotations

import json
import hashlib
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("curiosity_engine.renderer")

MIN_VALID_MP4_BYTES = 100_000


def resolve_ffprobe_executable() -> Optional[str]:
    configured = os.environ.get("CURIOLOOP_FFPROBE", "").strip()
    if configured:
        resolved = shutil.which(configured) or (configured if Path(configured).is_file() else None)
        if resolved:
            return resolved
    on_path = shutil.which("ffprobe")
    if on_path:
        return on_path
    ffmpeg = shutil.which(os.environ.get("CURIOLOOP_FFMPEG", "ffmpeg"))
    if ffmpeg:
        sibling = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if sibling.is_file():
            return str(sibling)
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _optional_project_asset_sha(project_dir: Path, relative: str) -> Optional[str]:
    path = project_dir / relative
    if path.is_symlink():
        raise OSError(f"Project asset is a symbolic link: {relative}")
    return _sha256(path) if path.is_file() else None


def render_manifest_path(mp4_path: Path) -> Path:
    return mp4_path.with_suffix(mp4_path.suffix + ".curioloop.json")


def current_render_matches(mp4_path: Path, project_dir: Path) -> bool:
    """Only reuse media when its exact project script and file hash match the manifest."""
    try:
        manifest_path = render_manifest_path(mp4_path)
        marker_path = project_dir / ".curioloop_project.json"
        script_path = project_dir / "script.json"
        if any(path.is_symlink() for path in (mp4_path, manifest_path, marker_path, script_path)) or project_dir.is_symlink():
            return False
        project_hash = _sha256(project_dir / "script.json")
        project = json.loads(marker_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        audio_hash = _optional_project_asset_sha(project_dir, "data/mix.wav")
        lines_hash = _optional_project_asset_sha(project_dir, "data/lines.json")
        words_hash = _optional_project_asset_sha(project_dir, "data/words.json")
        return bool(mp4_path.is_file() and project.get("project_id") == project_dir.name
                    and manifest.get("project_id") == project.get("project_id")
                    and manifest.get("renderer_version") == project.get("renderer_version")
                    and manifest.get("project_script_sha256") == project_hash
                    and manifest.get("source_audio_sha256") == audio_hash
                    and manifest.get("source_lines_sha256") == lines_hash
                    and manifest.get("source_words_sha256") == words_hash
                    and manifest.get("mp4_sha256") == _sha256(mp4_path))
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def write_render_manifest(mp4_path: Path, project_dir: Path, metadata: Dict[str, Any]) -> None:
    """Atomically bind a verified MP4 to the exact normalized project script."""
    marker_path = project_dir / ".curioloop_project.json"
    final = render_manifest_path(mp4_path)
    if any(path.is_symlink() for path in (mp4_path, marker_path, final)) or project_dir.is_symlink():
        raise RuntimeError("Render output, manifest, or project marker cannot be a symbolic link.")
    project = json.loads(marker_path.read_text(encoding="utf-8"))
    if project.get("project_id") != project_dir.name:
        raise RuntimeError("Render project ownership marker does not match its immutable project directory.")
    manifest = {"project_id": project["project_id"], "renderer_version": project.get("renderer_version"),
                "project_script_sha256": _sha256(project_dir / "script.json"), "mp4_sha256": _sha256(mp4_path),
                "source_audio_sha256": _optional_project_asset_sha(project_dir, "data/mix.wav"),
                "source_lines_sha256": _optional_project_asset_sha(project_dir, "data/lines.json"),
                "source_words_sha256": _optional_project_asset_sha(project_dir, "data/words.json"),
                "size_bytes": mp4_path.stat().st_size, "duration_sec": metadata.get("duration"),
                "width": metadata.get("width"), "height": metadata.get("height"), "fps": metadata.get("fps"),
                "verified_at": time.time()}
    staged = final.with_name(f".{final.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    staged.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(staged, final)


def _win_creation_flags() -> int:
    """Return Windows CREATE_NO_WINDOW flag so background pythonw runs don't pop consoles."""
    if sys.platform == "win32":
        return 0x08000000
    return 0


def _terminate_subprocess_tree(proc: subprocess.Popen) -> None:
    """Stop a timed-out worker and its descendants, including headless browsers."""
    if sys.platform == "win32" and proc.poll() is None:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                creationflags=_win_creation_flags(),
            )
        except (OSError, subprocess.SubprocessError):
            pass
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _run_subprocess_logged(
    cmd: list[str],
    cwd: Path,
    env: Dict[str, str],
    log_path: Path,
    timeout_sec: int,
    step_name: str,
    stall_timeout_sec: Optional[int] = None,
) -> None:
    """Run a worker with a bounded timeout, stall detection, and process-tree cleanup.

    Kept as a small utility for existing render orchestration and its watchdog tests.
    The Cartoon 3D capture path uses the same timeout and cleanup rules in its engine.
    """
    timeout = max(1.0, float(timeout_sec))
    stall_timeout = max(1.0, float(stall_timeout_sec)) if stall_timeout_sec is not None else None
    if log_path.is_symlink():
        raise RuntimeError(f"Refusing to follow a symbolic-link subprocess log: {log_path}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=_win_creation_flags(),
        )
        started = time.monotonic()
        last_activity = started
        last_size = -1
        poll_interval = min(1.0, max(0.1, min(timeout, stall_timeout or timeout) / 10.0))
        failure: Optional[str] = None
        while proc.poll() is None:
            time.sleep(poll_interval)
            now = time.monotonic()
            try:
                size = log_path.stat().st_size
            except OSError:
                size = last_size
            if size != last_size:
                last_size = size
                last_activity = now
            if stall_timeout is not None and now - last_activity >= stall_timeout:
                failure = f"{step_name} stalled with no progress for {stall_timeout:g}s"
                break
            if now - started >= timeout:
                failure = f"{step_name} timed out after {timeout:g}s"
                break
        if failure:
            _terminate_subprocess_tree(proc)
        else:
            proc.wait()

    if failure:
        try:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        except OSError:
            tail = ""
        logger.error("%s: %s\n%s", step_name, failure, tail)
        raise RuntimeError(f"{failure}: {tail}")
    if proc.returncode != 0:
        try:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        except OSError:
            tail = ""
        logger.error("%s failed (exit=%s):\n%s", step_name, proc.returncode, tail)
        raise RuntimeError(f"{step_name} failed (exit={proc.returncode}): {tail}")


def _progress_call(fn_name: str, *args: Any, **kwargs: Any) -> None:
    """Invoke progress_tracker helper cleanly without affecting standalone renderer calls."""
    try:
        from curiosity_engine.runner import progress_tracker
        getattr(progress_tracker, fn_name)(*args, **kwargs)
    except Exception:
        pass


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
    if mp4_path.is_symlink():
        raise RuntimeError(f"Rendered MP4 path is a symbolic link and cannot be validated: {mp4_path}")

    size_bytes = mp4_path.stat().st_size
    if size_bytes < min_bytes:
        raise RuntimeError(
            f"Rendered MP4 '{mp4_path.name}' is partial/corrupt ({size_bytes} bytes < {min_bytes} min bytes)."
        )

    ffprobe = resolve_ffprobe_executable()
    if not ffprobe:
        raise RuntimeError("FFprobe is missing; install it beside FFmpeg or set CURIOLOOP_FFPROBE.")
    cmd = [
        ffprobe,
        "-v", "error",
        "-show_entries", "format=duration,size",
        "-show_entries", "stream=codec_name,codec_type,width,height,r_frame_rate,avg_frame_rate",
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

    fps_text = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "0/1"
    try:
        numerator, denominator = fps_text.split("/", 1)
        fps = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        fps = 0.0

    return {
        "size_bytes": size_bytes,
        "duration": duration,
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "fps": fps,
        "video_codec": video_stream.get("codec_name"),
        "audio_codec": audio_stream.get("codec_name"),
    }


def render_project_video(
    project_dir: Path,
    output_mp4: Path,
    resume: bool = True,
    force_rebuild: bool = False,
) -> Path:
    """Execute render pipeline via the active VisualRenderingEngine.
    When resume=True and not force_rebuild, safely reuses verified pre-render artifacts.
    If no visual engine is configured, raises GenerationEngineNotConfiguredError.
    """
    from curiosity_engine.generation import (
        GenerationEngineNotConfiguredError,
        engine_registry,
    )

    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    if output_mp4.exists() and not force_rebuild and not current_render_matches(output_mp4, project_dir):
        raise RuntimeError(
            f"Existing output {output_mp4} is not bound to this project script; it was preserved. "
            "Choose a new output name or explicitly request a rebuild."
        )
    relative_render_dest = f"renders/{output_mp4.name}"
    rendered_file = project_dir / relative_render_dest

    # Read duration from data/lines.json if present
    lines_json_path = project_dir / "data" / "lines.json"
    dur = None
    if lines_json_path.exists():
        try:
            with open(lines_json_path, "r", encoding="utf-8") as f:
                dur = float(json.load(f)["duration"])
        except Exception:
            pass

    # Reuse only a file bound to this exact normalized script and an unchanged file hash.
    if resume and not force_rebuild and current_render_matches(output_mp4, project_dir):
        try:
            meta = validate_rendered_mp4(output_mp4, expected_duration=dur)
            logger.info(
                f"Reusing already-valid rendered MP4 at {output_mp4} "
                f"({meta['size_bytes']:,} bytes, {meta['duration']:.2f}s)."
            )
            return output_mp4
        except Exception:
            pass

    if resume and not force_rebuild and current_render_matches(rendered_file, project_dir):
        try:
            meta = validate_rendered_mp4(rendered_file, expected_duration=dur)
            logger.info(
                f"Reusing already-valid rendered MP4 at {rendered_file} "
                f"({meta['size_bytes']:,} bytes, {meta['duration']:.2f}s)."
            )
            staging_mp4 = output_mp4.with_name(f".{output_mp4.stem}.{os.getpid()}.{uuid.uuid4().hex}.tmp.mp4")
            if rendered_file.resolve() != output_mp4.resolve():
                try:
                    shutil.copy2(rendered_file, staging_mp4)
                    copied_meta = validate_rendered_mp4(staging_mp4, expected_duration=dur)
                    os.replace(staging_mp4, output_mp4)
                    write_render_manifest(output_mp4, project_dir, copied_meta)
                finally:
                    staging_mp4.unlink(missing_ok=True)
            return output_mp4
        except Exception as e:
            logger.info(f"Existing rendered file not reusable ({e}); re-rendering.")

    engine = engine_registry.get_visual_engine()
    if not engine.is_configured():
        raise GenerationEngineNotConfiguredError(
            "Visual rendering engine is not configured. "
            "Please register a VisualRenderingEngine with engine_registry."
        )

    rendered = engine.render_video(
        project_dir=project_dir,
        output_mp4=output_mp4,
        resume=resume,
        force_rebuild=force_rebuild,
    )
    meta = validate_rendered_mp4(rendered, expected_duration=dur)
    write_render_manifest(rendered, project_dir, meta)
    return rendered
