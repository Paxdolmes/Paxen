import pytest
from fastapi.testclient import TestClient

import paxen.main as main
from conftest import HOME, MORNING, WORK
from paxen.engine import clear_status_cache
from paxen.providers import get_provider


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "now", lambda: MORNING)
    get_provider().scenario = "normal"
    clear_status_cache()
    with TestClient(main.app) as c:
        tok = c.post("/v1/users").json()["token"]
        c.headers["Authorization"] = f"Bearer {tok}"
        yield c


def onboard(c):
    r = c.post("/v1/onboarding", json={
        "name": "Sam",
        "home": {"label": "home", "name": "Orford Road", "lat": HOME[0], "lon": HOME[1], "source": "saved"},
        "work": {"label": "work", "name": "Regent Street", "lat": WORK[0], "lon": WORK[1]},
        "morning": {"start": "08:00", "end": "08:45"}, "evening": {"start": "17:30", "end": "18:15"},
    })
    assert r.status_code == 201, r.text
    return r.json()


def test_auth_required():
    with TestClient(main.app) as c:
        assert c.get("/v1/dashboard").status_code == 401


def test_full_commute_flow(client):
    data = onboard(client)
    to_work = data["commutes"][0]["id"]

    d = client.get("/v1/dashboard").json()
    assert d["simulated"] and d["active_commute_id"] == to_work
    card = d["commutes"][0]
    assert card["status"] == "normal" and card["usual"]["summary"] == "Victoria"
    assert card["usual"]["legs"][1]["live"] is True

    client.post("/v1/dev/scenario", json={"scenario": "victoria-severe"})
    cmp = client.get(f"/v1/commutes/{to_work}/compare", params={"preference": "fastest"}).json()
    assert cmp["status"] == "slower" and cmp["recommended"]["summary"] != "Victoria"
    assert len(cmp["options"]) >= 3 and all("crowding" in o for o in cmp["options"])

    alerts = client.post("/v1/dev/check-now").json()["alerts"]
    assert alerts and alerts[0]["kind"] == "better_route"
    rec = cmp["recommended"]
    trip = client.post("/v1/trips", json={"commute_id": to_work, "signature": rec["id"], "summary": rec["summary"],
                                          "forecast_p50": rec["duration"]["p50"], "forecast_p10": rec["duration"]["p10"],
                                          "forecast_p90": rec["duration"]["p90"],
                                          "followed_alert_id": alerts[0]["id"]}).json()
    done = client.post(f"/v1/trips/{trip['id']}/arrive",
                       json={"arrived_at": "2026-11-03T09:02:00+00:00"}).json()
    assert done["duration_min"] == 42.0

    fb = client.post(f"/v1/alerts/{alerts[0]['id']}/feedback", json={"feedback": "useful"}).json()
    assert fb["feedback"] == "useful"
    ins = client.get("/v1/insights").json()
    assert ins["personal"]["alerts_followed"] == 1 and ins["personal"]["alerts_rated_useful"] == 1

    net = client.get("/v1/network/status").json()["lines"]
    assert net[0]["line_id"] == "victoria" and net[0]["on_my_routes"]

    # choose a different usual route
    other = next(o for o in cmp["options"] if not o["is_usual"])
    assert client.put(f"/v1/commutes/{to_work}/usual", json={"signature": other["id"]}).json()["usual_summary"] \
        == other["summary"]

    # privacy controls
    assert client.patch("/v1/me", json={"monitoring_paused": True}).json()["monitoring_paused"]
    assert client.delete("/v1/me/history").json()["trips_deleted"] == 1
    assert client.delete("/v1/me").status_code == 204
    assert client.get("/v1/me").status_code == 401


def test_place_search_and_validation(client):
    res = client.get("/v1/places/search", params={"q": "oxford"}).json()
    assert res and res[0]["name"] == "Oxford Circus"
    bad = client.post("/v1/commutes", json={"name": "x", "origin_id": "a", "dest_id": "b", "window_start": "25:00",
                                            "window_end": "08:00"})
    assert bad.status_code == 422


def test_seed_backfills_history(client):
    onboard(client)
    r = client.post("/v1/dev/seed").json()
    assert r["model"]["training"]["status"] == "promoted" and r["trips_created"] > 10
    d = client.get("/v1/dashboard").json()
    assert d["commutes"][0]["baseline"]["basis"] == "personal"
    assert client.get("/v1/insights").json()["model"]["status"] == "active"


def test_onboarding_with_chosen_stations(client):
    near = client.get("/v1/places/nearby-stops", params={"lat": HOME[0], "lon": HOME[1]}).json()
    station = next(n for n in near if n["stop_id"] == "walthamstow-central")
    assert station["walk_min"] > 0 and station["kind"] == "station"
    home = {"label": "home", "name": "12 Orford Road", "lat": HOME[0], "lon": HOME[1],
            "stops": [{k: station[k] for k in ("stop_id", "name", "kind", "lat", "lon", "walk_min", "modes", "lines")}]}
    r = client.post("/v1/onboarding", json={"home": home,
                                            "work": {"label": "work", "name": "Regent Street", "lat": WORK[0],
                                                     "lon": WORK[1]}})
    assert r.status_code == 201, r.text
    assert r.json()["places"][0]["stops"][0]["stop_id"] == "walthamstow-central"
    card = client.get("/v1/dashboard").json()["commutes"][0]
    assert card["chosen_stops_honoured"]
    assert all(o["legs"][1]["from"] == "Walthamstow Central" for o in card["options"])


def test_personal_data_endpoints_accept_post_bodies(client):
    onboard(client)
    assert client.post("/v1/places/search", json={"q": "oxford"}).json()[0]["name"] == "Oxford Circus"
    near = client.post("/v1/places/nearby-stops", json={"lat": HOME[0], "lon": HOME[1]}).json()
    assert any(n["stop_id"] == "walthamstow-central" for n in near)


def test_access_log_drops_query_strings():
    import logging

    import paxen.main as main

    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4:5", "GET", "/v1/trips/x/live?lat=51.5&lon=-0.1", "1.1", 200), None)
    main._NoQueryStrings().filter(rec)
    assert "51.5" not in rec.getMessage() and "/v1/trips/x/live" in rec.getMessage()
