"""Bounded in-memory caches. Keys that include a time bucket (journey plans, weather, crowding) would otherwise
grow forever in a long-running process."""
from __future__ import annotations

import time


def prune(cache: dict, max_age_s: float, max_entries: int) -> None:
    """Drop entries older than max_age_s; if still too big, drop the oldest. Values are (stored_at, value)."""
    if len(cache) <= max_entries:
        return
    now = time.monotonic()
    for k in [k for k, (t, _) in cache.items() if now - t > max_age_s]:
        cache.pop(k, None)
    if len(cache) > max_entries:
        for k, _ in sorted(cache.items(), key=lambda kv: kv[1][0])[: len(cache) - max_entries]:
            cache.pop(k, None)
