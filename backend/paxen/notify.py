from __future__ import annotations

import logging

import httpx

from .config import settings
from .db import Alert, User

log = logging.getLogger("paxen.notify")


def deliver(user: User, alert: Alert) -> str:
    """Every alert lands in the in-app inbox; push is best-effort on top (Expo push tokens supported)."""
    token = user.push_token or ""
    if not token.startswith("ExponentPushToken"):
        alert.delivered = "inbox"
        return alert.delivered
    conf = alert.confidence.capitalize()
    msg = {
        "to": token, "sound": "default", "priority": "high",
        "title": alert.data.get("push_title") or alert.title,
        "body": f"{alert.body}\nForecast confidence: {conf}",
        "data": {"alert_id": alert.id, "commute_id": alert.commute_id},
    }
    try:
        r = httpx.post(settings.expo_push_url, json=msg, timeout=10)
        r.raise_for_status()
        alert.delivered = "push"
    except Exception as e:  # never let a push failure break monitoring
        log.warning("push failed: %s", e)
        alert.delivered = "push_failed"
    return alert.delivered
