from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from .config import settings

_semaphore = threading.Semaphore(max(1, settings.max_concurrent_jobs))
_lock = threading.Lock()
_active = 0


def active_jobs() -> int:
    with _lock:
        return _active


@contextmanager
def acquire_job_slot(timeout: float = 0.05) -> Iterator[bool]:
    """Try to acquire a generation slot. Yields True if acquired."""
    global _active
    got = _semaphore.acquire(timeout=timeout)
    if not got:
        yield False
        return
    with _lock:
        _active += 1
    try:
        yield True
    finally:
        with _lock:
            _active = max(0, _active - 1)
        _semaphore.release()
