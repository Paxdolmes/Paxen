from paxen.domain import GOOD, MINOR, SEVERE, SUSPENDED
from paxen.providers.tfl import parse_arrivals, parse_journeys, parse_statuses

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
    assert a[0].direction == "Brixton Underground Station"


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
    assert j.legs[1].direction == "Brixton Underground Station" and j.legs[1].stops == 9
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


def test_terminating_train_counts_as_next_departure():
    from datetime import datetime, timezone
    from paxen.engine import _matches_direction
    [a] = parse_arrivals(TERMINUS, "940GZZLUWWL")
    assert _matches_direction(a, "Brixton Underground Station")
    [b] = parse_arrivals(ARRIVALS[:1], "940GZZLUWWL")
    assert not b.terminates_here


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
