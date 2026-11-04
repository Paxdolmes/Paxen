"""Address search, nearby stations, and journeys built around the stations a user chose."""
import httpx

from conftest import HOME, MORNING, WORK
from paxen.engine import apply_chosen_stops, clear_status_cache, evaluate_commute, uses_chosen_stops
from paxen.geocode import FULL_POSTCODE, PARTIAL_POSTCODE, search_addresses, search_postcodes
from paxen.providers.sim import SimProvider
from paxen.providers.tfl import parse_nearby
from test_engine import make_commute


def client_returning(payload, status=200):
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(status, json=payload)))


def test_postcode_patterns():
    assert FULL_POSTCODE.match("E17 9PH") and FULL_POSTCODE.match("sw1a1aa")
    assert PARTIAL_POSTCODE.match("E17") and PARTIAL_POSTCODE.match("SW1A 1")
    assert not PARTIAL_POSTCODE.match("Orford Road")


def test_postcode_lookup():
    res = search_postcodes("E17 9PH", client_returning({"result": {
        "postcode": "E17 9PH", "latitude": 51.5826, "longitude": -0.0128,
        "admin_ward": "Hoe Street", "admin_district": "Waltham Forest"}}))
    assert res[0].name == "E17 9PH" and res[0].detail == "Hoe Street, Waltham Forest" and res[0].kind == "address"
    assert search_postcodes("E17 9ZZ", client_returning({}, 404)) == []


def test_street_address_lookup():
    res = search_addresses("12 Orford Road", client_returning([{
        "lat": "51.5826", "lon": "-0.0128", "display_name": "12, Orford Road, Walthamstow, London, E17 9NJ",
        "address": {"house_number": "12", "road": "Orford Road", "suburb": "Walthamstow", "postcode": "E17 9NJ"}}]))
    assert res[0].name == "12 Orford Road" and res[0].detail == "Walthamstow, E17 9NJ"


def test_parse_nearby_stations_and_bus_stops():
    out = parse_nearby({"stopPoints": [
        {"naptanId": "940GZZLUVIC", "commonName": "Victoria Underground Station", "lat": 51.4965, "lon": -0.1447,
         "distance": 566.2, "modes": ["tube"], "lines": [{"id": "victoria", "name": "Victoria"}], "hubNaptanCode": "HUBVIC"},
        {"naptanId": "940GZZLUSJP", "commonName": "St. James's Park Underground Station", "lat": 51.4994,
         "lon": -0.1335, "distance": 299, "modes": ["tube"], "lines": [{"id": "district", "name": "District"}]},
    ]}, "station")
    assert [n.name for n in out] == ["St. James's Park", "Victoria"]  # nearest first, names cleaned
    assert out[1].hub == "HUBVIC" and out[0].walk_min == 5.2


def _pref(stop_id, provider, near):
    n = next(x for x in provider.nearby_stops(*near) if x.stop_id == stop_id)
    return {k: getattr(n, k) for k in ("stop_id", "name", "kind", "lat", "lon", "walk_min", "hub", "modes", "lines")}


def test_routes_follow_chosen_home_station(session):
    p = SimProvider("normal")
    c = make_commute(session)
    # Home station of choice: the Weaver line at St James Street, not the usual Victoria line at Walthamstow
    c.origin.preferred_stops = [_pref("st-james-street", p, HOME)]
    session.commit()
    journeys, honoured = apply_chosen_stops(p, c, MORNING, p.journeys(HOME, WORK, MORNING))
    assert honoured and journeys
    assert all(j.transit_legs[0].from_name == "St James Street" for j in journeys)
    assert journeys[0].legs[0].mode == "walking" and journeys[0].legs[0].from_name == "Home"


def test_no_choice_keeps_everything(session):
    p = SimProvider("normal")
    c = make_commute(session)
    js = p.journeys(HOME, WORK, MORNING)
    assert apply_chosen_stops(p, c, MORNING, js) == (js, True)


def test_evaluation_reports_when_choice_cannot_be_honoured(session):
    p = SimProvider("normal")
    c = make_commute(session)
    c.origin.preferred_stops = [{"stop_id": "nowhere", "name": "Nowhere", "kind": "station",
                                 "lat": 10.0, "lon": 10.0, "walk_min": 5}]
    session.commit()
    clear_status_cache()
    ev = evaluate_commute(session, p, c, MORNING, depart_at=MORNING)
    assert not ev.chosen_stops_honoured and ev.options  # falls back to all routes, and says so


def test_hub_and_name_matching():
    from paxen.domain import Journey, Leg
    leg = Leg("tube", 10, "Victoria", "Oxford Circus", MORNING, MORNING, line_id="victoria", from_stop_id="940GZZLUVIC")
    j = Journey([leg], 10, MORNING, MORNING)
    assert uses_chosen_stops(j, [{"stop_id": "910GVICTRIC", "name": "London Victoria", "hub": "HUBVIC"}], [])
    assert not uses_chosen_stops(j, [{"stop_id": "940GZZLUSJP", "name": "St. James's Park"}], [])


def test_interchange_listed_once():
    out = parse_nearby({"stopPoints": [
        {"naptanId": "940GZZLUWWL", "commonName": "Walthamstow Central Underground Station", "lat": 51.583,
         "lon": -0.0197, "distance": 710, "modes": ["tube"], "lines": [{"name": "Victoria"}], "hubNaptanCode": "HUBWHC"},
        {"naptanId": "910GWLTWCEN", "commonName": "Walthamstow Central Rail Station", "lat": 51.583, "lon": -0.0197,
         "distance": 720, "modes": ["overground"], "lines": [{"name": "Weaver"}], "hubNaptanCode": "HUBWHC"},
    ]}, "station")
    assert len(out) == 1 and out[0].lines == ["Victoria", "Weaver"] and out[0].modes == ["overground", "tube"]
