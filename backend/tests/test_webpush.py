"""Push notifications to the web app."""
import base64

import pytest
from fastapi.testclient import TestClient

import paxen.main as main
import paxen.webpush as wp
from conftest import MORNING
from paxen.db import Alert, User
from paxen.notify import deliver

SUB = {"endpoint": "https://push.example.net/abc", "keys": {"p256dh": "BKey", "auth": "secret"}, "expirationTime": None}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "now", lambda: MORNING)
    with TestClient(main.app) as c:
        c.headers["Authorization"] = f"Bearer {c.post('/v1/users').json()['token']}"
        yield c


def test_server_key_is_created_once_and_is_a_p256_point(client):
    k1, k2 = client.get("/v1/push/key").json()["public_key"], client.get("/v1/push/key").json()["public_key"]
    assert k1 == k2
    raw = base64.urlsafe_b64decode(k1 + "=" * (-len(k1) % 4))
    assert len(raw) == 65 and raw[0] == 4  # uncompressed P-256 point, as browsers expect


def test_subscribe_test_and_unsubscribe(client, monkeypatch):
    sent = []
    monkeypatch.setattr(wp, "send", lambda s, sub, title, body, data=None: sent.append((sub, title)) or "sent")
    assert client.post("/v1/push/subscribe", json={"subscription": {"endpoint": "http://x"}}).status_code == 422
    r = client.post("/v1/push/subscribe", json={"subscription": SUB})
    assert r.status_code == 200 and r.json()["push_enabled"] is True
    assert client.post("/v1/push/test").json() == {"result": "sent"}
    assert sent[0][0]["endpoint"] == SUB["endpoint"] and "expirationTime" not in sent[0][0]
    assert client.delete("/v1/push/subscribe").json()["push_enabled"] is False
    assert client.post("/v1/push/test").status_code == 409


def test_alerts_go_by_web_push_and_revoked_subscriptions_are_forgotten(session, monkeypatch):
    u = User(token_hash="p" * 64, web_push=SUB)
    session.add(u)
    session.flush()
    alert = Alert(user_id=u.id, commute_id="c", kind="better_route", title="Slower today", body="Take the Weaver",
                  confidence="high", data={"push_title": "YOUR COMMUTE IS SLOWER"})
    session.add(alert)
    session.flush()
    calls = []
    monkeypatch.setattr(wp, "send", lambda s, sub, title, body, data=None: calls.append((title, body)) or "sent")
    assert deliver(u, alert) == "push" and calls[0][0] == "YOUR COMMUTE IS SLOWER" and "Forecast confidence: High" in calls[0][1]
    monkeypatch.setattr(wp, "send", lambda *a, **k: "gone")
    assert deliver(u, alert) == "push_gone" and u.web_push is None
    assert deliver(u, alert) == "inbox"  # nothing left to push to
