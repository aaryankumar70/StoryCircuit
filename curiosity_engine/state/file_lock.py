"""Cross-process advisory locks for local JSON state and shared resources."""
from __future__ import annotations

from contextlib import contextmanager
import errno
import math
import os
from pathlib import Path
import time
from typing import Iterator, Optional


def _is_lock_contention(exc: OSError) -> bool:
    retryable = {
        errno.EACCES,
        errno.EAGAIN,
        errno.EDEADLK,
        getattr(errno, "EWOULDBLOCK", errno.EAGAIN),
    }
    return isinstance(exc, PermissionError) or exc.errno in retryable or getattr(exc, "winerror", None) in {32, 33, 36}


@contextmanager
def interprocess_file_lock(
    lock_path: Path,
    timeout_sec: Optional[float] = 30.0,
    poll_interval_sec: float = 0.05,
) -> Iterator[None]:
    """Hold an OS-level exclusive lock with an explicit, cross-platform wait bound.

    Windows' ``msvcrt.LK_LOCK`` gives up after a short fixed retry period. Use
    non-blocking attempts instead so long renderer stages can remain serialized
    without failing after roughly ten seconds.
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if timeout_sec is not None and (not math.isfinite(float(timeout_sec)) or float(timeout_sec) < 0):
        raise ValueError("timeout_sec must be a finite non-negative number or None.")
    if not math.isfinite(float(poll_interval_sec)) or float(poll_interval_sec) <= 0:
        raise ValueError("poll_interval_sec must be a finite positive number.")

    handle = open(lock_path, "a+b")
    acquired = False
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = None if timeout_sec is None else time.monotonic() + float(timeout_sec)

        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as exc:
                if not _is_lock_contention(exc):
                    raise
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out after {float(timeout_sec):.1f}s acquiring file lock: {lock_path}"
                    ) from exc
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                time.sleep(float(poll_interval_sec) if remaining is None else min(float(poll_interval_sec), remaining))

        try:
            yield
        finally:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
