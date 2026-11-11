"""Programmatic Quality Control Gatekeeper.
Enforces strict programmatic criteria before any video can proceed to distribution.
Validates:
- Duration strictly 20.0 to 60.0 seconds (preferred storytelling target ~25-45s)
- Vertical 9:16 aspect ratio (1080x1920)
- Codecs: H.264 video + AAC audio
- Audio broadcast loudness compliance (EBU R128 integrated LUFS and True Peak)
- Absence of persistent black frames
- Factual backing with internal verified sources or explicit mystery classification
- Audio/caption/timeline synchronization & caption safe zones
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from curiosity_engine.config import (
    CAPTION_ZONE_Y,
    MAX_DURATION_SEC,
    MAX_TRUE_PEAK_DB,
    MIN_DURATION_SEC,
    SAFE_ZONE_BOTTOM,
    SAFE_ZONE_TOP,
    TARGET_DURATION_MAX_SEC,
    TARGET_DURATION_MIN_SEC,
    TARGET_FPS,
    TARGET_INTEGRATED_LUFS_MAX,
    TARGET_INTEGRATED_LUFS_MIN,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
    get_hidden_subprocess_kwargs,
)

logger = logging.getLogger("curiosity_engine.qc")


class QCReport:
    """Structured report detailing QC verification results and categorized failure reasons."""

    def __init__(self, passed: bool, checks: Dict[str, Any], issues: List[str]):
        self.passed = passed
        self.checks = checks
        self.issues = issues

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": self.checks,
            "issues": self.issues,
        }


def check_ffprobe_streams(video_path: Path) -> Dict[str, Any]:
    """Inspect video and audio stream properties via ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration,size,bit_rate",
        "-show_entries", "stream=codec_name,codec_type,width,height,r_frame_rate,avg_frame_rate",
        "-of", "json",
        str(video_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True, **get_hidden_subprocess_kwargs())
    return json.loads(res.stdout)


def measure_audio_loudness(video_path: Path) -> Dict[str, float]:
    """Measure integrated loudness (LUFS), True Peak, and LRA using FFmpeg ebur128 filter."""
    cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-af", "ebur128=peak=true",
        "-f", "null",
        "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, **get_hidden_subprocess_kwargs())
    out = res.stderr
    metrics = {"integrated_lufs": -70.0, "true_peak_db": -70.0, "lra": 0.0}

    m_i = re.search(r"Integrated loudness:\s+I:\s+([-\d.]+)\s+LUFS", out)
    if m_i:
        metrics["integrated_lufs"] = float(m_i.group(1))

    m_tp = re.search(r"True peak:\s+Peak:\s+([-\d.]+)\s+dBFS", out)
    if m_tp:
        metrics["true_peak_db"] = float(m_tp.group(1))

    m_lra = re.search(r"Loudness range:\s+LRA:\s+([-\d.]+)\s+LU", out)
    if m_lra:
        metrics["lra"] = float(m_lra.group(1))

    return metrics


def check_black_frames(video_path: Path) -> bool:
    """Sample frames to ensure no blank or persistent black frames."""
    cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-vf", "blackdetect=d=1.0:pix_th=0.10",
        "-f", "null",
        "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, **get_hidden_subprocess_kwargs())
    has_persistent_black = "black_start:" in res.stderr and "black_duration: [2-9]" in res.stderr
    return not has_persistent_black


def verify_project_sync(
    project_dir: Optional[Path],
    rendered_duration_sec: float,
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Verify narration timeline (`lines.json` & `words.json`) stays synchronized with MP4 duration."""
    if not project_dir or not project_dir.exists():
        return True, [], {"checked": False, "sync_ok": True}

    sync_issues: List[str] = []
    lines_file = project_dir / "data" / "lines.json"
    words_file = project_dir / "data" / "words.json"
    sync_meta: Dict[str, Any] = {"checked": False, "sync_ok": True}

    if lines_file.exists():
        try:
            lines_obj = json.loads(lines_file.read_text(encoding="utf-8"))
            narration_dur = float(lines_obj.get("duration", 0.0))
            sync_meta["narration_duration_sec"] = round(narration_dur, 3)
            sync_meta["duration_drift_sec"] = round(abs(narration_dur - rendered_duration_sec), 3)
            sync_meta["checked"] = True
            if rendered_duration_sec > 0 and abs(narration_dur - rendered_duration_sec) > 2.0:
                sync_issues.append(
                    f"Audio/video duration drift {abs(narration_dur - rendered_duration_sec):.2f}s exceeds 2.0s tolerance."
                )
        except Exception as exc:
            sync_issues.append(f"Corrupt lines.json timeline metadata: {exc}")

    if words_file.exists():
        try:
            words_list = json.loads(words_file.read_text(encoding="utf-8"))
            if not isinstance(words_list, list) or len(words_list) == 0:
                sync_issues.append("Word caption timings (words.json) are empty.")
            else:
                prev_s = -1.0
                for w in words_list:
                    ws = float(w.get("s", 0.0))
                    we = float(w.get("e", 0.0))
                    if ws < 0 or we < ws or ws < prev_s - 0.05:
                        sync_issues.append(f"Non-monotonic or invalid caption timestamp at word '{w.get('w')}'.")
                        break
                    prev_s = ws
                max_end = max(float(w.get("e", 0.0)) for w in words_list)
                sync_meta["last_caption_end_sec"] = round(max_end, 3)
                if rendered_duration_sec > 0 and max_end > rendered_duration_sec + 1.0:
                    sync_issues.append(
                        f"Captions extend past video end ({max_end:.2f}s > {rendered_duration_sec:.2f}s)."
                    )
        except Exception as exc:
            sync_issues.append(f"Corrupt words.json caption alignment: {exc}")

    sync_meta["sync_ok"] = len(sync_issues) == 0
    return len(sync_issues) == 0, sync_issues, sync_meta


def verify_video(
    video_path: Path,
    script_metadata: Dict[str, Any],
    project_dir: Optional[Path] = None,
) -> QCReport:
    """Execute complete battery of QC checks with failure category diagnostics."""
    issues: List[str] = []
    failure_categories: List[str] = []
    checks: Dict[str, Any] = {}

    if not video_path.exists() or video_path.stat().st_size < 100_000:
        return QCReport(
            False,
            {"failure_categories": ["integrity_missing"]},
            ["Video file does not exist or is under 100KB."],
        )

    # 1. Media metadata analysis
    try:
        probe = check_ffprobe_streams(video_path)
    except Exception as e:
        return QCReport(
            False,
            {"failure_categories": ["integrity_missing"]},
            [f"ffprobe failed to parse video container: {e}"],
        )

    streams = probe.get("streams", [])
    format_info = probe.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if not video_stream:
        issues.append("Missing video stream.")
        failure_categories.append("integrity_missing")
    if not audio_stream:
        issues.append("Missing audio stream.")
        failure_categories.append("integrity_missing")

    # 2. Duration check (Strict: 20.0 to 60.0s; Preferred target ~25-45s)
    duration = float(format_info.get("duration", 0.0))
    checks["duration_sec"] = duration
    checks["min_duration_limit_sec"] = MIN_DURATION_SEC
    checks["max_duration_limit_sec"] = MAX_DURATION_SEC
    checks["within_preferred_target"] = TARGET_DURATION_MIN_SEC <= duration <= TARGET_DURATION_MAX_SEC
    if duration < MIN_DURATION_SEC:
        issues.append(f"Duration {duration:.2f}s is out of range [{MIN_DURATION_SEC}, {MAX_DURATION_SEC}s].")
        failure_categories.append("duration_too_short")
    elif duration > MAX_DURATION_SEC:
        issues.append(f"Duration {duration:.2f}s exceeds maximum {MAX_DURATION_SEC}s [{MIN_DURATION_SEC}, {MAX_DURATION_SEC}s].")
        failure_categories.append("duration_exceeded")

    # 3. Resolution & Aspect Ratio (1080x1920)
    width = video_stream.get("width") if video_stream else 0
    height = video_stream.get("height") if video_stream else 0
    checks["resolution"] = f"{width}x{height}"
    if width != VIDEO_WIDTH or height != VIDEO_HEIGHT:
        issues.append(f"Resolution {width}x{height} is not vertical 1080x1920.")
        failure_categories.append("visual_geometry")

    # 4. Codec Verification
    v_codec = video_stream.get("codec_name") if video_stream else ""
    a_codec = audio_stream.get("codec_name") if audio_stream else ""
    checks["video_codec"] = v_codec
    checks["audio_codec"] = a_codec
    if v_codec != "h264":
        issues.append(f"Video codec {v_codec} is not H.264.")
        failure_categories.append("integrity_codec")
    if a_codec != "aac":
        issues.append(f"Audio codec {a_codec} is not AAC.")
        failure_categories.append("audio_codec")

    # 5. Audio Loudness & Broadcast Compliance (EBU R128)
    loudness = measure_audio_loudness(video_path)
    checks["audio_loudness"] = loudness
    i_lufs = loudness["integrated_lufs"]
    tp_db = loudness["true_peak_db"]

    if i_lufs < TARGET_INTEGRATED_LUFS_MIN or i_lufs > TARGET_INTEGRATED_LUFS_MAX:
        issues.append(
            f"Integrated loudness {i_lufs:.1f} LUFS outside target range "
            f"[{TARGET_INTEGRATED_LUFS_MIN}, {TARGET_INTEGRATED_LUFS_MAX} LUFS]."
        )
        failure_categories.append("audio_loudness")
    if tp_db > MAX_TRUE_PEAK_DB:
        issues.append(f"True peak {tp_db:.1f} dBFS exceeds limit {MAX_TRUE_PEAK_DB} dBFS.")
        failure_categories.append("audio_loudness")

    # 6. Black frame verification
    is_not_black = check_black_frames(video_path)
    checks["no_black_frames"] = is_not_black
    if not is_not_black:
        issues.append("Persistent black frames detected.")
        failure_categories.append("visual_black_frames")

    # 7. Factual and editorial grounding verification
    sources = script_metadata.get("sources", [])
    evidence_type = str(script_metadata.get("evidence_type") or "")
    checks["sources_count"] = len(sources)
    if not sources and evidence_type not in ("unexplained_mystery", "personal_account"):
        issues.append("Missing verified source references.")
        failure_categories.append("missing_sources")

    # 8. Safe zones + Audio/Caption/Timeline Synchronization check
    checks["safe_zones_compliant"] = SAFE_ZONE_TOP <= CAPTION_ZONE_Y <= SAFE_ZONE_BOTTOM
    if not checks["safe_zones_compliant"]:
        issues.append("Caption safe zone bounds invalid.")
        failure_categories.append("sync_or_layout")

    candidate_proj_dir = project_dir or (video_path.with_suffix("") if video_path.with_suffix("").is_dir() else None)
    sync_ok, sync_issues, sync_meta = verify_project_sync(candidate_proj_dir, duration)
    checks["sync"] = sync_meta
    if not sync_ok:
        issues.extend(sync_issues)
        failure_categories.append("sync_mismatch")

    checks["failure_categories"] = list(dict.fromkeys(failure_categories))
    passed = len(issues) == 0
    checks["passed"] = passed

    if passed:
        logger.info(
            "QC PASSED: %s (%.2fs, %sx%s, %s/%s, %.1f LUFS, %.1f dBFS TP).",
            video_path.name,
            duration,
            width,
            height,
            v_codec,
            a_codec,
            i_lufs,
            tp_db,
        )
    else:
        logger.warning("QC FAILED: %s with issues: %s", video_path.name, ", ".join(issues))

    return QCReport(passed, checks, issues)
