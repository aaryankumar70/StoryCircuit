"""Shared sequential lock for memory-heavy local AI and rendering stages."""
from __future__ import annotations

from functools import wraps
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, TypeVar

from curiosity_engine.config import DATA_DIR
from curiosity_engine.state.file_lock import interprocess_file_lock

F = TypeVar("F", bound=Callable[..., Any])
DEFAULT_RESOURCE_LOCK_WAIT_SEC = 1800.0
MAX_RESOURCE_LOCK_WAIT_SEC = 7200.0


def resource_lock_path() -> Path:
    override = os.environ.get("CURIOLOOP_RESOURCE_LOCK_PATH")
    if override:
        return Path(override)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return Path(tempfile.gettempdir()) / "curioloop-pytest" / ".generation_resources.lock"
    return DATA_DIR / ".generation_resources.lock"


def resource_lock_timeout_sec() -> float:
    raw = os.environ.get("CURIOLOOP_RESOURCE_LOCK_WAIT_SEC", str(DEFAULT_RESOURCE_LOCK_WAIT_SEC))
    try:
        timeout = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("CURIOLOOP_RESOURCE_LOCK_WAIT_SEC must be a number.") from exc
    if not math.isfinite(timeout) or not 0 <= timeout <= MAX_RESOURCE_LOCK_WAIT_SEC:
        raise ValueError(
            f"CURIOLOOP_RESOURCE_LOCK_WAIT_SEC must be between 0 and {MAX_RESOURCE_LOCK_WAIT_SEC:.0f} seconds."
        )
    return timeout


def sequential_resource_stage(fn: F) -> F:
    @wraps(fn)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        lock_path = resource_lock_path()
        timeout = resource_lock_timeout_sec()
        with interprocess_file_lock(lock_path, timeout_sec=timeout):
            return fn(*args, **kwargs)
    return wrapped  # type: ignore[return-value]
