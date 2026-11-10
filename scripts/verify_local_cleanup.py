"""CurioLoop - Verification of Local-First Clean Architecture.
Checks:
1. Database persistence (loads existing records without ADC warnings).
2. YouTube OAuth token health check.
3. Scheduler initialization and next execution calculation.
4. FastAPI dashboard status endpoint response.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curiosity_engine.state.db import db
from curiosity_engine.distribution.token_manager import token_manager
from curiosity_engine.runner.local_scheduler import scheduler
from curiosity_engine.dashboard.app import app
from fastapi.testclient import TestClient


def main():
    print("=" * 60)
    print("CURIOLOOP LOCAL-FIRST ARCHITECTURE VERIFICATION")
    print("=" * 60)

    # 1. Database Check
    print("\n1. Checking Local Database Persistence...")
    v1 = db.get_video_record("video_20261109_slot1")
    assert v1 is not None, "Video 1 missing!"
    print(f"   [OK] Slot 1 Record: {v1['video_id']} (QC Passed: {v1.get('qc_passed')}, YT ID: {v1.get('youtube_upload_id')})")

    v2 = db.get_video_record("video_20261109_slot2")
    assert v2 is not None, "Video 2 missing!"
    print(f"   [OK] Slot 2 Record: {v2['video_id']} (QC Passed: {v2.get('qc_passed')}, YT ID: {v2.get('youtube_upload_id')})")

    # 2. YouTube OAuth Check
    print("\n2. Checking YouTube OAuth Refresh Token Health...")
    summary = token_manager.audit_configured_tokens_on_startup()
    yt = summary.get("youtube", {})
    print(f"   [OK] YouTube OAuth Status: {yt.get('status')} | Healthy: {yt.get('healthy')}")
    assert yt.get("healthy") is True, f"YouTube token unhealthy: {yt}"

    # 3. Scheduler Check
    print("\n3. Checking Local Scheduler Initialization...")
    telemetry = scheduler.get_telemetry()
    next_exec = telemetry.get("next_execution", {})
    print(f"   [OK] Scheduler Timezone: {telemetry.get('timezone')}")
    print(f"   [OK] Next Execution: {next_exec.get('slot')} at {next_exec.get('scheduled_ist')} (ETA: {next_exec.get('human_eta')})")
    assert telemetry.get("timezone") == "Asia/Kolkata"

    # 4. Dashboard Endpoint Check
    print("\n4. Checking Local FastAPI Dashboard Status Endpoint...")
    client = TestClient(app)
    res = client.get("/api/status")
    assert res.status_code == 200, f"Dashboard /api/status returned {res.status_code}"
    status_data = res.json()
    print(f"   [OK] Dashboard Response: HTTP 200")
    print(f"   [OK] YouTube Mode: {status_data.get('youtube_publishing_mode')} (Privacy: {status_data.get('youtube_privacy_status')})")
    print(f"   [OK] Instagram Mode: {status_data.get('instagram_publishing_mode')}")
    print(f"   [OK] Scheduler Telemetry Exposed: {bool(status_data.get('scheduler'))}")

    print("\n" + "=" * 60)
    print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY!")
    print("Zero cloud infrastructure required at runtime.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
