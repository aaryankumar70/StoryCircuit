"""Zero-cost LLM client supporting local Ollama and optional Gemini free tier."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

import requests

from reelforge import config

logger = logging.getLogger("reelforge.brain.llm")


def extract_json_object(raw_text: str) -> Optional[Dict[str, Any]]:
    """Extract and parse the first JSON object from model text."""
    if not raw_text:
        return None
    text = raw_text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start:end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


class ZeroCostLLM:
    """Routes structured JSON prompts to Gemini free tier (if configured) or local Ollama."""

    def is_ollama_available(self) -> bool:
        try:
            resp = requests.get(f"{config.OLLAMA_HOST}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.65,
    ) -> Optional[Dict[str, Any]]:
        if config.GEMINI_API_KEY:
            res = self._call_gemini(system_prompt, user_prompt, temperature)
            if res is not None:
                return res

        if self.is_ollama_available():
            res = self._call_ollama(system_prompt, user_prompt, temperature)
            if res is not None:
                return res

        return None

    def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
    ) -> Optional[Dict[str, Any]]:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{config.GEMINI_MODEL}:generateContent"
        )
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
            },
        }
        try:
            resp = requests.post(
                url,
                headers={"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"},
                json=payload,
                timeout=45,
            )
            if resp.status_code != 200:
                logger.warning("Gemini API returned %s: %s", resp.status_code, resp.text[:240])
                return None
            data = resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            raw = "".join(str(p.get("text", "")) for p in parts)
            return extract_json_object(raw)
        except Exception as exc:
            logger.warning("Gemini call failed, falling back to local Ollama: %s", exc)
            return None

    def _call_ollama(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
    ) -> Optional[Dict[str, Any]]:
        payload = {
            "model": config.OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": 4096,
            },
        }
        try:
            resp = requests.post(
                f"{config.OLLAMA_HOST}/api/chat",
                json=payload,
                timeout=config.OLLAMA_TIMEOUT_SEC,
            )
            if resp.status_code != 200:
                logger.warning("Ollama returned %s: %s", resp.status_code, resp.text[:200])
                return None
            content = resp.json().get("message", {}).get("content", "")
            return extract_json_object(content)
        except Exception as exc:
            logger.warning("Ollama call failed: %s", exc)
            return None
