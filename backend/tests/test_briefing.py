"""The daily commute briefing (paxen/briefing.py) and push delivery diagnostics (notify.push_stats)."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import paxen.main as main
from conftest import HOME, MORNING, WORK
from paxen import briefing
from paxen.db import Alert, Commute, SessionLocal
from paxen.engine import clear_status_cache, evaluate_commute, maybe_alert
from paxen.notify import deliver
from paxen.providers import get_provider

# MORNING is Tuesday 3 Nov 2026, 08:20 London


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "now", lambda: MORNING)
    get_provider().scenario = "normal"
    clear_status_cache()
    with TestClient(main.app) as c:
        c.headers["Authorization"] = "Bearer " + c.post("/v1/users").json()["token"]
        commutes = c.post("/v1/onboarding", json={
            "home": {"label": "home", "name": "Orford Road", "lat": HOME[0], "lon": HOME[1]},
            "work": {"label": "work", "name": "Regent Street", "lat": WORK[0], "lon": WORK[1]}}).json()["commutes"]
        c.get("/v1/dashboard")  # learns the usual route (Victoria) on a normal day, as using the app does
        yield c, commutes[0]["id"]
    get_provider().scenario = "normal"
    clear_status_cache()


def run(at):
    """One worker pass of the briefing loop at `at`; returns how many were sent."""
    clear_status_cache()
    with SessionLocal() as s:
        return briefing.send_due(s, get_provider(), at, True, deliver)


def briefings(c, commute_id):
    return [a for a in c.get("/v1/alerts").json() if a["kind"] == "briefing" and a["commute_id"] == commute_id]


def test_off_until_a_time_is_chosen_and_can_be_turned_off(client):
    c, to_work = client
    assert c.get("/v1/commutes").json()[0]["briefing_at"] is None
    assert run(MORNING) == 0 or not briefings(c, to_work)
    assert c.patch(f"/v1/commutes/{to_work}", json={"briefing_at": "07:45"}).json()["briefing_at"] == "07:45"
    assert c.patch(f"/v1/commutes/{to_work}", json={"briefing_at": "25:00"}).status_code == 422
    assert c.patch(f"/v1/commutes/{to_work}", json={"briefing_at": None}).json()["briefing_at"] is None


def test_sent_once_at_the_chosen_time_saying_stick_to_the_usual_route(client):
    c, to_work = client
    c.patch(f"/v1/commutes/{to_work}", json={"briefing_at": "07:45"})
    at = MORNING.replace(hour=7, minute=40)
    run(at)
    assert briefings(c, to_work) == []  # not yet
    run(at + timedelta(minutes=5))
    [b] = briefings(c, to_work)
    assert b["title"].startswith("To work: ")
    assert "Stick to your usual route (Victoria): leave 08:00, arrive about" in b["body"]
    assert b["body"].startswith("About ") and "(usually " in b["body"]
    run(at + timedelta(minutes=10))
    assert len(briefings(c, to_work)) == 1  # once a day


def test_a_quicker_route_is_advised_with_how_much_quicker(client):
    c, to_work = client
    c.patch(f"/v1/commutes/{to_work}", json={"briefing_at": "08:15"})
    get_provider().scenario = "victoria-severe"
    run(MORNING)
    [b] = briefings(c, to_work)
    assert "slower than normal" in b["title"]
    assert "Take the " in b["body"] and " min quicker than your usual route" in b["body"]
    assert b["gain_min"] >= 5 and b["recommended_summary"] != "Victoria"
    assert "Victoria: Severe delays." in b["body"]
    # the regular alert straight after would say the same thing: it's held back
    with SessionLocal() as s:
        cm = s.get(Commute, to_work)
        ev = evaluate_commute(s, get_provider(), cm, MORNING + timedelta(minutes=1))
        assert maybe_alert(s, ev, MORNING + timedelta(minutes=1)) is None


def test_a_small_gain_is_not_worth_switching_for(client):
    c, to_work = client
    c.patch("/v1/me", json={"min_gain_min": 30})  # only switch for a really big gain
    c.patch(f"/v1/commutes/{to_work}", json={"briefing_at": "08:15"})
    get_provider().scenario = "victoria-severe"
    run(MORNING)
    [b] = briefings(c, to_work)
    assert "Stick to your usual route (Victoria)" in b["body"]


def test_usual_route_not_running(client):
    c, to_work = client
    c.patch(f"/v1/commutes/{to_work}", json={"briefing_at": "08:15"})
    get_provider().scenario = "victoria-suspended"
    run(MORNING)
    [b] = briefings(c, to_work)
    assert b["title"] == "To work: your usual route isn't running"
    assert b["body"].startswith("Take the ") and "arrive about" in b["body"]


def test_not_on_other_days_when_paused_or_long_after_the_time(client):
    c, to_work = client
    c.patch(f"/v1/commutes/{to_work}", json={"briefing_at": "08:15"})
    run(MORNING + timedelta(days=4))  # Saturday: not a commute day
    run(MORNING + timedelta(minutes=25))  # 08:45: the worker was down at 08:15; too late to be useful
    assert briefings(c, to_work) == []
    c.patch("/v1/me", json={"monitoring_paused": True})
    run(MORNING)
    assert briefings(c, to_work) == []


def test_health_shows_whether_pushes_reach_phones(client):
    c, to_work = client
    c.patch("/v1/me", json={"push_token": "apns:" + "ab" * 32})
    c.patch(f"/v1/commutes/{to_work}", json={"briefing_at": "08:15"})
    run(MORNING)  # APNs isn't configured in tests, so the push fails and says why
    with SessionLocal() as s:
        a = s.query(Alert).filter(Alert.commute_id == to_work, Alert.kind == "briefing").one()
        assert a.delivered == "push_failed" and a.data["push_error"] == "not_configured"
    from paxen import recorder

    recorder._DATA_STATS.clear()
    push = c.get("/v1/health").json()["data"]["push"]
    assert push["apns_configured"] is False and push["devices"]["iphone"] >= 1
    assert push["errors_7d"]["not_configured"] >= 1 and push["alerts_7d"]["briefing"] >= 1


def test_the_worker_reports_whether_it_can_send_iphone_pushes(client, monkeypatch):
    c, _ = client
    from paxen import notify, recorder

    monkeypatch.setattr(notify, "_noted", None)
    with SessionLocal() as s:
        notify.note_worker(s, MORNING)
    recorder._DATA_STATS.clear()
    worker = c.get("/v1/health").json()["data"]["push"]["worker"]
    assert worker == {"apns_configured": False, "seen_at": MORNING.isoformat()}
