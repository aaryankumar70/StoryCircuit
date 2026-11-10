"""Telegram Bot API Notification Service for CurioLoop.

Provides durable, deduplicated, retry-safe operational alerts for:
- Confirmed PUBLIC YouTube publications (strictly gated on privacyStatus == 'public')
- OAuth 7-day expiration 24-hour warnings, urgent revocation alerts, and reauth confirmations
- Upload, scheduling, processing, rejection, auth, and missed-publication failures
- Once-per-IST-day operational summary

Security guarantees:
- Bot token and chat ID are read only from environment / config and NEVER logged or stored.
- Delivery errors are caught and persisted locally so Telegram outages never crash publishing.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import tempfile
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

from curiosity_engine import config

logger = logging.getLogger("curiosity_engine.notifications.telegram")

IST = ZoneInfo("Asia/Kolkata")
NOTIFICATIONS_STATE_FILE = config.DATA_DIR / "notifications_state.json"

_BOT_TOKEN_PATTERN = re.compile(r"bot\d{6,14}:[A-Za-z0-9_-]{20,}", re.IGNORECASE)
_RAW_BOT_TOKEN_PATTERN = re.compile(r"\b\d{8,14}:[A-Za-z0-9_-]{30,}\b")


def redact_telegram_secrets(text: str, extra_secrets: Optional[List[str]] = None) -> str:
    """Strip Telegram bot tokens and chat IDs from text before logging or persistence."""
    if not text:
        return ""
    sanitized = str(text)
    if extra_secrets:
        for secret in extra_secrets:
            if secret and len(secret.strip()) >= 4:
                sanitized = sanitized.replace(secret.strip(), "***REDACTED***")
                encoded = urllib.parse.quote(secret.strip(), safe="")
                if encoded and encoded != secret.strip():
                    sanitized = sanitized.replace(encoded, "***REDACTED***")
    sanitized = _BOT_TOKEN_PATTERN.sub("bot***REDACTED***", sanitized)
    sanitized = _RAW_BOT_TOKEN_PATTERN.sub("***REDACTED***", sanitized)
    return sanitized


class TelegramNotifier:
    """Persistent, retry-bounded Telegram Bot API notification dispatcher."""

    API_BASE = "https://api.telegram.org"

    def __init__(
        self,
        state_file: Optional[Path] = None,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        max_retries: int = 3,
        timeout_sec: float = 15.0,
        sleep_fn: Callable[[float], None] = time.sleep,
        http_post: Callable[..., Any] = requests.post,
    ) -> None:
        if state_file is not None:
            resolved_state = Path(state_file)
        elif "PYTEST_CURRENT_TEST" in os.environ:
            resolved_state = Path(tempfile.gettempdir()) / f"curiosity_test_notifications_{os.getpid()}.json"
        else:
            resolved_state = NOTIFICATIONS_STATE_FILE
        self.state_file = resolved_state
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._explicit_bot_token = bot_token
        self._explicit_chat_id = chat_id
        self.max_retries = max(1, int(max_retries))
        self.timeout_sec = float(timeout_sec)
        self.sleep_fn = sleep_fn
        self.http_post = http_post

    # ------------------------------------------------------------------
    # Credential Resolution (never logs or stores values)
    # ------------------------------------------------------------------
    def _resolve_credentials(self) -> Tuple[str, str]:
        config.sync_env_if_updated()
        token = (
            self._explicit_bot_token
            if self._explicit_bot_token is not None
            else os.environ.get("TELEGRAM_BOT_TOKEN", config.TELEGRAM_BOT_TOKEN)
        )
        chat_id = (
            self._explicit_chat_id
            if self._explicit_chat_id is not None
            else os.environ.get("TELEGRAM_CHAT_ID", config.TELEGRAM_CHAT_ID)
        )
        return (token or "").strip(), (chat_id or "").strip()

    def is_configured(self) -> bool:
        token, chat_id = self._resolve_credentials()
        return bool(token and chat_id)

    # ------------------------------------------------------------------
    # Atomic Local State Management
    # ------------------------------------------------------------------
    @staticmethod
    def _default_state() -> Dict[str, Any]:
        return {
            "sent_keys": {},
            "pending_events": [],
            "events": [],
            "last_success_at": None,
            "last_failure_at": None,
            "last_error": None,
            "last_daily_summary_date": None,
        }

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return self._default_state()
        try:
            with open(self.state_file, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if not isinstance(loaded, dict):
                return self._default_state()
            base = self._default_state()
            base.update(loaded)
            if not isinstance(base.get("sent_keys"), dict):
                base["sent_keys"] = {}
            if not isinstance(base.get("pending_events"), list):
                base["pending_events"] = []
            if not isinstance(base.get("events"), list):
                base["events"] = []
            return base
        except Exception as exc:
            logger.warning("Failed reading notifications_state.json: %s", exc)
            return self._default_state()

    def _save_state(self, state: Dict[str, Any]) -> None:
        # Keep history bounded cleanly while retaining dedup protection
        if len(state["events"]) > 200:
            state["events"] = state["events"][-200:]
        if len(state["pending_events"]) > 100:
            state["pending_events"] = state["pending_events"][-100:]
        sent_keys = state.get("sent_keys", {})
        if len(sent_keys) > 500:
            sorted_keys = sorted(sent_keys.items(), key=lambda kv: str(kv[1]))
            state["sent_keys"] = dict(sorted_keys[-500:])

        tmp_file = self.state_file.with_name(f"{self.state_file.name}.tmp")
        with open(tmp_file, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp_file, self.state_file)

    @staticmethod
    def _now_ist_iso() -> str:
        return datetime.now(IST).isoformat()

    def _record_event_history(
        self,
        state: Dict[str, Any],
        category: str,
        event_key: str,
        summary: str,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        entry = {
            "timestamp_ist": self._now_ist_iso(),
            "category": category,
            "event_key": event_key,
            "summary": summary[:240],
            "status": status,
        }
        if error:
            entry["error"] = error[:240]
        state["events"].append(entry)

    # ------------------------------------------------------------------
    # Low-Level Bot API Transport with Bounded Retries & Secret Isolation
    # ------------------------------------------------------------------
    def _deliver_message(self, message_html: str) -> Tuple[bool, Optional[str]]:
        token, chat_id = self._resolve_credentials()
        if not token or not chat_id:
            return False, "Telegram credentials not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing)"

        url = f"{self.API_BASE}/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message_html,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        last_error = "Unknown Telegram delivery error"
        secrets = [token, chat_id]

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.http_post(url, json=payload, timeout=self.timeout_sec)
                status_code = getattr(resp, "status_code", 0)
                if 200 <= status_code < 300:
                    try:
                        body = resp.json()
                    except Exception:
                        body = {"ok": True}
                    if body.get("ok", True):
                        return True, None
                    last_error = redact_telegram_secrets(
                        f"Telegram API ok=false: {body.get('description', 'unknown error')}",
                        secrets,
                    )
                else:
                    body_text = ""
                    try:
                        body_json = resp.json()
                        body_text = str(body_json.get("description") or body_json)
                    except Exception:
                        body_text = str(getattr(resp, "text", ""))[:200]
                    last_error = redact_telegram_secrets(
                        f"HTTP {status_code}: {body_text}",
                        secrets,
                    )
                    # Do not retry permanent client errors (except 429 rate-limit)
                    if 400 <= status_code < 500 and status_code != 429:
                        return False, last_error
            except Exception as exc:
                last_error = redact_telegram_secrets(f"{type(exc).__name__}: {exc}", secrets)

            if attempt < self.max_retries:
                backoff = min(4.0, float(2 ** (attempt - 1)))
                try:
                    self.sleep_fn(backoff)
                except Exception:
                    pass

        return False, last_error

    # ------------------------------------------------------------------
    # Unified Safe Dispatch + Persistence + Recovery Queue
    # ------------------------------------------------------------------
    def send_event(
        self,
        category: str,
        event_key: str,
        summary: str,
        message_html: str,
        queue_on_failure: bool = True,
    ) -> Dict[str, Any]:
        """Deliver a deduplicated notification safely; queue locally on failure."""
        try:
            state = self._load_state()
            if event_key in state["sent_keys"]:
                return {
                    "sent": False,
                    "status": "DEDUPED",
                    "event_key": event_key,
                }

            if not self.is_configured():
                msg = "Telegram bot token or chat ID not configured in .env"
                state["last_error"] = msg
                self._record_event_history(state, category, event_key, summary, "SKIPPED_UNCONFIGURED", msg)
                self._save_state(state)
                logger.info("Telegram skipped (%s): credentials missing.", category)
                return {
                    "sent": False,
                    "status": "SKIPPED_UNCONFIGURED",
                    "event_key": event_key,
                    "error": msg,
                }

            ok, err = self._deliver_message(message_html)
            now_ist = self._now_ist_iso()

            if ok:
                state["sent_keys"][event_key] = now_ist
                state["last_success_at"] = now_ist
                state["last_error"] = None
                state["pending_events"] = [
                    p for p in state["pending_events"] if p.get("event_key") != event_key
                ]
                self._record_event_history(state, category, event_key, summary, "SENT")
                self._save_state(state)
                return {
                    "sent": True,
                    "status": "SENT",
                    "event_key": event_key,
                }

            safe_err = redact_telegram_secrets(err or "Unknown failure")
            state["last_failure_at"] = now_ist
            state["last_error"] = safe_err
            if queue_on_failure:
                already_queued = any(p.get("event_key") == event_key for p in state["pending_events"])
                if not already_queued:
                    state["pending_events"].append(
                        {
                            "category": category,
                            "event_key": event_key,
                            "summary": summary[:240],
                            "message_html": message_html,
                            "queued_at_ist": now_ist,
                            "attempts": 1,
                        }
                    )
            self._record_event_history(
                state,
                category,
                event_key,
                summary,
                "PENDING" if queue_on_failure else "FAILED",
                safe_err,
            )
            self._save_state(state)
            logger.warning("Telegram delivery failed (%s, key=%s): %s", category, event_key, safe_err)
            return {
                "sent": False,
                "status": "PENDING" if queue_on_failure else "FAILED",
                "event_key": event_key,
                "error": safe_err,
            }
        except Exception as exc:
            safe_exc = redact_telegram_secrets(str(exc))
            logger.warning("Unexpected TelegramNotifier isolation catch: %s", safe_exc)
            return {
                "sent": False,
                "status": "ERROR",
                "event_key": event_key,
                "error": safe_exc,
            }

    def flush_pending_events(self, max_batch: int = 10) -> Dict[str, Any]:
        """Attempt recovery delivery of locally queued notifications after outage/restart."""
        try:
            state = self._load_state()
            pending = list(state.get("pending_events", []))
            if not pending or not self.is_configured():
                return {"flushed": 0, "remaining": len(pending)}

            remaining: List[Dict[str, Any]] = []
            flushed = 0

            for idx, item in enumerate(pending):
                if idx >= max_batch:
                    remaining.extend(pending[idx:])
                    break

                ev_key = str(item.get("event_key") or "")
                if ev_key in state["sent_keys"]:
                    continue

                ok, err = self._deliver_message(str(item.get("message_html") or ""))
                now_ist = self._now_ist_iso()
                if ok:
                    flushed += 1
                    state["sent_keys"][ev_key] = now_ist
                    state["last_success_at"] = now_ist
                    state["last_error"] = None
                    self._record_event_history(
                        state,
                        str(item.get("category") or "RECOVERY"),
                        ev_key,
                        str(item.get("summary") or "Recovered pending alert"),
                        "SENT",
                    )
                else:
                    item["attempts"] = int(item.get("attempts", 0)) + 1
                    safe_err = redact_telegram_secrets(err or "Retry failed")
                    item["last_error"] = safe_err
                    state["last_failure_at"] = now_ist
                    state["last_error"] = safe_err
                    remaining.append(item)
                    # Stop batch early on network outage rather than failing every queued item
                    if idx + 1 < len(pending):
                        remaining.extend(pending[idx + 1 :])
                    break

            state["pending_events"] = remaining
            self._save_state(state)
            return {"flushed": flushed, "remaining": len(remaining)}
        except Exception as exc:
            return {"flushed": 0, "remaining": 0, "error": redact_telegram_secrets(str(exc))}

    # ------------------------------------------------------------------
    # Domain Notification Methods
    # ------------------------------------------------------------------
    def notify_publication_success(
        self,
        video_id: str,
        title: str,
        youtube_id: str,
        published_at_ist: str,
        privacy_status: str,
        channel_id: str = "",
    ) -> Dict[str, Any]:
        """Notify ONLY when YouTube API has confirmed `privacy_status == 'public'`."""
        if str(privacy_status or "").strip().lower() != "public":
            return {
                "sent": False,
                "status": "SKIPPED_NOT_PUBLIC",
                "event_key": f"pub_public:{youtube_id}",
            }

        esc_title = html.escape(str(title or "CurioLoop Short"))
        esc_vid = html.escape(str(video_id or ""))
        esc_yt = html.escape(str(youtube_id or ""))
        esc_pub = html.escape(str(published_at_ist or self._now_ist_iso()))
        yt_url = f"https://www.youtube.com/shorts/{esc_yt}"
        channel_line = f"\n<b>Channel:</b> <code>{html.escape(channel_id)}</code>" if channel_id else ""

        msg = (
            f"<b>CurioLoop: Video Published Publicly</b>\n\n"
            f"<b>Title:</b> {esc_title}\n"
            f"<b>YouTube ID:</b> <code>{esc_yt}</code>\n"
            f"<b>Local Video ID:</b> <code>{esc_vid}</code>\n"
            f"<b>Published (IST):</b> {esc_pub}"
            f"{channel_line}\n"
            f"<b>Link:</b> {yt_url}"
        )
        return self.send_event(
            category="PUBLICATION_SUCCESS",
            event_key=f"pub_public:{youtube_id}",
            summary=f"Published publicly: {title} ({youtube_id})",
            message_html=msg,
        )

    def notify_oauth_expiry_warning(
        self,
        hours_remaining: float,
        estimated_reauth_ist: str,
        date_str: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Warn ~24 hours before the 7-day Testing-mode OAuth refresh token expires."""
        day_key = date_str or datetime.now(IST).strftime("%Y-%m-%d")
        hrs_rounded = max(0.0, round(float(hours_remaining), 1))
        esc_est = html.escape(str(estimated_reauth_ist or "Soon"))
        msg = (
            f"<b>CurioLoop Warning: YouTube OAuth Expires in ~{hrs_rounded:.1f}h</b>\n\n"
            f"Google OAuth consent is in Testing mode (7-day refresh token limit).\n"
            f"<b>Estimated Expiry (IST):</b> {esc_est}\n\n"
            f"<b>Action Required:</b>\n"
            f"• Open local Dashboard (<code>http://127.0.0.1:{config.DASHBOARD_PORT}</code>) and click <b>Reconnect YouTube Account</b>\n"
            f"• Or double-click <code>reauthorize_youtube.bat</code> in <code>D:\\yt</code>"
        )
        return self.send_event(
            category="OAUTH_EXPIRY_WARNING",
            event_key=f"oauth_expiry_24h:{day_key}",
            summary=f"OAuth expiring in ~{hrs_rounded:.1f}h (est. {estimated_reauth_ist})",
            message_html=msg,
        )

    def notify_oauth_rejected(
        self,
        error_reason: str,
        date_bucket: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Urgent alert when YouTube OAuth refresh is rejected/revoked."""
        bucket = date_bucket or datetime.now(IST).strftime("%Y-%m-%d_%H")
        safe_reason = redact_telegram_secrets(str(error_reason or "OAuth token rejected"))
        esc_reason = html.escape(safe_reason[:220])
        msg = (
            f"<b>URGENT — CurioLoop YouTube OAuth Rejected</b>\n\n"
            f"<b>Reason:</b> {esc_reason}\n"
            f"<b>Safety Status:</b> New uploads/scheduling paused automatically. Already-scheduled YouTube videos remain untouched.\n\n"
            f"<b>How to Restore:</b>\n"
            f"1. Open Dashboard (<code>http://127.0.0.1:{config.DASHBOARD_PORT}</code>) -> Click <b>Reconnect YouTube Account</b>\n"
            f"2. Or run <code>reauthorize_youtube.bat</code>\n"
            f"Automation will resume automatically after healthy verification."
        )
        return self.send_event(
            category="OAUTH_REJECTED",
            event_key=f"oauth_rejected:{bucket}",
            summary=f"OAuth rejected: {safe_reason[:120]}",
            message_html=msg,
        )

    def notify_reauth_success(
        self,
        scopes: List[str],
        estimated_reauth_ist: str,
        resumed_automation: bool,
    ) -> Dict[str, Any]:
        """Confirm healthy YouTube OAuth reconnection & scope verification."""
        now_key = datetime.now(IST).strftime("%Y-%m-%d_%H%M")
        esc_est = html.escape(str(estimated_reauth_ist or "Unknown"))
        resume_text = "Resumed automatically" if resumed_automation else "Enabled and ready"
        msg = (
            f"<b>CurioLoop: YouTube OAuth Reconnected</b>\n\n"
            f"<b>Upload &amp; Schedule Scopes:</b> Verified ({len(scopes)} scopes)\n"
            f"<b>Next Estimated Reauth (IST):</b> {esc_est}\n"
            f"<b>Automation:</b> {html.escape(resume_text)}"
        )
        return self.send_event(
            category="OAUTH_REAUTH_SUCCESS",
            event_key=f"oauth_reauth_ok:{now_key}",
            summary=f"OAuth reauthorized cleanly (next reauth: {estimated_reauth_ist})",
            message_html=msg,
        )

    def notify_failure(
        self,
        failure_type: str,
        title: str,
        detail: str,
        video_id: str = "",
        youtube_id: str = "",
        dedup_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Alert on upload, schedule, processing, rejection, auth, or missed publication failure."""
        hour_bucket = datetime.now(IST).strftime("%Y-%m-%d_%H")
        target_id = youtube_id or video_id or "general"
        key = dedup_key or f"failure:{failure_type}:{target_id}:{hour_bucket}"
        safe_detail = redact_telegram_secrets(str(detail or "No details"))
        esc_type = html.escape(str(failure_type))
        esc_title = html.escape(str(title or "Operational Issue"))
        esc_detail = html.escape(safe_detail[:300])
        vid_line = f"\n<b>Video ID:</b> <code>{html.escape(video_id)}</code>" if video_id else ""
        yt_line = f"\n<b>YouTube ID:</b> <code>{html.escape(youtube_id)}</code>" if youtube_id else ""

        msg = (
            f"<b>CurioLoop Alert [{esc_type}]</b>\n\n"
            f"<b>Event:</b> {esc_title}"
            f"{vid_line}"
            f"{yt_line}\n"
            f"<b>Details:</b> {esc_detail}\n"
            f"<b>Time (IST):</b> {html.escape(datetime.now(IST).strftime('%Y-%m-%d %H:%M IST'))}"
        )
        return self.send_event(
            category=failure_type,
            event_key=key,
            summary=f"[{failure_type}] {title}: {safe_detail[:120]}",
            message_html=msg,
        )

    def notify_daily_summary(
        self,
        date_str: str,
        production_count: int,
        daily_limit: int,
        published_public_count: int,
        scheduled_pending_count: int,
        next_scheduled_ist: str,
        oauth_status: str,
        oauth_reauth_ist: str,
        last_failure: str = "",
    ) -> Dict[str, Any]:
        """Send once-per-IST-day operational summary."""
        state = self._load_state()
        if state.get("last_daily_summary_date") == date_str or f"daily_summary:{date_str}" in state.get("sent_keys", {}):
            return {"sent": False, "status": "DEDUPED", "event_key": f"daily_summary:{date_str}"}

        fail_line = (
            f"\n<b>Last Failure:</b> {html.escape(redact_telegram_secrets(last_failure)[:140])}"
            if last_failure
            else "\n<b>Failures Today:</b> None"
        )
        msg = (
            f"<b>CurioLoop Daily Operational Summary ({html.escape(date_str)})</b>\n\n"
            f"<b>Produced Today:</b> {production_count} / {daily_limit}\n"
            f"<b>Confirmed Public:</b> {published_public_count}\n"
            f"<b>Scheduled Pending:</b> {scheduled_pending_count}\n"
            f"<b>Next Scheduled (IST):</b> {html.escape(next_scheduled_ist or 'None queued')}\n"
            f"<b>YouTube OAuth:</b> {html.escape(oauth_status)} (Reauth est: {html.escape(oauth_reauth_ist or 'Unknown')})"
            f"{fail_line}"
        )
        res = self.send_event(
            category="DAILY_SUMMARY",
            event_key=f"daily_summary:{date_str}",
            summary=f"Daily summary {date_str}: {production_count}/{daily_limit} produced, {published_public_count} public",
            message_html=msg,
        )
        if res.get("sent"):
            state = self._load_state()
            state["last_daily_summary_date"] = date_str
            self._save_state(state)
        return res

    # ------------------------------------------------------------------
    # Dashboard Inspection (Sanitized)
    # ------------------------------------------------------------------
    def get_health(self, history_limit: int = 20) -> Dict[str, Any]:
        """Return Telegram integration health & recent alert history without leaking secrets."""
        configured = self.is_configured()
        state = self._load_state()
        events = list(reversed(state.get("events", [])))[:history_limit]
        pending_count = len(state.get("pending_events", []))

        if not configured:
            status = "NOT_CONFIGURED"
        elif pending_count > 0 and state.get("last_error"):
            status = "DEGRADED"
        elif state.get("last_error") and not state.get("last_success_at"):
            status = "ERROR"
        else:
            status = "HEALTHY"

        return {
            "configured": configured,
            "status": status,
            "last_success_at": state.get("last_success_at"),
            "last_failure_at": state.get("last_failure_at"),
            "last_error": redact_telegram_secrets(str(state.get("last_error") or "")) or None,
            "last_daily_summary_date": state.get("last_daily_summary_date"),
            "pending_count": pending_count,
            "recent_events": events,
        }


_notifier_singleton: Optional[TelegramNotifier] = None


def get_telegram_notifier() -> TelegramNotifier:
    """Return shared TelegramNotifier instance using live DATA_DIR."""
    global _notifier_singleton
    if _notifier_singleton is None or _notifier_singleton.state_file.parent != config.DATA_DIR:
        _notifier_singleton = TelegramNotifier()
    return _notifier_singleton
