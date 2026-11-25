"""YouTube Data API v3 uploader for 9:16 Shorts and 16:9 Long-Format videos with safe scheduling."""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from zoneinfo import ZoneInfo

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from reelforge import config
from reelforge.brain.metadata import clean_youtube_title, fit_tags_within_budget

logger = logging.getLogger("reelforge.youtube.uploader")

_HEALTH_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_HEALTH_CACHE_TTL_SEC = 300.0


def clear_health_cache() -> None:
    _HEALTH_CACHE["ts"] = 0.0
    _HEALTH_CACHE["data"] = None


def _mask_client_id(cid: str) -> str:
    clean = (cid or "").strip()
    if not clean:
        return ""
    if len(clean) <= 18:
        return clean[:4] + "..." + clean[-4:]
    return clean[:12] + "..." + clean[-16:]


class YouTubeUploadError(RuntimeError):
    pass


def _strip_links(text: str) -> str:
    return re.sub(r"[<>]+", "", re.sub(r"https?://\S+", "", text or "")).strip()


def _resolve_auth_timestamp(has_refresh: bool) -> Optional[datetime]:
    """Return UTC datetime of last YouTube OAuth authorization, seeding from .env mtime if missing."""
    if not has_refresh:
        return None
    raw = (os.environ.get("YOUTUBE_AUTH_TS") or config.YOUTUBE_AUTH_TS or "").strip()
    if raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except Exception:
            pass
    # Backfill once from .env mtime when refresh token was authorized prior to YOUTUBE_AUTH_TS tracking
    if config.ENV_FILE.exists():
        try:
            dt = datetime.fromtimestamp(config.ENV_FILE.stat().st_mtime, tz=timezone.utc)
            iso = dt.isoformat()
            config.save_env_values({"YOUTUBE_AUTH_TS": iso})
            return dt
        except Exception:
            pass
    dt = datetime.now(timezone.utc)
    return dt


def _build_reauth_telemetry(has_refresh: bool, state: str) -> Dict[str, Any]:
    """Compute 7-day OAuth expiry countdown telemetry for Testing-mode Google OAuth apps."""
    if not has_refresh:
        return {
            "auth_timestamp": None,
            "reauth_expires_at": None,
            "reauth_expires_local": "",
            "reauth_remaining_seconds": 0,
            "reauth_max_days": config.YOUTUBE_OAUTH_MAX_AGE_DAYS,
            "reauth_state": "unconnected",
        }
    auth_dt = _resolve_auth_timestamp(has_refresh)
    if not auth_dt:
        return {
            "auth_timestamp": None,
            "reauth_expires_at": None,
            "reauth_expires_local": "",
            "reauth_remaining_seconds": 0,
            "reauth_max_days": config.YOUTUBE_OAUTH_MAX_AGE_DAYS,
            "reauth_state": "unconnected",
        }
    expires_dt = auth_dt + timedelta(days=config.YOUTUBE_OAUTH_MAX_AGE_DAYS)
    now_utc = datetime.now(timezone.utc)
    remaining = max(0, int((expires_dt - now_utc).total_seconds()))
    try:
        local_dt = expires_dt.astimezone(ZoneInfo(config.SCHEDULER_TIMEZONE))
        local_str = local_dt.strftime("%b %d, %H:%M %Z")
    except Exception:
        local_str = expires_dt.strftime("%Y-%m-%d %H:%M UTC")

    if state == "token_invalid" or remaining <= 0:
        reauth_state = "expired"
    elif remaining <= 48 * 3600:
        reauth_state = "expiring_soon"
    else:
        reauth_state = "ok"

    return {
        "auth_timestamp": auth_dt.isoformat(),
        "reauth_expires_at": expires_dt.isoformat(),
        "reauth_expires_local": local_str,
        "reauth_remaining_seconds": remaining,
        "reauth_max_days": config.YOUTUBE_OAUTH_MAX_AGE_DAYS,
        "reauth_state": reauth_state,
    }


class YouTubeUploader:
    """Official YouTube Data API v3 uploader for Shorts (9:16) and Long-Format (16:9)."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
        mode: Optional[str] = None,
    ):
        config.reload_env()
        info = config.load_client_secret_info()
        fallback_id = info["client_id"] if info else ""
        fallback_sec = info["client_secret"] if info else ""
        self.client_id = client_id if client_id is not None else (os.environ.get("YOUTUBE_CLIENT_ID") or config.YOUTUBE_CLIENT_ID or fallback_id)
        self.client_secret = client_secret if client_secret is not None else (os.environ.get("YOUTUBE_CLIENT_SECRET") or config.YOUTUBE_CLIENT_SECRET or fallback_sec)
        self.refresh_token = refresh_token if refresh_token is not None else (os.environ.get("YOUTUBE_REFRESH_TOKEN") or config.YOUTUBE_REFRESH_TOKEN)
        self.mode = (mode or os.environ.get("YOUTUBE_PUBLISHING_MODE") or config.YOUTUBE_PUBLISHING_MODE or "live").strip().lower()
        self.privacy_status = (os.environ.get("YOUTUBE_PRIVACY_STATUS") or config.YOUTUBE_PRIVACY_STATUS or "private").strip().lower()
        self._client_info = info
        self._service = None

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)

    def _get_service(self):
        if self._service is not None:
            return self._service
        if not self.is_configured():
            return None
        creds = Credentials(
            None,
            refresh_token=self.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
        )
        self._service = build("youtube", "v3", credentials=creds)
        return self._service

    def get_connection_status(self, verify_network: bool = False) -> Dict[str, Any]:
        """Return non-secret YouTube client JSON & OAuth connection telemetry."""
        has_client = bool(self.client_id and self.client_secret)
        has_refresh = bool(self.refresh_token)
        info = self._client_info
        cached_title = (os.environ.get("YOUTUBE_CHANNEL_TITLE") or config.YOUTUBE_CHANNEL_TITLE or "").strip()
        cached_id = (os.environ.get("YOUTUBE_CHANNEL_ID") or config.YOUTUBE_CHANNEL_ID or "").strip()
        base: Dict[str, Any] = {
            "configured": has_client and has_refresh,
            "has_client_credentials": has_client,
            "has_refresh_token": has_refresh,
            "client_json_present": bool(info),
            "client_json_type": info["client_type"] if info else None,
            "client_id_masked": _mask_client_id(self.client_id),
            "healthy": False,
            "state": "missing_client",
            "mode": self.mode,
            "privacy_status": self.privacy_status,
            "channel_title": cached_title if has_refresh else "",
            "channel_id": cached_id if has_refresh else "",
            "last_checked_at": None,
            "message": "",
            **_build_reauth_telemetry(has_refresh, "connected" if has_refresh else "unconnected"),
        }

        if not has_client:
            base["state"] = "missing_client"
            base["message"] = "Upload client_secret.json to configure YouTube OAuth."
            return base

        if not has_refresh:
            base["state"] = "needs_auth"
            base["message"] = "Client JSON loaded. Click Connect YouTube OAuth to authorize."
            return base

        cached = _HEALTH_CACHE.get("data")
        now_ts = time.time()
        if not verify_network and cached and (now_ts - float(_HEALTH_CACHE.get("ts") or 0.0)) < _HEALTH_CACHE_TTL_SEC:
            out = dict(cached)
            out["mode"] = self.mode
            out["privacy_status"] = self.privacy_status
            out["client_json_present"] = bool(info)
            out["client_json_type"] = info["client_type"] if info else None
            out["client_id_masked"] = _mask_client_id(self.client_id)
            out.update(_build_reauth_telemetry(has_refresh, str(out.get("state") or "connected")))
            return out

        if not verify_network:
            base["healthy"] = True
            base["state"] = "connected"
            base["message"] = f"Connected to {cached_title}" if cached_title else "OAuth credentials connected."
            base.update(_build_reauth_telemetry(has_refresh, "connected"))
            return base

        try:
            resp = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=12,
            )
            checked_at = datetime.now(timezone.utc).isoformat()
            base["last_checked_at"] = checked_at
            if resp.status_code == 200:
                base["healthy"] = True
                base["state"] = "connected"
                base["message"] = "OAuth token valid."
                try:
                    svc = self._get_service()
                    if svc:
                        ch = svc.channels().list(mine=True, part="snippet").execute()
                        items = ch.get("items") or []
                        if items:
                            base["channel_id"] = str(items[0].get("id") or "")
                            base["channel_title"] = str((items[0].get("snippet") or {}).get("title") or "")
                            if base["channel_title"]:
                                base["message"] = f"Connected to {base['channel_title']}"
                                config.save_env_values(
                                    {
                                        "YOUTUBE_CHANNEL_TITLE": base["channel_title"],
                                        "YOUTUBE_CHANNEL_ID": base["channel_id"],
                                    }
                                )
                except Exception as exc:
                    logger.debug("Channel lookup failed after token refresh: %s", exc)
                base.update(_build_reauth_telemetry(has_refresh, "connected"))
                _HEALTH_CACHE["ts"] = now_ts
                _HEALTH_CACHE["data"] = dict(base)
                return base

            base["state"] = "token_invalid"
            base["message"] = f"OAuth refresh rejected ({resp.status_code}); reconnect YouTube OAuth."
            base.update(_build_reauth_telemetry(has_refresh, "token_invalid"))
            _HEALTH_CACHE["ts"] = now_ts
            _HEALTH_CACHE["data"] = dict(base)
            return base
        except Exception as exc:
            base["state"] = "token_invalid"
            base["message"] = str(exc)
            base.update(_build_reauth_telemetry(has_refresh, "token_invalid"))
            return base

    def check_health(self) -> Dict[str, Any]:
        return self.get_connection_status(verify_network=True)

    def _reconcile_existing(
        self,
        target_title: str,
        *,
        exclude_ids: Optional[Set[str]] = None,
        is_long: bool = False,
    ) -> Optional[Dict[str, Any]]:
        svc = self._get_service()
        if not svc:
            return None
        excluded = exclude_ids or set()
        try:
            ch = svc.channels().list(mine=True, part="contentDetails").execute()
            items = ch.get("items", [])
            if not items:
                return None
            uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
            pl = svc.playlistItems().list(playlistId=uploads_id, part="snippet", maxResults=25).execute()
            for entry in pl.get("items", []):
                snip = entry.get("snippet", {})
                vid = snip.get("resourceId", {}).get("videoId")
                if vid and vid in excluded:
                    continue
                if snip.get("title", "").strip() == target_title.strip():
                    url = f"https://www.youtube.com/watch?v={vid}" if is_long else f"https://www.youtube.com/shorts/{vid}"
                    return {
                        "success": True,
                        "video_id": vid,
                        "url": url,
                        "title": target_title,
                        "reconciled": True,
                        "simulated": False,
                    }
        except Exception as exc:
            logger.warning("Reconciliation lookup skipped: %s", exc)
        return None

    def upload_short(
        self,
        *,
        video_path: Path,
        title: str,
        description: str,
        tags: List[str],
        privacy_status: Optional[str] = None,
        publish_at: Optional[datetime] = None,
        force_mode: Optional[str] = None,
        exclude_youtube_ids: Optional[Set[str]] = None,
        is_long: bool = False,
    ) -> Dict[str, Any]:
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        effective_mode = (force_mode or self.mode).strip().lower()
        privacy = (privacy_status or self.privacy_status or config.YOUTUBE_PRIVACY_STATUS or "private").strip().lower()
        if privacy not in {"private", "unlisted", "public"}:
            privacy = "private"

        yt_title = clean_youtube_title(title, is_long=is_long)
        safe_desc = _strip_links(description)
        if not is_long and "#shorts" not in safe_desc.lower():
            safe_desc = f"{safe_desc}\n\n#Shorts".strip()
        safe_desc = safe_desc[:4900]
        clean_tags = fit_tags_within_budget(tags, max_chars=470, max_count=15)

        publish_iso = None
        if publish_at is not None:
            dt_utc = publish_at.astimezone(timezone.utc) if publish_at.tzinfo else publish_at.replace(tzinfo=timezone.utc)
            min_future = datetime.now(timezone.utc) + timedelta(minutes=16)
            if dt_utc < min_future:
                dt_utc = min_future
            publish_iso = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            # YouTube Data API v3 requires privacyStatus='private' when scheduling publishAt
            privacy = "private"

        if effective_mode == "simulation":
            sim_id = f"sim_{video_path.parent.name}"
            url = f"https://www.youtube.com/watch?v={sim_id}" if is_long else f"https://www.youtube.com/shorts/{sim_id}"
            return {
                "success": True,
                "video_id": sim_id,
                "url": url,
                "title": yt_title,
                "privacy_status": privacy,
                "publish_at": publish_iso,
                "simulated": True,
            }

        svc = self._get_service()
        if not svc:
            raise YouTubeUploadError(
                "YouTube OAuth is not connected yet. Upload client_secret.json and click Connect YouTube OAuth first."
            )

        reconciled = self._reconcile_existing(yt_title, exclude_ids=exclude_youtube_ids, is_long=is_long)
        if reconciled:
            return reconciled

        status_body: Dict[str, Any] = {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        }
        if publish_iso:
            status_body["publishAt"] = publish_iso

        body = {
            "snippet": {
                "title": yt_title,
                "description": safe_desc,
                "tags": clean_tags,
                "categoryId": config.YOUTUBE_CATEGORY_ID,
            },
            "status": status_body,
        }

        media = MediaFileUpload(str(video_path), chunksize=2 * 1024 * 1024, resumable=True)
        request = svc.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        retries = 0
        while response is None:
            try:
                _, response = request.next_chunk()
                retries = 0
            except HttpError as exc:
                status_code = getattr(exc.resp, "status", 0)
                if status_code in {429, 500, 502, 503, 504} and retries < 3:
                    retries += 1
                    time.sleep(2 ** retries)
                    continue
                raise YouTubeUploadError(f"YouTube API error ({status_code}): {exc}") from exc
            except Exception as exc:
                if retries < 3:
                    retries += 1
                    time.sleep(2 ** retries)
                    continue
                raise YouTubeUploadError(f"YouTube upload interrupted: {exc}") from exc

        vid = str(response.get("id") or "")
        if not vid:
            raise YouTubeUploadError("YouTube upload finished without returning a video ID.")

        resp_status = response.get("status", {})
        url = f"https://www.youtube.com/watch?v={vid}" if is_long else f"https://www.youtube.com/shorts/{vid}"
        return {
            "success": True,
            "video_id": vid,
            "url": url,
            "title": yt_title,
            "privacy_status": resp_status.get("privacyStatus", privacy),
            "publish_at": resp_status.get("publishAt") or publish_iso,
            "simulated": False,
        }

    upload_video = upload_short
