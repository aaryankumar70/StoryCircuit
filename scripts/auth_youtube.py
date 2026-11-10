"""Interactive CLI Authorization Helper for YouTube Data API v3.
Guides the user through Google OAuth 2.0 consent setup and permanent token generation.

CRITICAL POLICY REQUIREMENT:
To prevent refresh tokens from expiring after 7 days, the OAuth Consent Screen
in Google Cloud Console MUST be published to 'In production' status.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from curiosity_engine.config import (
    ENV_FILE,
    YOUTUBE_CLIENT_ID,
    YOUTUBE_CLIENT_SECRET,
    YOUTUBE_REFRESH_TOKEN,
)
from curiosity_engine.distribution.token_manager import token_manager

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


def print_step(title: str) -> None:
    print(f"\n{'='*70}\n{title}\n{'='*70}")


def verify_granted_scopes(access_token: str) -> list[str]:
    """Query Google tokeninfo endpoint without logging credentials."""
    import requests

    try:
        resp = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"access_token": access_token},
            timeout=10,
        )
        if resp.status_code == 200:
            scope_str = resp.json().get("scope", "")
            return [s for s in scope_str.split() if s]
    except Exception as e:
        print(f"[WARNING] Could not query tokeninfo for granted scopes: {e}")
    return []


def run_youtube_oauth_flow(scope_mode: str = "narrow", force: bool = False, yes: bool = False) -> None:
    requested_scopes = FULL_SCOPES if scope_mode == "full" else NARROW_SCOPES

    print_step("CURIOSITY ENGINE • YOUTUBE OAUTH 2.0 AUTHORIZATION WIZARD")
    print(
        "This wizard authorizes the existing Desktop OAuth client for automated\n"
        "YouTube Shorts uploads & scheduled publishing with offline access.\n"
    )

    print("STEP 1: OAUTH CONSENT SCREEN CONFIGURATION (PREVENT 7-DAY EXPIRATION)")
    print("-" * 70)
    print("1. Open Google Cloud Console -> APIs & Services -> OAuth consent screen.")
    print("2. Ensure User Type is 'External'.")
    print("3. CRITICAL: Publishing status MUST be 'In production' ('PUBLISH APP').")
    print("   * Tokens minted while 'Testing' expire after 7 days.")
    print("   * After switching to 'In production', authorize once here to persist")
    print("     a long-lived refresh token.")
    print("-" * 70)

    print("\nSTEP 2: OAUTH CLIENT CREDENTIALS")
    print("-" * 70)

    client_id = (YOUTUBE_CLIENT_ID or os.environ.get("YOUTUBE_CLIENT_ID") or "").strip()
    client_secret = (YOUTUBE_CLIENT_SECRET or os.environ.get("YOUTUBE_CLIENT_SECRET") or "").strip()
    if not client_id:
        client_id = input("\nEnter your YouTube Client ID: ").strip()
    else:
        print(f"[OK] Reusing configured Desktop OAuth Client ID: {client_id}")
    if not client_secret:
        client_secret = input("Enter your YouTube Client Secret: ").strip()
    else:
        print("[OK] Reusing configured Desktop OAuth Client Secret: [REDACTED]")

    if not client_id or not client_secret:
        print("\n[ERROR] Client ID and Client Secret are required. Aborting.")
        sys.exit(1)

    if not force and YOUTUBE_REFRESH_TOKEN:
        health = token_manager.check_youtube_health(client_id, client_secret, YOUTUBE_REFRESH_TOKEN)
        existing_scopes = set(health.get("scopes", []))
        if health.get("healthy") and set(requested_scopes).issubset(existing_scopes):
            print("\n[OK] Existing refresh token is HEALTHY and already grants all requested scopes:")
            for s in sorted(existing_scopes):
                print(f"     - {s}")
            print("     Pass '--force' if you are switching consent screen from Testing -> Production")
            print("     and explicitly want to mint a replacement Production refresh token.")
            return

    print("\nSTEP 3: LAUNCHING BROWSER FOR AUTHORIZATION")
    print(f"Requested Scopes ({scope_mode}):")
    for s in requested_scopes:
        print(f"  - {s}")
    print("-" * 70)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("[ERROR] 'google_auth_oauthlib' is required. Run 'pip install google-auth-oauthlib'.")
        sys.exit(1)

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost:8080/"],
        }
    }

    try:
        flow = InstalledAppFlow.from_client_config(client_config, scopes=requested_scopes)
        # prompt='consent' and access_type='offline' ensure a refresh_token is returned
        credentials = flow.run_local_server(
            port=8080,
            prompt="consent",
            access_type="offline",
            success_message="Authorization complete! You may return to the Curiosity Engine terminal.",
        )
    except Exception as e:
        print(f"\n[ERROR] Local server OAuth flow failed ({e}).")
        print("Falling back to console-based authorization...")
        flow = InstalledAppFlow.from_client_config(client_config, scopes=requested_scopes)
        credentials = flow.run_console(access_type="offline", prompt="consent")

    refresh_token = credentials.refresh_token
    if not refresh_token:
        print("\n[WARNING] Google did not return a new refresh token.")
        print("Revoke prior consent at https://myaccount.google.com/permissions and rerun.")
        sys.exit(1)

    granted = verify_granted_scopes(credentials.token) if credentials.token else list(credentials.scopes or [])

    print_step("AUTHORIZATION SUCCESSFUL!")
    print(f"Refresh Token Obtained: [REDACTED len={len(refresh_token)}]")
    print("Verified Granted Scopes:")
    for s in granted:
        print(f"  - {s}")

    # Persist to local .env file
    save_env = "y" if yes else input("\nSave these credentials to your local .env file? [Y/n]: ").strip().lower()
    if save_env in ("", "y", "yes"):
        lines = []
        if ENV_FILE.exists():
            lines = ENV_FILE.read_text(encoding="utf-8").splitlines()

        keys_to_set = {
            "YOUTUBE_CLIENT_ID": client_id,
            "YOUTUBE_CLIENT_SECRET": client_secret,
            "YOUTUBE_REFRESH_TOKEN": refresh_token,
        }

        updated_keys = set()
        new_lines = []
        for line in lines:
            matched = False
            for k, v in keys_to_set.items():
                if line.startswith(f"{k}="):
                    new_lines.append(f"{k}={v}")
                    updated_keys.add(k)
                    matched = True
                    break
            if not matched:
                new_lines.append(line)

        for k, v in keys_to_set.items():
            if k not in updated_keys:
                new_lines.append(f"{k}={v}")

        ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        token_manager.check_youtube_health(client_id, client_secret, refresh_token)
        print(f"[OK] Saved credentials safely to {ENV_FILE} and updated token_state.json.")

    print("\nNext step: Verify token status in the Studio Dashboard.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube OAuth 2.0 Authorization Helper")
    parser.add_argument(
        "--scope-mode",
        choices=["narrow", "full"],
        default="narrow",
        help="narrow = youtube.upload + youtube.readonly; full = adds youtube.force-ssl",
    )
    parser.add_argument("--force", action="store_true", help="Force re-authorization even if existing token is healthy")
    parser.add_argument("--yes", "-y", action="store_true", help="Automatically save new credentials to .env without prompting")
    args = parser.parse_args()
    run_youtube_oauth_flow(scope_mode=args.scope_mode, force=args.force, yes=args.yes)
