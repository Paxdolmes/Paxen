"""Train fullness estimates (paxen/fullness.py): typical load x live gap x live busyness, and the boarding answers
that check them."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from paxen import fullness, numbat
from paxen.domain import Arrival, Journey, Leg
from paxen.engine import NetworkContext, forecast_journey
from paxen.forecast import CorrectionModel

REAL = numbat.get()
needs_data = pytest.mark.skipif(REAL is None, reason="NUMBAT data file not built")
FBY = "940GZZLUFBY"  # Fulham Broadway
NOW = datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)  # Tuesday 08:00 London (GMT in November)


def test_the_gap_ahead_scales_the_load_within_limits():
    assert fullness.gap_factor(240, 240) == 1.0
    assert fullness.gap_factor(480, 240) == pytest.approx(1.85)  # twice the usual gap: nearly twice the people
    assert fullness.gap_factor(60, 240) == 0.5  # right behind another train: never assumed empty
    assert fullness.gap_factor(3600, 240) == 2.0
    assert fullness.gap_factor(None, 240) == 1.0
    assert fullness.live_factor(None) == 1.0
    assert fullness.live_factor(1.6) == pytest.approx(1.3)  # damped: a busy station is a hint, not a headcount
    assert fullness.live_factor(5.0) == 1.4 and fullness.live_factor(0.1) == 0.75


@needs_data
def test_fulham_broadway_eastbound_in_the_morning_peak():
    when = NOW + timedelta(minutes=15)
    usual = fullness.train_fullness("district", FBY, "eastbound", when)
    assert usual["level"] == "standing" and usual["directional"]
    assert 0.6 <= usual["typical_share"] < 0.8
    late = fullness.train_fullness("district", FBY, "eastbound", when, gap_s=8 * 60)  # 8 min after the last one
    assert late["level"] == "packed" and late["gap_min"] == 8.0
    close = fullness.train_fullness("district", FBY, "eastbound", when, gap_s=2 * 60)
    assert close["level"] == "space"
    busy = fullness.train_fullness("district", FBY, "eastbound", when, live_vs_typical=1.8)
    assert busy["share"] > usual["share"]
    assert fullness.train_fullness("district", FBY, "eastbound", when.replace(hour=12))["level"] == "space"
    assert fullness.train_fullness("national-rail", "910GXXX", None, when) is None  # no capacity or loads known


@needs_data
def test_upstream_follows_the_train_backwards():
    when = NOW + timedelta(minutes=15)
    assert REAL.upstream("district", FBY, "eastbound", when, 2) == ["940GZZLUPSG", "940GZZLUPYB"]
    assert REAL.upstream("district", FBY, "westbound", when, 1) == ["940GZZLUWBN"]
    assert REAL.upstream("district", FBY, None, when) == []


def test_advice_only_when_a_train_shortly_behind_is_clearly_emptier():
    def train(at_local, in_min, level, share, gap=None):
        return {"in_min": in_min, "at_local": at_local,
                "fullness": {"level": level, "share": share, "gap_min": gap, "headway_min": 4.0}}

    trains = [train("08:04", 2.0, "packed", 1.0, gap=7.0), train("08:06", 4.0, "space", 0.4)]
    assert fullness.advice(trains, 0) == ("The 08:04 is likely packed (7-minute gap ahead of it). The 08:06 should "
                                          "have space, and you'd arrive about 2 minutes later.")
    assert fullness.advice([train("08:04", 2.0, "packed", 1.0), train("08:06", 4.0, "packed", 0.95)], 0) is None
    assert fullness.advice([train("08:04", 2.0, "packed", 1.0), train("08:12", 10.0, "space", 0.4)], 0) is None
    assert fullness.advice([train("08:04", 2.0, "standing", 0.7), train("08:06", 4.0, "space", 0.4)], 0) is None


class FulhamBroadway:
    """TfL as it might look at 08:00: an 08:04 after a long gap, an 08:06 right behind it, an 08:10."""
    name = "tfl"

    def arrivals(self, stop_id, now):
        def a(vid, mins):
            t = now + timedelta(minutes=mins)
            return Arrival(vid, stop_id, "Fulham Broadway", "district", "District", "tube", "inbound",
                           "Upminster", t, int(mins * 60), now, platform="Eastbound - Platform 1")
        return SimpleNamespace(items=[a("1", 4), a("2", 6), a("3", 10)])


@needs_data
def test_the_journey_forecast_says_which_train_to_wait_for():
    walk = Leg("walking", 2.0, "Home", "Fulham Broadway", NOW, NOW + timedelta(minutes=2))
    dis = Leg("tube", 6.0, "Fulham Broadway", "Earl's Court", NOW + timedelta(minutes=4), NOW + timedelta(minutes=10),
              line_id="district", line_name="District", from_stop_id=FBY,
              stop_ids=[FBY, "940GZZLUWBN", "940GZZLUECT"])
    j = Journey([walk, dis], 10.0, NOW, NOW + timedelta(minutes=10), "tfl")
    seen = {}

    def last_seen(stop_id, line_id, directions, before):
        seen["asked"] = (stop_id, line_id, directions)
        return NOW - timedelta(minutes=3)  # the train ahead of the 08:04 left at 07:57

    ctx = NetworkContext(FulhamBroadway(), NOW, {}, CorrectionModel(), last_seen=last_seen)
    f = forecast_journey(j, ctx, NOW)
    assert seen["asked"] == (FBY, "district", {"inbound", "eastbound"})
    b = f.fullness
    assert b["live"] and b["stop"] == "Fulham Broadway" and b["level"] == "packed"
    assert [t["at_local"] for t in b["trains"]] == ["08:04", "08:06", "08:10"]
    assert b["trains"][0]["fullness"]["gap_min"] == 7.0 and b["trains"][1]["fullness"]["level"] == "space"
    assert b["advice"].startswith("The 08:04 is likely packed (7-minute gap ahead of it). The 08:06 should have space")
    assert f.legs[1].trains == b["trains"] and f.legs[1].catch_index == 0


@needs_data
def test_without_a_countdown_the_usual_fullness_is_shown():
    class NoLive:
        name = "tfl"

        def arrivals(self, stop_id, now):
            raise RuntimeError("no live data")

    depart = NOW + timedelta(days=1)  # tomorrow: too far ahead for live trains
    dis = Leg("tube", 6.0, "Fulham Broadway", "Earl's Court", depart, depart + timedelta(minutes=6),
              line_id="district", line_name="District", from_stop_id=FBY, direction="Eastbound",
              stop_ids=[FBY, "940GZZLUWBN", "940GZZLUECT"])
    f = forecast_journey(Journey([dis], 6.0, depart, depart + timedelta(minutes=6), "tfl"),
                         NetworkContext(NoLive(), NOW, {}, CorrectionModel()), depart)
    assert f.fullness["live"] is False and f.fullness["label"] == "Usually standing room"
    assert f.fullness["trains"] == [] and f.fullness["advice"] is None


def test_last_seen_uses_recent_sightings_only(session):
    from paxen.db import ObservedArrival
    from paxen.timeutil import naive_utc

    def sighting(mins_ago, direction="eastbound", method="trackernet", stop=FBY):
        t = naive_utc(NOW - timedelta(minutes=mins_ago))
        session.add(ObservedArrival(source="tfl", stop_id=stop, line_id="district", vehicle_id=str(mins_ago),
                                    direction=direction, arrived_at=t, earliest=t, latest=t, method=method,
                                    quality=1.0))

    sighting(9)
    sighting(3)
    sighting(1, direction="westbound")
    sighting(2, method="countdown_inferred")  # inferred arrivals lag behind: not used for the gap
    session.commit()
    look = fullness.last_seen_lookup(session, "tfl", NOW)
    assert look(FBY, "district", {"eastbound"}, NOW + timedelta(minutes=4)) == NOW - timedelta(minutes=3)
    # the train that's due is not its own train ahead
    assert look(FBY, "district", {"eastbound"}, NOW - timedelta(minutes=3, seconds=-20)) == NOW - timedelta(minutes=9)
    assert look(FBY, "district", {"northbound"}, NOW) is None
    stale = fullness.last_seen_lookup(session, "tfl", NOW + timedelta(minutes=10))  # nothing seen for 9+ minutes
    assert stale(FBY, "district", {"eastbound"}, NOW + timedelta(minutes=12)) is None


@pytest.fixture
def client(monkeypatch):
    import paxen.main as main
    from paxen.engine import clear_status_cache
    from paxen.providers import get_provider

    get_provider().scenario = "normal"
    clear_status_cache()
    with TestClient(main.app) as c:
        c.headers["Authorization"] = "Bearer " + c.post("/v1/users").json()["token"]
        yield c


def test_boarding_answers_are_kept_once_per_trip_and_station(client):
    trip = client.post("/v1/trips", json={"summary": "District"}).json()
    body = {"trip_id": trip["id"], "line_id": "district", "stop_id": FBY, "level": "packed", "share": 1.02,
            "typical_share": 0.67, "gap_min": 7.0, "got_on": False, "train_at": NOW.isoformat()}
    assert client.post("/v1/boarding", json=body).json()["got_on"] is False
    assert client.post("/v1/boarding", json={**body, "got_on": True}).json()["got_on"] is True  # changed their mind
    from paxen import recorder

    recorder._DATA_STATS.clear()  # the health stats are cached for 10 minutes
    stats = client.get("/v1/health").json()["data"]["boarding_reports"]
    assert stats.get("packed", {}).get("reports", 0) >= 1
    other = client.post("/v1/users").json()["token"]
    r = client.post("/v1/boarding", json=body, headers={"Authorization": "Bearer " + other})
    assert r.status_code == 404  # someone else's trip
    assert client.delete("/v1/me/history").status_code == 200
