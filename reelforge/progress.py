"""Real-time production and distribution stage progress tracking for StoryCircuit."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

PRODUCTION_STAGES: Tuple[Tuple[str, str], ...] = (
    ("selecting_topic", "Topic"),
    ("writing_script", "Script"),
    ("generating_narration", "Narration"),
    ("preparing_music", "Music"),
    ("resolving_visuals", "Visuals"),
    ("rendering_video", "Render"),
    ("running_qc", "QC"),
)

DISTRIBUTION_STAGES: Tuple[Tuple[str, str], ...] = (
    ("uploading", "Upload"),
    ("scheduled", "Scheduled"),
)

STAGE_ORDER: List[str] = [k for k, _ in (*PRODUCTION_STAGES, *DISTRIBUTION_STAGES)]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def format_elapsed(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    total = int(round(seconds))
    hrs, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    if hrs > 0:
        return f"{hrs}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def build_progress_payload(
    *,
    stage: str,
    stage_label: str,
    percent: int,
    detail: str = "",
    started_at: Optional[str] = None,
    completed_stages: Optional[List[str]] = None,
    failed_stage: Optional[str] = None,
) -> Dict[str, Any]:
    now = _utc_now()
    return {
        "stage": stage,
        "stage_label": stage_label,
        "percent": max(0, min(100, int(percent))),
        "detail": detail,
        "started_at": started_at or now,
        "updated_at": now,
        "completed_stages": list(completed_stages or []),
        "failed_stage": failed_stage,
    }


def _stage_pips_for_job(job: Optional[Dict[str, Any]]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    if not job:
        return (
            [{"key": k, "label": lbl, "status": "pending"} for k, lbl in PRODUCTION_STAGES],
            [{"key": k, "label": lbl, "status": "pending"} for k, lbl in DISTRIBUTION_STAGES],
        )

    status = str(job.get("status") or "planned")
    prog = job.get("progress") or {}
    cur_stage = str(prog.get("stage") or "")
    done_set = set(prog.get("completed_stages") or [])
    failed_stage = prog.get("failed_stage")

    # Backfill completed stages for legacy jobs without progress_json
    if not prog:
        if status in {"qc_passed", "uploaded", "scheduled"}:
            done_set = {k for k, _ in PRODUCTION_STAGES}
        if status == "uploaded":
            done_set.add("uploading")
        elif status == "scheduled":
            done_set.update({"uploading", "scheduled"})
        elif status == "qc_failed":
            done_set = {k for k, _ in PRODUCTION_STAGES[:-1]}
            failed_stage = "running_qc"

    def _map(stages: Tuple[Tuple[str, str], ...]) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for key, lbl in stages:
            if failed_stage == key or (status in {"failed", "qc_failed"} and cur_stage == key):
                st = "failed"
            elif key in done_set:
                st = "completed"
            elif cur_stage == key and status in {"rendering", "uploading"}:
                st = "active"
            elif key == "scheduled" and status == "qc_passed":
                st = "waiting"
            else:
                st = "pending"
            out.append({"key": key, "label": lbl, "status": st})
        return out

    return _map(PRODUCTION_STAGES), _map(DISTRIBUTION_STAGES)


def summarize_job_progress(job: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize any job into a UI-ready progress & stage-pip snapshot."""
    if not job:
        prod_pips, dist_pips = _stage_pips_for_job(None)
        return {
            "phase": "idle",
            "stage": "not_started",
            "stage_label": "Waiting for run",
            "percent": 0,
            "detail": "",
            "is_active": False,
            "elapsed_formatted": "--:--",
            "production_stages": prod_pips,
            "distribution_stages": dist_pips,
        }

    status = str(job.get("status") or "planned")
    prog = job.get("progress") or {}
    prod_pips, dist_pips = _stage_pips_for_job(job)

    started_dt = _parse_iso(prog.get("started_at") or job.get("created_at"))
    updated_dt = _parse_iso(prog.get("updated_at") or job.get("updated_at"))
    is_active = status in {"rendering", "uploading"}
    end_dt = datetime.now(timezone.utc) if is_active else (updated_dt or datetime.now(timezone.utc))
    elapsed_sec = (end_dt - started_dt).total_seconds() if started_dt else None

    if status == "scheduled":
        phase = "waiting_schedule"
        pct = 100
        label = "Scheduled on YouTube"
    elif status == "uploaded":
        phase = "completed"
        pct = 100
        label = "Uploaded (Simulated)" if job.get("simulated") else "Uploaded to YouTube"
    elif status == "qc_passed":
        phase = "waiting_distribution"
        pct = 95
        label = "QC Passed • Ready to upload"
    elif status in {"failed", "qc_failed"}:
        phase = "failed"
        pct = int(prog.get("percent") or 0)
        label = prog.get("stage_label") or ("QC Failed" if status == "qc_failed" else "Pipeline Failed")
    elif is_active:
        phase = "distribution" if status == "uploading" else "production"
        pct = int(prog.get("percent") or 10)
        label = prog.get("stage_label") or "Rendering..."
    else:
        phase = "idle"
        pct = int(prog.get("percent") or 0)
        label = prog.get("stage_label") or status.replace("_", " ").title()

    return {
        "phase": phase,
        "stage": prog.get("stage") or status,
        "stage_label": label,
        "percent": max(0, min(100, pct)),
        "detail": prog.get("detail") or "",
        "is_active": is_active,
        "elapsed_formatted": format_elapsed(elapsed_sec),
        "production_stages": prod_pips,
        "distribution_stages": dist_pips,
    }


def build_slot_timeline(
    today_jobs: List[Dict[str, Any]],
    *,
    slot1_time: str,
    slot2_time: str,
) -> List[Dict[str, Any]]:
    """Build Slot 1 and Slot 2 timeline cards from today's persisted jobs."""
    slot_times = {1: slot1_time, 2: slot2_time}
    by_slot: Dict[int, Dict[str, Any]] = {}
    for j in today_jobs:
        snum = j.get("slot_num")
        if snum in (1, 2):
            by_slot[int(snum)] = j

    timeline: List[Dict[str, Any]] = []
    for snum in (1, 2):
        job = by_slot.get(snum)
        snap = summarize_job_progress(job)
        qc = (job or {}).get("qc") or {}
        checks = qc.get("checks") or {}
        timeline.append(
            {
                "slot_num": snum,
                "slot_label": f"Slot {snum}",
                "target_time": slot_times[snum],
                "job_id": (job or {}).get("id"),
                "title": (job or {}).get("title") or "",
                "status": (job or {}).get("status") or "idle",
                "style": (job or {}).get("style") or "--",
                "duration_sec": checks.get("duration_sec"),
                "youtube_id": (job or {}).get("youtube_id"),
                "youtube_url": (job or {}).get("youtube_url"),
                "publish_at": (job or {}).get("publish_at"),
                "simulated": bool((job or {}).get("simulated", True)),
                "error": (job or {}).get("error") or "",
                **snap,
            }
        )
    return timeline


def build_daily_summary(today_jobs: List[Dict[str, Any]], max_daily: int = 2) -> Dict[str, Any]:
    """Compute daily target progress summary for the top KPI card."""
    slot_jobs: Dict[int, Dict[str, Any]] = {}
    for j in today_jobs:
        snum = j.get("slot_num")
        if snum in (1, 2):
            slot_jobs[int(snum)] = j

    # If manual jobs ran today without slot numbers, still reflect QC/uploads cleanly
    all_today = list(slot_jobs.values()) if slot_jobs else today_jobs
    qc_passed = sum(1 for j in all_today if j.get("status") in {"qc_passed", "uploaded", "scheduled"})
    uploaded = sum(1 for j in all_today if j.get("status") == "uploaded")
    scheduled = sum(1 for j in all_today if j.get("status") == "scheduled")
    failed = sum(1 for j in all_today if j.get("status") in {"failed", "qc_failed"})
    active = sum(1 for j in all_today if j.get("status") in {"rendering", "uploading"})

    done_count = min(max_daily, uploaded + scheduled)
    ready_or_done = min(max_daily, qc_passed)
    remaining = max(0, max_daily - ready_or_done)
    # 50% credit for QC passed, 100% for uploaded/scheduled
    pct = min(100, int(round(((done_count + 0.5 * max(0, ready_or_done - done_count)) / max(1, max_daily)) * 100)))

    return {
        "target": max_daily,
        "completed": done_count,
        "ready_or_done": ready_or_done,
        "qc_passed": qc_passed,
        "uploaded": uploaded,
        "scheduled": scheduled,
        "failed": failed,
        "active": active,
        "remaining": remaining,
        "percent": pct,
    }
