"""YouTube Data API v3 uploader with safe simulation/private defaults and duplicate protection."""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from reelforge import config

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
    return re.sub(r"https?://\S+", "", text or "").strip()


class YouTubeUploader:
    """Official YouTube Data API v3 Shorts uploader."""

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
        self.mode = (mode or os.environ.get("YOUTUBE_PUBLISHING_MODE") or config.YOUTUBE_PUBLISHING_MODE).strip().lower()
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
            "channel_title": "",
            "channel_id": "",
            "last_checked_at": None,
            "message": "",
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
            return out

        if not verify_network:
            base["healthy"] = True
            base["state"] = "connected"
            base["message"] = "OAuth credentials present (click Test Connection to verify)."
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
                except Exception as exc:
                    logger.debug("Channel lookup failed after token refresh: %s", exc)
                _HEALTH_CACHE["ts"] = now_ts
                _HEALTH_CACHE["data"] = dict(base)
                return base

            base["state"] = "token_invalid"
            base["message"] = f"OAuth refresh rejected ({resp.status_code}); reconnect YouTube OAuth."
            _HEALTH_CACHE["ts"] = now_ts
            _HEALTH_CACHE["data"] = dict(base)
            return base
        except Exception as exc:
            base["state"] = "token_invalid"
            base["message"] = str(exc)
            return base

    def check_health(self) -> Dict[str, Any]:
        return self.get_connection_status(verify_network=True)

    def _reconcile_existing(self, target_title: str, exclude_ids: Optional[Set[str]] = None) -> Optional[Dict[str, Any]]:
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
                    return {
                        "success": True,
                        "video_id": vid,
                        "url": f"https://www.youtube.com/shorts/{vid}",
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
    ) -> Dict[str, Any]:
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        effective_mode = (force_mode or self.mode).strip().lower()
        privacy = (privacy_status or config.YOUTUBE_PRIVACY_STATUS or "private").strip().lower()
        if privacy not in {"private", "unlisted", "public"}:
            privacy = "private"

        clean_title = re.sub(r"\s*#[A-Za-z0-9_]+\b", "", _strip_links(title)).strip(" -|")
        yt_title = f"{clean_title[:84].rstrip()} #Shorts" if clean_title else "ReelForge Short #Shorts"
        safe_desc = _strip_links(description)
        if "#shorts" not in safe_desc.lower():
            safe_desc = f"{safe_desc}\n\n#Shorts".strip()
        clean_tags = [t.replace("#", "").strip() for t in tags if t.strip()][:15]

        publish_iso = None
        if publish_at is not None:
            dt_utc = publish_at.astimezone(timezone.utc) if publish_at.tzinfo else publish_at.replace(tzinfo=timezone.utc)
            publish_iso = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            # YouTube requires privacyStatus='private' when scheduling publishAt
            privacy = "private"

        if effective_mode != "live":
            sim_id = f"sim_{video_path.parent.name}"
            return {
                "success": True,
                "video_id": sim_id,
                "url": f"https://www.youtube.com/shorts/{sim_id}",
                "title": yt_title,
                "privacy_status": privacy,
                "publish_at": publish_iso,
                "simulated": True,
            }

        svc = self._get_service()
        if not svc:
            raise YouTubeUploadError(
                "Live YouTube upload requested, but OAuth credentials are missing. "
                "Run `.venv/bin/python scripts/auth_youtube.py` first."
            )

        reconciled = self._reconcile_existing(yt_title, exclude_ids=exclude_youtube_ids)
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

        media = MediaFileUpload(str(video_path), chunksize=1024 * 1024, resumable=True)
        request = svc.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            _, response = request.next_chunk()

        vid = str(response.get("id") or "")
        if not vid:
            raise YouTubeUploadError("YouTube upload finished without returning a video ID.")

        resp_status = response.get("status", {})
        return {
            "success": True,
            "video_id": vid,
            "url": f"https://www.youtube.com/shorts/{vid}",
            "title": yt_title,
            "privacy_status": resp_status.get("privacyStatus", privacy),
            "publish_at": resp_status.get("publishAt") or publish_iso,
            "simulated": False,
        }
