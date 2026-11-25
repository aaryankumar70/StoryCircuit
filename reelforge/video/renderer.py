"""Lightweight native FFmpeg renderer for 1080x1920 Shorts (CPU-friendly)."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Callable, List, Optional

from reelforge import config
from reelforge.models import BeatSpec, MotionType, StoryPlan, WordTiming
from reelforge.video.captions import write_word_synced_ass

logger = logging.getLogger("reelforge.video.renderer")


def _zoompan_expr(motion: MotionType, frames: int) -> str:
    fmax = max(1, frames - 1)
    if motion == MotionType.ZOOM_OUT:
        return (
            f"zoompan=z='1.12-0.11*(on/{fmax})':"
            "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT}:fps={config.VIDEO_FPS}"
        )
    if motion == MotionType.PAN_LEFT:
        return (
            "zoompan=z='1.10':"
            f"x='(iw-iw/zoom)*(1-on/{fmax})':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT}:fps={config.VIDEO_FPS}"
        )
    if motion == MotionType.PAN_RIGHT:
        return (
            "zoompan=z='1.10':"
            f"x='(iw-iw/zoom)*(on/{fmax})':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT}:fps={config.VIDEO_FPS}"
        )
    if motion == MotionType.PULSE:
        return (
            "zoompan=z='1.03+0.05*sin(on*0.14)':"
            "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT}:fps={config.VIDEO_FPS}"
        )
    # Default ZOOM_IN
    return (
        f"zoompan=z='1.01+0.11*(on/{fmax})':"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT}:fps={config.VIDEO_FPS}"
    )


def _render_beat_clip(beat: BeatSpec, out_mp4: Path) -> Path:
    if not beat.resolved_image_path:
        raise FileNotFoundError(f"Beat {beat.index} missing resolved image.")
    duration = max(0.6, beat.end_sec - beat.start_sec)
    frames = max(18, int(round(duration * config.VIDEO_FPS)))
    zp = _zoompan_expr(beat.motion, frames)

    # Upscale slightly before zoompan for smooth subpixel motion without high RAM use
    vf = (
        f"scale=1350:2400:flags=lanczos,"
        f"{zp},"
        f"fade=t=in:st=0:d=0.14,"
        f"format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", beat.resolved_image_path,
        "-vf", vf,
        "-t", f"{duration:.3f}",
        "-r", str(config.VIDEO_FPS),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "21",
        "-pix_fmt", "yuv420p",
        "-an",
        str(out_mp4),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    return out_mp4


def render_short_video(
    plan: StoryPlan,
    narration_wav: Path,
    bgm_wav: Path,
    words: List[WordTiming],
    work_dir: Path,
    output_mp4: Path,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> Path:
    """Render all animated beat clips, burn synced captions, mix audio, and produce final MP4."""
    clips_dir = work_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    beat_clips: List[Path] = []
    total_steps = len(plan.beats) + 1
    for idx, beat in enumerate(plan.beats, start=1):
        clip_path = clips_dir / f"clip_{beat.index:02d}.mp4"
        beat_clips.append(_render_beat_clip(beat, clip_path))
        if on_progress:
            on_progress(idx, total_steps, f"Clip {idx}/{len(plan.beats)}")

    concat_txt = clips_dir / "clips_concat.txt"
    concat_txt.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in beat_clips),
        encoding="utf-8",
    )
    video_only = work_dir / "video_silent.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_txt),
            "-c", "copy",
            str(video_only),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )

    ass_path = write_word_synced_ass(words, work_dir / "captions.ass", style=plan.style)
    # Escape colons and single quotes for FFmpeg subtitles filter
    ass_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    # Mix narration (0 dB) + ambient music (-19 dB), then broadcast-normalize to -16 LUFS
    filter_complex = (
        f"[0:v]subtitles='{ass_escaped}',format=yuv420p[vout];"
        f"[1:a]volume=1.0[narr];"
        f"[2:a]volume=0.11[mus];"
        f"[narr][mus]amix=inputs=2:duration=first:dropout_transition=2,"
        f"loudnorm=I={config.TARGET_LUFS}:TP={config.MAX_TRUE_PEAK_DB}:LRA=8[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_only),
        "-i", str(narration_wav),
        "-i", str(bgm_wav),
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        "-ac", "2",
        "-movflags", "+faststart",
        "-shortest",
        str(output_mp4),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    if on_progress:
        on_progress(total_steps, total_steps, "Final mux & loudness")
    return output_mp4
