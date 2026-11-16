"""Where a request's time goes, reported in a Server-Timing response header (visible in any HTTP client), so slow
responses in production can be explained without access to the server."""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar

_phases: ContextVar[dict | None] = ContextVar("paxen_phases", default=None)


def start() -> dict:
    d: dict[str, float] = {}
    _phases.set(d)
    return d


@contextmanager
def phase(name: str):
    d = _phases.get()
    if d is None:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        d[name] = d.get(name, 0.0) + (time.perf_counter() - t0) * 1000


def header(d: dict) -> str:
    return ", ".join(f"{k};dur={v:.0f}" for k, v in d.items())
