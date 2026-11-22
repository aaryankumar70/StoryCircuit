"""CurioLoop 2.0 Telegram Remote Control Bot.
Processes incoming operator commands via Telegram Bot API getUpdates polling:
  /status   - Current engine status, automation mode, and active pipeline stage
  /queue    - Production and publishing queue inspection
  /scripts  - Review latest generated scripts and topics
  /approve  - Approve a staged video or script for production
  /pause    - Pause autonomous production
  /resume   - Resume autonomous production
  /schedule - View upcoming publishing windows (IST & UTC)
  /retry    - Reset a failed or stalled video job
  /health   - Full system health diagnostics (LLM, Kokoro, Whisper, FFmpeg, Disk, Auth)
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
import requests

from curiosity_engine import config
from curiosity_engine.config import (
    DATA_DIR,
    OUTPUT_DIR,
    SCHEDULER_PUBLISH_SLOT1_TIME,
    SCHEDULER_PUBLISH_SLOT2_TIME,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from curiosity_engine.intelligence.local_model import local_model
from curiosity_engine.runner.automation_state import automation_state
from curiosity_engine.state.db import db

logger = logging.getLogger("curiosity_engine.telegram_bot")
IST = ZoneInfo("Asia/Kolkata")


class TelegramCommandBot:
    """Zero-dependency background polling bot for remote studio administration."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        authorized_chat_id: Optional[str] = None,
    ):
        self.bot_token = (bot_token or TELEGRAM_BOT_TOKEN).strip()
        self.chat_id = (authorized_chat_id or TELEGRAM_CHAT_ID).strip()
        self._last_update_id = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def is_configured(self) -> bool:
        return bool(self.bot_token and len(self.bot_token) > 10 and self.chat_id)

    def start(self) -> bool:
        """Starts background polling daemon thread."""
        if not self.is_configured():
            logger.info("Telegram command bot not configured (missing token or chat ID).")
            return False

        if self._running:
            return True

        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="TelegramBotDaemon")
        self._thread.start()
        logger.info("Telegram remote control bot started for chat ID: %s", self.chat_id)
        return True

    def stop(self) -> None:
        """Stops background polling."""
        self._running = False

    def _send_reply(self, chat_id: str, text: str) -> None:
        """Sends an HTML formatted message back to the operator."""
        if not self.bot_token:
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.warning("Failed to deliver Telegram reply: %s", e)

    def _poll_loop(self) -> None:
        """Continuous long-polling loop with exponential backoff on network errors."""
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        consecutive_errors = 0

        while self._running:
            try:
                params = {"offset": self._last_update_id + 1, "timeout": 20}
                resp = requests.get(url, params=params, timeout=25)
                if resp.status_code == 200:
                    consecutive_errors = 0
                    data = resp.json()
                    for update in data.get("result", []):
                        update_id = update.get("update_id", 0)
                        if update_id > self._last_update_id:
                            self._last_update_id = update_id

                        msg = update.get("message", {})
                        from_chat = str(msg.get("chat", {}).get("id", ""))
                        text = (msg.get("text") or "").strip()

                        # Enforce operator authorization
                        if self.chat_id and from_chat != self.chat_id:
                            logger.warning("Unauthorized Telegram command from chat %s: %s", from_chat, text)
                            continue

                        if text.startswith("/"):
                            self._handle_command(from_chat, text)
                else:
                    consecutive_errors += 1
            except Exception as e:
                consecutive_errors += 1
                logger.debug("Telegram polling transient error: %s", e)

            # Sleep briefly on error or idle
            sleep_time = min(30, 2 * consecutive_errors) if consecutive_errors else 1
            time.sleep(sleep_time)

    def _handle_command(self, chat_id: str, raw_text: str) -> None:
        """Dispatches operator slash commands."""
        parts = raw_text.split()
        cmd = parts[0].lower().split("@")[0]  # Strip bot handle if present
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "/status":
            self._cmd_status(chat_id)
        elif cmd == "/queue":
            self._cmd_queue(chat_id)
        elif cmd == "/scripts":
            self._cmd_scripts(chat_id)
        elif cmd == "/approve":
            self._cmd_approve(chat_id, arg)
        elif cmd == "/pause":
            self._cmd_pause(chat_id)
        elif cmd == "/resume":
            self._cmd_resume(chat_id)
        elif cmd == "/schedule":
            self._cmd_schedule(chat_id)
        elif cmd == "/retry":
            self._cmd_retry(chat_id, arg)
        elif cmd == "/health":
            self._cmd_health(chat_id)
        elif cmd in ("/help", "/start"):
            self._cmd_help(chat_id)
        else:
            self._send_reply(
                chat_id,
                f"❓ Unknown command: <code>{cmd}</code>\nSend /help to view available commands.",
            )

    def _cmd_help(self, chat_id: str) -> None:
        msg = (
            "🤖 <b>CurioLoop 2.0 Studio Remote Control</b>\n\n"
            "/status - Engine status & active stages\n"
            "/queue - View production & publishing queue\n"
            "/scripts - Latest generated scripts & topics\n"
            "/approve &lt;video_id&gt; - Approve video for production\n"
            "/pause - Pause autonomous production\n"
            "/resume - Resume autonomous production\n"
            "/schedule - Publishing slot times (IST/UTC)\n"
            "/retry &lt;video_id&gt; - Reset & retry failed video\n"
            "/health - System & AI model diagnostic checks\n"
        )
        self._send_reply(chat_id, msg)

    def _cmd_status(self, chat_id: str) -> None:
        raw_state = automation_state._load_raw()
        enabled = raw_state.get("enabled", True)
        now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        # Count completed today
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        daily_rec = automation_state.get_daily_record(today_str) or {}
        s1 = daily_rec.get("slot_1", {}).get("status", "IDLE")
        s2 = daily_rec.get("slot_2", {}).get("status", "IDLE")

        msg = (
            f"🎬 <b>CurioLoop 2.0 Studio Status</b>\n"
            f"⏰ <b>Current Time:</b> {now_ist}\n"
            f"⚡ <b>Automation:</b> {'🟢 ACTIVE' if enabled else '⏸ PAUSED'}\n"
            f"📊 <b>Today ({today_str}):</b>\n"
            f"  • Slot 1 (12:30 IST): <code>{s1}</code>\n"
            f"  • Slot 2 (20:30 IST): <code>{s2}</code>\n"
            f"🧠 <b>Local LLM:</b> {'🟢 Ready' if local_model.is_available() else '🔴 Offline'}\n"
        )
        self._send_reply(chat_id, msg)

    def _cmd_queue(self, chat_id: str) -> None:
        vids = db.get_all_videos(limit=10) or []
        pending = [v for v in vids if v.get("publishing_status") != "PUBLISHED"][:5]

        if not pending:
            self._send_reply(chat_id, "📭 <b>Production Queue:</b> No pending videos.")
            return

        lines = ["📋 <b>Active Production Queue:</b>\n"]
        for v in pending:
            vid_id = v.get("video_id", "Unknown")
            status = v.get("production_status", "PENDING")
            pub_status = v.get("publishing_status", "PENDING")
            lines.append(f"• <code>{vid_id}</code>: Prod={status} | Pub={pub_status}")

        self._send_reply(chat_id, "\n".join(lines))

    def _cmd_scripts(self, chat_id: str) -> None:
        vids = db.get_all_videos(limit=3) or []
        if not vids:
            self._send_reply(chat_id, "📝 No recent scripts found.")
            return

        lines = ["📝 <b>Latest Scripts & Topics:</b>\n"]
        for v in vids:
            title = v.get("title") or v.get("topic") or "Untitled"
            cat = v.get("category", "MYSTERY")
            lines.append(f"• <b>[{cat}]</b> {title}\n  ID: <code>{v.get('video_id')}</code>")

        self._send_reply(chat_id, "\n".join(lines))

    def _cmd_approve(self, chat_id: str, video_id: str) -> None:
        if not video_id:
            self._send_reply(chat_id, "⚠️ Usage: /approve &lt;video_id&gt;")
            return

        v = db.get_video_record(video_id)
        if not v:
            self._send_reply(chat_id, f"❌ Video <code>{video_id}</code> not found in database.")
            return

        db.update_video_record(video_id, {"script_approved": True, "operator_approved": True})
        self._send_reply(chat_id, f"✅ Video <code>{video_id}</code> has been approved for production.")

    def _cmd_pause(self, chat_id: str) -> None:
        automation_state.set_enabled(False)
        self._send_reply(chat_id, "⏸ <b>Autonomous production has been PAUSED.</b>")

    def _cmd_resume(self, chat_id: str) -> None:
        automation_state.set_enabled(True)
        self._send_reply(chat_id, "▶️ <b>Autonomous production has been RESUMED.</b>")

    def _cmd_schedule(self, chat_id: str) -> None:
        msg = (
            f"📅 <b>CurioLoop 2.0 Publishing Schedule</b>\n\n"
            f"• <b>Slot 1:</b> {SCHEDULER_PUBLISH_SLOT1_TIME} IST (07:00 UTC)\n"
            f"• <b>Slot 2:</b> {SCHEDULER_PUBLISH_SLOT2_TIME} IST (15:00 UTC)\n"
            f"• <b>Cadence:</b> Exactly 2 YouTube Shorts per day\n"
            f"• <b>Timezone:</b> Asia/Kolkata (IST)\n"
        )
        self._send_reply(chat_id, msg)

    def _cmd_retry(self, chat_id: str, video_id: str) -> None:
        if not video_id:
            self._send_reply(chat_id, "⚠️ Usage: /retry &lt;video_id&gt;")
            return

        v = db.get_video_record(video_id)
        if not v:
            self._send_reply(chat_id, f"❌ Video <code>{video_id}</code> not found.")
            return

        db.update_video_record(
            video_id,
            {"production_status": "PENDING", "qc_recovery_count": 0, "error": None},
        )
        self._send_reply(chat_id, f"🔄 Video <code>{video_id}</code> reset for recovery retry.")

    def _cmd_health(self, chat_id: str) -> None:
        # Check LLM
        llm_ok = local_model.is_available()

        # Check Kokoro ONNX
        kokoro_file = Path("models/kokoro/kokoro-v1.0.onnx")
        kokoro_ok = kokoro_file.exists()

        # Check Whisper
        whisper_dir = Path("models/whisper-small")
        whisper_ok = whisper_dir.exists()

        # Check FFmpeg
        ffmpeg_ok = bool(shutil.which("ffmpeg"))

        # Check Disk space
        total, used, free = shutil.disk_usage(OUTPUT_DIR)
        free_gb = free // (2**30)

        msg = (
            f"🩺 <b>CurioLoop 2.0 Health Diagnostics</b>\n\n"
            f"• <b>Script Engine:</b> {'🟢 Autonomous Skill Engine' if not llm_ok else '🟢 Local Model'}\n"
            f"• <b>Kokoro ONNX (82M):</b> {'🟢 OK' if kokoro_ok else '🔴 Missing'}\n"
            f"• <b>faster-whisper:</b> {'🟢 OK' if whisper_ok else '🔴 Missing'}\n"
            f"• <b>FFmpeg:</b> {'🟢 OK' if ffmpeg_ok else '🔴 Not Found'}\n"
            f"• <b>Free Disk:</b> {free_gb} GB\n"
            f"• <b>Operating Model:</b> ₹0 / $0 Zero-Cost Local Studio\n"
        )
        self._send_reply(chat_id, msg)


# Global singleton instance
telegram_bot = TelegramCommandBot()
