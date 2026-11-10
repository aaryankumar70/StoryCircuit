"""Official Meta Instagram Graph API Publisher for Instagram Reels.
Standardized on Instagram Login (graph.instagram.com) with dynamic API versioning (v22.0).
Implements official 3-step Reels container flow, container status polling,
duplicate reconciliation, and clear error categorization.

Strict ₹0 Budget: Never silently substitutes mock success when live upload is requested.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from curiosity_engine.config import (
    INSTAGRAM_ACCESS_TOKEN,
    INSTAGRAM_ACCOUNT_ID,
    INSTAGRAM_API_VERSION,
    INSTAGRAM_PUBLISHING_MODE,
    PUBLISHING_MODE,
)
from curiosity_engine.distribution.video_host import BaseVideoHost, get_video_host

logger = logging.getLogger("curiosity_engine.instagram")


class InstagramPublisherError(Exception):
    """Base exception for Instagram publishing errors."""
    pass


class InstagramAuthError(InstagramPublisherError):
    """Raised when access token is invalid, expired, or permissions are insufficient."""
    pass


class InstagramMediaProcessingError(InstagramPublisherError):
    """Raised when container media processing fails on Meta servers."""
    pass


class InstagramDuplicateError(InstagramPublisherError):
    """Raised when duplicate publishing is prevented."""
    pass


class InstagramPublisher:
    """Official Meta Instagram Graph API client using pure Instagram Login."""

    def __init__(
        self,
        access_token: Optional[str] = None,
        account_id: Optional[str] = None,
        api_version: Optional[str] = None,
        mode: Optional[str] = None,
        video_host: Optional[BaseVideoHost] = None,
    ):
        self.access_token = access_token if access_token is not None else (INSTAGRAM_ACCESS_TOKEN or os.environ.get("INSTAGRAM_ACCESS_TOKEN"))
        self.account_id = account_id if account_id is not None else (INSTAGRAM_ACCOUNT_ID or os.environ.get("INSTAGRAM_ACCOUNT_ID"))
        self.api_version = (api_version or INSTAGRAM_API_VERSION or "v22.0").strip()
        self.mode = (mode or INSTAGRAM_PUBLISHING_MODE or PUBLISHING_MODE or "disabled").strip().lower()
        self.video_host = video_host or get_video_host()
        self.base_url = f"https://graph.instagram.com/{self.api_version}"

    def is_configured(self) -> bool:
        """Check if access token and account ID are populated."""
        return bool(self.access_token and self.account_id and len(self.access_token.strip()) > 20)

    def reconcile_existing_post(self, caption_prefix: str) -> Optional[Dict[str, Any]]:
        """Query recent media on the Instagram account to prevent duplicate reel publishing."""
        if not self.is_configured():
            return None

        url = f"{self.base_url}/{self.account_id}/media"
        params = {
            "fields": "id,caption,permalink,timestamp",
            "access_token": self.access_token,
            "limit": 5,
        }

        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("data", []):
                    post_caption = item.get("caption", "")
                    if caption_prefix.strip() and caption_prefix.strip() in post_caption:
                        media_id = item.get("id")
                        permalink = item.get("permalink", f"https://www.instagram.com/reel/{media_id}/")
                        logger.warning(
                            f"Duplicate Instagram Reel prevented: found recent post '{media_id}' matching caption."
                        )
                        return {
                            "success": True,
                            "media_id": media_id,
                            "url": permalink,
                            "reconciled": True,
                            "simulated": False,
                        }
        except Exception as e:
            logger.warning(f"Instagram duplicate reconciliation check encountered non-fatal error: {e}")

        return None

    def publish_reel(
        self,
        video_path: Path,
        caption: str,
        hashtags: List[str],
        cover_url: Optional[str] = None,
        force_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Publish video to Instagram Reels via official 3-step container flow.
        Never silently falls back to simulation when 'live' mode is requested.
        """
        effective_mode = (force_mode or self.mode).strip().lower()

        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        clean_hashtags = " ".join([h if h.startswith("#") else f"#{h}" for h in hashtags if h.strip()])
        full_caption = f"{caption}\n\n{clean_hashtags}".strip()

        # Handle DISABLED mode (Default: strict ₹0 target with zero network calls)
        if effective_mode == "disabled":
            logger.info("[INSTAGRAM DISABLED] Instagram publishing is disabled (₹0 target). Bypassing without network calls.")
            return {
                "success": True,
                "media_id": None,
                "url": None,
                "published_at": None,
                "caption": full_caption,
                "simulated": False,
                "disabled": True,
                "status": "DISABLED",
            }

        # Mode enforcement: strict separation between LIVE and SIMULATION
        if effective_mode == "live":
            if not self.is_configured():
                raise InstagramAuthError(
                    "Live Instagram publishing requested, but credentials are not configured. "
                    "Run 'python scripts/auth_instagram.py' to establish tokens."
                )

            # Check duplicate reconciliation before creating a container
            caption_hook = caption.split("\n")[0][:40]
            reconciled = self.reconcile_existing_post(caption_hook)
            if reconciled:
                return reconciled

            # Obtain hosted video URL
            hosted_video_url = self.video_host.host_video(video_path)
            if "simulation.curioloop.local" in hosted_video_url:
                raise InstagramPublisherError(
                    "Cannot publish live Instagram Reel using a simulated video URL. "
                    "External hosting is disabled pending verified zero-cost audit."
                )

            # Step 1: Create media container
            container_url = f"{self.base_url}/{self.account_id}/media"
            container_payload: Dict[str, Any] = {
                "media_type": "REELS",
                "video_url": hosted_video_url,
                "caption": full_caption,
                "access_token": self.access_token,
            }
            if cover_url:
                container_payload["cover_url"] = cover_url

            logger.info(f"Creating Instagram Reel container for account {self.account_id}...")
            res = requests.post(container_url, data=container_payload, timeout=60)

            if res.status_code != 200:
                err_body = res.json().get("error", {}) if "application/json" in res.headers.get("Content-Type", "") else {}
                code = err_body.get("code")
                subcode = err_body.get("error_subcode")
                msg = err_body.get("message", res.text)

                if code == 190 or subcode in (463, 467):
                    raise InstagramAuthError(
                        f"Instagram access token expired or revoked (code={code}, subcode={subcode}): {msg}"
                    )
                raise InstagramPublisherError(f"Container creation failed ({res.status_code}): {msg}")

            container_id = res.json().get("id")
            logger.info(f"Container created successfully. ID: {container_id}")

            # Step 2: Poll container processing status
            status_url = f"{self.base_url}/{container_id}"
            max_polls = 30
            poll_interval = 10
            is_ready = False

            try:
                for poll in range(max_polls):
                    time.sleep(poll_interval)
                    status_res = requests.get(
                        status_url,
                        params={"fields": "status_code,status", "access_token": self.access_token},
                        timeout=30,
                    )
                    if status_res.status_code == 200:
                        status_data = status_res.json()
                        status_code = status_data.get("status_code")
                        logger.info(f"Container {container_id} status (poll {poll+1}): {status_code}")
                        if status_code == "FINISHED":
                            is_ready = True
                            break
                        elif status_code == "ERROR":
                            raise InstagramMediaProcessingError(
                                f"Instagram server processing failed for container {container_id}: {status_data}"
                            )
                        elif status_code == "EXPIRED":
                            raise InstagramMediaProcessingError(
                                f"Instagram container {container_id} expired during server processing."
                            )
                    elif status_res.status_code == 400:
                        err_json = status_res.json().get("error", {})
                        if err_json.get("code") == 190:
                            raise InstagramAuthError("Token expired while polling container status.")
            finally:
                # Cleanup temporary hosted file once ingestion finishes or errors
                self.video_host.cleanup(hosted_video_url)

            if not is_ready:
                raise TimeoutError(f"Instagram container {container_id} processing timed out after 300s.")

            # Step 3: Publish container
            publish_url = f"{self.base_url}/{self.account_id}/media_publish"
            publish_res = requests.post(
                publish_url,
                data={"creation_id": container_id, "access_token": self.access_token},
                timeout=60,
            )
            if publish_res.status_code != 200:
                raise InstagramPublisherError(
                    f"Media publish failed ({publish_res.status_code}): {publish_res.text}"
                )

            media_id = publish_res.json().get("id")
            logger.info(f"Instagram Reel successfully published! Media ID: {media_id}")
            return {
                "success": True,
                "media_id": media_id,
                "url": f"https://www.instagram.com/reel/{media_id}/",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "caption": full_caption,
                "simulated": False,
            }

        # Default / Explicit Simulation Mode
        sim_id = f"ig_sim_{int(time.time())}"
        logger.info(f"[SIMULATION MODE] Simulated Instagram Reel publish -> Media ID: {sim_id}")
        return {
            "success": True,
            "media_id": sim_id,
            "url": f"https://www.instagram.com/reel/{sim_id}/",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "caption": full_caption,
            "simulated": True,
        }


instagram_publisher = InstagramPublisher()
