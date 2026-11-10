"""Verification script for YouTube OAuth loading, token health, and dashboard status."""
import json
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from curiosity_engine.config import (
    YOUTUBE_CLIENT_ID,
    YOUTUBE_CLIENT_SECRET,
    YOUTUBE_REFRESH_TOKEN,
)
from curiosity_engine.dashboard.app import app
from curiosity_engine.distribution.token_manager import token_manager

print("=== 1. Checking .env auto-load ===")
print("YOUTUBE_CLIENT_ID loaded:", bool(YOUTUBE_CLIENT_ID))
print("YOUTUBE_CLIENT_SECRET loaded:", bool(YOUTUBE_CLIENT_SECRET))
print("YOUTUBE_REFRESH_TOKEN loaded:", bool(YOUTUBE_REFRESH_TOKEN))

print("\n=== 2. Testing actual Google token refresh ===")
health_res = token_manager.check_youtube_health(
    YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
)
print("Token refresh status:", health_res.get("status"))
print("Is healthy:", health_res.get("healthy"))
print("Reauth required:", health_res.get("reauth_required"))

print("\n=== 3. Testing /api/status via TestClient ===")
with TestClient(app) as client:
    resp = client.get("/api/status")
    print("HTTP Status Code:", resp.status_code)
    data = resp.json()
    token_health = data.get("token_health")
    print("token_health is dict:", isinstance(token_health, dict))
    if isinstance(token_health, dict):
        yt = token_health.get("youtube", {})
        print("Dashboard YouTube status:", yt.get("status"))
        print("Dashboard YouTube healthy:", yt.get("healthy"))
        print("Dashboard YouTube alert:", yt.get("alert"))

    raw_text = resp.text
    # Check that secrets are NEVER exposed in raw text
    print("Raw text contains client_secret:", YOUTUBE_CLIENT_SECRET in raw_text if YOUTUBE_CLIENT_SECRET else False)
    print("Raw text contains refresh_token:", YOUTUBE_REFRESH_TOKEN in raw_text if YOUTUBE_REFRESH_TOKEN else False)
