"""Interactive YouTube OAuth 2.0 setup script for ReelForge (StoryCircuit)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import set_key
from google_auth_oauthlib.flow import InstalledAppFlow

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reelforge import config  # noqa: E402

NARROW_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

FULL_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

SCOPES = NARROW_SCOPES


def main(scope_mode: str = "narrow") -> None:
    env_file = config.ensure_env_file()
    requested_scopes = FULL_SCOPES if scope_mode == "full" else NARROW_SCOPES

    info = config.load_client_secret_info()
    if info:
        client_id = info["client_id"]
        client_secret = info["client_secret"]
        client_config = info["raw"]
    else:
        client_id = (
            os.environ.get("YOUTUBE_CLIENT_ID")
            or config.YOUTUBE_CLIENT_ID
            or input("YouTube OAuth Client ID: ").strip()
        )
        client_secret = (
            os.environ.get("YOUTUBE_CLIENT_SECRET")
            or config.YOUTUBE_CLIENT_SECRET
            or input("YouTube OAuth Client Secret: ").strip()
        )
        if not client_id or not client_secret:
            print("Client ID and Client Secret are required.")
            sys.exit(1)
        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }

    flow = InstalledAppFlow.from_client_config(client_config, requested_scopes)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not creds.refresh_token:
        print("No refresh token returned. Revoke app access in Google Account and re-run with prompt=consent.")
        sys.exit(1)

    set_key(str(env_file), "YOUTUBE_CLIENT_ID", client_id)
    set_key(str(env_file), "YOUTUBE_CLIENT_SECRET", client_secret)
    set_key(str(env_file), "YOUTUBE_REFRESH_TOKEN", creds.refresh_token)
    print("Saved YouTube OAuth credentials to .env! Flip YOUTUBE_PUBLISHING_MODE=live when ready.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube OAuth 2.0 Authorization Helper")
    parser.add_argument(
        "--scope-mode",
        choices=["narrow", "full"],
        default="narrow",
        help="narrow = youtube.upload + youtube.readonly; full = adds youtube.force-ssl",
    )
    parser.add_argument("--force", action="store_true", help="Force re-authorization")
    parser.add_argument("--yes", "-y", action="store_true", help="Non-interactive save")
    args = parser.parse_args()
    main(scope_mode=args.scope_mode)
