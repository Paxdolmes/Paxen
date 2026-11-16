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


def test_commute_alerts_carry_buttons(key, monkeypatch, session):
    seen = fake_client(monkeypatch, 200)
    u = User(token_hash="b" * 64, push_token="apns:abcd")
    session.add(u)
    session.flush()
    alert = Alert(user_id=u.id, commute_id="c1", kind="better_route", title="t", body="b", confidence="high",
                  recommended_signature="tube:victoria", data={})
    session.add(alert)
    session.flush()
    assert deliver(u, alert) == "push"
    assert seen["json"]["aps"]["category"] == "commute"
    assert seen["json"]["commute_id"] == "c1" and seen["json"]["signature"] == "tube:victoria"
    apns.send("apns:abcd", "t", "b")
    assert "category" not in seen["json"]["aps"]  # a test push has no commute: no buttons


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


def test_a_trip_on_the_lock_screen_is_kept_up_to_date_and_ended(key, monkeypatch, session):
    from datetime import datetime, timedelta, timezone

    from paxen import activity
    from paxen.db import Trip

    seen = fake_client(monkeypatch, 200)
    now = datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)
    u = User(token_hash="c" * 64)
    session.add(u)
    session.flush()
    trip = Trip(user_id=u.id, started_at=now.replace(tzinfo=None), status="active", activity_token="ab" * 32)
    session.add(trip)
    session.flush()
    eta = now + timedelta(minutes=24)
    live = {"status": "active", "summary": "District", "eta": eta.isoformat(), "phase": "waiting", "current_leg": 1,
            "legs": [{"mode": "walking", "to": "Fulham Broadway"},
                     {"mode": "tube", "line_name": "District", "from": "Fulham Broadway", "to": "Victoria"}],
            "next_departure": {"line_name": "District", "stop": "Fulham Broadway", "catch_index": 0,
                               "trains": [{"at": (now + timedelta(minutes=3)).isoformat()}]},
            "disruptions": [{"line_name": "District", "description": "Minor delays"}]}
    p = activity.props(live)
    assert p == {"status": "active", "summary": "District", "eta": int(eta.timestamp() * 1000),
                 "headline": "Wait for the District at Fulham Broadway", "next": "District from Fulham Broadway",
                 "nextAt": int((now + timedelta(minutes=3)).timestamp() * 1000), "note": "District: Minor delays"}

    assert activity.push_all(session, None, now, lambda s, provider, t, at: live) == 1
    aps = seen["json"]["aps"]
    assert seen["url"].endswith("/3/device/" + "ab" * 32) and aps["event"] == "update"
    assert seen["headers"]["apns-topic"] == "com.paxdolmes.paxen.push-type.liveactivity"
    assert seen["headers"]["apns-push-type"] == "liveactivity" and seen["headers"]["apns-priority"] == "5"
    assert aps["content-state"]["name"] == "PaxenTrip" and json.loads(aps["content-state"]["props"]) == p
    assert aps["stale-date"] == aps["timestamp"] + 300 and trip.activity_token

    activity.push_all(session, None, now, lambda s, provider, t, at: {"status": "arrived", "summary": "District"})
    aps = seen["json"]["aps"]
    assert aps["event"] == "end" and json.loads(aps["content-state"]["props"])["headline"] == "You’ve arrived"
    assert trip.activity_token is None  # nothing more is sent for this trip
