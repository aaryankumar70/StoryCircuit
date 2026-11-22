"""Local AI Model Adapter for CurioLoop 2.0.
Strictly local-first, zero-cost LLM orchestration via Ollama.
Enforces sequential memory lifecycle: immediately evicts model weights after generation (keep_alive: "0s").
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar, Union
import requests
from pydantic import BaseModel, ValidationError
from curiosity_engine.generation.resource_lock import sequential_resource_stage

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("LOCAL_LLM_MODEL", "autonomous-skill")


class LocalModelError(RuntimeError):
    """Raised when local model invocation fails or cannot recover."""
    pass


class LocalModelAdapter:
    """Zero-cost local LLM adapter interfacing with Ollama REST API.
    Designed for AMD Ryzen 5 PRO 4650U with strict memory discipline.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_URL,
        model_name: str = DEFAULT_MODEL,
        timeout: int = 120,
        context_size: Optional[int] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        try:
            configured_timeout = int(os.environ.get("LOCAL_LLM_TIMEOUT_SEC", str(timeout)))
        except (TypeError, ValueError):
            configured_timeout = timeout
        self.timeout = max(15, min(configured_timeout, 600))
        try:
            configured_context = int(
                os.environ.get("LOCAL_LLM_CONTEXT_SIZE", "8192") if context_size is None else context_size
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("LOCAL_LLM_CONTEXT_SIZE must be an integer from 4096 to 32768.") from exc
        if not 4096 <= configured_context <= 32768:
            raise ValueError("LOCAL_LLM_CONTEXT_SIZE must be between 4096 and 32768 tokens.")
        self.context_size = configured_context
        # Construction/import must stay side-effect free. Readiness is checked only
        # when a caller explicitly asks or starts an inference request.

    def _find_ollama_executable(self) -> Optional[Path]:
        """Locates ollama.exe in system PATH or standard Windows AppData directory."""
        which_path = shutil.which("ollama")
        if which_path:
            return Path(which_path)
        
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidate = Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"
            if candidate.exists():
                return candidate
        
        return None

    def _ensure_ollama_ready(self) -> bool:
        """Verifies Ollama is running and responding to ping."""
        try:
            resp = requests.get(f"{self.base_url}/api/version", timeout=3)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass

        if os.environ.get("OLLAMA_AUTOSTART", "0").strip() != "1":
            return False

        # Background launch is available only after an explicit local CLI opt-in.
        ollama_bin = self._find_ollama_executable()
        if ollama_bin and ollama_bin.exists():
            logger.info("Ollama service not detected; launching background daemon: %s", ollama_bin)
            try:
                subprocess.Popen(
                    [str(ollama_bin), "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                # Wait up to 10 seconds for service to bind
                for _ in range(20):
                    time.sleep(0.5)
                    try:
                        r = requests.get(f"{self.base_url}/api/version", timeout=1)
                        if r.status_code == 200:
                            logger.info("Ollama service successfully started.")
                            return True
                    except requests.RequestException:
                        continue
            except Exception as e:
                logger.warning("Failed to auto-launch Ollama service: %s", e)

        return False

    def is_available(self) -> bool:
        """Checks if Ollama is accessible and has the requested model available.
        Disabled by default to operate in autonomous zero-dependency mode.
        """
        if not os.environ.get("CURIOLOOP_ENABLE_OLLAMA"):
            return False
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            wanted = self.model_name.casefold()
            normalized = {str(m).strip().casefold() for m in models}
            return wanted in normalized or (wanted.endswith(":latest") and wanted[:-7] in normalized) or f"{wanted}:latest" in normalized
        except Exception:
            return False

    def is_configured(self) -> bool:
        """Alias for is_available for drop-in compatibility with Gemini client."""
        return self.is_available()

    def list_installed_models(self) -> List[str]:
        """Returns all locally available model tags."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return [m.get("name", "") for m in data.get("models", [])]
        except Exception as e:
            logger.warning("Failed to list Ollama models: %s", e)
        return []

    def unload_model(self) -> bool:
        """Explicitly unloads model from RAM to guarantee zero memory contention
        with Kokoro ONNX, Whisper, and Playwright video rendering.
        """
        try:
            payload = {
                "model": self.model_name,
                "keep_alive": "0s",
            }
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.warning("Failed to explicitly unload model %s: %s", self.model_name, e)
            return False

    @sequential_resource_stage
    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        system_instruction: Optional[str] = None,
        format_json: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stop: Optional[List[str]] = None,
    ) -> str:
        """Executes single-turn inference with immediate RAM deallocation.
        
        Args:
            prompt: User/task prompt.
            system: Optional system instruction prompt.
            system_instruction: Alias for system instruction (drop-in Gemini client compatibility).
            format_json: If True, instructs Ollama to enforce valid JSON output.
            temperature: Sampling temperature.
            max_tokens: Max generated token limit.
            stop: Optional stop tokens.
            
        Returns:
            The raw string output generated by the model.
        """
        self._ensure_ollama_ready()
        endpoint = f"{self.base_url}/api/generate"
        eff_system = system or system_instruction
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "0s",  # Crucial: Unload immediately to keep system RAM <= 5.5GB
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": self.context_size,
            },
        }
        if eff_system:
            payload["system"] = eff_system
        if format_json:
            payload["format"] = "json"
        if stop:
            payload["options"]["stop"] = stop

        try:
            response = requests.post(endpoint, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            raw_response = data.get("response", "").strip()
            return raw_response
        except requests.RequestException as e:
            raise LocalModelError(
                f"Ollama inference error against {endpoint} with model {self.model_name}: {e}"
            ) from e

    def generate_json(
        self,
        prompt: str,
        system: Optional[str] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        """Generates text and parses it into a Python dictionary.
        Robustly extracts JSON from markdown blocks or cleans trailing characters.
        """
        raw_text = self.generate(
            prompt=prompt,
            system=system,
            system_instruction=system_instruction,
            format_json=True,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self._extract_json(raw_text)

    def generate_structured(
        self,
        prompt: str,
        schema: Type[T],
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_retries: int = 2,
        max_tokens: int = 4096,
    ) -> T:
        """Generates output validated against a Pydantic v2 schema.
        Includes self-correcting retry loop if schema validation fails.
        """
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        system_with_schema = (
            (system or "")
            + "\n\nYou must reply ONLY with a valid JSON object matching this schema:\n"
            + schema_json
        )

        max_retries = max(0, min(int(max_retries), 3))
        max_tokens = max(256, min(int(max_tokens), 8192))
        last_error = ""
        current_prompt = prompt

        for attempt in range(max_retries + 1):
            if attempt > 0:
                current_prompt = (
                    f"{prompt}\n\n[CRITICAL CORRECTION] Your previous JSON response failed schema validation:\n"
                    f"{last_error}\n\nPlease output ONLY valid JSON adhering strictly to the required schema."
                )

            try:
                raw_dict = self.generate_json(
                    prompt=current_prompt,
                    system=system_with_schema,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except LocalModelError as err:
                last_error = str(err)
                logger.warning("Structured output parse attempt %d failed: %s", attempt + 1, last_error)
                continue

            try:
                validated = schema.model_validate(raw_dict)
                return validated
            except ValidationError as err:
                last_error = str(err)
                logger.warning(
                    "Structured output validation attempt %d failed: %s",
                    attempt + 1,
                    last_error,
                )

        raise LocalModelError(
            f"Failed to generate output conforming to schema {schema.__name__} after {max_retries + 1} attempts. Last error: {last_error}"
        )

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Extracts JSON object from text, handling markdown fences and extraneous text."""
        cleaned = text.strip()
        # Remove markdown code blocks if present
        if "```" in cleaned:
            matches = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
            if matches:
                cleaned = matches[0].strip()

        # Find first '{' and last '}'
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            cleaned = cleaned[first_brace : last_brace + 1]

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            # Fallback regex for common JSON repair
            logger.error("JSON parse failure on: %s", text[:200])
            raise LocalModelError(f"Failed to parse JSON from local model response: {e}") from e


# Singleton instance for general use across pipeline
local_model = LocalModelAdapter()
