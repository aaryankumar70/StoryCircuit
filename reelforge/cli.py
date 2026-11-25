"""Command-line interface for ReelForge."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import uvicorn

from reelforge import config
from reelforge.models import SourceMode
from reelforge.pipeline import run_generation_job
from reelforge.scheduler.daily import publish_job_to_youtube, run_daily_slots, serve_scheduler_loop
from reelforge.storage.db import ReelDatabase


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="reelforge", description="Zero-cost YouTube Shorts studio")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_web = sub.add_parser("web", help="Start the local Web Dashboard")
    p_web.add_argument("--host", default=config.DASHBOARD_HOST)
    p_web.add_argument("--port", type=int, default=config.DASHBOARD_PORT)

    p_gen = sub.add_parser("generate", help="Generate a single Short")
    p_gen.add_argument("--mode", choices=["random", "plan", "custom_script"], default="random")
    p_gen.add_argument("--topic", default="")
    p_gen.add_argument("--category", default="auto")
    p_gen.add_argument("--style", default="auto")
    p_gen.add_argument("--script", default="")
    p_gen.add_argument("--script-file", default="")
    p_gen.add_argument("--visual-mode", default=None)
    p_gen.add_argument("--upload", action="store_true")

    p_plan = sub.add_parser("plan-add", help="Queue a topic/script into the multi-day plan")
    p_plan.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_plan.add_argument("--slot", type=int, choices=[1, 2], default=1)
    p_plan.add_argument("--topic", required=True)
    p_plan.add_argument("--category", default="story")
    p_plan.add_argument("--style", default="auto")
    p_plan.add_argument("--script-file", default="")

    p_daily = sub.add_parser("run-daily", help="Run today's 2-video cycle (Slot 1 & Slot 2)")
    p_daily.add_argument("--date", default=None)
    p_daily.add_argument("--no-upload", action="store_true")
    p_daily.add_argument("--visual-mode", default=None)

    p_sched = sub.add_parser("scheduler", help="Run continuous 2-video/day scheduler daemon")
    p_sched.add_argument("--poll", type=int, default=300)

    p_up = sub.add_parser("upload", help="Upload a QC-passed job to YouTube")
    p_up.add_argument("job_id")
    p_up.add_argument("--live", action="store_true")

    args = parser.parse_args()
    db = ReelDatabase()

    if args.cmd == "web":
        uvicorn.run("reelforge.web.app:app", host=args.host, port=args.port, reload=False)
        return

    if args.cmd == "generate":
        script_txt = args.script
        if args.script_file:
            script_txt = Path(args.script_file).read_text(encoding="utf-8")
        job = run_generation_job(
            db,
            mode=SourceMode(args.mode),
            topic=args.topic,
            category=args.category,
            style=args.style,
            custom_script=script_txt,
            visual_mode=args.visual_mode,
        )
        if args.upload and job.get("status") == "qc_passed":
            publish_job_to_youtube(db, job["id"])
            job = db.get_job(job["id"]) or job
        print(json.dumps({"id": job["id"], "status": job["status"], "title": job["title"], "video_path": job.get("video_path"), "qc": job.get("qc")}, indent=2))
        return

    if args.cmd == "plan-add":
        script_txt = Path(args.script_file).read_text(encoding="utf-8") if args.script_file else ""
        pid = db.add_plan_item(
            planned_date=args.date,
            slot_num=args.slot,
            topic=args.topic,
            category=args.category,
            style=args.style,
            custom_script=script_txt,
        )
        print(f"Queued plan item {pid} for {args.date} slot {args.slot}.")
        return

    if args.cmd == "run-daily":
        jobs = run_daily_slots(db, date_str=args.date, auto_upload=not args.no_upload, visual_mode=args.visual_mode)
        print(json.dumps([{"id": j["id"], "slot": j.get("slot_num"), "status": j["status"], "title": j["title"]} for j in jobs], indent=2))
        return

    if args.cmd == "scheduler":
        serve_scheduler_loop(poll_seconds=args.poll)
        return

    if args.cmd == "upload":
        res = publish_job_to_youtube(db, args.job_id, force_mode="live" if args.live else None)
        print(json.dumps(res, indent=2))
