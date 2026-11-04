"""Keep credentials out of logs, the database and API responses.

TfL keys travel as a query parameter (?app_key=...), and httpx puts the full URL in its error messages, so any
upstream error would otherwise leak the key wherever the message ends up.
"""
from __future__ import annotations

import re

import httpx

_SECRET_PARAM = re.compile(r"((?:app_key|app_id|api_key|apikey|key|token|subscription-key)=)[^&\s'\"<>]+", re.I)


def redact(text: object) -> str:
    return _SECRET_PARAM.sub(r"\1***", str(text))


class UpstreamError(httpx.HTTPError):
    """An upstream HTTP failure, described without the request URL (which may carry credentials)."""

    def __init__(self, what: str, status: int | None = None):
        super().__init__(f"{what}: HTTP {status}" if status is not None else what)
        self.status = status


def check(r: httpx.Response, what: str) -> httpx.Response:
    """Like r.raise_for_status(), but the error never contains the URL or query string."""
    if r.is_error:
        raise UpstreamError(what, r.status_code)
    return r
