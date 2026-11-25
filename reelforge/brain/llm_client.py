"""Zero-cost LLM client with automatic failsafe: Gemini Free Tier -> Local Ollama -> Offline."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

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
    """Routes structured JSON prompts to Gemini free tier (if configured), falling back to local Ollama."""

    @staticmethod
    def _gemini_key() -> str:
        config.reload_env()
        return (os.environ.get("GEMINI_API_KEY") or config.GEMINI_API_KEY or "").strip()

    @staticmethod
    def _gemini_model() -> str:
        return (os.environ.get("GEMINI_MODEL") or config.GEMINI_MODEL or "gemini-2.5-flash").strip()

    def _list_ollama_models(self) -> List[str]:
        try:
            resp = requests.get(f"{config.OLLAMA_HOST}/api/tags", timeout=3)
            if resp.status_code != 200:
                return []
            models = resp.json().get("models") or []
            return [str(m.get("name")) for m in models if m.get("name")]
        except Exception:
            return []

    def is_ollama_available(self) -> bool:
        return len(self._list_ollama_models()) > 0 or self._ping_ollama()

    @staticmethod
    def _ping_ollama() -> bool:
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
        api_key = self._gemini_key()
        if api_key:
            res = self._call_gemini(system_prompt, user_prompt, temperature, api_key=api_key)
            if res is not None:
                return res
            logger.warning("Gemini request failed or returned invalid JSON; falling back to local Ollama.")

        local_models = self._list_ollama_models()
        if local_models or self._ping_ollama():
            model_name = config.OLLAMA_MODEL
            if local_models and model_name not in local_models:
                model_name = local_models[0]
            res = self._call_ollama(system_prompt, user_prompt, temperature, model_name=model_name)
            if res is not None:
                return res

        return None

    def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        *,
        api_key: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        key = api_key if api_key is not None else self._gemini_key()
        if not key:
            return None
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._gemini_model()}:generateContent"
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
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
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
        *,
        model_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        payload = {
            "model": model_name or config.OLLAMA_MODEL,
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
