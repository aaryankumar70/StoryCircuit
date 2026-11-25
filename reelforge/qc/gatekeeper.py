"""Deterministic QC checks before any Short can be queued or uploaded."""
from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from reelforge import config
from reelforge.models import QCReport


def _probe_streams(video_path: Path) -> Dict[str, Any]:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size,bit_rate",
        "-show_entries", "stream=codec_name,codec_type,width,height",
        "-of", "json",
        str(video_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=45)
    return json.loads(res.stdout or "{}")


def _measure_loudness(video_path: Path) -> Dict[str, float]:
    res = subprocess.run(
        ["ffmpeg", "-i", str(video_path), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = res.stderr or ""
    lufs = -70.0
    tp = -70.0
    m_i = re.search(r"Integrated loudness:\s+I:\s+([-\d.]+)\s+LUFS", out)
    if m_i:
        lufs = float(m_i.group(1))
    m_tp = re.search(r"True peak:\s+Peak:\s+([-\d.]+)\s+dBFS", out)
    if m_tp:
        tp = float(m_tp.group(1))
    return {"integrated_lufs": lufs, "true_peak_db": tp}


def _has_black_gaps(video_path: Path) -> bool:
    res = subprocess.run(
        ["ffmpeg", "-i", str(video_path), "-vf", "blackdetect=d=1.0:pix_th=0.10", "-an", "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if res.returncode != 0:
        return True
    durs = [float(v) for v in re.findall(r"black_duration:\s*([0-9]+(?:\.[0-9]+)?)", res.stderr or "")]
    return any(d >= 1.0 for d in durs)


def _has_frozen_segments(video_path: Path) -> bool:
    res = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(video_path), "-vf", "freezedetect=n=-50dB:d=2.5", "-an", "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if res.returncode != 0:
        return True
    durs = [float(v) for v in re.findall(r"freeze_duration:\s*([0-9]+(?:\.[0-9]+)?)", res.stderr or "")]
    return any(d >= 2.5 for d in durs)


def verify_video(
    video_path: Path,
    *,
    words_json_path: Optional[Path] = None,
    min_duration_sec: Optional[float] = None,
    max_duration_sec: Optional[float] = None,
) -> QCReport:
    issues: List[str] = []
    checks: Dict[str, Any] = {}

    if not video_path.exists() or video_path.stat().st_size < 100_000:
        return QCReport(passed=False, checks={"exists": False}, issues=["Video file missing or under 100KB."])

    checks["size_bytes"] = video_path.stat().st_size
    probe = _probe_streams(video_path)
    streams = probe.get("streams", [])
    fmt = probe.get("format", {})

    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if not v_stream:
        issues.append("Missing video stream.")
    if not a_stream:
        issues.append("Missing audio stream.")

    duration = float(fmt.get("duration") or 0.0)
    checks["duration_sec"] = round(duration, 3)
    min_d = min_duration_sec if min_duration_sec is not None else config.MIN_DURATION_SEC
    max_d = max_duration_sec if max_duration_sec is not None else config.MAX_DURATION_SEC
    if not math.isfinite(duration) or duration < min_d or duration > max_d:
        issues.append(f"Duration {duration:.2f}s outside [{min_d:.0f}s, {max_d:.0f}s].")

    w = int((v_stream or {}).get("width") or 0)
    h = int((v_stream or {}).get("height") or 0)
    v_codec = str((v_stream or {}).get("codec_name") or "")
    a_codec = str((a_stream or {}).get("codec_name") or "")
    checks.update({"resolution": f"{w}x{h}", "video_codec": v_codec, "audio_codec": a_codec})

    if w != config.VIDEO_WIDTH or h != config.VIDEO_HEIGHT:
        issues.append(f"Resolution {w}x{h} != {config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT}.")
    if v_codec != "h264":
        issues.append(f"Video codec '{v_codec}' is not h264.")
    if a_codec != "aac":
        issues.append(f"Audio codec '{a_codec}' is not aac.")

    loud = _measure_loudness(video_path)
    checks.update(loud)
    if loud["integrated_lufs"] < -24.0 or loud["integrated_lufs"] > -11.0:
        issues.append(f"Audio loudness {loud['integrated_lufs']:.1f} LUFS out of broadcast range [-24, -11].")
    if loud["true_peak_db"] > 0.0:
        issues.append(f"Audio clipping detected (true peak {loud['true_peak_db']:.2f} dBFS).")

    black_bad = _has_black_gaps(video_path)
    freeze_bad = _has_frozen_segments(video_path)
    checks["black_gap_detected"] = black_bad
    checks["frozen_segment_detected"] = freeze_bad
    if black_bad:
        issues.append("Persistent black frames detected (>= 1.0s).")
    if freeze_bad:
        issues.append("Static frozen segment detected (>= 2.5s).")

    if words_json_path and words_json_path.exists():
        words = json.loads(words_json_path.read_text(encoding="utf-8"))
        checks["word_count"] = len(words)
        if not words:
            issues.append("Caption words.json is empty.")
        else:
            last_end = max(float(item.get("end_sec", 0.0)) for item in words)
            checks["last_caption_end_sec"] = round(last_end, 3)
            if last_end > duration + 1.0:
                issues.append(f"Captions extend past video end ({last_end:.2f}s > {duration:.2f}s).")

    return QCReport(passed=len(issues) == 0, checks=checks, issues=issues)
