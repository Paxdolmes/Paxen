from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta

import httpx

from .config import settings
from .db import Alert, User

log = logging.getLogger("paxen.notify")


def open_url(alert: Alert) -> str:
    """Where tapping the notification goes: Today for the briefing (route and times), the Alerts tab otherwise."""
    return "/" if alert.kind == "briefing" else "/?tab=alerts"


def push_body(alert: Alert, conf: str) -> str:
    if alert.kind == "briefing":  # already says what to do; keep it short enough for a lock screen
        return alert.body
    return f"{alert.body}\nForecast confidence: {conf}"


def deliver(user: User, alert: Alert) -> str:
    """Every alert lands in the in-app inbox; push is best-effort on top (web push, or Expo for a native app)."""
    conf = alert.confidence.capitalize()
    if user.web_push:
        from sqlalchemy.orm import object_session

        from .webpush import send

        res = send(object_session(user), user.web_push, alert.data.get("push_title") or alert.title,
                   push_body(alert, conf), {"alert_id": alert.id, "url": open_url(alert)})
        if res == "gone":
            user.web_push = None  # the browser revoked it: stop trying
        alert.delivered = {"sent": "push", "gone": "push_gone"}.get(res, "push_failed")
        return alert.delivered
    token = user.push_token or ""
    if token.startswith("apns:"):  # the iPhone app
        from . import apns

        res = apns.send(token, alert.data.get("push_title") or alert.title, push_body(alert, conf),
                        {"alert_id": alert.id, "url": open_url(alert)})
        if res == "gone":
            user.push_token = None
        alert.delivered = {"sent": "push", "gone": "push_gone"}.get(res, "push_failed")
        if res != "sent" and apns.last_error:
            alert.data = {**(alert.data or {}), "push_error": apns.last_error}  # shown on /v1/health
        return alert.delivered
    if not token.startswith("ExponentPushToken"):
        alert.delivered = "inbox"
        return alert.delivered
    msg = {
        "to": token, "sound": "default", "priority": "high",
        "title": alert.data.get("push_title") or alert.title,
        "body": push_body(alert, conf),
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


def push_stats(s, now: datetime) -> dict:
    """For /v1/health: devices that can get pushes, how the last week's alerts were delivered and why pushes
    failed (counts only, nothing personal). `apns_configured` is this process's view (the API); a worker without
    the APNs settings shows up as errors "not_configured"."""
    from sqlalchemy import select

    from . import apns
    from .timeutil import naive_utc

    devices = Counter()
    for token, web in s.execute(select(User.push_token, User.web_push)).all():
        if (token or "").startswith("apns:"):
            devices["iphone"] += 1
        elif token:
            devices["expo"] += 1
        if web:
            devices["web"] += 1
    rows = s.execute(select(Alert.kind, Alert.delivered, Alert.data)
                     .where(Alert.created_at >= naive_utc(now - timedelta(days=7)))).all()
    return {"apns_configured": apns.configured(), "devices": dict(devices),
            "alerts_7d": dict(Counter(k for k, _, _ in rows)),
            "delivered_7d": dict(Counter(d or "unknown" for _, d, _ in rows)),
            "errors_7d": dict(Counter((data or {}).get("push_error") or "unknown"
                                      for _, d, data in rows if d in ("push_failed", "push_gone")))}
