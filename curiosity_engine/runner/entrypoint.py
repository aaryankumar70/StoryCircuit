"""Curiosity Engine CLI Entrypoint.
Usage:
  python -m curiosity_engine.runner.entrypoint --mode=generate [--date=YYYY-MM-DD]
  python -m curiosity_engine.runner.entrypoint --mode=publish-1 [--date=YYYY-MM-DD]
  python -m curiosity_engine.runner.entrypoint --mode=publish-2 [--date=YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import logging
import sys

from curiosity_engine.runner.pipeline import run_daily_generation, run_slot_publishing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("curiosity_engine.entrypoint")


def main() -> None:
    parser = argparse.ArgumentParser(description="Curiosity Engine Local Studio Runner")
    parser.add_argument(
        "--mode",
        required=True,
        choices=["generate", "publish-1", "publish-2"],
        help="Job execution mode: 'generate' (Job 1: 05:30 IST), 'publish-1' (Job 2: 10:00 IST), or 'publish-2' (Job 3: 18:00 IST)",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Target date YYYY-MM-DD (defaults to today UTC)",
    )

    args = parser.parse_args()

    try:
        if args.mode == "generate":
            logger.info("Executing Job 1: Generating two original daily videos...")
            v1, v2 = run_daily_generation(target_date=args.date)
            success_count = sum(1 for v in [v1, v2] if v and v.get("qc_passed"))
            if success_count == 0:
                logger.error("Both video generations failed!")
                sys.exit(1)
            logger.info(f"Job 1 complete. Successfully produced {success_count}/2 videos.")

        elif args.mode == "publish-1":
            logger.info("Executing Job 2: Publishing Video 1 (10:00 AM IST slot)...")
            res = run_slot_publishing(slot_index=1, target_date=args.date)
            if not res or res.get("publishing_status") != "PUBLISHED":
                logger.error("Job 2 failed to publish Video 1.")
                sys.exit(1)
            logger.info("Job 2 successfully completed.")

        elif args.mode == "publish-2":
            logger.info("Executing Job 3: Publishing Video 2 (6:00 PM IST slot)...")
            res = run_slot_publishing(slot_index=2, target_date=args.date)
            if not res or res.get("publishing_status") != "PUBLISHED":
                logger.error("Job 3 failed to publish Video 2.")
                sys.exit(1)
            logger.info("Job 3 successfully completed.")

    except Exception as e:
        logger.exception(f"Fatal error during entrypoint execution: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
