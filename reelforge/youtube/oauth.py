"""In-app YouTube OAuth 2.0 flow and client_secret.json management."""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional

from google_auth_oauthlib.flow import InstalledAppFlow

from reelforge import config
from reelforge.youtube.uploader import YouTubeUploader, clear_health_cache

logger = logging.getLogger("reelforge.youtube.oauth")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

_SUCCESS_HTML = b"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>StoryCircuit YouTube OAuth</title>
<style>
  body { background:#090B0E; color:#F1F5F9; font-family:system-ui,sans-serif; display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }
  .box { background:#11141A; border:1px solid rgba(180,240,59,.4); border-radius:12px; padding:28px 32px; max-width:460px; text-align:center; }
  h2 { color:#B4F03B; margin:0 0 10px; }
  p { color:#94A3B8; line-height:1.5; margin:0; }
</style></head>
<body><div class="box">
  <h2>YouTube Connected</h2>
  <p>StoryCircuit received your OAuth refresh token. You can close this tab and return to the dashboard.</p>
</div></body></html>"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class YouTubeOAuthManager:
    """Manages client_secret.json uploads and localhost browser OAuth authorization."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = {
            "status": "idle",
            "message": "",
            "auth_url": "",
            "channel_title": "",
            "started_at": None,
            "finished_at": None,
            "error": "",
        }

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def _set_state(self, **updates: Any) -> None:
        with self._lock:
            self._state.update(updates)

    def save_client_secret_bytes(self, raw_bytes: bytes) -> Dict[str, Any]:
        if not raw_bytes or len(raw_bytes) > 256 * 1024:
            raise ValueError("Client JSON file is empty or exceeds 256 KB.")
        try:
            payload = json.loads(raw_bytes.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"Invalid JSON file: {exc}") from exc

        parsed = config.parse_client_secret_payload(payload)
        target = config.CLIENT_SECRET_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(parsed["raw"], indent=2), encoding="utf-8")
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass

        config.save_env_values(
            {
                "YOUTUBE_CLIENT_ID": parsed["client_id"],
                "YOUTUBE_CLIENT_SECRET": parsed["client_secret"],
            }
        )
        clear_health_cache()
        self._set_state(
            status="idle",
            message=f"Uploaded {parsed['client_type']} OAuth client JSON.",
            error="",
        )
        return {
            "saved": True,
            "client_type": parsed["client_type"],
            "path": str(target),
            "youtube": YouTubeUploader().get_connection_status(verify_network=False),
        }

    def start_oauth_flow(self) -> Dict[str, Any]:
        with self._lock:
            if self._state.get("status") == "running":
                return dict(self._state)

        info = config.load_client_secret_info()
        if info:
            client_config = info["raw"]
            client_id = info["client_id"]
            client_secret = info["client_secret"]
        else:
            config.reload_env()
            client_id = os.environ.get("YOUTUBE_CLIENT_ID", config.YOUTUBE_CLIENT_ID).strip()
            client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", config.YOUTUBE_CLIENT_SECRET).strip()
            if not client_id or not client_secret:
                raise ValueError("Upload a Google OAuth client_secret.json first.")
            client_config = {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }

        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        result_box: Dict[str, Optional[str]] = {"code": None, "error": None}

        class _CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if "error" in qs:
                    result_box["error"] = qs["error"][0]
                    self.send_response(400)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(f"OAuth failed: {result_box['error']}".encode("utf-8"))
                    return
                if "code" in qs:
                    result_box["code"] = qs["code"][0]
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(_SUCCESS_HTML)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

        server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
        server.timeout = 1.0
        port = server.server_address[1]
        flow.redirect_uri = f"http://localhost:{port}/"
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )

        self._set_state(
            status="running",
            message="Complete Google consent in the browser window (or click Open Google Consent).",
            auth_url=auth_url,
            channel_title="",
            started_at=_utc_now(),
            finished_at=None,
            error="",
        )

        def _worker() -> None:
            try:
                try:
                    webbrowser.open(auth_url)
                except Exception:
                    pass

                deadline = datetime.now(timezone.utc).timestamp() + 300.0
                while datetime.now(timezone.utc).timestamp() < deadline:
                    server.handle_request()
                    if result_box["code"] or result_box["error"]:
                        break

                if result_box["error"]:
                    raise RuntimeError(f"Google OAuth returned error: {result_box['error']}")
                if not result_box["code"]:
                    raise TimeoutError("Timed out after 5 minutes waiting for Google OAuth consent.")

                flow.fetch_token(code=result_box["code"])
                creds = flow.credentials
                if not creds or not creds.refresh_token:
                    raise RuntimeError(
                        "No refresh token returned. Revoke prior app access in Google Account and reconnect."
                    )

                config.save_env_values(
                    {
                        "YOUTUBE_CLIENT_ID": client_id,
                        "YOUTUBE_CLIENT_SECRET": client_secret,
                        "YOUTUBE_REFRESH_TOKEN": creds.refresh_token,
                    }
                )
                clear_health_cache()
                health = YouTubeUploader().get_connection_status(verify_network=True)
                ch_title = health.get("channel_title") or ""
                self._set_state(
                    status="succeeded",
                    message=f"Connected to YouTube{f' ({ch_title})' if ch_title else ''}.",
                    auth_url="",
                    channel_title=ch_title,
                    finished_at=_utc_now(),
                    error="",
                )
            except Exception as exc:
                logger.warning("OAuth authorization failed: %s", exc)
                self._set_state(
                    status="failed",
                    message=str(exc),
                    auth_url="",
                    finished_at=_utc_now(),
                    error=str(exc),
                )
            finally:
                try:
                    server.server_close()
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()
        return self.get_status()

    def disconnect(self) -> Dict[str, Any]:
        config.save_env_values({"YOUTUBE_REFRESH_TOKEN": ""})
        clear_health_cache()
        self._set_state(
            status="idle",
            message="Disconnected YouTube OAuth refresh token.",
            auth_url="",
            channel_title="",
            error="",
        )
        return YouTubeUploader().get_connection_status(verify_network=False)
