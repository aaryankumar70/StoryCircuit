"""Interactive CLI Authorization Helper for Instagram API with Instagram Login.
Guides the user through exchanging short-lived tokens for 60-day long-lived tokens
via graph.instagram.com, with automatic account ID discovery.

Strictly avoids legacy Facebook Page tokens or mixed authentication flows.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, Any

import requests

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from curiosity_engine.config import INSTAGRAM_API_VERSION


def print_step(title: str) -> None:
    print(f"\n{'='*70}\n{title}\n{'='*70}")


def run_instagram_auth_flow():
    print_step("CURIOSITY ENGINE • INSTAGRAM LOGIN AUTHORIZATION WIZARD")
    print(
        "This wizard configures official Instagram Reels publishing via the\n"
        "Instagram Platform (graph.instagram.com) with a 60-day Long-Lived Token.\n"
    )

    print("STEP 1: META FOR DEVELOPERS APP SETUP")
    print("-" * 70)
    print("1. Go to https://developers.facebook.com/apps/.")
    print("2. Create a Business app and add the 'Instagram' product (Instagram Platform).")
    print("3. Ensure the target Instagram account is a Professional (Creator or Business) account.")
    print("4. Under 'Roles' or 'Instagram Testers', add your Instagram account.")
    print("5. Generate a Short-Lived User Access Token with scopes:")
    print("   * instagram_business_basic")
    print("   * instagram_business_content_publish")
    print("-" * 70)

    app_id = os.environ.get("INSTAGRAM_APP_ID") or input("\nEnter your Meta App ID: ").strip()
    app_secret = os.environ.get("INSTAGRAM_APP_SECRET") or input("Enter your Meta App Secret: ").strip()
    short_token = input("Enter the Short-Lived User Access Token from Graph API Explorer: ").strip()

    if not app_secret or not short_token:
        print("\n[ERROR] App Secret and Short-Lived Token are required. Aborting.")
        sys.exit(1)

    print("\nSTEP 2: EXCHANGING FOR 60-DAY LONG-LIVED ACCESS TOKEN")
    print("-" * 70)

    exchange_url = "https://graph.instagram.com/access_token"
    params = {
        "grant_type": "ig_exchange_token",
        "client_secret": app_secret,
        "access_token": short_token,
    }

    try:
        resp = requests.get(exchange_url, params=params, timeout=20)
        if resp.status_code != 200:
            print(f"[ERROR] Token exchange failed ({resp.status_code}): {resp.text}")
            sys.exit(1)

        data = resp.json()
        long_lived_token = data.get("access_token")
        expires_in = data.get("expires_in", 5184000)
        days = int(expires_in / 86400)
        print(f"[OK] Successfully obtained 60-day token (valid for {days} days).")
    except Exception as e:
        print(f"[ERROR] Failed to contact Instagram Graph API: {e}")
        sys.exit(1)

    print("\nSTEP 3: DISCOVERING INSTAGRAM PROFESSIONAL ACCOUNT ID")
    print("-" * 70)

    version = INSTAGRAM_API_VERSION or "v22.0"
    me_url = f"https://graph.instagram.com/{version}/me"
    try:
        me_resp = requests.get(
            me_url,
            params={"fields": "id,username", "access_token": long_lived_token},
            timeout=15,
        )
        if me_resp.status_code != 200:
            print(f"[ERROR] Failed to query user account details: {me_resp.text}")
            sys.exit(1)

        me_data = me_resp.json()
        account_id = me_data.get("id")
        username = me_data.get("username", "Unknown")
        print(f"[OK] Connected to Instagram Account: @{username} (ID: {account_id})")
    except Exception as e:
        print(f"[ERROR] Failed to discover account ID: {e}")
        sys.exit(1)

    print_step("AUTHORIZATION COMPLETE!")
    print(f"Account ID:   {account_id} (@{username})")
    print(f"Access Token: {long_lived_token[:10]}...{long_lived_token[-6:]}")
    print("Token Manager will automatically refresh this token every 30 days.")

    # Save to .env
    env_file = PROJECT_ROOT / ".env"
    save_env = input("\nSave these credentials to your local .env file? [Y/n]: ").strip().lower()
    if save_env in ("", "y", "yes"):
        lines = []
        if env_file.exists():
            lines = env_file.read_text(encoding="utf-8").splitlines()

        keys_to_set = {
            "INSTAGRAM_ACCESS_TOKEN": long_lived_token,
            "INSTAGRAM_ACCOUNT_ID": account_id,
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

        env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"[OK] Credentials saved safely to {env_file} (excluded from Git).")


if __name__ == "__main__":
    run_instagram_auth_flow()
