"""Native push to the iPhone app (paxen/apns.py)."""
import base64
import json

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

import paxen.apns as apns
from paxen.db import Alert, User
from paxen.notify import deliver


@pytest.fixture
def key(monkeypatch):
    k = ec.generate_private_key(ec.SECP256R1())
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    monkeypatch.setenv("APNS_KEY_ID", "ABC123DEFG")
    monkeypatch.setenv("APNS_TEAM_ID", "TEAM123456")
    monkeypatch.setenv("APNS_PRIVATE_KEY", pem.decode().replace("\n", "\\n"))  # as pasted into a one-line variable
    monkeypatch.setattr(apns, "_jwt", None)
    return k


def fake_client(monkeypatch, status, body=b""):
    seen = {}

    def handler(request: httpx.Request):
        seen.update(url=str(request.url), headers=dict(request.headers), json=json.loads(request.content))
        return httpx.Response(status, content=body)

    monkeypatch.setattr(apns, "_client", httpx.Client(transport=httpx.MockTransport(handler)))
    return seen


def test_signed_request_to_apple(key, monkeypatch):
    seen = fake_client(monkeypatch, 200)
    assert apns.send("apns:abcd", "Paxen", "Slower today", {"url": "/?tab=alerts"}) == "sent"
    assert seen["url"] == "https://api.push.apple.com/3/device/abcd"
    assert seen["headers"]["apns-topic"] == "com.paxdolmes.paxen" and seen["headers"]["apns-push-type"] == "alert"
    assert seen["json"]["aps"]["alert"] == {"title": "Paxen", "body": "Slower today"} and seen["json"]["url"] == "/?tab=alerts"
    head, claims, sig = seen["headers"]["authorization"].removeprefix("bearer ").split(".")
    pad = lambda x: base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))  # noqa: E731
    assert json.loads(pad(head)) == {"alg": "ES256", "kid": "ABC123DEFG"} and json.loads(pad(claims))["iss"] == "TEAM123456"
    raw = pad(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key.public_key().verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if wrong


def test_uninstalled_app_is_forgotten(key, monkeypatch, session):
    fake_client(monkeypatch, 410, b'{"reason":"Unregistered"}')
    u = User(token_hash="a" * 64, push_token="apns:dead")
    session.add(u)
    session.flush()
    alert = Alert(user_id=u.id, commute_id=None, kind="better_route", title="t", body="b", confidence="high", data={})
    session.add(alert)
    session.flush()
    assert deliver(u, alert) == "push_gone" and u.push_token is None


def test_not_configured_never_breaks_monitoring(monkeypatch):
    for k in ("APNS_KEY_ID", "APNS_TEAM_ID", "APNS_PRIVATE_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert apns.send("apns:abcd", "t", "b") == "failed"
