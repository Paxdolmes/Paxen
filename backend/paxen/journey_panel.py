"""The journey panel: a fixed set of real Tube commutes whose actual door-to-door times are replayed from measured
train movements every day (paxen/replay.py). Fixed, so days can be compared and the evaluation can't be steered.

Built once with TfL's journey planner (Tube only, station to station, 08:30 on a weekday, the quickest route) and
saved to data/journey_panel.json:

    python -m paxen.journey_panel tube_stops.json      # the JSON of TfL's /StopPoint/Mode/tube

Each journey is a list of legs: {"line_id", "from", "to", "stop_ids", "minutes"} for a train, {"walk": minutes}
for walking between platforms at a change. Only lines Trackernet measures are used.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PANEL_FILE = Path(__file__).parent / "data" / "journey_panel.json"

# Home stations across every measured line, inner and outer; work stations where most commutes end.
HOMES = [
    "Brixton", "Walthamstow Central", "Tottenham Hale", "Seven Sisters", "Highbury & Islington", "Fulham Broadway",
    "Wimbledon", "Upminster", "Barking", "East Ham", "Mile End", "Ealing Broadway", "Stratford", "Leytonstone",
    "Woodford", "Morden", "Tooting Bec", "Balham", "Clapham Common", "Edgware", "High Barnet", "Finchley Central",
    "Kentish Town", "Stanmore", "Kilburn", "Canada Water", "Harrow-on-the-Hill", "Wembley Park", "Finchley Road",
    "Uxbridge", "Arnos Grove", "Finsbury Park", "Hammersmith (Dist&Picc Line)", "Acton Town", "Hounslow Central",
    "Queen's Park", "Elephant & Castle", "Harrow & Wealdstone", "Shepherd's Bush Market", "Richmond",
]
WORKS = ["Bank", "Oxford Circus", "King's Cross St. Pancras", "Canary Wharf", "Liverpool Street", "Victoria",
         "Waterloo", "London Bridge", "Holborn", "Green Park"]


def station_ids(stops_json: dict) -> dict[str, str]:
    from .trackernet import norm_name

    out = {}
    for sp in stops_json.get("stopPoints", []):
        if sp.get("stopType") == "NaptanMetroStation" and sp.get("naptanId", "").startswith("940GZZLU"):
            out[norm_name(sp["commonName"].replace(" Underground Station", ""))] = sp["naptanId"]
    return out


def plan(from_id: str, to_id: str, client) -> list[dict] | None:
    from .providers.tfl import parse_journeys
    from .trackernet import LINE_CODES

    measured = {l for ls in LINE_CODES.values() for l in ls}
    r = client.get(f"https://api.tfl.gov.uk/Journey/JourneyResults/{from_id}/to/{to_id}",
                   params={"mode": "tube", "date": "20261118", "time": "0830", "timeIs": "Departing",
                           "journeyPreference": "LeastTime"})
    if r.status_code != 200:
        return None
    best = None
    for j in parse_journeys(r.json()):
        rides = [l for l in j.legs if l.is_transit]
        if not rides or any(l.line_id not in measured or not l.from_stop_id or not l.to_stop_id for l in rides):
            continue
        if best is None or j.duration_min < best.duration_min:
            best = j
    if best is None:
        return None
    legs: list[dict] = []
    seen_ride = False
    for l in best.legs:
        if l.is_transit:
            legs.append({"line_id": l.line_id, "from": l.from_stop_id, "to": l.to_stop_id,
                         "stop_ids": l.stop_ids, "minutes": l.duration_min})
            seen_ride = True
        elif seen_ride and l.duration_min:  # walking at a change (not before the first train or after the last)
            legs.append({"walk": l.duration_min})
    while legs and "walk" in legs[-1]:
        legs.pop()
    return legs


def build(stops_path: str) -> list[dict]:
    import httpx

    from .trackernet import norm_name

    ids = station_ids(json.loads(Path(stops_path).read_text()))
    panel = []
    with httpx.Client(timeout=30, headers={"User-Agent": "paxen-commute/0.1"}) as client:
        for home in HOMES:
            for work in WORKS:
                a, b = ids.get(norm_name(home)), ids.get(norm_name(work))
                if not a or not b:
                    print("unknown station:", home if not a else work, file=sys.stderr)
                    continue
                legs = None
                for attempt in range(3):
                    try:
                        legs = plan(a, b, client)
                        break
                    except Exception:
                        time.sleep(5)
                time.sleep(1.2)  # TfL's limit for callers without a key
                if legs:
                    panel.append({"id": f"{a}>{b}", "from_name": home, "to_name": work, "legs": legs})
    return panel


if __name__ == "__main__":
    panel = build(sys.argv[1])
    PANEL_FILE.write_text(json.dumps(panel, indent=1))
    print(len(panel), "journeys")
