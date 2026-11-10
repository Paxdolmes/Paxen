"""How full the next trains are likely to be when they reach your station.

Nothing measures how many people are on a London train in real time, so this is an estimate from three things
that are known:

1. TfL's NUMBAT model: the typical number of passengers on board as trains pull out of this station, for this
   direction, day type and quarter hour (paxen.numbat, `depart_load_per_train`).
2. The gap ahead of each train, live. Passengers build up on platforms between trains, so a train running after a
   long gap carries more of them than the typical train and the one close behind it carries fewer. The gap comes
   from the live arrivals (the train ahead is in the same countdown), or, for the next train, from when the train
   ahead was last seen at this platform (Trackernet for the Tube, Darwin for the Overground and Elizabeth line).
3. How busy this station and the two before it are right now compared with usual (TfL's live, Wi-Fi based station
   crowding), damped: a busy station is a hint, not a count of the people on board.

The product is compared with the train's approximate capacity (seats plus standing at about four people per square
metre) to give a level: "Likely packed", "Standing room" or "Space likely". It is labelled an estimate everywhere.
Users can say whether they got on the first train (BoardingReport), which is how the thresholds get calibrated.

This module has no effect on journey times, the prediction model or its training data.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from . import numbat
from .timeutil import aware, local, naive_utc

# Seats plus standing at roughly 4 people per square metre, per train, by line (TfL and rolling stock figures;
# approximate, and trains on a line are not all the same length). Lines missing here get no estimate.
CAPACITY = {
    "bakerloo": 700, "central": 930, "circle": 865, "district": 865, "hammersmith-city": 865, "jubilee": 770,
    "metropolitan": 1003, "northern": 662, "piccadilly": 684, "victoria": 950, "waterloo-city": 444,
    "elizabeth": 1500, "dlr": 300, "tram": 200,
    # London Overground: Class 710s (4 cars) on most lines, Class 378s (5 cars) on Mildmay and Windrush
    "liberty": 680, "lioness": 680, "suffragette": 680, "weaver": 680, "mildmay": 880, "windrush": 880,
}

PACKED, STANDING, SPACE = "packed", "standing", "space"
LABELS = {PACKED: "Likely packed", STANDING: "Standing room", SPACE: "Space likely"}
TYPICAL_LABELS = {PACKED: "Usually packed", STANDING: "Usually standing room", SPACE: "Usually has space"}
RANK = {SPACE: 0, STANDING: 1, PACKED: 2}
PACKED_AT = 0.9  # share of capacity; at about this many people, getting on at a busy door is hard
STANDING_AT = 0.6  # the seats are long gone and people stand in the doorways and aisles
LEFT_BEHIND_AT = 1.05  # more people than fit: some on the platform wait for the next one

GAP_WEIGHT = 0.85  # some passengers time their arrival to a train, so load grows a little slower than the gap
GAP_FACTOR = (0.5, 2.0)
LIVE_WEIGHT = 0.5
LIVE_FACTOR = (0.75, 1.4)
UPSTREAM_STATIONS = 2
SAME_TRAIN_S = 45  # a train seen at the platform this close to a countdown's time is that train
FEED_STALE = timedelta(minutes=6)  # no sighting at this stop for this long: the gap ahead can't be trusted
ADVICE_MAX_WAIT_MIN = 6.0  # only suggest waiting for a train this soon after the packed one
ADVICE_MIN_DROP = 0.15  # and only when it is clearly emptier

BASIS = ("Estimate from TfL's typical loads for this time and direction, the live gap between trains and how busy "
         "stations are right now. Not a count of passengers.")


def gap_factor(gap_s: float | None, headway_s: float | None) -> float:
    if not gap_s or not headway_s or gap_s <= 0 or headway_s <= 0:
        return 1.0
    return max(GAP_FACTOR[0], min(GAP_FACTOR[1], 1 + GAP_WEIGHT * (gap_s / headway_s - 1)))


def live_factor(live_vs_typical: float | None) -> float:
    if live_vs_typical is None:
        return 1.0
    return max(LIVE_FACTOR[0], min(LIVE_FACTOR[1], 1 + LIVE_WEIGHT * (live_vs_typical - 1)))


def level_of(share: float) -> str:
    return PACKED if share >= PACKED_AT else STANDING if share >= STANDING_AT else SPACE


def train_fullness(line_id: str | None, stop_id: str | None, bound: str | None, when: datetime,
                   gap_s: float | None = None, live_vs_typical: float | None = None) -> dict | None:
    """Estimated fullness of a train leaving stop_id at `when`. None where there is no basis for one."""
    cap = CAPACITY.get(line_id or "")
    if not cap:
        return None
    c = numbat.stop_context(line_id, stop_id, bound, when)
    if not c:
        return None
    load = c.get("depart_load_per_train") or c.get("load_per_train")
    if not load:
        return None
    headway = c.get("sched_headway_s")
    share = load * gap_factor(gap_s, headway) * live_factor(live_vs_typical) / cap
    level = level_of(share)
    label = LABELS[level]
    if share >= LEFT_BEHIND_AT:
        label = "Likely packed, may not fit"
    return {"level": level, "label": label, "share": round(share, 2), "typical_share": round(load / cap, 2),
            "gap_min": round(gap_s / 60, 1) if gap_s else None,
            "headway_min": round(headway / 60, 1) if headway else None, "directional": bool(c.get("directional"))}


def live_busyness(provider, line_id: str | None, stop_id: str | None, bound: str | None,
                  when: datetime) -> float | None:
    """Average of TfL's live-vs-usual busyness at this station and the ones a train calls at before it."""
    lookup = getattr(provider, "station_crowding", None)
    nb = numbat.get()
    if not lookup or not stop_id:
        return None
    stops = [stop_id] + (nb.upstream(line_id, stop_id, bound, when, UPSTREAM_STATIONS) if nb else [])
    ratios = []
    for sid in stops:
        try:
            c = lookup(sid, when, live=True)
        except Exception:
            c = None
        if c and c.get("live_vs_typical") is not None:
            ratios.append(c["live_vs_typical"])
    return round(sum(ratios) / len(ratios), 2) if ratios else None


def last_seen_lookup(s, source: str, now: datetime) -> Callable[[str, str, set[str], datetime], datetime | None]:
    """When the train ahead was last at a platform, from real-time sightings (Trackernet, Darwin).

    Returns lookup(stop_id, line_id, directions, before): the latest sighting before `before` (and not the train
    that is due then), or None when there's nothing recent enough to trust."""
    from sqlalchemy import select

    from .db import ObservedArrival

    cache: dict[tuple[str, str], list[tuple[datetime, str | None]]] = {}

    def lookup(stop_id: str, line_id: str, directions: set[str], before: datetime) -> datetime | None:
        key = (stop_id, line_id)
        if key not in cache:
            try:
                rows = s.execute(select(ObservedArrival.arrived_at, ObservedArrival.direction).where(
                    ObservedArrival.source == source, ObservedArrival.stop_id == stop_id,
                    ObservedArrival.line_id == line_id, ObservedArrival.method.in_(("trackernet", "darwin")),
                    ObservedArrival.arrived_at >= naive_utc(now - timedelta(minutes=45)))).all()
            except Exception:
                rows = []
            cache[key] = [(aware(t), d) for t, d in rows]
        rows = cache[key]
        if not rows or max(t for t, _ in rows) < now - FEED_STALE:
            return None  # the feed isn't reporting this stop just now
        times = [t for t, d in rows if d in directions and t < before - timedelta(seconds=SAME_TRAIN_S)]
        return max(times) if times else None

    return lookup


def hhmm(when: datetime) -> str:
    return local(when).strftime("%H:%M")


def advice(trains: list[dict], catch: int) -> str | None:
    """Wait for the next train when the one you'd catch is likely packed and one shortly behind it isn't."""
    if not trains or catch >= len(trains):
        return None
    t0 = trains[catch]
    f0 = t0.get("fullness")
    if not f0 or f0["level"] != PACKED:
        return None
    for t in trains[catch + 1:]:
        f = t.get("fullness")
        later = t["in_min"] - t0["in_min"]
        if later > ADVICE_MAX_WAIT_MIN:
            break
        if f and RANK[f["level"]] < RANK[PACKED] and f["share"] <= f0["share"] - ADVICE_MIN_DROP:
            why = ""
            if f0.get("gap_min") and f0.get("headway_min") and f0["gap_min"] >= 1.3 * f0["headway_min"]:
                why = f" ({round(f0['gap_min'])}-minute gap ahead of it)"
            room = "should have space" if f["level"] == SPACE else "should have more room"
            mins = max(1, round(later))
            return (f"The {t0['at_local']} is likely packed{why}. The {t['at_local']} {room}, and you'd arrive about "
                    f"{mins} minute{'s' if mins != 1 else ''} later.")
    return None


def summary(line_name: str | None, stop: str, trains: list[dict], catch: int, typical: dict | None) -> dict | None:
    """What the app shows for the train you'd board: the one you'd catch, the ones behind it and any advice."""
    if trains and catch < len(trains) and trains[catch].get("fullness"):
        f = trains[catch]["fullness"]
        return {"line_name": line_name, "stop": stop, "live": True, "level": f["level"], "label": f["label"],
                "train_at": trains[catch]["at"], "trains": trains, "catch_index": catch,
                "advice": advice(trains, catch), "basis": BASIS}
    if typical:
        return {"line_name": line_name, "stop": stop, "live": False, "level": typical["level"],
                "label": TYPICAL_LABELS[typical["level"]], "train_at": None,
                "trains": [], "catch_index": None, "advice": None,
                "basis": "Typical for this time and direction, from TfL's loads model. Live estimates start about "
                         "20 minutes before you leave."}
    return None


def calibration(s) -> dict:
    """For /v1/health: per estimated level, how many said they got on the first train. If "Likely packed" trains
    are mostly boarded, the thresholds are too low (and the other way round)."""
    from sqlalchemy import func, select

    from .db import BoardingReport

    rows = s.execute(select(BoardingReport.level, BoardingReport.got_on, func.count())
                     .group_by(BoardingReport.level, BoardingReport.got_on)).all()
    out: dict[str, dict[str, int]] = {}
    for level, got_on, n in rows:
        d = out.setdefault(level or "none", {"reports": 0, "got_on": 0})
        d["reports"] += n
        d["got_on"] += n if got_on else 0
    return out
