from __future__ import annotations

import logging

import httpx

from .config import settings
from .db import Alert, User

log = logging.getLogger("paxen.notify")


def deliver(user: User, alert: Alert) -> str:
    """Every alert lands in the in-app inbox; push is best-effort on top (web push, or Expo for a native app)."""
    conf = alert.confidence.capitalize()
    if user.web_push:
        from sqlalchemy.orm import object_session

        from .webpush import send

        res = send(object_session(user), user.web_push, alert.data.get("push_title") or alert.title,
                   f"{alert.body}\nForecast confidence: {conf}", {"alert_id": alert.id, "url": "/?tab=alerts"})
        if res == "gone":
            user.web_push = None  # the browser revoked it: stop trying
        alert.delivered = {"sent": "push", "gone": "push_gone"}.get(res, "push_failed")
        return alert.delivered
    token = user.push_token or ""
    if not token.startswith("ExponentPushToken"):
        alert.delivered = "inbox"
        return alert.delivered
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
