"""In-process counters for basic observability (Slice C)."""

from __future__ import annotations

import threading
from collections import Counter

_lock = threading.Lock()
_counters: Counter = Counter()


def incr(name: str, amount: int = 1) -> None:
    with _lock:
        _counters[name] += amount


def snapshot() -> dict[str, int]:
    with _lock:
        return dict(_counters)


def reset_for_tests() -> None:
    with _lock:
        _counters.clear()
