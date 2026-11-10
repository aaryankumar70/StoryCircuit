"""Gemini API Free-Tier Client for Autonomous Topic Discovery & Scriptwriting."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

from curiosity_engine.config import GEMINI_API_KEY

logger = logging.getLogger("curiosity_engine.gemini")

DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiClient:
    """Wrapper for Gemini API free-tier with exponential backoff and rate-limit guard."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")
        self.sdk_client = None

        if self.api_key:
            try:
                from google import genai
                self.sdk_client = genai.Client(api_key=self.api_key)
                logger.info("Initialized Google GenAI SDK client.")
            except Exception as e:
                logger.warning(f"Google GenAI SDK init error ({e}), will use direct HTTP API.")
                self.sdk_client = None

    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 10)

    def generate_json(self, prompt: str, system_instruction: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Generate structured JSON response from Gemini."""
        if not self.is_configured():
            logger.info("Gemini API key not configured; skipping AI call.")
            return None

        # 1. Try SDK if available
        if self.sdk_client:
            for attempt in range(3):
                try:
                    config = {"response_mime_type": "application/json"}
                    if system_instruction:
                        config["system_instruction"] = system_instruction

                    response = self.sdk_client.models.generate_content(
                        model=DEFAULT_MODEL,
                        contents=prompt,
                        config=config,
                    )
                    text = response.text.strip()
                    # Clean possible markdown fence
                    if text.startswith("```json"):
                        text = text[7:]
                    if text.startswith("```"):
                        text = text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    return json.loads(text.strip())
                except Exception as e:
                    logger.warning(f"SDK attempt {attempt+1} failed ({e}); retrying...")
                    time.sleep(2 * (attempt + 1))

        # 2. Direct HTTP REST fallback
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{DEFAULT_MODEL}:generateContent?key={self.api_key}"
        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        for attempt in range(3):
            try:
                resp = requests.post(url, json=payload, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text_val = candidates[0]["content"]["parts"][0]["text"].strip()
                        if text_val.startswith("```json"):
                            text_val = text_val[7:]
                        if text_val.startswith("```"):
                            text_val = text_val[3:]
                        if text_val.endswith("```"):
                            text_val = text_val[:-3]
                        return json.loads(text_val.strip())
                elif resp.status_code == 429:
                    logger.warning("Gemini rate limit 429 reached. Backing off 5s...")
                    time.sleep(5)
                else:
                    logger.error(f"Gemini API error {resp.status_code}: {resp.text}")
                    break
            except Exception as e:
                logger.warning(f"HTTP call attempt {attempt+1} failed: {e}")
                time.sleep(2 * (attempt + 1))

        return None


gemini_client = GeminiClient()
