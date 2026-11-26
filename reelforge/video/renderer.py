"""Unified 2D animated scene + FFmpeg subtitle/loudness mux renderer."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Callable, List, Optional

from reelforge import config
from reelforge.models import StoryPlan, WordTiming
from reelforge.video.captions import write_word_synced_ass
from reelforge.visuals.scene2d import render_2d_scene_video

logger = logging.getLogger("reelforge.video.renderer")


def render_short_video(
    plan: StoryPlan,
    narration_wav: Path,
    bgm_wav: Path,
    words: List[WordTiming],
    work_dir: Path,
    output_mp4: Path,
    duration_sec: Optional[float] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> Path:
    """Render 30 FPS 2D world + character animation, burn word-synced captions, and normalize audio."""
    width = int(plan.target_width or config.VIDEO_WIDTH)
    height = int(plan.target_height or config.VIDEO_HEIGHT)
    est_dur = float(duration_sec or max((b.end_sec for b in plan.beats), default=10.0))

    video_only = work_dir / "video_silent.mp4"

    def _on_2d(done: int, total: int, desc: str) -> None:
        if on_progress:
            on_progress(done, total + 1, desc)

    render_2d_scene_video(
        plan=plan,
        words=words,
        work_dir=work_dir,
        out_mp4=video_only,
        duration_sec=est_dur,
        on_progress=_on_2d,
    )

    ass_path = write_word_synced_ass(
        words,
        work_dir / "captions.ass",
        style=plan.style,
        width=width,
        height=height,
    )
    ass_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

    mux_timeout = max(300, int(est_dur * 5))
    output_mp4.parent.mkdir(parents=True, exist_ok=True)

    filter_complex = (
        f"[0:v]noise=alls=4:allf=t+u,subtitles='{ass_escaped}',format=yuv420p[vout];"
        f"[1:a]volume=1.0[narr];"
        f"[2:a]volume=0.12[mus];"
        f"[narr][mus]amix=inputs=2:duration=first:dropout_transition=2,"
        f"loudnorm=I={config.TARGET_LUFS}:TP={config.MAX_TRUE_PEAK_DB}:LRA=8,"
        f"alimiter=limit=0.89[aout]"
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
        "-preset", config.VIDEO_ENCODE_PRESET,
        "-crf", str(config.VIDEO_CRF),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        "-ac", "2",
        "-movflags", "+faststart",
        "-shortest",
        str(output_mp4),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=mux_timeout)
    if on_progress:
        on_progress(100, 100, "Final mux & loudness")
    return output_mp4


render_video = render_short_video
