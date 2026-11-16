from paxen.domain import GOOD, MINOR, SEVERE, SUSPENDED
from paxen.providers.tfl import parse_arrivals, parse_journeys, parse_mode_arrivals, parse_statuses

ARRIVALS = [
    {"id": "-1", "vehicleId": "241", "naptanId": "940GZZLUWWL", "stationName": "Walthamstow Central Underground Station",
     "lineId": "victoria", "lineName": "Victoria", "platformName": "Southbound - Platform 3",
     "direction": "outbound", "destinationName": "Brixton Underground Station",
     "timestamp": "2026-11-03T08:05:00.1234567Z", "timeToStation": 240,
     "expectedArrival": "2026-11-03T08:09:00Z", "modeName": "tube"},
    {"id": "-2", "vehicleId": "242", "naptanId": "940GZZLUWWL", "stationName": "Walthamstow Central",
     "lineId": "victoria", "lineName": "Victoria", "destinationName": "Brixton Underground Station",
     "timestamp": "2026-11-03T08:05:00Z", "timeToStation": 60, "expectedArrival": "2026-11-03T08:06:00Z",
     "modeName": "tube"},
]

STATUS = [
    {"id": "victoria", "name": "Victoria", "modeName": "tube",
     "lineStatuses": [{"statusSeverity": 9, "statusSeverityDescription": "Minor Delays", "reason": "Signal failure"},
                      {"statusSeverity": 6, "statusSeverityDescription": "Severe Delays", "reason": "Faulty train"}]},
    {"id": "central", "name": "Central", "modeName": "tube",
     "lineStatuses": [{"statusSeverity": 10, "statusSeverityDescription": "Good Service"}]},
    {"id": "weaver", "name": "Weaver", "modeName": "overground",
     "lineStatuses": [{"statusSeverity": 20, "statusSeverityDescription": "Service Closed"}]},
    {"id": "jubilee", "name": "Jubilee", "modeName": "tube",
     "lineStatuses": [{"statusSeverity": 9, "statusSeverityDescription": "Minor Delays"}]},
]

JOURNEYS = {"journeys": [{
    "startDateTime": "2026-11-03T08:05:00", "arrivalDateTime": "2026-11-03T08:38:00", "duration": 33,
    "legs": [
        {"duration": 9, "departureTime": "2026-11-03T08:05:00", "arrivalTime": "2026-11-03T08:14:00",
         "mode": {"id": "walking"}, "departurePoint": {"commonName": "Orford Road"},
         "arrivalPoint": {"commonName": "Walthamstow Central", "naptanId": "940GZZLUWWL"}},
        {"duration": 22, "departureTime": "2026-11-03T08:15:00", "arrivalTime": "2026-11-03T08:37:00",
         "mode": {"id": "tube"},
         "routeOptions": [{"name": "Victoria", "directions": ["Brixton Underground Station"],
                           "lineIdentifier": {"id": "victoria", "name": "Victoria"}}],
         "departurePoint": {"commonName": "Walthamstow Central", "naptanId": "940GZZLUWWL"},
         "arrivalPoint": {"commonName": "Oxford Circus", "naptanId": "940GZZLUOXC"},
         "path": {"stopPoints": [{}, {}, {}, {}, {}, {}, {}, {}, {}]}},
        {"duration": 2, "departureTime": "2026-11-03T08:37:00", "arrivalTime": "2026-11-03T08:38:00",
         "mode": {"id": "walking"}, "departurePoint": {"commonName": "Oxford Circus"},
         "arrivalPoint": {"commonName": "Regent Street"}},
    ]}]}


def test_parse_arrivals_sorted_and_tolerates_7_digit_fractions():
    a = parse_arrivals(ARRIVALS, "940GZZLUWWL")
    assert [x.vehicle_id for x in a] == ["242", "241"]
    assert a[1].feed_timestamp.microsecond == 123456
    assert a[0].direction == "Brixton"  # TfL suffixes stripped for display


def test_parse_statuses_uses_worst_status():
    s = {x.line_id: x for x in parse_statuses(STATUS)}
    assert s["victoria"].category == SEVERE and s["victoria"].reason == "Faulty train"
    assert s["central"].category == GOOD
    assert s["weaver"].category == SUSPENDED
    assert s["jubilee"].category == MINOR


def test_parse_journeys():
    [j] = parse_journeys(JOURNEYS)
    assert j.summary == "Victoria"
    assert j.walking_min == 11 and j.changes == 0
    assert j.signature == "tube:victoria@940GZZLUWWL"
    assert j.legs[1].direction == "Brixton" and j.legs[1].stops == 9
    assert j.departure.utcoffset().total_seconds() == 0  # London local in November == UTC


TERMINUS = [  # Walthamstow Central: TfL lists each incoming train once per possible platform
    {"vehicleId": "236", "naptanId": "940GZZLUWWL", "lineId": "victoria", "lineName": "Victoria",
     "platformName": "Southbound - Platform 1", "destinationNaptanId": "940GZZLUWWL",
     "destinationName": "Walthamstow Central Underground Station", "timeToStation": 70,
     "expectedArrival": "2026-11-03T08:06:10Z", "timestamp": "2026-11-03T08:05:00Z", "modeName": "tube"},
    {"vehicleId": "236", "naptanId": "940GZZLUWWL", "lineId": "victoria", "lineName": "Victoria",
     "platformName": "Southbound - Platform 2", "destinationNaptanId": "940GZZLUWWL",
     "destinationName": "Walthamstow Central Underground Station", "timeToStation": 129,
     "expectedArrival": "2026-11-03T08:07:09Z", "timestamp": "2026-11-03T08:05:00Z", "modeName": "tube"},
]


def test_terminus_duplicates_collapse_and_are_flagged():
    [a] = parse_arrivals(TERMINUS, "940GZZLUWWL")
    assert a.time_to_station_s == 70 and a.terminates_here


def _leg(line, frm, to, direction=None):
    from datetime import datetime, timezone

    from paxen.domain import Leg

    t = datetime(2026, 11, 3, 8, 5, tzinfo=timezone.utc)
    return Leg("tube", 10.0, "A", "B", t, t, line_id=line, line_name=line, from_stop_id=frm, to_stop_id=to,
               direction=direction, stop_ids=[frm, to])


def test_terminating_train_counts_as_next_departure():
    from paxen.engine import goes_your_way

    [a] = parse_arrivals(TERMINUS, "940GZZLUWWL")
    assert goes_your_way(a, _leg("victoria", "940GZZLUWWL", "940GZZLUOXC", "Brixton Underground Station"))
    [b] = parse_arrivals(ARRIVALS[:1], "940GZZLUWWL")
    assert not b.terminates_here


def _row(vehicle, platform, tts, dest_id=None, dest="", stop="940GZZLUFBY", line="district", loc="", **kw):
    return {"vehicleId": vehicle, "naptanId": stop, "lineId": line, "lineName": line.title(), "modeName": "tube",
            "platformName": platform, "timeToStation": tts, "destinationNaptanId": dest_id, "destinationName": dest,
            "currentLocation": loc, "expectedArrival": "2026-11-03T08:10:00Z", "timestamp": "2026-11-03T08:05:00Z",
            **kw}


def test_a_trains_way_out_and_way_back_are_both_kept():
    """Farringdon, 16 Nov 2026: Metropolitan train 450 is due eastbound in 28 s and, after turning round at Aldgate,
    westbound in 19 minutes. They are different calls; the old rule kept only the first."""
    rows = [_row("450", "Eastbound - Platform 1", 28, "940GZZLUALD", "Aldgate Underground Station",
                 stop="940GZZLUFCN", line="metropolitan"),
            _row("450", "Westbound - Platform 2", 1139, None, "", stop="940GZZLUFCN", line="metropolitan")]
    out = parse_arrivals(rows, "940GZZLUFCN")
    assert [(a.platform, a.time_to_station_s, a.destination_id) for a in out] == [
        ("Eastbound - Platform 1", 28, "940GZZLUALD"), ("Westbound - Platform 2", 1139, None)]


def test_alternative_platforms_in_one_direction_are_one_train():
    rows = [_row("402", "Southbound Fast - Platform 6", 57, "940GZZLUALD", stop="940GZZLUHOH", line="metropolitan"),
            _row("402", "Southbound - Platform 5", 87, "940GZZLUALD", stop="940GZZLUHOH", line="metropolitan")]
    [a] = parse_arrivals(rows, "940GZZLUHOH")
    assert a.time_to_station_s == 57


def test_unidentified_trains_sharing_an_id_stay_separate():
    """Uxbridge: three different trains with the placeholder id 000, each listed on three platforms."""
    ux = "940GZZLUUXB"
    rows = [_row("000", f"Eastbound - Platform {p}", t, ux, "Uxbridge Underground Station", stop=ux,
                 line="metropolitan") for t in (489, 729, 849) for p in (1, 2, 4)]
    rows += [_row("000", "Westbound - Platform 1", t, ux, "Uxbridge", stop="940GZZLUICK", line="metropolitan")
             for t in (189, 369, 549)]  # Ickenham: three trains towards Uxbridge
    rows += [_row("000", "Eastbound - Platform 2", 190, None, "", stop="940GZZLUICK", line="metropolitan")]
    out = parse_mode_arrivals(rows)
    assert sorted(a.time_to_station_s for a in out if a.stop_id == ux) == [489, 729, 849]
    assert all(a.terminates_here for a in out if a.stop_id == ux)
    ick = sorted((a.time_to_station_s, a.platform) for a in out if a.stop_id == "940GZZLUICK")
    assert ick == [(189, "Westbound - Platform 1"), (190, "Eastbound - Platform 2"),
                   (369, "Westbound - Platform 1"), (549, "Westbound - Platform 1")]


def test_a_train_at_the_platform_is_flagged():
    here, coming = parse_arrivals([_row("101", "Eastbound - Platform 2", 12, "940GZZLUUPM", loc="At Platform"),
                                   _row("102", "Eastbound - Platform 2", 180, "940GZZLUUPM",
                                        loc="At Parsons Green Platform 1")], "940GZZLUFBY")
    assert here.at_platform and not coming.at_platform


def test_trains_are_matched_by_where_they_go_not_by_one_destination_name():
    """Fulham Broadway to Victoria. TfL's planner says "Upminster" (the train it happened to pick), but Barking and
    Tower Hill trains call at Victoria too; Edgware Road trains leave the same platform and don't."""
    from paxen.engine import goes_your_way, same_track

    leg = _leg("district", "940GZZLUFBY", "940GZZLUVIC", "Upminster")

    def train(dest_id, dest, platform="Eastbound - Platform 2", **kw):
        [a] = parse_arrivals([_row("070", platform, 200, dest_id, dest, **kw)], "940GZZLUFBY")
        return a

    assert goes_your_way(train("940GZZLUUPM", "Upminster Underground Station"), leg)
    assert goes_your_way(train("940GZZLUBKG", "Barking Underground Station"), leg)
    assert goes_your_way(train("940GZZLUTWH", "Tower Hill Underground Station"), leg)
    edgware = train("940GZZLUERC", "Edgware Road (Circle Line) Underground Station")
    assert not goes_your_way(edgware, leg) and same_track(edgware, leg)  # not yours, but ahead of yours
    wimbledon = train("940GZZLUWIM", "Wimbledon Underground Station", "Westbound - Platform 1")
    assert not goes_your_way(wimbledon, leg) and not same_track(wimbledon, leg)
    assert not goes_your_way(train("940GZZLUSSQ", "Sloane Square Underground Station"), leg)  # stops short
    # no destination given (a train's return trip): not claimed where the line branches before your stop...
    assert not goes_your_way(train(None, ""), leg)
    # ...but fine where every eastbound train passes your stop, and never from the wrong platform
    to_earls_court = _leg("district", "940GZZLUFBY", "940GZZLUECT", "Upminster")
    assert goes_your_way(train(None, ""), to_earls_court) and goes_your_way(edgware, to_earls_court)
    assert not goes_your_way(train(None, "", "Westbound - Platform 1"), to_earls_court)


def test_a_train_terminating_mid_line_is_not_your_next_departure():
    from paxen.engine import goes_your_way

    [a] = parse_arrivals([_row("055", "Eastbound - Platform 2", 90, "940GZZLUTWH", "Tower Hill Underground Station",
                               stop="940GZZLUTWH")], "940GZZLUTWH")
    assert a.terminates_here
    assert not goes_your_way(a, _leg("district", "940GZZLUTWH", "940GZZLUUPM", "Upminster"))


def test_off_the_map_falls_back_to_names():
    from paxen.domain import Arrival
    from paxen.engine import goes_your_way

    def bus(dest):
        t = _leg("25", "490A", "490B").departure
        return Arrival("LX1", "490A", "Stop A", "25", "25", "bus", dest, dest, t, 120, t)

    leg = _leg("25", "490A", "490B", "City Thameslink")
    leg.mode = "bus"
    assert goes_your_way(bus("City Thameslink"), leg) and not goes_your_way(bus("Ilford"), leg)
    assert not goes_your_way(bus(""), leg)  # an empty destination used to match everything


def test_wait_when_only_other_trains_are_showing():
    from paxen.engine import wait_behind

    assert wait_behind(8.0, 0) == 4.0  # nothing on your track: the usual half a headway
    assert wait_behind(8.0, 3.0) == 5.5  # yours is behind a train 3 minutes away
    assert wait_behind(8.0, 11.0) == 15.0  # a whole headway has gone by without one of yours


def test_journeys_deduplicated_by_route():
    from copy import deepcopy
    from paxen.providers.tfl import dedupe_journeys
    slower = deepcopy(JOURNEYS)
    slower["journeys"][0]["duration"] = 40
    out = dedupe_journeys(parse_journeys(JOURNEYS) + parse_journeys(slower) + parse_journeys(JOURNEYS))
    assert len(out) == 1 and out[0].duration_min == 33


def test_place_search_dedupes_station_names():
    from paxen.providers.tfl import parse_place_search
    res = parse_place_search({"matches": [
        {"name": "Walthamstow Central Underground Station", "lat": 51.58, "lon": -0.02, "id": "940GZZLUWWL",
         "modes": ["tube"]},
        {"name": "Walthamstow Central Station", "lat": 51.58, "lon": -0.02, "id": "910GWLTWCEN"},
        {"name": "Walthamstow Queens Road Rail Station", "lat": 51.58, "lon": -0.02, "id": "910GWLTHQRD"},
    ]})
    assert [r.name for r in res] == ["Walthamstow Central", "Walthamstow Queens Road"]


SECTION_STATUS = [{
    "id": "elizabeth", "name": "Elizabeth line", "modeName": "elizabeth-line",
    "lineStatuses": [{"statusSeverity": 6, "statusSeverityDescription": "Severe Delays",
                      "reason": "Severe delays between Paddington and Heathrow.",
                      "disruption": {"affectedStops": [{"naptanId": "910GACTONML"}, {"naptanId": "910GEALINGB"}]}}],
}]


def test_section_disruption_only_hits_legs_that_call_there():
    [st] = parse_statuses(SECTION_STATUS)
    assert st.category == SEVERE  # the line, as a whole, has severe delays
    assert st.category_for(["910GLIVST", "910GFRNDXR", "910GTOTCTRD"]) == GOOD  # central section unaffected
    assert st.category_for(["910GPADTON", "910GACTONML", "910GEALINGB"]) == SEVERE
    assert st.category_for([]) == SEVERE  # leg without stop detail: stay conservative


def test_journey_legs_carry_stop_ids():
    from copy import deepcopy
    data = deepcopy(JOURNEYS)
    data["journeys"][0]["legs"][1]["path"]["stopPoints"] = [{"id": "940GZZLUBLR"}, {"id": "940GZZLUOXC"}]
    leg = parse_journeys(data)[0].legs[1]
    assert leg.stop_ids == ["940GZZLUWWL", "940GZZLUBLR", "940GZZLUOXC"]


def test_invalid_key_falls_back_to_anonymous():
    import httpx
    from paxen.providers.tfl import TflProvider

    seen = []

    def handler(req: httpx.Request):
        seen.append("app_key" in req.url.params)
        if "app_key" in req.url.params:
            return httpx.Response(429, text="Invalid app_key is provided.")
        return httpx.Response(200, json=STATUS)

    p = TflProvider("https://api.tfl.gov.uk", "your-500-requests-primary-key")
    p.client = httpx.Client(transport=httpx.MockTransport(handler))
    from datetime import datetime, timezone
    res = p.line_statuses(datetime.now(timezone.utc))
    assert len(res.items) == 4 and seen == [True, False] and p.app_key is None


def test_crowding_profile_relative_to_station_peak():
    from datetime import datetime
    from paxen.providers.tfl import crowding_at, parse_crowding_profile
    from paxen.timeutil import LONDON
    prof = parse_crowding_profile({"isFound": True, "timeBands": [
        {"timeBand": "08:15-08:30", "percentageOfBaseLine": 0.46},
        {"timeBand": "08:30-08:45", "percentageOfBaseLine": 0.49},
        {"timeBand": "13:30-13:45", "percentageOfBaseLine": 0.10}]})
    at = crowding_at(prof, datetime(2026, 11, 3, 8, 20, tzinfo=LONDON))
    assert at["band"] == "08:15" and at["ratio"] == 0.94 and at["day"] == "Tue"
    assert parse_crowding_profile({"isFound": False, "timeBands": []}) is None


def test_network_endpoint_without_time_to_station():
    from paxen.providers.tfl import parse_mode_arrivals
    rows = [{"naptanId": "910GACTONML", "lineId": "elizabeth", "vehicleId": "2026110367", "timeToStation": None,
             "timestamp": "2026-11-03T14:16:17.343Z", "expectedArrival": "2026-11-03T14:24:17Z",
             "destinationName": "Heathrow Terminal 4 Rail Station"}]
    [a] = parse_mode_arrivals(rows)
    assert a.time_to_station_s == 480 and a.stop_id == "910GACTONML" and a.direction == "Heathrow Terminal 4"


def test_upstream_errors_never_carry_the_key():
    import httpx
    import pytest
    from paxen.providers.tfl import TflProvider
    from paxen.redact import redact

    p = TflProvider("https://api.tfl.gov.uk", "SECRETKEY123")
    p.client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(503, text="busy")))
    with pytest.raises(httpx.HTTPError) as exc:
        p.arrivals("940GZZLUVIC", None, max_age_s=0)
    assert "SECRETKEY123" not in str(exc.value) and "503" in str(exc.value)
    assert redact("for url 'https://x/y?app_key=SECRETKEY123&z=1'") == "for url 'https://x/y?app_key=***&z=1'"


def test_time_bucketed_caches_stay_bounded():
    import time
    from paxen.cache import prune
    c = {i: (time.monotonic() - (1000 if i < 900 else 0), i) for i in range(1200)}
    prune(c, max_age_s=120, max_entries=500)
    assert len(c) <= 500 and all(k >= 900 for k in c)  # expired entries go first
