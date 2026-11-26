"""Python bridge to the Chromium Stick-Host + Documentary Infographics + B-Roll Overlay renderer."""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

from reelforge import config
from reelforge.models import StoryPlan, WordTiming

logger = logging.getLogger("reelforge.visuals.scene2d")

_RENDER2D_SCRIPT = Path(__file__).resolve().parent / "render2d.mjs"


def _file_to_data_url(path_str: Optional[str]) -> str:
    if not path_str:
        return ""
    p = Path(path_str)
    if not p.exists() or not p.is_file():
        return ""
    mime, _ = mimetypes.guess_type(str(p))
    if not mime or not mime.startswith("image/"):
        mime = "image/png"
    raw = p.read_bytes()
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _load_character_sprites() -> Dict[str, str]:
    """Load optional custom PNG sprites from assets/character/*.png."""
    sprites: Dict[str, str] = {}
    if config.CHARACTER_DIR.exists():
        for png in sorted(config.CHARACTER_DIR.glob("*.png")):
            sprites[png.stem.lower()] = _file_to_data_url(str(png))
    return sprites


def _prepare_broll_clip(
    src_video: Path,
    out_mp4: Path,
    *,
    frames: int,
    fps: int,
    width: int,
    height: int,
) -> Path:
    """Loop/trim and scale-crop HD stock video B-roll cleanly to exact WxH and exact frame count."""
    exact_dur = frames / float(fps)
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"eq=contrast=1.03:saturation=0.96,"
        f"fps={fps},format=yuv420p"
    )
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-i", str(src_video),
            "-t", f"{exact_dur:.6f}",
            "-vf", vf,
            "-frames:v", str(frames),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "17",
            "-pix_fmt", "yuv420p",
            "-an",
            str(out_mp4),
        ],
        check=True,
        capture_output=True,
        timeout=max(90, int(exact_dur * 10)),
    )
    return out_mp4


def build_scene_manifest(
    plan: StoryPlan,
    words: List[WordTiming],
    *,
    duration_sec: Optional[float] = None,
    segments: Optional[List[Dict]] = None,
) -> Dict:
    total_dur = float(duration_sec or max((b.end_sec for b in plan.beats), default=5.0))
    beats_payload = []
    for b in plan.beats:
        beats_payload.append({
            "index": b.index,
            "speaker": b.speaker,
            "text": b.text,
            "characters": [c.model_dump() for c in b.characters],
            "camera_shot": b.camera_shot,
            "host_appearance": b.host_appearance,
            "callout_title": b.callout_title,
            "callout_stat": b.callout_stat,
            "start_sec": b.start_sec,
            "end_sec": b.end_sec,
            "image_data_url": _file_to_data_url(b.resolved_image_path),
        })
    return {
        "title": plan.title,
        "category": plan.category,
        "style": plan.style.value,
        "width": int(plan.target_width or config.VIDEO_WIDTH),
        "height": int(plan.target_height or config.VIDEO_HEIGHT),
        "fps": int(config.VIDEO_FPS),
        "encode_preset": config.VIDEO_ENCODE_PRESET,
        "encode_crf": config.VIDEO_CRF,
        "duration_sec": round(max(1.0, total_dur), 4),
        "beats": beats_payload,
        "words": [w.model_dump() for w in words],
        "character_sprites": _load_character_sprites(),
        "segments": segments or [],
    }


def render_2d_beat_preview(
    plan: StoryPlan,
    out_png: Path,
    *,
    beat_index: int = 0,
    words: Optional[List[WordTiming]] = None,
    work_dir: Optional[Path] = None,
) -> Path:
    """Render a single high-resolution PNG frame of a Stick-Host / Documentary beat."""
    target_dir = work_dir or out_png.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = target_dir / f"preview_{beat_index:02d}_manifest.json"
    manifest = build_scene_manifest(plan, words or [])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    beat = next((b for b in plan.beats if b.index == beat_index), plan.beats[0] if plan.beats else None)
    sample_t = ((beat.start_sec + beat.end_sec) * 0.5) if beat and beat.end_sec > beat.start_sec else 0.5

    res = subprocess.run(
        [
            "node",
            str(_RENDER2D_SCRIPT),
            "--mode", "frame",
            "--manifest", str(manifest_path),
            "--time", f"{sample_t:.3f}",
            "--out", str(out_png),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if res.returncode != 0:
        raise RuntimeError(f"2D frame render failed ({res.returncode}): {(res.stderr or res.stdout)[-500:]}")
    return out_png


def render_2d_scene_video(
    plan: StoryPlan,
    words: List[WordTiming],
    work_dir: Path,
    out_mp4: Path,
    *,
    duration_sec: float,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> Path:
    """Render all beats (mixing Stick-Host infographics, 2.5D art/archival, and HD B-roll video overlays) into silent H.264 MP4."""
    work_dir.mkdir(parents=True, exist_ok=True)
    width = int(plan.target_width or config.VIDEO_WIDTH)
    height = int(plan.target_height or config.VIDEO_HEIGHT)
    fps = int(config.VIDEO_FPS)
    has_broll = any(b.resolved_video_path and Path(b.resolved_video_path).exists() for b in plan.beats)

    if not has_broll:
        manifest_path = work_dir / "scene_manifest.json"
        manifest = build_scene_manifest(plan, words, duration_sec=duration_sec)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        cmd = ["node", str(_RENDER2D_SCRIPT), "--mode", "video", "--manifest", str(manifest_path), "--out", str(out_mp4)]
        _run_render2d_process(cmd, duration_sec, on_progress)
        return out_mp4

    # Hybrid segment render: B-roll video beats get transparent Stick-Host/HUD overlay; other beats render in contiguous Chromium spans
    seg_dir = work_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    segments: List[Dict] = []
    clip_paths: List[Path] = []
    span_start: Optional[float] = None
    span_end: float = 0.0

    def _flush_span() -> None:
        nonlocal span_start
        if span_start is None:
            return
        frames = max(1, int(round((span_end - span_start) * fps)))
        seg_mp4 = (seg_dir / f"seg_{len(clip_paths):03d}.mp4").resolve()
        segments.append({"start_sec": round(span_start, 4), "frames": frames, "bg_video": None, "out": str(seg_mp4)})
        clip_paths.append(seg_mp4)
        span_start = None

    for b in plan.beats:
        b_start = b.start_sec
        b_end = max(b_start + 0.4, b.end_sec)
        if b.resolved_video_path and Path(b.resolved_video_path).exists():
            _flush_span()
            frames = max(12, int(round((b_end - b_start) * fps)))
            bg_mp4 = _prepare_broll_clip(
                Path(b.resolved_video_path),
                (seg_dir / f"broll_{b.index:03d}.mp4").resolve(),
                frames=frames,
                fps=fps,
                width=width,
                height=height,
            )
            seg_mp4 = (seg_dir / f"seg_{len(clip_paths):03d}.mp4").resolve()
            segments.append({"start_sec": round(b_start, 4), "frames": frames, "bg_video": str(bg_mp4), "out": str(seg_mp4)})
            clip_paths.append(seg_mp4)
        else:
            if span_start is None:
                span_start = b_start
            span_end = b_end
    _flush_span()

    manifest_path = work_dir / "scene_manifest.json"
    manifest = build_scene_manifest(plan, words, duration_sec=duration_sec, segments=segments)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    cmd = ["node", str(_RENDER2D_SCRIPT), "--mode", "segments", "--manifest", str(manifest_path)]
    _run_render2d_process(cmd, duration_sec, on_progress)

    concat_txt = seg_dir / "concat.txt"
    concat_txt.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in clip_paths), encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c", "copy", str(out_mp4)],
        check=True,
        capture_output=True,
        timeout=180,
    )
    return out_mp4


def _run_render2d_process(
    cmd: List[str],
    duration_sec: float,
    on_progress: Optional[Callable[[int, int, str], None]],
) -> None:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    total_timeout = max(300, int(duration_sec * 10))
    try:
        if proc.stdout:
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("PROGRESS ") and on_progress:
                    parts = line.split(" ", 1)[1].split("/")
                    if len(parts) == 2:
                        done, tot = int(parts[0]), max(1, int(parts[1]))
                        on_progress(done, tot, f"Rendering visual frames ({done}/{tot})")
                elif line.startswith("SEGMENT ") and on_progress:
                    parts = line.split(" ", 1)[1].split("/")
                    if len(parts) == 2:
                        done, tot = int(parts[0]), max(1, int(parts[1]))
                        on_progress(done, tot, f"Compositing scene {done}/{tot}")
        stderr_txt = proc.stderr.read() if proc.stderr else ""
        ret = proc.wait(timeout=total_timeout)
        if ret != 0:
            raise RuntimeError(f"2D renderer failed ({ret}): {stderr_txt[-500:]}")
    except subprocess.TimeoutExpired:
        proc.kill()
        raise TimeoutError(f"2D renderer timed out after {total_timeout}s")
