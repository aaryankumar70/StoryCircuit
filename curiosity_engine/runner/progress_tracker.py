"""Live Production Stage & ETA Progress Engine for CurioLoop.

Derives real progress, elapsed timings, measurable intra-stage fractions, and
historically grounded ETA estimates from persisted stage states and live render logs.

Design rules:
- Never invents percentages or counts down fake timers.
- Distinguishes Production (Topic -> Script -> Narration -> Visuals -> Render -> QC)
  from Distribution (Private Upload -> Scheduled -> Published).
- Handles QC recovery states explicitly and falls back to 'Estimating remaining time...'
  whenever historical stage duration samples are insufficient.
"""
from __future__ import annotations

import json
import logging
import os
import re
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from curiosity_engine import config
from curiosity_engine.state.db import db

logger = logging.getLogger("curiosity_engine.progress_tracker")

IST = ZoneInfo(config.SCHEDULER_TIMEZONE)
TIMING_HISTORY_FILE = config.DATA_DIR / "stage_timing_history.json"

# Canonical weighted stage definitions (total = 100 across full Production -> Published flow)
PRODUCTION_STAGE_ORDER: Tuple[Tuple[str, str, int], ...] = (
    ("selecting_topic", "Selecting topic", 4),
    ("writing_script", "Writing script", 8),
    ("generating_narration", "Generating narration", 10),
    ("preparing_visuals", "Preparing visuals", 14),
    ("rendering_video", "Rendering video", 48),
    ("running_qc", "Running QC", 6),
)

DISTRIBUTION_STAGE_ORDER: Tuple[Tuple[str, str, int], ...] = (
    ("uploading_privately", "Uploading privately", 6),
    ("scheduling_publication", "Scheduling publication", 4),
    ("published", "Published", 0),
)

ALL_STAGE_WEIGHTS: Dict[str, int] = {
    k: w for k, _, w in (*PRODUCTION_STAGE_ORDER, *DISTRIBUTION_STAGE_ORDER)
}
STAGE_LABELS: Dict[str, str] = {
    k: label for k, label, _ in (*PRODUCTION_STAGE_ORDER, *DISTRIBUTION_STAGE_ORDER)
}
STAGE_LABELS["qc_recovery"] = "QC Recovery"
STAGE_LABELS["not_started"] = "Not started"
STAGE_LABELS["failed"] = "Failed"

_RENDER_FRAME_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s+frames")
MAX_HISTORY_SAMPLES = 25


def _parse_iso(val: Any) -> Optional[datetime]:
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def format_duration_mmss(seconds: Optional[float]) -> str:
    """Format elapsed/remaining seconds compactly as MM:SS or H:MM:SS."""
    if seconds is None or seconds < 0:
        return "--:--"
    total = int(round(seconds))
    hrs, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    if hrs > 0:
        return f"{hrs}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


class StageTimingStore:
    """Persists observed durations of real completed production/distribution stages."""

    def __init__(self, history_file: Optional[Path] = None) -> None:
        self._explicit_file = Path(history_file) if history_file is not None else None

    def _resolve_file(self) -> Path:
        if self._explicit_file is not None:
            p = self._explicit_file
        elif "PYTEST_CURRENT_TEST" in os.environ:
            p = Path(tempfile.gettempdir()) / f"curiosity_test_stage_timings_{os.getpid()}.json"
        else:
            p = TIMING_HISTORY_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _load(self) -> Dict[str, Any]:
        sf = self._resolve_file()
        default = {"stages": {}, "updated_at": None}
        if not sf.exists():
            return default
        try:
            loaded = json.loads(sf.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("stages"), dict):
                default.update(loaded)
                return default
        except Exception:
            pass
        return default

    def _save(self, state: Dict[str, Any]) -> None:
        sf = self._resolve_file()
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        tmp = sf.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, sf)

    def record_stage_duration(
        self,
        stage_key: str,
        duration_sec: float,
        frames_count: Optional[int] = None,
    ) -> None:
        """Record observed wall-clock duration for a genuinely completed stage."""
        if not stage_key or duration_sec <= 0.05:
            return
        state = self._load()
        stages = state.setdefault("stages", {})
        bucket = list(stages.get(stage_key) or [])
        bucket.append(round(float(duration_sec), 3))
        stages[stage_key] = bucket[-MAX_HISTORY_SAMPLES:]

        if stage_key == "rendering_video" and frames_count and frames_count > 30:
            spf = list(stages.get("rendering_sec_per_frame") or [])
            spf.append(round(float(duration_sec) / float(frames_count), 5))
            stages["rendering_sec_per_frame"] = spf[-MAX_HISTORY_SAMPLES:]

        self._save(state)

    def get_stage_estimate(self, stage_key: str, total_frames: Optional[int] = None) -> Optional[float]:
        """Return median historical duration (seconds) for stage, or None when insufficient data."""
        state = self._load()
        stages = state.get("stages", {})
        if stage_key == "rendering_video" and total_frames and total_frames > 0:
            spf_samples = stages.get("rendering_sec_per_frame") or []
            if spf_samples:
                return round(float(statistics.median(spf_samples)) * float(total_frames), 2)
        samples = stages.get(stage_key) or []
        if not samples:
            return None
        return round(float(statistics.median(samples)), 2)


timing_store = StageTimingStore()


def _resolve_store(db_client: Any = None) -> Any:
    """Resolve active DatabaseClient, honoring patched `pipeline.db` in tests cleanly."""
    if db_client is not None:
        return db_client
    pip_mod = sys.modules.get("curiosity_engine.runner.pipeline")
    if pip_mod is not None and getattr(pip_mod, "db", None) is not None:
        return getattr(pip_mod, "db")
    return db


def record_stage_start(
    video_id: str,
    stage_key: str,
    detail: Optional[Dict[str, Any]] = None,
    db_client: Any = None,
    timing: Optional[StageTimingStore] = None,
    now_utc: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Persist real stage transition timestamp without erasing prior completed stages."""
    store = _resolve_store(db_client)
    t_store = timing or timing_store
    rec = store.get_video_record(video_id)
    if not rec:
        return None
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_iso = now.isoformat()

    out = dict(rec)
    progress = dict(out.get("stage_progress") or {})
    completed = list(progress.get("completed_stages") or [])
    stage_starts = dict(progress.get("stage_started_at") or {})
    stage_durations = dict(progress.get("stage_durations_sec") or {})

    prev_stage = progress.get("active_stage")

    # While inside QC recovery, sub-operations (e.g. prepare_visuals, render, qc) update
    # recovery substage telemetry cleanly without erasing the QC Recovery active status.
    if prev_stage == "qc_recovery" and stage_key in (
        "writing_script",
        "generating_narration",
        "preparing_visuals",
        "rendering_video",
        "running_qc",
    ):
        merged_detail = dict(progress.get("stage_detail") or {})
        merged_detail["substage"] = stage_key
        if detail:
            merged_detail.update(detail)
        progress["stage_detail"] = merged_detail
        stage_starts[stage_key] = now_iso
        progress["stage_started_at"] = stage_starts
        out["stage_progress"] = progress
        store.save_video_record(video_id, out)
        return out

    if prev_stage and prev_stage != stage_key and prev_stage != "qc_recovery":
        prev_start_dt = _parse_iso(stage_starts.get(prev_stage))
        if prev_start_dt and prev_stage not in stage_durations:
            dur = max(0.1, (now - prev_start_dt).total_seconds())
            stage_durations[prev_stage] = round(dur, 2)
            t_store.record_stage_duration(prev_stage, dur)
        if prev_stage in ALL_STAGE_WEIGHTS and prev_stage not in completed:
            completed.append(prev_stage)

    if stage_key not in stage_starts or prev_stage != stage_key:
        stage_starts[stage_key] = now_iso
    if not progress.get("job_started_at") or prev_stage == "failed":
        progress["job_started_at"] = now_iso

    progress["active_stage"] = stage_key
    progress["active_stage_started_at"] = stage_starts[stage_key]
    progress["completed_stages"] = completed
    progress["stage_started_at"] = stage_starts
    progress["stage_durations_sec"] = stage_durations
    progress["failed_stage"] = None
    progress["waiting_reason"] = None
    if detail:
        merged_detail = dict(progress.get("stage_detail") or {})
        merged_detail.update(detail)
        progress["stage_detail"] = merged_detail
    elif prev_stage != stage_key:
        progress["stage_detail"] = {}

    out["lifecycle_stage"] = stage_key.upper()
    out["stage_progress"] = progress
    store.save_video_record(video_id, out)
    return out


def complete_qc_recovery(
    video_id: str,
    db_client: Any = None,
    timing: Optional[StageTimingStore] = None,
    now_utc: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Close out QC recovery cleanly and restore normal pipeline progression."""
    store = _resolve_store(db_client)
    t_store = timing or timing_store
    rec = store.get_video_record(video_id)
    if not rec:
        return None
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_iso = now.isoformat()
    progress = dict(rec.get("stage_progress") or {})
    completed = list(progress.get("completed_stages") or [])
    for prod_key, _, _ in PRODUCTION_STAGE_ORDER:
        if prod_key not in completed:
            completed.append(prod_key)
    stage_ends = dict(progress.get("stage_completed_at") or {})
    stage_ends["qc_recovery"] = now_iso
    stage_ends["running_qc"] = now_iso

    rec_start = _parse_iso((progress.get("stage_started_at") or {}).get("qc_recovery"))
    stage_durations = dict(progress.get("stage_durations_sec") or {})
    if rec_start:
        dur = max(0.1, (now - rec_start).total_seconds())
        stage_durations["qc_recovery"] = round(dur, 2)
        t_store.record_stage_duration("qc_recovery", dur)

    progress["active_stage"] = "running_qc"
    progress["completed_stages"] = completed
    progress["stage_completed_at"] = stage_ends
    progress["stage_durations_sec"] = stage_durations
    progress["stage_detail"] = {}
    rec["lifecycle_stage"] = "COMPLETED"
    rec["stage_progress"] = progress
    store.save_video_record(video_id, rec)
    return rec


def record_stage_checkpoint(
    video_id: str,
    stage_key: str,
    fraction: float,
    message: str,
    extra_detail: Optional[Dict[str, Any]] = None,
    db_client: Any = None,
) -> None:
    """Record a measurable intra-stage sub-checkpoint (e.g. align/check/cues/mix)."""
    store = _resolve_store(db_client)
    rec = store.get_video_record(video_id)
    if not rec:
        return
    progress = dict(rec.get("stage_progress") or {})
    detail = dict(progress.get("stage_detail") or {})
    detail["intra_stage_fraction"] = max(0.0, min(0.98, float(fraction)))
    detail["measurable_detail"] = message
    if extra_detail:
        detail.update(extra_detail)
    progress["active_stage"] = progress.get("active_stage") or stage_key
    progress["stage_detail"] = detail
    rec["stage_progress"] = progress
    store.save_video_record(video_id, rec)


def record_stage_complete(
    video_id: str,
    stage_key: str,
    frames_count: Optional[int] = None,
    db_client: Any = None,
    timing: Optional[StageTimingStore] = None,
    now_utc: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Mark a stage completed and persist its true observed duration for future ETAs."""
    store = _resolve_store(db_client)
    t_store = timing or timing_store
    rec = store.get_video_record(video_id)
    if not rec:
        return None
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_iso = now.isoformat()

    progress = dict(rec.get("stage_progress") or {})
    completed = list(progress.get("completed_stages") or [])
    stage_starts = dict(progress.get("stage_started_at") or {})
    stage_ends = dict(progress.get("stage_completed_at") or {})
    stage_durations = dict(progress.get("stage_durations_sec") or {})

    if stage_key in ALL_STAGE_WEIGHTS and stage_key not in completed:
        completed.append(stage_key)
    stage_ends[stage_key] = now_iso

    start_dt = _parse_iso(stage_starts.get(stage_key))
    if start_dt:
        dur = max(0.1, (now - start_dt).total_seconds())
        stage_durations[stage_key] = round(dur, 2)
        t_store.record_stage_duration(stage_key, dur, frames_count=frames_count)

    progress["completed_stages"] = completed
    progress["stage_completed_at"] = stage_ends
    progress["stage_durations_sec"] = stage_durations
    if progress.get("active_stage") == stage_key:
        progress["stage_detail"] = {}

    rec["stage_progress"] = progress
    store.save_video_record(video_id, rec)
    return rec


def record_stage_failed(
    video_id: str,
    stage_key: Optional[str],
    error_message: str,
    db_client: Any = None,
) -> None:
    """Persist failed stage metadata without erasing completed upstream steps."""
    store = _resolve_store(db_client)
    rec = store.get_video_record(video_id)
    if not rec:
        return
    progress = dict(rec.get("stage_progress") or {})
    failed_at = stage_key or progress.get("active_stage") or "unknown"
    progress["failed_stage"] = failed_at
    progress["active_stage"] = "failed"
    progress["error"] = str(error_message or "Production failed")
    progress["failed_at"] = datetime.now(timezone.utc).isoformat()
    rec["lifecycle_stage"] = "FAILED"
    rec["stage_progress"] = progress
    store.save_video_record(video_id, rec)


def parse_live_render_progress(video_id: str, output_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Read tail of output/<video_id>/logs/render.log read-only to measure exact rendered frame progress."""
    if not video_id:
        return None
    root = Path(output_dir) if output_dir else config.OUTPUT_DIR
    log_file = root / Path(video_id).name / "logs" / "render.log"
    if not log_file.is_file():
        return None
    try:
        # Read only up to last 4KB so polling stays instant on disk
        size = log_file.stat().st_size
        with open(log_file, "r", encoding="utf-8", errors="replace") as fh:
            if size > 4096:
                fh.seek(size - 4096)
            tail = fh.read()
    except OSError:
        return None

    matches = _RENDER_FRAME_RE.findall(tail)
    if not matches:
        return None
    done_str, total_str = matches[-1]
    frames_done = int(done_str)
    frames_total = int(total_str)
    if frames_total <= 0:
        return None
    ratio = max(0.0, min(1.0, frames_done / float(frames_total)))
    return {
        "frames_done": frames_done,
        "frames_total": frames_total,
        "fraction": ratio,
        "label": f"{frames_done}/{frames_total} frames",
    }


def _estimate_remaining_eta(
    active_stage: str,
    completed_set: set[str],
    stage_elapsed_sec: Optional[float],
    live_render: Optional[Dict[str, Any]],
    total_frames: Optional[int],
    timing: StageTimingStore,
    phase: str,
) -> Tuple[bool, Optional[float], str]:
    """Compute historically grounded ETA, or honestly report 'Estimating remaining time...'."""
    if phase == "production":
        remaining_keys = [
            k for k, _, _ in PRODUCTION_STAGE_ORDER
            if k not in completed_set
        ]
    elif phase == "recovery":
        # Recovery finishes re-render + QC
        remaining_keys = ["rendering_video", "running_qc"]
    elif phase == "distribution":
        remaining_keys = [
            k for k, _, _ in DISTRIBUTION_STAGE_ORDER
            if k not in completed_set and k != "published"
        ]
    else:
        return False, None, ""

    if not remaining_keys:
        return False, None, "Estimating remaining time..."

    total_eta = 0.0
    for idx, key in enumerate(remaining_keys):
        is_current = (idx == 0 and (key == active_stage or phase == "recovery"))
        # If actively rendering and at least 60 frames completed, derive live speed cleanly
        if key == "rendering_video" and live_render and live_render.get("frames_done", 0) >= 60 and stage_elapsed_sec and stage_elapsed_sec >= 5.0:
            done = live_render["frames_done"]
            total = live_render["frames_total"]
            sec_per_frame = stage_elapsed_sec / float(done)
            hist_dur = timing.get_stage_estimate("rendering_video", total_frames=total)
            if hist_dur and hist_dur > 0:
                hist_spf = hist_dur / float(total)
                sec_per_frame = (sec_per_frame * 0.7) + (hist_spf * 0.3)
            rem = max(0.0, (total - done) * sec_per_frame)
            total_eta += rem
            continue

        est = timing.get_stage_estimate(key, total_frames=total_frames)
        if est is None:
            return False, None, "Estimating remaining time..."
        if is_current and stage_elapsed_sec is not None:
            total_eta += max(0.0, est - stage_elapsed_sec)
        else:
            total_eta += est

    return True, round(total_eta, 1), format_duration_mmss(total_eta)


def build_slot_progress_snapshot(
    slot_index: int,
    video_rec: Optional[Dict[str, Any]],
    sched_slot_rec: Optional[Dict[str, Any]],
    target_time_ist: str,
    automation_enabled: bool = True,
    oauth_paused: bool = False,
    output_dir: Optional[Path] = None,
    timing: Optional[StageTimingStore] = None,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build complete compact slot snapshot separating Production from Distribution cleanly."""
    t_store = timing or timing_store
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)

    # 1. Idle / Not started slot
    if not video_rec:
        if isinstance(sched_slot_rec, dict) and sched_slot_rec.get("generation_status") == "FAILED":
            err = sched_slot_rec.get("error") or "Generation failed"
            return _terminal_failed_snapshot(slot_index, None, err, target_time_ist, completed_set=set())

        waiting_txt = (
            "Paused — automation disabled"
            if not automation_enabled
            else ("Paused — waiting for YouTube OAuth" if oauth_paused else f"Queued for daily run ({target_time_ist})")
        )
        return _idle_snapshot(slot_index, target_time_ist, waiting_txt, paused=(not automation_enabled or oauth_paused))

    vid_id = str(video_rec.get("video_id") or "")
    progress_rec = dict(video_rec.get("stage_progress") or {})
    completed_list = list(progress_rec.get("completed_stages") or [])
    completed_set = set(completed_list)
    stage_durations = dict(progress_rec.get("stage_durations_sec") or {})
    stage_starts = dict(progress_rec.get("stage_started_at") or {})
    stage_detail = dict(progress_rec.get("stage_detail") or {})

    ui_status = str(video_rec.get("ui_status") or "").upper()
    prod_status = str(video_rec.get("production_status") or "PENDING").upper()
    pub_status = str(video_rec.get("publishing_status") or "PENDING").upper()
    life_hint = str(video_rec.get("lifecycle_stage") or "").lower()
    active_hint = str(progress_rec.get("active_stage") or life_hint or "").lower()

    sched_ist = None
    if video_rec.get("scheduled_publish_at"):
        dt = _parse_iso(video_rec.get("scheduled_publish_at"))
        if dt:
            sched_ist = dt.astimezone(IST).strftime("%Y-%m-%d %H:%M IST")

    # Infer completed stages accurately for legacy pre-tracker records
    if video_rec.get("topic") and "selecting_topic" not in completed_set:
        completed_set.add("selecting_topic")
    if (video_rec.get("script") or {}).get("lines") and "writing_script" not in completed_set and prod_status not in ("WRITING_SCRIPT",):
        completed_set.add("writing_script")
    if prod_status == "COMPLETED" and video_rec.get("qc_passed") is True:
        for k, _, _ in PRODUCTION_STAGE_ORDER:
            completed_set.add(k)
    elif prod_status == "RENDERED" and "rendering_video" not in completed_set:
        for k in ("generating_narration", "preparing_visuals", "rendering_video"):
            completed_set.add(k)
    elif prod_status == "ASSETS_READY":
        for k in ("generating_narration",):
            completed_set.add(k)

    # 2. Published Publicly (100% terminal success)
    if ui_status == "PUBLISHED_PUBLIC":
        for k, _, _ in (*PRODUCTION_STAGE_ORDER, *DISTRIBUTION_STAGE_ORDER):
            completed_set.add(k)
        total_elapsed = _compute_job_elapsed(video_rec, progress_rec, now, is_running=False)
        return _completed_snapshot(
            slot_index, video_rec, target_time_ist, completed_set, stage_durations,
            stage="Published",
            stage_id="published",
            phase="completed",
            overall_percent=100,
            progress_mode="complete",
            elapsed_sec=total_elapsed,
            eta_text="Live on YouTube",
            sched_ist=sched_ist,
        )

    # 3. Scheduled (Production 100%, Private Upload + Scheduling Done, waiting release window)
    if ui_status == "SCHEDULED" or (ui_status == "SIMULATED" and video_rec.get("scheduled_publish_at")):
        for k, _, _ in PRODUCTION_STAGE_ORDER:
            completed_set.add(k)
        completed_set.update({"uploading_privately", "scheduling_publication"})
        total_elapsed = _compute_job_elapsed(video_rec, progress_rec, now, is_running=False)
        wait_note = f"Waiting release ({sched_ist or target_time_ist})"
        return _completed_snapshot(
            slot_index, video_rec, target_time_ist, completed_set, stage_durations,
            stage="Scheduled",
            stage_id="scheduled",
            phase="waiting_schedule",
            overall_percent=96,
            progress_mode="waiting",
            elapsed_sec=total_elapsed,
            eta_text=wait_note,
            waiting_state=wait_note,
            sched_ist=sched_ist,
        )

    # 4. QC Recovery in progress
    is_recovering = (
        prod_status in ("RECOVERING", "QC_RECOVERING")
        or active_hint == "qc_recovery"
    )
    if is_recovering:
        live_render = parse_live_render_progress(vid_id, output_dir=output_dir)
        rec_start = _parse_iso(stage_starts.get("qc_recovery") or progress_rec.get("active_stage_started_at") or video_rec.get("updated_at"))
        stage_elapsed = max(0.0, (now - rec_start).total_seconds()) if rec_start else None
        job_elapsed = _compute_job_elapsed(video_rec, progress_rec, now, is_running=True)

        rec_detail = {
            "attempt": int(stage_detail.get("attempt") or video_rec.get("recovery_attempts") or 1),
            "max_attempts": int(stage_detail.get("max_attempts") or config.MAX_QC_RECOVERY_ATTEMPTS),
            "reason": str(stage_detail.get("reason") or video_rec.get("error") or "QC failure"),
            "next_action": str(stage_detail.get("next_action") or "Regenerating failed asset"),
            "substage": str(stage_detail.get("substage") or "preparing_recovery"),
        }
        measurable_pct = None
        measurable_label = rec_detail["substage"].replace("_", " ").title()
        # Honest base weight from upstream completed production (<=84%) plus measurable frame fraction if re-rendering
        base_pct = sum(ALL_STAGE_WEIGHTS.get(k, 0) for k in ("selecting_topic", "writing_script", "generating_narration", "preparing_visuals") if k in completed_set)
        if live_render and rec_detail["substage"] in ("rendering_video", "rendering"):
            measurable_pct = round(live_render["fraction"] * 100.0, 1)
            measurable_label = live_render["label"]
            overall_pct = round(min(89.0, base_pct + ALL_STAGE_WEIGHTS["rendering_video"] * live_render["fraction"]), 1)
            p_mode = "determinate"
        else:
            overall_pct = max(22, min(84, base_pct))
            p_mode = "indeterminate"

        dur_sec = video_rec.get("duration_sec") or (video_rec.get("script") or {}).get("duration")
        est_frames = int(round(float(dur_sec) * 30)) if dur_sec else None
        eta_ok, eta_sec, eta_txt = _estimate_remaining_eta(
            "qc_recovery", completed_set, stage_elapsed, live_render, est_frames, t_store, "recovery"
        )
        return _active_snapshot(
            slot_index=slot_index,
            video_rec=video_rec,
            target_time_ist=target_time_ist,
            completed_set=completed_set,
            stage_durations=stage_durations,
            active_stage="qc_recovery",
            stage_label=f"QC Recovery (Attempt {rec_detail['attempt']}/{rec_detail['max_attempts']})",
            phase="recovery",
            overall_percent=overall_pct,
            progress_mode=p_mode,
            intra_stage_percent=measurable_pct,
            measurable_detail=measurable_label,
            elapsed_sec=job_elapsed,
            stage_elapsed_sec=stage_elapsed,
            eta_available=eta_ok,
            eta_seconds=eta_sec,
            eta_text=eta_txt,
            recovery_detail=rec_detail,
            sched_ist=sched_ist,
        )

    # 5. Terminal Failure
    if ui_status == "FAILED" or prod_status in ("FAILED", "REJECTED_QC") or pub_status in ("FAILED", "PUBLISH_FAILED"):
        failed_stage = progress_rec.get("failed_stage")
        if not failed_stage:
            if prod_status == "REJECTED_QC" or (video_rec.get("qc_passed") is False and (video_rec.get("qc_results") or video_rec.get("local_video_path"))):
                failed_stage = "running_qc"
            elif pub_status in ("FAILED", "PUBLISH_FAILED"):
                failed_stage = "uploading_privately"
            else:
                failed_stage = progress_rec.get("active_stage") or "unknown"
        if failed_stage == "running_qc":
            for k in ("selecting_topic", "writing_script", "generating_narration", "preparing_visuals", "rendering_video"):
                if video_rec.get("local_video_path") or k in completed_set:
                    completed_set.add(k)
        err = video_rec.get("youtube_error") or video_rec.get("error") or "Failed"
        return _terminal_failed_snapshot(
            slot_index, video_rec, err, target_time_ist,
            completed_set=completed_set,
            stage_durations=stage_durations,
            failed_stage=failed_stage,
            elapsed_sec=_compute_job_elapsed(video_rec, progress_rec, now, is_running=False),
            sched_ist=sched_ist,
        )

    # 6. Distribution (after Production COMPLETED & QC passed)
    if (prod_status == "COMPLETED" and video_rec.get("qc_passed")) or active_hint in ("uploading_privately", "scheduling_publication"):
        for k, _, _ in PRODUCTION_STAGE_ORDER:
            completed_set.add(k)

        dist_active = (
            pub_status == "UPLOADING"
            or active_hint in ("uploading_privately", "scheduling_publication")
        )
        if not dist_active and pub_status in ("PENDING", "GENERATED") and not video_rec.get("youtube_upload_id"):
            total_elapsed = _compute_job_elapsed(video_rec, progress_rec, now, is_running=False)
            wait_note = (
                "Paused — waiting for YouTube OAuth"
                if oauth_paused
                else "Production complete — awaiting upload window"
            )
            return _completed_snapshot(
                slot_index, video_rec, target_time_ist, completed_set, stage_durations,
                stage="Ready to upload",
                stage_id="uploading_privately",
                phase="waiting_distribution",
                overall_percent=90,
                progress_mode="waiting",
                elapsed_sec=total_elapsed,
                eta_text=wait_note,
                waiting_state=wait_note,
                sched_ist=sched_ist,
            )

        if active_hint == "scheduling_publication" or pub_status == "UPLOADED_PRIVATE" or ui_status == "UPLOADED_PRIVATE":
            completed_set.add("uploading_privately")
            cur_stage = "scheduling_publication"
            wait_note = str(progress_rec.get("waiting_reason") or "Confirming YouTube publish schedule")
        else:
            cur_stage = "uploading_privately"
            wait_note = "Uploading video stream to YouTube"

        st_start = _parse_iso(stage_starts.get(cur_stage) or video_rec.get("updated_at"))
        stage_elapsed = max(0.0, (now - st_start).total_seconds()) if st_start else None
        job_elapsed = _compute_job_elapsed(video_rec, progress_rec, now, is_running=True)
        done_pct = sum(ALL_STAGE_WEIGHTS.get(k, 0) for k in completed_set)
        if oauth_paused:
            eta_ok, eta_sec, eta_txt = False, None, "Paused — waiting for YouTube OAuth"
            p_mode = "waiting"
        else:
            eta_ok, eta_sec, eta_txt = _estimate_remaining_eta(
                cur_stage, completed_set, stage_elapsed, None, None, t_store, "distribution"
            )
            p_mode = "indeterminate"
            wait_note = None if cur_stage == "uploading_privately" else wait_note

        return _active_snapshot(
            slot_index=slot_index,
            video_rec=video_rec,
            target_time_ist=target_time_ist,
            completed_set=completed_set,
            stage_durations=stage_durations,
            active_stage=cur_stage,
            stage_label=STAGE_LABELS.get(cur_stage, "Uploading privately"),
            phase="distribution",
            overall_percent=min(95, done_pct),
            progress_mode=p_mode,
            intra_stage_percent=None,
            measurable_detail=wait_note,
            elapsed_sec=job_elapsed,
            stage_elapsed_sec=stage_elapsed,
            eta_available=eta_ok,
            eta_seconds=eta_sec,
            eta_text=eta_txt,
            waiting_state=wait_note if oauth_paused else None,
            sched_ist=sched_ist,
        )

    # 7. Active Production Stage (Selecting Topic -> Running QC)
    cur_stage = _resolve_active_production_stage(prod_status, active_hint, completed_set)
    # Enforce monotonicity: nothing after cur_stage is marked completed in active normal production
    order_keys = [k for k, _, _ in PRODUCTION_STAGE_ORDER]
    if cur_stage in order_keys:
        cur_idx = order_keys.index(cur_stage)
        for prior_k in order_keys[:cur_idx]:
            completed_set.add(prior_k)
        for future_k in order_keys[cur_idx:]:
            completed_set.discard(future_k)

    st_start = _parse_iso(stage_starts.get(cur_stage) or progress_rec.get("active_stage_started_at") or video_rec.get("updated_at"))
    stage_elapsed = max(0.0, (now - st_start).total_seconds()) if st_start else None
    job_elapsed = _compute_job_elapsed(video_rec, progress_rec, now, is_running=True)

    live_render = parse_live_render_progress(vid_id, output_dir=output_dir) if cur_stage == "rendering_video" else None
    done_pct = sum(ALL_STAGE_WEIGHTS.get(k, 0) for k in completed_set)

    intra_pct: Optional[float] = None
    measurable_msg: Optional[str] = stage_detail.get("measurable_detail")
    p_mode = "indeterminate"
    overall_pct = float(done_pct)

    if cur_stage == "rendering_video" and live_render and live_render.get("frames_done", 0) > 0:
        intra_pct = round(live_render["fraction"] * 100.0, 1)
        measurable_msg = live_render["label"]
        overall_pct = round(min(84.0, done_pct + ALL_STAGE_WEIGHTS["rendering_video"] * live_render["fraction"]), 1)
        p_mode = "determinate"
    elif cur_stage == "preparing_visuals" and stage_detail.get("intra_stage_fraction") is not None:
        frac = float(stage_detail["intra_stage_fraction"])
        intra_pct = round(frac * 100.0, 1)
        overall_pct = round(min(35.0, done_pct + ALL_STAGE_WEIGHTS["preparing_visuals"] * frac), 1)
        p_mode = "determinate"

    dur_sec = video_rec.get("duration_sec") or (video_rec.get("script") or {}).get("duration")
    est_frames = (live_render or {}).get("frames_total") or (int(round(float(dur_sec) * 30)) if dur_sec else None)
    eta_ok, eta_sec, eta_txt = _estimate_remaining_eta(
        cur_stage, completed_set, stage_elapsed, live_render, est_frames, t_store, "production"
    )

    return _active_snapshot(
        slot_index=slot_index,
        video_rec=video_rec,
        target_time_ist=target_time_ist,
        completed_set=completed_set,
        stage_durations=stage_durations,
        active_stage=cur_stage,
        stage_label=STAGE_LABELS.get(cur_stage, cur_stage),
        phase="production",
        overall_percent=overall_pct,
        progress_mode=p_mode,
        intra_stage_percent=intra_pct,
        measurable_detail=measurable_msg,
        elapsed_sec=job_elapsed,
        stage_elapsed_sec=stage_elapsed,
        eta_available=eta_ok,
        eta_seconds=eta_sec,
        eta_text=eta_txt,
        sched_ist=sched_ist,
    )


def _resolve_active_production_stage(prod_status: str, active_hint: str, completed_set: set[str]) -> str:
    if active_hint in ALL_STAGE_WEIGHTS:
        return active_hint
    mapping = {
        "STARTING": "selecting_topic" if "selecting_topic" not in completed_set else "writing_script",
        "SELECTING_TOPIC": "selecting_topic",
        "WRITING_SCRIPT": "writing_script",
        "SCRIPTED": "generating_narration",
        "ASSETS_READY": "preparing_visuals",
        "RENDERING": "rendering_video",
        "RENDERED": "running_qc",
        "QC_RUNNING": "running_qc",
        "RUNNING_QC": "running_qc",
    }
    return mapping.get(prod_status, "selecting_topic")


def _compute_job_elapsed(
    video_rec: Dict[str, Any],
    progress_rec: Dict[str, Any],
    now: datetime,
    is_running: bool = False,
) -> Optional[float]:
    start_dt = _parse_iso(progress_rec.get("job_started_at") or progress_rec.get("active_stage_started_at"))
    if not start_dt:
        return None
    end_dt = _parse_iso(
        (progress_rec.get("stage_completed_at") or {}).get("running_qc")
        or progress_rec.get("failed_at")
    )
    if not is_running and end_dt is None:
        return None
    ref_dt = end_dt if (not is_running and end_dt is not None) else now
    diff = (ref_dt - start_dt).total_seconds()
    return max(0.0, round(diff, 1)) if diff >= 0 else None


def _build_stage_arrays(
    completed_set: set[str],
    active_stage: Optional[str],
    failed_stage: Optional[str],
    stage_durations: Dict[str, float],
    phase: str,
    sched_ist: Optional[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    prod_stages = []
    for k, label, _ in PRODUCTION_STAGE_ORDER:
        if failed_stage == k:
            st = "failed"
        elif k in completed_set:
            st = "completed"
        elif active_stage == k or (active_stage == "qc_recovery" and k == "running_qc"):
            st = "recovery" if active_stage == "qc_recovery" else "active"
        else:
            st = "pending"
        prod_stages.append({
            "stage_id": k,
            "label": label,
            "status": st,
            "duration_sec": stage_durations.get(k),
        })

    dist_stages = []
    for k, label, _ in DISTRIBUTION_STAGE_ORDER:
        if failed_stage == k:
            st = "failed"
        elif k in completed_set:
            st = "completed"
        elif active_stage == k:
            st = "active"
        elif (phase == "waiting_schedule" and k == "published") or (phase == "waiting_distribution" and k == "uploading_privately"):
            st = "waiting"
        else:
            st = "pending"
        dist_stages.append({
            "stage_id": k,
            "label": label,
            "status": st,
            "detail": sched_ist if k in ("scheduling_publication", "published") and sched_ist else None,
        })

    return prod_stages, dist_stages


def _base_meta(slot_index: int, video_rec: Optional[Dict[str, Any]], target_time_ist: str, sched_ist: Optional[str]) -> Dict[str, Any]:
    return {
        "slot_index": slot_index,
        "slot_label": f"Slot {slot_index}",
        "target_time_ist": target_time_ist,
        "video_id": video_rec.get("video_id") if video_rec else None,
        "topic": video_rec.get("topic") if video_rec else None,
        "title": (video_rec.get("youtube_title") or (video_rec.get("script") or {}).get("title") or video_rec.get("topic")) if video_rec else None,
        "category": video_rec.get("category") if video_rec else None,
        "style": video_rec.get("style") if video_rec else None,
        "duration_sec": video_rec.get("duration_sec") if video_rec else None,
        "recovery_attempts": int((video_rec or {}).get("recovery_attempts") or 0),
        "max_recovery_attempts": config.MAX_QC_RECOVERY_ATTEMPTS,
        "youtube_id": (video_rec or {}).get("youtube_upload_id"),
        "scheduled_publish_at_ist": sched_ist,
        "error": (video_rec or {}).get("youtube_error") or (video_rec or {}).get("error"),
        "has_local_mp4": bool((video_rec or {}).get("has_local_mp4", False)),
        "local_file_cleaned": bool((video_rec or {}).get("local_file_cleaned", False)),
    }


def _idle_snapshot(slot_index: int, target_time_ist: str, waiting_txt: str, paused: bool = False) -> Dict[str, Any]:
    prod, dist = _build_stage_arrays(set(), None, None, {}, "paused" if paused else "idle", None)
    return {
        **_base_meta(slot_index, None, target_time_ist, None),
        "stage": "Not started",
        "stage_id": "not_started",
        "stage_label": "Paused" if paused else "Not started",
        "phase": "paused" if paused else "idle",
        "is_active": False,
        "overall_percent": 0,
        "progress_mode": "waiting",
        "intra_stage_percent": None,
        "measurable_detail": None,
        "elapsed_sec": None,
        "elapsed_formatted": "--:--",
        "eta_available": False,
        "eta_seconds": None,
        "eta_text": waiting_txt,
        "waiting_state": waiting_txt,
        "recovery_detail": None,
        "production_complete": False,
        "production_stages": prod,
        "distribution_stages": dist,
    }


def _active_snapshot(
    slot_index: int,
    video_rec: Dict[str, Any],
    target_time_ist: str,
    completed_set: set[str],
    stage_durations: Dict[str, float],
    active_stage: str,
    stage_label: str,
    phase: str,
    overall_percent: float,
    progress_mode: str,
    intra_stage_percent: Optional[float],
    measurable_detail: Optional[str],
    elapsed_sec: Optional[float],
    stage_elapsed_sec: Optional[float],
    eta_available: bool,
    eta_seconds: Optional[float],
    eta_text: str,
    waiting_state: Optional[str] = None,
    recovery_detail: Optional[Dict[str, Any]] = None,
    sched_ist: Optional[str] = None,
) -> Dict[str, Any]:
    prod, dist = _build_stage_arrays(completed_set, active_stage, None, stage_durations, phase, sched_ist)
    return {
        **_base_meta(slot_index, video_rec, target_time_ist, sched_ist),
        "stage": stage_label,
        "stage_id": active_stage,
        "stage_label": stage_label,
        "phase": phase,
        "is_active": True,
        "overall_percent": int(round(min(99.0, max(0.0, overall_percent)))),
        "progress_mode": progress_mode,
        "intra_stage_percent": intra_stage_percent,
        "measurable_detail": measurable_detail,
        "elapsed_sec": elapsed_sec,
        "elapsed_formatted": format_duration_mmss(elapsed_sec),
        "stage_elapsed_sec": round(stage_elapsed_sec, 1) if stage_elapsed_sec is not None else None,
        "eta_available": eta_available,
        "eta_seconds": eta_seconds,
        "eta_text": eta_text,
        "waiting_state": waiting_state,
        "recovery_detail": recovery_detail,
        "production_complete": all(k in completed_set for k, _, _ in PRODUCTION_STAGE_ORDER),
        "production_stages": prod,
        "distribution_stages": dist,
    }


def _completed_snapshot(
    slot_index: int,
    video_rec: Dict[str, Any],
    target_time_ist: str,
    completed_set: set[str],
    stage_durations: Dict[str, float],
    stage: str,
    stage_id: str,
    phase: str,
    overall_percent: int,
    progress_mode: str,
    elapsed_sec: Optional[float],
    eta_text: str,
    waiting_state: Optional[str] = None,
    sched_ist: Optional[str] = None,
) -> Dict[str, Any]:
    prod, dist = _build_stage_arrays(completed_set, None, None, stage_durations, phase, sched_ist)
    return {
        **_base_meta(slot_index, video_rec, target_time_ist, sched_ist),
        "stage": stage,
        "stage_id": stage_id,
        "stage_label": stage,
        "phase": phase,
        "is_active": False,
        "overall_percent": overall_percent,
        "progress_mode": progress_mode,
        "intra_stage_percent": None,
        "measurable_detail": None,
        "elapsed_sec": elapsed_sec,
        "elapsed_formatted": format_duration_mmss(elapsed_sec),
        "eta_available": False,
        "eta_seconds": None,
        "eta_text": eta_text,
        "waiting_state": waiting_state,
        "recovery_detail": None,
        "production_complete": True,
        "production_stages": prod,
        "distribution_stages": dist,
    }


def _terminal_failed_snapshot(
    slot_index: int,
    video_rec: Optional[Dict[str, Any]],
    error_msg: str,
    target_time_ist: str,
    completed_set: set[str],
    stage_durations: Optional[Dict[str, float]] = None,
    failed_stage: Optional[str] = None,
    elapsed_sec: Optional[float] = None,
    sched_ist: Optional[str] = None,
) -> Dict[str, Any]:
    prod, dist = _build_stage_arrays(completed_set, None, failed_stage, stage_durations or {}, "failed", sched_ist)
    stopped_pct = min(95, sum(ALL_STAGE_WEIGHTS.get(k, 0) for k in completed_set))
    fail_label = STAGE_LABELS.get(failed_stage or "", "Production")
    return {
        **_base_meta(slot_index, video_rec, target_time_ist, sched_ist),
        "stage": "Failed after retries",
        "stage_id": "failed",
        "stage_label": f"Failed at {fail_label}",
        "failed_stage": failed_stage,
        "phase": "failed",
        "is_active": False,
        "overall_percent": stopped_pct,
        "progress_mode": "failed",
        "intra_stage_percent": None,
        "measurable_detail": None,
        "elapsed_sec": elapsed_sec,
        "elapsed_formatted": format_duration_mmss(elapsed_sec),
        "eta_available": False,
        "eta_seconds": None,
        "eta_text": f"Stopped at {fail_label}",
        "waiting_state": None,
        "recovery_detail": None,
        "production_complete": all(k in completed_set for k, _, _ in PRODUCTION_STAGE_ORDER),
        "error": error_msg,
        "production_stages": prod,
        "distribution_stages": dist,
    }
