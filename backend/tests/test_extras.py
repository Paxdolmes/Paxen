"""Fares, planned closures, rain, air quality and live trips."""
from datetime import timedelta

from conftest import HOME, MORNING, WORK
from paxen.conditions import upcoming_disruptions, walking_penalty, weather_from_forecast
from paxen.providers.tfl import parse_air_quality, parse_future_statuses, parse_journeys
from test_tfl_parsing import JOURNEYS


def test_fares_and_route_shape_parsed():
    from copy import deepcopy
    data = deepcopy(JOURNEYS)
    data["journeys"][0]["fare"] = {"totalCost": 310, "fares": [{"cost": 310, "peak": 360, "offPeak": 310}]}
    data["journeys"][0]["legs"][1]["path"]["lineString"] = "[[51.583, -0.0197],[51.55, -0.10],[51.515, -0.1418]]"
    [j] = parse_journeys(data)
    assert (j.fare_pence, j.fare_peak_pence, j.fare_off_peak_pence) == (310, 360, 310)
    assert j.legs[1].path[0] == (51.583, -0.0197) and len(j.legs[1].path) == 3


def test_future_statuses_and_upcoming_filter():
    rows = parse_future_statuses([{"id": "weaver", "name": "Weaver", "lineStatuses": [
        {"statusSeverity": 5, "statusSeverityDescription": "Part Closure", "reason": "No service after 2245",
         "validityPeriods": [{"fromDate": "2026-11-09T22:45:00Z", "toDate": "2026-11-10T01:29:00Z"}]},
        {"statusSeverity": 10, "statusSeverityDescription": "Good Service"}]}])
    assert len(rows) == 1 and rows[0]["category"] == "part_suspended"

    class P:
        def future_statuses(self, line_ids, start, end):
            return rows + [{**rows[0], "from": MORNING.isoformat()}]  # one already happening: not "upcoming"

    from paxen.conditions import clear_cache
    clear_cache()
    up = upcoming_disruptions(P(), ["weaver"], MORNING)
    assert len(up) == 1 and up[0]["starts_local"] == "Mon 09 Nov, 22:45"


def test_air_quality_parse():
    aq = parse_air_quality({"currentForecast": [
        {"forecastType": "Current", "forecastBand": "High", "forecastSummary": "High air pollution forecast"},
        {"forecastType": "Future", "forecastBand": "Moderate"}]})
    assert aq == {"band": "High", "summary": "High air pollution forecast", "tomorrow_band": "Moderate", "level": 2}


def test_weather_and_walking_penalty():
    data = {"hourly": {"time": ["2026-11-03T08:00", "2026-11-03T09:00"], "precipitation_probability": [80, 10],
                       "precipitation": [1.2, 0], "temperature_2m": [9.5, 10], "weather_code": [61, 3]}}
    w = weather_from_forecast(data, MORNING)
    assert w["wet"] and w["summary"] == "Rain likely" and w["time"] == "08:00"
    k, why = walking_penalty(w, {"band": "High", "level": 2})
    assert k > 0.6 and len(why) == 2
    assert walking_penalty(None, {"band": "Low", "level": 0}) == (0.0, [])


def test_rain_ranks_long_walks_lower(session):
    from paxen.engine import clear_status_cache, evaluate_commute
    from paxen.providers.sim import SimProvider
    from test_engine import make_commute
    c = make_commute(session)
    p = SimProvider("normal")
    clear_status_cache()
    dry = evaluate_commute(session, p, c, MORNING, depart_at=MORNING)
    wet = evaluate_commute(session, p, c, MORNING, depart_at=MORNING, conditions={"weather": {
        "wet": True, "rain_mm": 3, "summary": "Heavy rain", "time": "08:00"}})
    assert wet.conditions["walking_note"].startswith("Routes with long walks ranked lower")
    assert dry.conditions["walking_note"] is None
    dry_score = {f.signature: f.score for f in dry.options}
    for f in wet.options:  # each route pays 0.6 per walking minute in heavy rain; more walking, bigger penalty
        assert abs((f.score - dry_score[f.signature]) - 0.6 * f.journey.walking_min) < 1e-6


def test_live_trip_progress_and_auto_arrival(monkeypatch):
    import paxen.main as main
    from fastapi.testclient import TestClient
    from paxen.engine import clear_status_cache
    from paxen.providers import get_provider
    get_provider().scenario = "normal"
    clear_status_cache()
    clock = {"t": MORNING}
    monkeypatch.setattr(main, "now", lambda: clock["t"])
    with TestClient(main.app) as c:
        c.headers["Authorization"] = "Bearer " + c.post("/v1/users").json()["token"]
        cid = c.post("/v1/onboarding", json={
            "home": {"label": "home", "name": "Home", "lat": HOME[0], "lon": HOME[1]},
            "work": {"label": "work", "name": "Work", "lat": WORK[0], "lon": WORK[1]}}).json()["commutes"][0]["id"]
        opt = c.get(f"/v1/commutes/{cid}/compare").json()["recommended"]
        assert opt["legs"][1]["path"] and len(opt["legs"][1]["path"]) >= 2  # map shape available
        trip = c.post("/v1/trips", json={"commute_id": cid, "signature": opt["id"]}).json()
        assert trip["status"] == "active" and trip["has_plan"]

        live = c.get(f"/v1/trips/{trip['id']}/live").json()  # no position: by the clock
        assert live["status"] == "active" and live["located_by"] == "clock" and live["current_leg"] == 0
        assert live["remaining_min"]["p50"] > 0 and live["next_departure"]["stop"] == "Walthamstow Central"

        clock["t"] = MORNING + timedelta(minutes=12)  # on the train, between stations
        mid = opt["legs"][1]["path"][len(opt["legs"][1]["path"]) // 2]
        live = c.post(f"/v1/trips/{trip['id']}/live", json={"lat": mid[0], "lon": mid[1]}).json()
        assert live["located_by"] == "position" and live["current_leg"] == 1 and live["phase"] == "on_board"
        before = live["remaining_min"]["p50"]

        clock["t"] = MORNING + timedelta(minutes=31)  # at the destination: ends itself
        done = c.post(f"/v1/trips/{trip['id']}/live", json={"lat": WORK[0], "lon": WORK[1]}).json()
        assert done["status"] == "arrived" and done["duration_min"] == 31.0 and before > 0
        assert c.get("/v1/trips").json()[0]["status"] == "arrived"


def test_stale_trip_closed_without_learning_from_it(session):
    from paxen.db import Trip
    from paxen.live import close_stale
    t = Trip(user_id="u", started_at=(MORNING - timedelta(hours=3)).replace(tzinfo=None), status="active",
             plan={"forecast": {"p90": 40}})
    session.add(t)
    session.commit()
    assert close_stale(session, MORNING) == 1
    assert t.status == "auto_closed" and t.duration_min is None


def test_impossibly_fast_trip_not_learned_from():
    from paxen.db import Trip
    from paxen.live import finish
    t = Trip(user_id="u", started_at=MORNING.replace(tzinfo=None), status="active", plan={"forecast": {"p10": 38}})
    finish(t, MORNING + timedelta(minutes=2))
    assert t.status == "too_fast" and t.duration_min is None
