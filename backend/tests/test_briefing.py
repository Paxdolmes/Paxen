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
    assert {k: worker[k] for k in ("apns_configured", "seen_at", "prediction_retention_days")} == {
        "apns_configured": False, "seen_at": MORNING.isoformat(), "prediction_retention_days": 60}
    # whether the raw archive is set up and working, and the disk safety switch
    assert worker["archive"]["configured"] is False and worker["archive"]["last_error"] is None
    assert worker["db_pause_mb"] == recorder.DEFAULT_PAUSE_MB and worker["recording_paused"] is None


def test_not_commuting_today_silences_today_only(client):
    c, to_work = client
    c.patch(f"/v1/commutes/{to_work}", json={"briefing_at": "08:15"})
    assert c.get("/v1/me").json()["away_today"] is False
    assert c.patch("/v1/me", json={"away_today": True}).json()["away_today"] is True
    run(MORNING)
    assert briefings(c, to_work) == []
    get_provider().scenario = "victoria-suspended"  # the usual route is down: normally an alert
    clear_status_cache()
    with SessionLocal() as s:
        ev = evaluate_commute(s, get_provider(), s.get(Commute, to_work), MORNING)
        assert maybe_alert(s, ev, MORNING) is None
        tomorrow = MORNING + timedelta(days=1)  # it lapses by itself
        ev = evaluate_commute(s, get_provider(), s.get(Commute, to_work), tomorrow)
        assert maybe_alert(s, ev, tomorrow) is not None
    assert c.patch("/v1/me", json={"away_today": False}).json()["away_today"] is False
    get_provider().scenario = "normal"
    assert run(MORNING) == 1 and len(briefings(c, to_work)) == 1


def test_this_week_in_numbers(client):
    c, to_work = client
    from paxen.db import Trip
    from paxen.insights import week_summary
    from paxen.timeutil import naive_utc

    def trip(days_ago, minutes, forecast, alert=None):
        t0 = naive_utc(MORNING - timedelta(days=days_ago))
        return Trip(user_id="u", started_at=t0, arrived_at=t0 + timedelta(minutes=minutes), duration_min=minutes,
                    forecast_p50=forecast, followed_alert_id=alert)

    saved = Alert(id="a1", user_id="u", kind="better_route", title="t", body="b", confidence="high", gain_min=8.0)
    trips = [trip(1, 30, 31), trip(2, 34, 30), trip(3, 26, 27, "a1"), trip(9, 40, 35), trip(10, 36, 35)]
    w = week_summary(trips, [saved], MORNING)
    assert w["trips"] == 3 and w["minutes_travelled"] == 90 and w["typical_min"] == 30
    assert w["typical_last_week_min"] == 38 and w["quickest_min"] == 26 and w["slowest_min"] == 34
    assert w["forecast_within_2_min"] == 0.67 and w["routes_switched"] == 1 and w["minutes_saved"] == 9.0
    empty = week_summary([], [], MORNING)
    assert empty["trips"] == 0 and empty["typical_min"] is None and empty["forecast_within_2_min"] is None
    assert c.get("/v1/insights").json()["personal"]["week"]["trips"] == 0
