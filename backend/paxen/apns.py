"""Native push to the Paxen iPhone app through Apple Push Notification service (APNs).

The app (web/ios, Capacitor) registers with APNs and stores its device token as `push_token = "apns:<hex>"`.
Configure on the API and worker (from developer.apple.com > Keys, a key with "Apple Push Notifications service"):

    APNS_KEY_ID        the key's 10-character id
    APNS_TEAM_ID       your Apple Developer team id
    APNS_PRIVATE_KEY   the contents of the downloaded AuthKey_XXXXXXXXXX.p8 file
    APNS_TOPIC         the app's bundle id (default com.paxdolmes.paxen)
    APNS_HOST          api.push.apple.com (TestFlight and App Store builds; the default)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time

import httpx

log = logging.getLogger("paxen.apns")
PREFIX = "apns:"
last_error: str | None = None  # why the last push in this process failed, for the alert's record (notify.deliver)
_jwt: tuple[float, str] | None = None
_client: httpx.Client | None = None


def configured() -> bool:
    return all(os.getenv(k) for k in ("APNS_KEY_ID", "APNS_TEAM_ID", "APNS_PRIVATE_KEY"))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _token() -> str:
    """Provider token (ES256 JWT), reused for 50 minutes as Apple asks (it refuses one older than an hour)."""
    global _jwt
    if _jwt and time.time() - _jwt[0] < 50 * 60:
        return _jwt[1]
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    pem = os.environ["APNS_PRIVATE_KEY"].replace("\\n", "\n").encode()
    key = serialization.load_pem_private_key(pem, password=None)
    now = int(time.time())
    head = _b64(json.dumps({"alg": "ES256", "kid": os.environ["APNS_KEY_ID"]}).encode())
    body = _b64(json.dumps({"iss": os.environ["APNS_TEAM_ID"], "iat": now}).encode())
    r, s = decode_dss_signature(key.sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256())))
    token = f"{head}.{body}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    _jwt = (now, token)
    return token


def send(push_token: str, title: str, body: str, data: dict | None = None) -> str:
    """'sent', 'gone' (the app was deleted or the token is no longer valid: forget it) or 'failed'."""
    global _client, last_error
    last_error = None
    if not configured():
        log.warning("APNs isn't configured (APNS_KEY_ID, APNS_TEAM_ID, APNS_PRIVATE_KEY): push not sent")
        last_error = "not_configured"
        return "failed"
    device = push_token.removeprefix(PREFIX)
    host = os.getenv("APNS_HOST", "api.push.apple.com")
    payload = {"aps": {"alert": {"title": title, "body": body}, "sound": "default"}, **(data or {})}
    try:
        _client = _client or httpx.Client(http2=True, timeout=10)
        r = _client.post(f"https://{host}/3/device/{device}", json=payload, headers={
            "authorization": f"bearer {_token()}", "apns-topic": os.getenv("APNS_TOPIC", "com.paxdolmes.paxen"),
            "apns-push-type": "alert", "apns-priority": "10", "apns-expiration": str(int(time.time()) + 1800)})
    except Exception as e:  # never let a push failure break monitoring
        log.warning("APNs push failed: %s", type(e).__name__)
        last_error = type(e).__name__
        return "failed"
    if r.status_code == 200:
        return "sent"
    try:
        reason = (r.json() if r.content else {}).get("reason", "")
    except ValueError:
        reason = ""
    last_error = f"{r.status_code} {reason}".strip()
    if r.status_code == 410 or reason in ("BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"):
        return "gone"
    log.warning("APNs push failed (%s %s)", r.status_code, reason)
    return "failed"
