"""Web push notifications for the Paxen web app (PWA).

Standard Web Push with VAPID: works in Chrome, Edge and Firefox on desktop and Android, and in Safari on iPhone
(iOS 16.4+) once Paxen has been added to the Home Screen. The server's VAPID key pair is created on first use and
kept in the database, so nothing has to be configured except, ideally, a contact address for push services:

    PAXEN_VAPID_SUBJECT=mailto:you@example.com
"""
from __future__ import annotations

import base64
import json
import logging
import os

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import AppSecret

log = logging.getLogger("paxen.webpush")
DEFAULT_SUBJECT = "mailto:alerts@paxen.app"


def _keys(s: Session) -> tuple[str, str]:
    """(private PEM, public key as base64url), creating and storing them the first time."""
    row = s.get(AppSecret, "vapid_private_pem")
    if row is None:
        from py_vapid import Vapid02

        v = Vapid02()
        v.generate_keys()
        try:
            s.add(AppSecret(name="vapid_private_pem", value=v.private_pem().decode()))
            s.commit()
        except IntegrityError:  # another process created them first: use theirs
            s.rollback()
        row = s.get(AppSecret, "vapid_private_pem")
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid02

    v = Vapid02.from_pem(row.value.encode())
    pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return row.value, base64.urlsafe_b64encode(pub).rstrip(b"=").decode()


def public_key(s: Session) -> str:
    return _keys(s)[1]


def valid_subscription(sub: dict) -> bool:
    keys = sub.get("keys") or {}
    return isinstance(sub.get("endpoint"), str) and sub["endpoint"].startswith("https://") \
        and bool(keys.get("p256dh")) and bool(keys.get("auth"))


def send(s: Session, subscription: dict, title: str, body: str, data: dict | None = None) -> str:
    """'sent', 'gone' (the browser revoked the subscription: forget it) or 'failed'."""
    from py_vapid import Vapid02
    from pywebpush import WebPushException, webpush

    pem, _ = _keys(s)
    payload = json.dumps({"title": title, "body": body, "data": data or {}})
    try:
        webpush(subscription, payload, vapid_private_key=Vapid02.from_pem(pem.encode()),
                vapid_claims={"sub": os.getenv("PAXEN_VAPID_SUBJECT", DEFAULT_SUBJECT)}, ttl=1800, timeout=10)
        return "sent"
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):
            return "gone"
        log.warning("web push failed (%s)", status or type(e).__name__)
        return "failed"
    except Exception as e:  # never let a push failure break monitoring
        log.warning("web push failed: %s", type(e).__name__)
        return "failed"
