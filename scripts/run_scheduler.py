"""Curiosity Engine - Local Autonomous Scheduler CLI Runner.
Usage:
    python scripts/run_scheduler.py --status          # Read-only telemetry & status
    python scripts/run_scheduler.py --dry-run         # Read-only evaluation (zero production/uploads)
    python scripts/run_scheduler.py --validate        # Read-only dependency & OAuth validation
    python scripts/run_scheduler.py --once --confirm  # Explicit single catch-up execution
    python scripts/run_scheduler.py --daemon          # Continuous autonomous daemon
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = DATA_DIR / "scheduler.log"


def _configure_safe_stdio_and_logging() -> logging.Logger:
    """Configure UTF-8 file logging before importing runtime modules so pythonw crashes are captured."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    elif isinstance(sys.stdout, io.TextIOWrapper):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    elif isinstance(sys.stderr, io.TextIOWrapper):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    handlers: list[logging.Handler] = [
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ]
    if sys.stdout and getattr(sys.stdout, "name", "") != os.devnull:
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    return logging.getLogger("curiosity_engine.runner")


startup_logger = _configure_safe_stdio_and_logging()


def main():
    parser = argparse.ArgumentParser(
        description="Curiosity Engine Autonomous Scheduler Runner (Local-First, ₹0 Budget)"
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--status", action="store_true", help="Read-only: print scheduler telemetry and exit")
    mode_group.add_argument("--dry-run", action="store_true", help="Read-only: preview planned actions & blockers without side effects")
    mode_group.add_argument("--validate", action="store_true", help="Read-only: validate config, binaries, models, and OAuth scopes")
    mode_group.add_argument("--once", action="store_true", help="Execute single catch-up batch (requires --confirm safeguard)")
    mode_group.add_argument("--daemon", action="store_true", help="Run continuous background scheduler daemon")

    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required explicit confirmation flag when invoking --once production",
    )
    parser.add_argument("--interval", type=int, default=15, help="Daemon poll interval in seconds (default: 15)")

    args = parser.parse_args()

    if args.daemon:
        startup_logger.info("Launcher starting scheduler daemon process (PID=%s)...", os.getpid())

    try:
        from curiosity_engine.runner.local_scheduler import scheduler
    except Exception as exc:
        startup_logger.error("Scheduler startup import failure: %s\n%s", exc, traceback.format_exc())
        sys.exit(1)

    if args.status:
        telemetry = scheduler.get_telemetry()
        print(json.dumps(telemetry, indent=2, ensure_ascii=False))
        sys.exit(0)
    elif args.dry_run:
        plan = scheduler.evaluate_dry_run()
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        sys.exit(0)
    elif args.validate:
        report = scheduler.validate_environment(check_oauth_network=True)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        sys.exit(0 if report["valid"] else 1)
    elif args.once:
        if not args.confirm:
            print(
                "\n[SAFEGUARD BLOCKED] '--once' triggers actual video generation and publishing.\n"
                "For read-only inspection, use:\n"
                "  python scripts/run_scheduler.py --status\n"
                "  python scripts/run_scheduler.py --dry-run\n"
                "  python scripts/run_scheduler.py --validate\n\n"
                "To explicitly confirm catch-up execution, run:\n"
                "  python scripts/run_scheduler.py --once --confirm\n"
            )
            sys.exit(2)
        recovered = scheduler.run_catchup_check()
        print(f"Catch-up evaluated. Executed {len(recovered)} batch record(s).")
        sys.exit(0)
    elif args.daemon:
        try:
            scheduler.run_daemon(poll_interval_sec=args.interval)
        except Exception as exc:
            startup_logger.error("Scheduler daemon crashed: %s\n%s", exc, traceback.format_exc())
            sys.exit(1)
    else:
        parser.print_help()
        print("\nTip: Use '--status', '--dry-run', or '--validate' for safe read-only checks, or '--daemon' to start the daemon.")
        sys.exit(0)


if __name__ == "__main__":
    main()
