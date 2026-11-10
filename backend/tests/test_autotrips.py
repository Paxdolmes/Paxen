"""Automatic trips from Home/Work geofence crossings (paxen/autotrips.py), and what counts as valid data."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from conftest import HOME, MORNING, WORK


@pytest.fixture
def app(monkeypatch):
    import paxen.main as main
    from paxen.engine import clear_status_cache
    from paxen.providers import get_provider

    get_provider().scenario = "normal"
    clear_status_cache()
    clock = {"t": MORNING}
    monkeypatch.setattr(main, "now", lambda: clock["t"])
    with TestClient(main.app) as c:
        c.headers["Authorization"] = "Bearer " + c.post("/v1/users").json()["token"]
        commutes = c.post("/v1/onboarding", json={
            "home": {"label": "home", "name": "Home", "lat": HOME[0], "lon": HOME[1]},
            "work": {"label": "work", "name": "Work", "lat": WORK[0], "lon": WORK[1]}}).json()["commutes"]
        places = {p["label"]: p["id"] for p in c.get("/v1/places").json()}
        yield c, clock, places, commutes


def event(c, clock, place_id, kind, minutes):
    clock["t"] = MORNING + timedelta(minutes=minutes)
    return c.post("/v1/trips/events", json={"place_id": place_id, "event": kind, "at": clock["t"].isoformat()}).json()


def test_off_until_the_user_turns_it_on(app):
    c, clock, places, _ = app
    assert event(c, clock, places["home"], "exit", 0)["action"] == "ignored"
    assert c.patch("/v1/me", json={"auto_trips": True}).json()["auto_trips"] is True
    assert event(c, clock, places["home"], "exit", 0)["action"] == "started"


def test_a_normal_commute_is_recorded_with_the_forecast_at_departure(app):
    c, clock, places, _ = app
    c.patch("/v1/me", json={"auto_trips": True})
    assert event(c, clock, places["home"], "exit", 0)["action"] == "started"
    done = event(c, clock, places["work"], "enter", 30)
    assert done["action"] == "recorded" and 32 <= done["duration_min"] <= 35  # 30 min + walking to/from the edges
    [trip] = c.get("/v1/trips").json()
    assert trip["source"] == "detected" and trip["status"] == "arrived" and trip["forecast"]["p50"]
    assert c.get("/v1/me").json()["auto_trip_stats"]["recorded"] == 1


def test_a_stop_at_the_shops_is_deleted_not_learned_from(app):
    c, clock, places, _ = app
    c.patch("/v1/me", json={"auto_trips": True})
    event(c, clock, places["home"], "exit", 0)
    done = event(c, clock, places["work"], "enter", 85)  # 85 minutes for a ~30 minute commute
    assert done["action"] == "discarded" and done["reason"] == "too_slow"
    assert c.get("/v1/trips").json() == []  # nothing kept
    assert c.get("/v1/me").json()["auto_trip_stats"]["skipped"] == {"too_slow": 1}


def test_going_back_home_is_not_a_commute(app):
    c, clock, places, _ = app
    c.patch("/v1/me", json={"auto_trips": True})
    event(c, clock, places["home"], "exit", 0)
    assert event(c, clock, places["home"], "enter", 20)["action"] == "dropped"
    assert event(c, clock, places["work"], "enter", 40)["action"] == "ignored"
    assert c.get("/v1/trips").json() == []


def test_a_running_live_trip_is_ended_on_arrival_and_not_doubled(app):
    c, clock, places, commutes = app
    c.patch("/v1/me", json={"auto_trips": True})
    opt = c.get(f"/v1/commutes/{commutes[0]['id']}/compare").json()["recommended"]
    trip = c.post("/v1/trips", json={"commute_id": commutes[0]["id"], "signature": opt["id"]}).json()
    assert event(c, clock, places["home"], "exit", 2)["action"] == "ignored"
    ended = event(c, clock, places["work"], "enter", 31)
    assert ended["action"] == "live trip ended" and ended["trip_id"] == trip["id"] and ended["status"] == "arrived"
    assert len(c.get("/v1/trips").json()) == 1


def test_turning_it_off_forgets_a_departure_in_progress(app):
    c, clock, places, _ = app
    c.patch("/v1/me", json={"auto_trips": True})
    event(c, clock, places["home"], "exit", 0)
    c.patch("/v1/me", json={"auto_trips": False})
    assert c.get("/v1/trips").json() == []


def test_invalid_trips_are_deleted_after_a_day(session):
    from paxen.db import Trip, User
    from paxen.live import close_stale, finish

    u = User(token_hash="x" * 64)
    session.add(u)
    session.flush()
    slow = Trip(user_id=u.id, started_at=MORNING.replace(tzinfo=None), status="active",
                forecast_p10=28, forecast_p50=31, forecast_p90=36)
    session.add(slow)
    finish(slow, MORNING + timedelta(minutes=70))
    assert slow.status == "too_slow" and slow.duration_min is None  # kept a day for the app to show, never learned
    ok = Trip(user_id=u.id, started_at=MORNING.replace(tzinfo=None), status="active",
              forecast_p10=28, forecast_p50=31, forecast_p90=36)
    session.add(ok)
    finish(ok, MORNING + timedelta(minutes=38))
    assert ok.status == "arrived" and ok.duration_min == 38.0
    session.commit()
    close_stale(session, MORNING + timedelta(days=1, minutes=5))
    assert [t.status for t in session.query(Trip).all()] == ["arrived"]
