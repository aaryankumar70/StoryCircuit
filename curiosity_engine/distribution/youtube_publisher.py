"""Official YouTube Data API v3 Publisher for YouTube Shorts.
Supports OAuth 2.0 token rotation, dedicated upload quota tracking (100 uploads/day),
resumable chunked uploads, categorized error diagnostics, duplicate upload reconciliation,
and private/unlisted test publishing.

Strict ₹0 Budget: Never silently substitutes mock success when live upload is requested.
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

from curiosity_engine import config
from curiosity_engine.content.description_generator import strip_external_links
from curiosity_engine.distribution.youtube_quota import youtube_quota
from curiosity_engine.config import (
    PUBLISHING_MODE,
    YOUTUBE_CLIENT_ID,
    YOUTUBE_CLIENT_SECRET,
    YOUTUBE_PRIVACY_STATUS,
    YOUTUBE_PUBLISHING_MODE,
    YOUTUBE_REFRESH_TOKEN,
    YOUTUBE_UPLOAD_DAILY_LIMIT,
)

logger = logging.getLogger("curiosity_engine.youtube")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

# Disposable test uploads that must never count toward daily production limits
# or be modified/rescheduled by automated production jobs.
NON_PRODUCTION_TEST_YOUTUBE_IDS = frozenset({"N3QUKd0u71U"})


class YouTubePublisherError(Exception):
    """Base exception for YouTube publishing errors."""
    pass


class DailyPublishingLimitError(YouTubePublisherError):
    """Raised when daily production publication limit or slot capacity is reached."""
    pass


class YouTubeAuthError(YouTubePublisherError):
    """Raised when OAuth token is expired, revoked, or invalid."""
    pass


class YouTubeQuotaError(YouTubePublisherError):
    """Raised when project API upload quota is exhausted."""
    pass


class YouTubeChannelLimitError(YouTubePublisherError):
    """Raised when channel-level daily upload limit is reached (anti-spam)."""
    pass


class YouTubePublisher:
    """Official YouTube Data API v3 client with hardened error classification and reconciliation."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
        mode: Optional[str] = None,
    ):
        if client_id is None and client_secret is None and refresh_token is None:
            config.sync_env_if_updated()
        self.client_id = client_id if client_id is not None else (os.environ.get("YOUTUBE_CLIENT_ID") or config.YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_ID)
        self.client_secret = client_secret if client_secret is not None else (os.environ.get("YOUTUBE_CLIENT_SECRET") or config.YOUTUBE_CLIENT_SECRET or YOUTUBE_CLIENT_SECRET)
        self.refresh_token = refresh_token if refresh_token is not None else (os.environ.get("YOUTUBE_REFRESH_TOKEN") or config.YOUTUBE_REFRESH_TOKEN or YOUTUBE_REFRESH_TOKEN)
        self.mode = (mode or YOUTUBE_PUBLISHING_MODE or PUBLISHING_MODE or "simulation").strip().lower()
        self.daily_upload_limit = YOUTUBE_UPLOAD_DAILY_LIMIT
        self.service = None
        self._init_service()

    def refresh_credentials_if_changed(self) -> bool:
        """Hot-reload YouTube credentials from .env if updated by reauthorization."""
        config.sync_env_if_updated()
        new_cid = os.environ.get("YOUTUBE_CLIENT_ID") or config.YOUTUBE_CLIENT_ID or ""
        new_sec = os.environ.get("YOUTUBE_CLIENT_SECRET") or config.YOUTUBE_CLIENT_SECRET or ""
        new_ref = os.environ.get("YOUTUBE_REFRESH_TOKEN") or config.YOUTUBE_REFRESH_TOKEN or ""
        if (new_cid, new_sec, new_ref) != (self.client_id or "", self.client_secret or "", self.refresh_token or ""):
            if new_cid and new_sec and new_ref:
                self.client_id = new_cid
                self.client_secret = new_sec
                self.refresh_token = new_ref
                self._init_service()
                logger.info("Reloaded updated YouTube OAuth credentials from .env.")
                return True
        return False

    def _init_service(self) -> None:
        """Initialize Google API client if credentials are provided."""
        if self.client_id and self.client_secret and self.refresh_token:
            try:
                # Omit explicit scopes here so tokens authorized with either subset or full scopes refresh cleanly
                creds = Credentials(
                    None,
                    refresh_token=self.refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                )
                self.service = build("youtube", "v3", credentials=creds)
                logger.info("YouTube Data API v3 client initialized successfully.")
            except Exception as e:
                logger.warning(f"YouTube client initialization failed: {e}")
                self.service = None
        else:
            self.service = None

    def is_configured(self) -> bool:
        """Check if OAuth credentials are fully provided."""
        return bool(self.client_id and self.client_secret and self.refresh_token)

    def reconcile_existing_upload(
        self,
        target_title: str,
        exclude_video_ids: Optional[set[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Check if a video with the exact title was already uploaded to avoid duplicate publishing.
        Skips YouTube IDs in exclude_video_ids (already claimed by other local video records).
        """
        if not self.service:
            return None

        excluded = exclude_video_ids or set()
        try:
            # Query recent uploads on the channel
            channels_response = self.service.channels().list(mine=True, part="contentDetails").execute()
            youtube_quota.record_operation("channels.list")
            items = channels_response.get("items", [])
            if not items:
                return None

            uploads_list_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
            playlist_items = self.service.playlistItems().list(
                playlistId=uploads_list_id,
                part="snippet",
                maxResults=25,
            ).execute()
            youtube_quota.record_operation("playlistItems.list")

            for item in playlist_items.get("items", []):
                snippet = item.get("snippet", {})
                title = snippet.get("title", "")
                if title.strip() == target_title.strip():
                    video_id = snippet.get("resourceId", {}).get("videoId")
                    if video_id and video_id in excluded:
                        logger.info(
                            f"Skipping channel video {video_id} ('{title}') during reconciliation: "
                            "already claimed by another local record."
                        )
                        continue
                    logger.warning(
                        f"Duplicate upload prevented: found matching video '{title}' (ID: {video_id}) on channel."
                    )
                    verified_st = self.get_video_status(video_id) if video_id else None
                    confirmed_publish_at = verified_st.get("publish_at") if verified_st else None
                    privacy = verified_st.get("privacy_status") if verified_st else None
                    return {
                        "success": True,
                        "video_id": video_id,
                        "url": f"https://www.youtube.com/shorts/{video_id}",
                        "title": title,
                        "privacy_status": privacy or "private",
                        "publish_at": confirmed_publish_at,
                        "schedule_confirmed": bool(confirmed_publish_at and privacy == "private"),
                        "reconciled": True,
                        "simulated": False,
                    }
        except Exception as e:
            logger.warning(f"Upload reconciliation query failed (proceeding with upload check): {e}")

        return None

    def upload_short(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: List[str],
        category_id: str = "27",  # 27 = Education
        privacy_status: Optional[str] = None,
        publish_at: Optional[datetime] = None,
        force_mode: Optional[str] = None,
        exclude_youtube_ids: Optional[set[str]] = None,
    ) -> Dict[str, Any]:
        """Upload video file as a YouTube Short with verified metadata.
        Never silently falls back to simulation when 'live' mode is requested.
        Strictly defaults to 'private' privacy unless explicitly configured.
        """
        effective_mode = (force_mode or self.mode).strip().lower()
        effective_privacy = (privacy_status or YOUTUBE_PRIVACY_STATUS or "private").strip().lower()
        if effective_privacy not in ["private", "unlisted", "public"]:
            effective_privacy = "private"

        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Sanitize title cleanly (strip external links and stray hashtag stuffing before appending #Shorts)
        clean_title_base = re.sub(r"\s*#[A-Za-z0-9_]+\b", "", strip_external_links(title)).strip(" -|")
        yt_title = f"{clean_title_base[:80].rstrip()} #Shorts" if clean_title_base else "CurioLoop Story #Shorts"

        safe_desc = strip_external_links(description)
        if "#Shorts" not in safe_desc and "#shorts" not in safe_desc:
            yt_description = f"{safe_desc}\n\n#Shorts #Curiosity" if safe_desc else "#Shorts #Curiosity"
        else:
            yt_description = safe_desc

        clean_tags = [t.replace("#", "").strip() for t in tags if t.strip()]

        # Mode enforcement: strict separation between LIVE and SIMULATION
        if effective_mode == "live":
            if not self.is_configured():
                raise YouTubeAuthError(
                    "Live YouTube publishing requested, but OAuth credentials are not configured. "
                    "Run 'python scripts/auth_youtube.py' to establish OAuth credentials."
                )
            if not self.service:
                self._init_service()
                if not self.service:
                    raise YouTubeAuthError(
                        "Live YouTube publishing requested, but client service failed to initialize. "
                        "Check client_id and refresh_token validity."
                    )

            # Reconcile duplicate before uploading
            reconciled = self.reconcile_existing_upload(
                yt_title,
                exclude_video_ids=exclude_youtube_ids,
            )
            if reconciled:
                return reconciled

            status_body: Dict[str, Any] = {
                "privacyStatus": effective_privacy,
                "selfDeclaredMadeForKids": False,
            }
            if publish_at:
                if publish_at.astimezone(timezone.utc) <= datetime.now(timezone.utc):
                    raise YouTubePublisherError(
                        f"Refusing to schedule video in the past: {publish_at.isoformat()}"
                    )
                status_body["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                status_body["privacyStatus"] = "private"

            body = {
                "snippet": {
                    "title": yt_title,
                    "description": yt_description,
                    "tags": clean_tags,
                    "categoryId": category_id,
                    "defaultLanguage": "en",
                },
                "status": status_body,
            }

            media = MediaFileUpload(
                str(video_path),
                mimetype="video/mp4",
                resumable=True,
                chunksize=1024 * 1024 * 4,  # 4MB chunks
            )
            request = self.service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )

            response = None
            for attempt in range(5):
                try:
                    status, response = request.next_chunk()
                    if status:
                        logger.info(f"YouTube Upload Progress: {int(status.progress() * 100)}%")
                    if response is not None:
                        youtube_quota.record_operation("videos.insert")
                        video_id = response.get("id")
                        resp_status = response.get("status", {})
                        confirmed_publish_at = resp_status.get("publishAt")
                        confirmed_privacy = resp_status.get("privacyStatus", status_body.get("privacyStatus"))
                        upload_status = resp_status.get("uploadStatus")
                        rejection_reason = resp_status.get("rejectionReason")

                        if publish_at and video_id:
                            verified_st = self.get_video_status(video_id)
                            if verified_st:
                                confirmed_publish_at = verified_st.get("publish_at") or confirmed_publish_at
                                confirmed_privacy = verified_st.get("privacy_status") or confirmed_privacy
                                upload_status = verified_st.get("upload_status") or upload_status
                                rejection_reason = verified_st.get("rejection_reason") or rejection_reason

                        if upload_status == "rejected":
                            raise YouTubePublisherError(
                                f"YouTube rejected uploaded video {video_id}: "
                                f"reason={rejection_reason or 'unknown'}"
                            )

                        logger.info(f"YouTube Upload Complete! Video ID: {video_id} (publishAt={confirmed_publish_at})")
                        return {
                            "success": True,
                            "video_id": video_id,
                            "url": f"https://www.youtube.com/shorts/{video_id}",
                            "published_at": datetime.now(timezone.utc).isoformat(),
                            "title": yt_title,
                            "privacy_status": confirmed_privacy,
                            "upload_status": upload_status,
                            "publish_at": confirmed_publish_at,
                            "schedule_confirmed": bool(confirmed_publish_at and confirmed_privacy == "private"),
                            "simulated": False,
                        }
                except HttpError as e:
                    error_content = str(e.content) if hasattr(e, "content") else str(e)
                    logger.error(f"YouTube API HttpError on attempt {attempt+1}: {error_content}")

                    if "uploadLimitExceeded" in error_content:
                        raise YouTubeChannelLimitError(
                            "YouTube channel daily upload limit reached (uploadLimitExceeded). "
                            "Wait until tomorrow UTC before uploading additional videos."
                        ) from e
                    elif "quotaExceeded" in error_content:
                        raise YouTubeQuotaError(
                            "YouTube Data API project quota exhausted (quotaExceeded)."
                        ) from e
                    elif "invalid_grant" in error_content:
                        raise YouTubeAuthError(
                            "YouTube OAuth refresh token expired or revoked ('invalid_grant'). "
                            "Reauthorization required via 'python scripts/auth_youtube.py'."
                        ) from e

                    # Transient retry for 5xx errors
                    if e.resp.status in [500, 502, 503, 504]:
                        time.sleep(2 * (attempt + 1))
                        continue
                    raise YouTubePublisherError(f"YouTube API error: {e}") from e
                except Exception as e:
                    logger.error(f"Unexpected error during YouTube upload: {e}")
                    raise YouTubePublisherError(f"Unexpected upload failure: {e}") from e

            raise YouTubePublisherError("YouTube upload chunking exhausted all 5 retry attempts.")

        # Default / Explicit Simulation Mode
        sim_id = f"yt_sim_{int(time.time())}"
        sim_publish_at = (
            publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            if publish_at else None
        )
        logger.info(f"[SIMULATION MODE] Simulated YouTube Shorts upload: '{yt_title}' -> ID: {sim_id}")
        return {
            "success": True,
            "video_id": sim_id,
            "url": f"https://www.youtube.com/shorts/{sim_id}",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "title": yt_title,
            "privacy_status": f"simulation_{effective_privacy}",
            "publish_at": sim_publish_at,
            "schedule_confirmed": False,
            "simulated": True,
        }

    def _ensure_live_service(self) -> None:
        """Ensure OAuth credentials and YouTube API service are ready for live mutations."""
        if not self.is_configured():
            raise YouTubeAuthError("YouTube OAuth credentials are not configured.")
        if not self.service:
            self._init_service()
            if not self.service:
                raise YouTubeAuthError("YouTube service initialization failed.")

    def _build_preserved_status_body(
        self,
        video_id: str,
        privacy_status: str = "private",
        publish_at_utc: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a videos.update status body preserving safe existing flags."""
        existing_status: Dict[str, Any] = {}
        try:
            list_resp = self.service.videos().list(part="status", id=video_id).execute()
            youtube_quota.record_operation("videos.list")
            items = list_resp.get("items", [])
            if items:
                existing_status = items[0].get("status", {})
        except Exception:
            existing_status = {}

        merged_status: Dict[str, Any] = {
            k: v for k, v in existing_status.items()
            if k in ("embeddable", "license", "publicStatsViewable", "selfDeclaredMadeForKids")
        }
        merged_status["privacyStatus"] = privacy_status
        if publish_at_utc:
            merged_status["publishAt"] = publish_at_utc
        return merged_status

    @staticmethod
    def _raise_update_http_error(e: HttpError, video_id: str, action: str) -> None:
        """Translate YouTube videos.update HttpError into actionable domain exceptions."""
        error_content = str(e.content) if hasattr(e, "content") else str(e)
        logger.error(f"YouTube API HttpError {action} video {video_id}: {error_content}")
        if "invalid_grant" in error_content:
            raise YouTubeAuthError("OAuth token expired or revoked ('invalid_grant').") from e
        if "insufficientPermissions" in error_content or "PERMISSION_DENIED" in error_content:
            raise YouTubeAuthError(
                f"YouTube API rejected videos.update while {action} (403 insufficientPermissions): "
                "Current OAuth refresh token lacks 'youtube.force-ssl' scope. "
                "Re-run 'python scripts/auth_youtube.py' to grant scheduling update scope, "
                "or schedule directly at upload time via publish_at."
            ) from e
        raise YouTubePublisherError(f"YouTube error while {action}: {e}") from e

    def schedule_publication(
        self,
        video_id: str,
        publish_at: datetime,
        force_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Schedule publication of a private YouTube video using status.publishAt.
        In YouTube Data API v3, setting publishAt requires status.privacyStatus to be 'private'
        and a future UTC RFC 3339 timestamp.
        """
        if publish_at.astimezone(timezone.utc) <= datetime.now(timezone.utc):
            raise YouTubePublisherError(
                f"Cannot schedule publication in the past: {publish_at.isoformat()}"
            )

        effective_mode = (force_mode or self.mode).strip().lower()
        publish_at_utc = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        if effective_mode == "live":
            self._ensure_live_service()
            merged_status = self._build_preserved_status_body(
                video_id=video_id,
                privacy_status="private",
                publish_at_utc=publish_at_utc,
            )
            body = {"id": video_id, "status": merged_status}
            try:
                response = self.service.videos().update(part="status", body=body).execute()
                youtube_quota.record_operation("videos.update")
                status = response.get("status", {})
                confirmed_at = status.get("publishAt")
                confirmed_privacy = status.get("privacyStatus")
                if not confirmed_at or confirmed_privacy != "private":
                    raise YouTubePublisherError(
                        f"YouTube API response did not confirm scheduled private state: {response}"
                    )
                logger.info(f"YouTube video {video_id} scheduled for publication at {confirmed_at}")
                return {
                    "success": True,
                    "video_id": video_id,
                    "publish_at": confirmed_at,
                    "privacy_status": confirmed_privacy,
                    "status": "SCHEDULED",
                    "schedule_confirmed": True,
                    "simulated": False,
                }
            except YouTubePublisherError:
                raise
            except HttpError as e:
                self._raise_update_http_error(e, video_id, "scheduling")
            except Exception as e:
                logger.error(f"Unexpected error scheduling YouTube video {video_id}: {e}")
                raise YouTubePublisherError(f"Unexpected scheduling failure: {e}") from e

        # Simulation Mode (explicitly marks schedule_confirmed=False!)
        logger.info(f"[SIMULATION MODE] Simulated schedule for YouTube video {video_id} at {publish_at_utc}")
        return {
            "success": True,
            "video_id": video_id,
            "publish_at": publish_at_utc,
            "privacy_status": "simulation_private",
            "status": "SCHEDULED",
            "schedule_confirmed": False,
            "simulated": True,
        }

    def get_video_status(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Query YouTube Data API v3 for actual video status, privacy, and scheduled publish time."""
        if not self.is_configured():
            return None
        if not self.service:
            self._init_service()
        if not self.service:
            return None

        try:
            request = self.service.videos().list(part="status,snippet", id=video_id)
            response = request.execute()
            youtube_quota.record_operation("videos.list")
            items = response.get("items", [])
            if not items:
                return None
            item = items[0]
            status = item.get("status", {})
            snippet = item.get("snippet", {})
            return {
                "video_id": video_id,
                "title": snippet.get("title"),
                "upload_status": status.get("uploadStatus"),
                "privacy_status": status.get("privacyStatus"),
                "publish_at": status.get("publishAt"),
                "rejection_reason": status.get("rejectionReason"),
            }
        except Exception as e:
            logger.warning(f"Failed to fetch YouTube status for {video_id}: {e}")
            return None

    def cancel_schedule(
        self,
        video_id: str,
        force_mode: Optional[str] = None,
        verify_timeout_sec: float = 20.0,
        poll_interval_sec: float = 2.0,
    ) -> Dict[str, Any]:
        """Cancel scheduled publication on a private YouTube video, keeping it private.
        Executes videos.update once and uses bounded readback polling to handle
        YouTube Data API read-after-write propagation delay.
        """
        effective_mode = (force_mode or self.mode).strip().lower()
        if effective_mode != "live":
            return {
                "success": True,
                "video_id": video_id,
                "privacy_status": "simulation_private",
                "publish_at": None,
                "schedule_cancelled": False,
                "simulated": True,
            }

        self._ensure_live_service()
        # Setting privacyStatus='private' and omitting publishAt cancels scheduled publication
        merged_status = self._build_preserved_status_body(
            video_id=video_id,
            privacy_status="private",
            publish_at_utc=None,
        )

        try:
            response = self.service.videos().update(
                part="status",
                body={"id": video_id, "status": merged_status},
            ).execute()
            youtube_quota.record_operation("videos.update")
            status_obj = response.get("status", {})
            last_privacy = status_obj.get("privacyStatus")
            last_publish_at = status_obj.get("publishAt")

            # Bounded read-after-write polling; videos.update is never repeated.
            timeout_sec = max(0.0, float(verify_timeout_sec))
            interval_sec = max(0.0, float(poll_interval_sec))
            deadline = time.monotonic() + timeout_sec
            attempt = 0

            while True:
                attempt += 1
                verified = self.get_video_status(video_id)
                if verified is not None:
                    last_privacy = verified.get("privacy_status")
                    last_publish_at = verified.get("publish_at")
                    if last_privacy == "private" and not last_publish_at:
                        logger.info(
                            f"Cancelled scheduled publication for {video_id} "
                            f"(confirmed on readback attempt {attempt}); video remains private."
                        )
                        return {
                            "success": True,
                            "video_id": video_id,
                            "privacy_status": last_privacy,
                            "publish_at": last_publish_at,
                            "schedule_cancelled": True,
                            "simulated": False,
                        }

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                sleep_sec = min(interval_sec, remaining)
                if sleep_sec > 0:
                    time.sleep(sleep_sec)

            raise YouTubePublisherError(
                f"Timed out after {timeout_sec:.1f}s confirming schedule cancellation for {video_id}: "
                f"last observed privacyStatus={last_privacy!r}, publishAt={last_publish_at!r}"
            )
        except YouTubePublisherError:
            raise
        except HttpError as e:
            self._raise_update_http_error(e, video_id, "cancelling schedule")
        except Exception as e:
            raise YouTubePublisherError(f"Unexpected schedule cancellation failure: {e}") from e


youtube_publisher = YouTubePublisher()
