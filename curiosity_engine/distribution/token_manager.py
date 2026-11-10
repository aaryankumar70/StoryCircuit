"""OAuth Token Lifecycle & Health Management for Curiosity Engine.
Treats all refresh tokens as potentially revocable or expiring.
Provides proactive health audits, automated 30-day Instagram rolling renewal,
and clear reauthorization alerts.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import requests

from curiosity_engine import config
from curiosity_engine.config import (
    DATA_DIR,
    INSTAGRAM_ACCESS_TOKEN,
    INSTAGRAM_ACCOUNT_ID,
    INSTAGRAM_API_VERSION,
    PUBLISHING_MODE,
    YOUTUBE_CLIENT_ID,
    YOUTUBE_CLIENT_SECRET,
    YOUTUBE_REFRESH_TOKEN,
)

logger = logging.getLogger("curiosity_engine.distribution.token_manager")
TOKEN_STATE_FILE = DATA_DIR / "token_state.json"
IST = ZoneInfo("Asia/Kolkata")
YOUTUBE_TESTING_LIFETIME_DAYS = 7


def _token_fingerprint(token: str) -> str:
    """Return a non-reversible short digest for detecting refresh token rotation."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _build_expiry_fields(
    authorized_at_iso: str,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Calculate expected 7-day Testing-mode expiry metadata and 24h warning flags."""
    now = now_utc or datetime.now(timezone.utc)
    auth_dt = datetime.fromisoformat(authorized_at_iso)
    if auth_dt.tzinfo is None:
        auth_dt = auth_dt.replace(tzinfo=timezone.utc)
    exp_dt = auth_dt + timedelta(days=YOUTUBE_TESTING_LIFETIME_DAYS)
    seconds_left = max(0.0, (exp_dt - now).total_seconds())
    hours_left = round(seconds_left / 3600.0, 1)
    days_left = round(seconds_left / 86400.0, 2)
    return {
        "authorized_at": auth_dt.astimezone(timezone.utc).isoformat(),
        "expected_expires_at": exp_dt.astimezone(timezone.utc).isoformat(),
        "hours_until_expiry": hours_left,
        "days_until_expiry": days_left,
        "estimated_reauth_date_ist": exp_dt.astimezone(IST).strftime("%Y-%m-%d %H:%M IST"),
        "warning_24h_due": seconds_left <= 86400.0,
        "expiry_policy": "TESTING_7_DAYS",
    }


class TokenManager:
    """Manages token lifecycles, health checks, and reauthorization alerting."""

    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = state_file or TOKEN_STATE_FILE
        self._state: Dict[str, Any] = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load token state from {self.state_file}: {e}")
        return {
            "youtube": {
                "status": "UNCONFIGURED",
                "last_checked": None,
                "reauth_required": False,
                "alert": None,
            },
            "instagram": {
                "status": "UNCONFIGURED",
                "last_checked": None,
                "expires_at": None,
                "reauth_required": False,
                "alert": None,
            },
        }

    def _save_state(self) -> None:
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to persist token state: {e}")

    # -------------------------------------------------------------------------
    # YouTube Token Health
    # -------------------------------------------------------------------------
    def record_youtube_authorization(
        self,
        refresh_token: str,
        authorized_at_utc: Optional[datetime] = None,
    ) -> None:
        """Record the timestamp when a new YouTube OAuth refresh token was issued."""
        if not refresh_token:
            return
        auth_dt = authorized_at_utc or datetime.now(timezone.utc)
        if auth_dt.tzinfo is None:
            auth_dt = auth_dt.replace(tzinfo=timezone.utc)
        yt = dict(self._state.get("youtube") or {})
        yt["token_fingerprint"] = _token_fingerprint(refresh_token)
        yt.update(_build_expiry_fields(auth_dt.isoformat(), now_utc=datetime.now(timezone.utc)))
        self._state["youtube"] = yt
        self._save_state()

    def check_youtube_health(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate YouTube OAuth refresh token by requesting a temporary access token."""
        if client_id is None and client_secret is None and refresh_token is None:
            config.sync_env_if_updated()

        cid = client_id if client_id is not None else (os.environ.get("YOUTUBE_CLIENT_ID") or config.YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_ID)
        sec = client_secret if client_secret is not None else (os.environ.get("YOUTUBE_CLIENT_SECRET") or config.YOUTUBE_CLIENT_SECRET or YOUTUBE_CLIENT_SECRET)
        ref = refresh_token if refresh_token is not None else (os.environ.get("YOUTUBE_REFRESH_TOKEN") or config.YOUTUBE_REFRESH_TOKEN or YOUTUBE_REFRESH_TOKEN)

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        if not (cid and sec and ref):
            res = {
                "status": "UNCONFIGURED",
                "healthy": False,
                "reauth_required": False,
                "last_checked": now_iso,
                "alert": "YouTube OAuth credentials not configured. Running in simulation mode.",
            }
            self._state["youtube"] = res
            self._save_state()
            return res

        existing = dict(self._state.get("youtube") or {})
        fp = _token_fingerprint(ref)
        prev_fp = existing.get("token_fingerprint")
        if prev_fp == fp and existing.get("authorized_at"):
            authorized_at_iso = existing["authorized_at"]
        elif not prev_fp and existing.get("authorized_at"):
            authorized_at_iso = existing["authorized_at"]
        else:
            authorized_at_iso = now_iso

        # Validate refresh token against Google OAuth endpoint
        token_endpoint = "https://oauth2.googleapis.com/token"
        payload = {
            "client_id": cid,
            "client_secret": sec,
            "refresh_token": ref,
            "grant_type": "refresh_token",
        }

        try:
            resp = requests.post(token_endpoint, data=payload, timeout=15)
            if resp.status_code == 200:
                granted_scopes: list[str] = []
                can_upload = True
                can_update_schedule = None
                scope_warning = None
                try:
                    tok_json = resp.json()
                    access_tok = tok_json.get("access_token") if isinstance(tok_json, dict) else None
                    if isinstance(access_tok, str) and access_tok:
                        ti = requests.get(
                            "https://oauth2.googleapis.com/tokeninfo",
                            params={"access_token": access_tok},
                            timeout=10,
                        )
                        if ti.status_code == 200:
                            scope_str = ti.json().get("scope", "")
                            granted_scopes = [s for s in scope_str.split() if s]
                            can_upload = any(
                                s in granted_scopes
                                for s in (
                                    "https://www.googleapis.com/auth/youtube.upload",
                                    "https://www.googleapis.com/auth/youtube",
                                    "https://www.googleapis.com/auth/youtube.force-ssl",
                                )
                            )
                            can_update_schedule = any(
                                s in granted_scopes
                                for s in (
                                    "https://www.googleapis.com/auth/youtube",
                                    "https://www.googleapis.com/auth/youtube.force-ssl",
                                )
                            )
                            if not can_update_schedule:
                                scope_warning = (
                                    "Token grants youtube.upload/readonly (uploads with publishAt succeed), "
                                    "but lacks 'youtube.force-ssl' needed for standalone videos.update schedule retries. "
                                    "Re-run 'python scripts/auth_youtube.py' to enable full scheduling updates."
                                )
                except Exception:
                    pass

                res = {
                    "status": "HEALTHY",
                    "healthy": True,
                    "reauth_required": False,
                    "last_checked": now_iso,
                    "alert": None,
                    "token_fingerprint": fp,
                }
                res.update(_build_expiry_fields(authorized_at_iso, now_utc=now_dt))
                if granted_scopes:
                    res["scopes"] = granted_scopes
                    res["can_upload"] = can_upload
                    res["can_update_schedule"] = bool(can_update_schedule)
                if scope_warning:
                    res["scope_warning"] = scope_warning
            else:
                error_data = resp.json() if "application/json" in resp.headers.get("Content-Type", "") else {}
                error_code = error_data.get("error", "unknown")
                error_desc = error_data.get("error_description", resp.text)

                if error_code == "invalid_grant":
                    alert_msg = (
                        "CRITICAL: YouTube OAuth refresh token expired or revoked ('invalid_grant'). "
                        "Google consent in Testing mode expires after 7 days. "
                        "Action: Click 'Reconnect YouTube Account' in the local Dashboard, "
                        "run 'reauthorize_youtube.bat', or run 'python scripts/auth_youtube.py --force --scope-mode full'."
                    )
                    res = {
                        "status": "REVOKED_OR_EXPIRED",
                        "healthy": False,
                        "reauth_required": True,
                        "last_checked": now_iso,
                        "alert": alert_msg,
                        "details": error_desc,
                        "token_fingerprint": fp,
                        "authorized_at": authorized_at_iso,
                    }
                else:
                    res = {
                        "status": f"ERROR_{resp.status_code}",
                        "healthy": False,
                        "reauth_required": False,
                        "last_checked": now_iso,
                        "alert": f"YouTube token check returned error: {error_code} - {error_desc}",
                        "token_fingerprint": fp,
                        "authorized_at": authorized_at_iso,
                    }
        except Exception as e:
            res = {
                "status": "NETWORK_ERROR",
                "healthy": False,
                "reauth_required": False,
                "last_checked": now_iso,
                "alert": f"Network error contacting Google OAuth: {e}",
                "token_fingerprint": fp,
                "authorized_at": authorized_at_iso,
            }

        self._state["youtube"] = res
        self._save_state()
        return res

    # -------------------------------------------------------------------------
    # Instagram Token Health & Rolling Refresh
    # -------------------------------------------------------------------------
    def check_instagram_health(
        self,
        access_token: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate Instagram long-lived token via graph.instagram.com and auto-refresh if expiring."""
        token = access_token if access_token is not None else (INSTAGRAM_ACCESS_TOKEN or os.environ.get("INSTAGRAM_ACCESS_TOKEN", ""))
        acct = account_id if account_id is not None else (INSTAGRAM_ACCOUNT_ID or os.environ.get("INSTAGRAM_ACCOUNT_ID", ""))

        now_iso = datetime.now(timezone.utc).isoformat()

        if not (token and acct and len(token.strip()) > 20):
            res = {
                "status": "UNCONFIGURED",
                "healthy": False,
                "reauth_required": False,
                "last_checked": now_iso,
                "days_remaining": None,
                "alert": "Instagram Access Token or Account ID not configured. Running in simulation mode.",
            }
            self._state["instagram"] = res
            self._save_state()
            return res

        version = INSTAGRAM_API_VERSION
        check_url = f"https://graph.instagram.com/{version}/me"

        try:
            resp = requests.get(
                check_url,
                params={"fields": "id,username", "access_token": token},
                timeout=15,
            )
            if resp.status_code == 200:
                # Check stored expiration date
                stored_expires_at = self._state.get("instagram", {}).get("expires_at")
                days_remaining = None
                if stored_expires_at:
                    try:
                        exp_dt = datetime.fromisoformat(stored_expires_at)
                        days_remaining = max(0, (exp_dt - datetime.now(timezone.utc)).days)
                    except Exception:
                        pass

                # If days remaining is less than 15, trigger rolling renewal
                if days_remaining is not None and days_remaining < 15:
                    logger.info("Instagram token has fewer than 15 days remaining. Initiating rolling refresh...")
                    refreshed = self.refresh_instagram_token(token)
                    if refreshed.get("success"):
                        return refreshed

                res = {
                    "status": "HEALTHY",
                    "healthy": True,
                    "reauth_required": False,
                    "days_remaining": days_remaining if days_remaining is not None else 60,
                    "last_checked": now_iso,
                    "alert": None,
                }
            else:
                err_data = resp.json().get("error", {})
                code = err_data.get("code")
                subcode = err_data.get("error_subcode")
                message = err_data.get("message", resp.text)

                # Error 190, subcode 463/467 indicates expired or invalidated token
                if code == 190 or subcode in (463, 467):
                    alert_msg = (
                        "CRITICAL: Instagram Long-Lived Access Token has expired or been revoked. "
                        "Action: Run 'python scripts/auth_instagram.py' to generate a fresh 60-day token."
                    )
                    res = {
                        "status": "REVOKED_OR_EXPIRED",
                        "healthy": False,
                        "reauth_required": True,
                        "last_checked": now_iso,
                        "days_remaining": 0,
                        "alert": alert_msg,
                        "details": message,
                    }
                else:
                    res = {
                        "status": f"ERROR_{code}",
                        "healthy": False,
                        "reauth_required": False,
                        "last_checked": now_iso,
                        "days_remaining": None,
                        "alert": f"Instagram Graph API returned error: {message}",
                    }
        except Exception as e:
            res = {
                "status": "NETWORK_ERROR",
                "healthy": False,
                "reauth_required": False,
                "last_checked": now_iso,
                "days_remaining": None,
                "alert": f"Network error contacting Instagram API: {e}",
            }

        self._state["instagram"] = res
        self._save_state()
        return res

    def refresh_instagram_token(self, current_token: str) -> Dict[str, Any]:
        """Perform rolling 60-day extension of Instagram Long-Lived User Token."""
        refresh_url = "https://graph.instagram.com/refresh_access_token"
        params = {
            "grant_type": "ig_refresh_token",
            "access_token": current_token,
        }
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            resp = requests.get(refresh_url, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                new_token = data.get("access_token")
                expires_in_sec = data.get("expires_in", 5184000)  # Default 60 days
                exp_dt = datetime.fromtimestamp(time.time() + expires_in_sec, timezone.utc)

                res = {
                    "success": True,
                    "status": "HEALTHY",
                    "healthy": True,
                    "reauth_required": False,
                    "new_token": new_token,
                    "expires_at": exp_dt.isoformat(),
                    "days_remaining": int(expires_in_sec / 86400),
                    "last_checked": now_iso,
                    "alert": None,
                }
                self._state["instagram"] = res
                self._save_state()
                logger.info(f"Successfully refreshed Instagram long-lived token. Valid for {res['days_remaining']} days.")
                return res
            else:
                return {
                    "success": False,
                    "status": "REFRESH_FAILED",
                    "healthy": False,
                    "reauth_required": True,
                    "alert": f"Failed to refresh Instagram token: {resp.text}",
                }
        except Exception as e:
            return {
                "success": False,
                "status": "NETWORK_ERROR",
                "healthy": False,
                "reauth_required": False,
                "alert": f"Network error during Instagram token refresh: {e}",
            }

    def get_summary(self) -> Dict[str, Any]:
        """Return combined token health summary for dashboard and monitoring."""
        # Reload latest persisted state if modified by another process (e.g., auth script / daemon)
        self._state = self._load_state()
        yt = dict(self._state.get("youtube", {}))
        if yt.get("authorized_at") and yt.get("healthy"):
            try:
                yt.update(_build_expiry_fields(yt["authorized_at"]))
            except Exception:
                pass
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "youtube": yt,
            "instagram": self._state.get("instagram", {}),
        }

    def audit_configured_tokens_on_startup(self) -> Dict[str, Any]:
        """Perform one-time health audit during application startup for configured credentials.
        Avoids redundant external network requests on periodic polling endpoints.
        """
        logger.info("Performing startup token health audit...")
        config.sync_env_if_updated()
        cid = os.environ.get("YOUTUBE_CLIENT_ID") or config.YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_ID
        sec = os.environ.get("YOUTUBE_CLIENT_SECRET") or config.YOUTUBE_CLIENT_SECRET or YOUTUBE_CLIENT_SECRET
        ref = os.environ.get("YOUTUBE_REFRESH_TOKEN") or config.YOUTUBE_REFRESH_TOKEN or YOUTUBE_REFRESH_TOKEN
        ig_tok = os.environ.get("INSTAGRAM_ACCESS_TOKEN") or config.INSTAGRAM_ACCESS_TOKEN or INSTAGRAM_ACCESS_TOKEN
        ig_acct = os.environ.get("INSTAGRAM_ACCOUNT_ID") or config.INSTAGRAM_ACCOUNT_ID or INSTAGRAM_ACCOUNT_ID

        # Audit YouTube credentials if configured
        if cid and sec and ref:
            self.check_youtube_health(cid, sec, ref)
        else:
            self._state["youtube"] = {
                "status": "UNCONFIGURED",
                "healthy": False,
                "reauth_required": False,
                "last_checked": datetime.now(timezone.utc).isoformat(),
                "alert": "YouTube OAuth credentials not configured. Running in simulation mode.",
            }
            self._save_state()

        # Audit Instagram credentials if configured
        if ig_tok and ig_acct:
            self.check_instagram_health(ig_tok, ig_acct)
        else:
            self._state["instagram"] = {
                "status": "UNCONFIGURED",
                "healthy": False,
                "reauth_required": False,
                "last_checked": datetime.now(timezone.utc).isoformat(),
                "days_remaining": None,
                "alert": "Instagram Access Token or Account ID not configured. Running in simulation mode.",
            }
            self._save_state()

        return self.get_summary()


token_manager = TokenManager()
