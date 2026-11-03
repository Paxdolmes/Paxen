"""A deterministic simulated London corridor.

Used for local development, demos and tests when the real TfL feed is not
reachable. It deliberately reproduces the properties the prediction engine
cares about:

* vehicles keep stable ids across polls, so predictions can be matched to
  (inferred) arrivals;
* the "provider" countdown systematically under-estimates waits at longer lead
  times (more so on some lines and under disruption), so a correction model has
  a real bias to learn;
* line status disruptions lengthen headways and add delay.

Everything is a pure function of (scenario, time), so results are reproducible.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..domain import (
    GOOD, MINOR, PART_SUSPENDED, SEVERE, SUSPENDED,
    Arrival, FetchResult, Journey, Leg, LineStatus, PlaceResult,
)
from ..timeutil import local

STATIONS: dict[str, tuple[str, float, float]] = {
    "walthamstow-central": ("Walthamstow Central", 51.5830, -0.0197),
    "blackhorse-road": ("Blackhorse Road", 51.5866, -0.0417),
    "tottenham-hale": ("Tottenham Hale", 51.5882, -0.0594),
    "seven-sisters": ("Seven Sisters", 51.5822, -0.0749),
    "finsbury-park": ("Finsbury Park", 51.5642, -0.1065),
    "highbury-islington": ("Highbury & Islington", 51.5460, -0.1040),
    "kings-cross": ("King's Cross St. Pancras", 51.5308, -0.1238),
    "euston": ("Euston", 51.5282, -0.1337),
    "warren-street": ("Warren Street", 51.5247, -0.1384),
    "oxford-circus": ("Oxford Circus", 51.5152, -0.1418),
    "green-park": ("Green Park", 51.5067, -0.1428),
    "victoria": ("Victoria", 51.4965, -0.1447),
    "vauxhall": ("Vauxhall", 51.4861, -0.1253),
    "brixton": ("Brixton", 51.4627, -0.1145),
    "stratford": ("Stratford", 51.5416, -0.0042),
    "mile-end": ("Mile End", 51.5251, -0.0332),
    "bethnal-green": ("Bethnal Green", 51.5270, -0.0549),
    "liverpool-street": ("Liverpool Street", 51.5178, -0.0823),
    "bank": ("Bank", 51.5133, -0.0886),
    "st-pauls": ("St. Paul's", 51.5146, -0.0973),
    "holborn": ("Holborn", 51.5174, -0.1201),
    "tottenham-court-road": ("Tottenham Court Road", 51.5165, -0.1310),
    "bond-street": ("Bond Street", 51.5142, -0.1494),
    "marble-arch": ("Marble Arch", 51.5136, -0.1586),
    "notting-hill-gate": ("Notting Hill Gate", 51.5094, -0.1967),
    "st-james-street": ("St James Street", 51.5809, -0.0329),
    "clapton": ("Clapton", 51.5615, -0.0571),
    "hackney-downs": ("Hackney Downs", 51.5488, -0.0605),
    "canary-wharf": ("Canary Wharf", 51.5035, -0.0187),
    "canada-water": ("Canada Water", 51.4982, -0.0502),
    "london-bridge": ("London Bridge", 51.5052, -0.0864),
    "waterloo": ("Waterloo", 51.5036, -0.1143),
    "westminster": ("Westminster", 51.5010, -0.1254),
    "baker-street": ("Baker Street", 51.5226, -0.1571),
    "camden-town": ("Camden Town", 51.5392, -0.1426),
    "angel": ("Angel", 51.5322, -0.1058),
    "old-street": ("Old Street", 51.5263, -0.0873),
    "moorgate": ("Moorgate", 51.5186, -0.0886),
    "whitechapel": ("Whitechapel", 51.5195, -0.0597),
    "farringdon": ("Farringdon", 51.5203, -0.1053),
    "paddington": ("Paddington", 51.5154, -0.1755),
    "hackney-wick": ("Hackney Wick", 51.5434, -0.0249),
    "hackney-central": ("Hackney Central", 51.5470, -0.0560),
    "dalston-kingsland": ("Dalston Kingsland", 51.5481, -0.0757),
    "canonbury": ("Canonbury", 51.5487, -0.0921),
    # bus stops
    "bakers-arms": ("Leyton, Baker's Arms", 51.5717, -0.0137),
    "lower-clapton": ("Lower Clapton Road", 51.5560, -0.0540),
    "mare-street": ("Mare Street", 51.5455, -0.0555),
    "shoreditch-church": ("Shoreditch Church", 51.5272, -0.0779),
    "old-street-bus": ("Old Street Roundabout", 51.5258, -0.0880),
    "clerkenwell-road": ("Clerkenwell Road", 51.5222, -0.1020),
    "holborn-bus": ("Holborn Station (Kingsway)", 51.5170, -0.1196),
    "oxford-circus-bus": ("Oxford Circus (Regent Street)", 51.5155, -0.1410),
    "hoe-street": ("Hoe Street", 51.5795, -0.0170),
}


@dataclass(frozen=True)
class SimLine:
    id: str
    name: str
    mode: str
    stops: tuple[str, ...]
    inter_min: float
    headway_min: float
    bias: float  # fraction of lead time the provider countdown under-states


LINES: dict[str, SimLine] = {l.id: l for l in [
    SimLine("victoria", "Victoria", "tube", (
        "walthamstow-central", "blackhorse-road", "tottenham-hale", "seven-sisters", "finsbury-park",
        "highbury-islington", "kings-cross", "euston", "warren-street", "oxford-circus", "green-park",
        "victoria", "vauxhall", "brixton"), 2.2, 2.5, 0.10),
    SimLine("central", "Central", "tube", (
        "stratford", "mile-end", "bethnal-green", "liverpool-street", "bank", "st-pauls", "holborn",
        "tottenham-court-road", "oxford-circus", "bond-street", "marble-arch", "notting-hill-gate"), 2.0, 3.0, 0.06),
    SimLine("weaver", "Weaver line", "overground", (
        "walthamstow-central", "st-james-street", "clapton", "hackney-downs", "liverpool-street"), 3.2, 10.0, 0.04),
    SimLine("mildmay", "Mildmay line", "overground", (
        "stratford", "hackney-wick", "hackney-central", "dalston-kingsland", "canonbury", "highbury-islington"),
        2.6, 7.5, 0.05),
    SimLine("jubilee", "Jubilee", "tube", (
        "stratford", "canary-wharf", "canada-water", "london-bridge", "waterloo", "westminster", "green-park",
        "bond-street", "baker-street"), 2.4, 3.0, 0.05),
    SimLine("northern", "Northern", "tube", (
        "camden-town", "euston", "kings-cross", "angel", "old-street", "moorgate", "bank", "london-bridge"),
        2.0, 3.5, 0.07),
    SimLine("elizabeth", "Elizabeth line", "elizabeth-line", (
        "stratford", "whitechapel", "liverpool-street", "farringdon", "tottenham-court-road", "bond-street",
        "paddington"), 2.8, 5.0, 0.04),
    SimLine("greater-anglia", "Greater Anglia", "national-rail", ("stratford", "liverpool-street"), 7.0, 10.0, 0.05),
    SimLine("w15", "W15", "bus", ("hoe-street", "bakers-arms"), 6.0, 10.0, 0.16),
    SimLine("55", "55", "bus", (
        "bakers-arms", "lower-clapton", "mare-street", "shoreditch-church", "old-street-bus",
        "clerkenwell-road", "holborn-bus", "oxford-circus-bus"), 6.5, 8.0, 0.18),
]}

# Bus stops that are a short walk from rail stations (walk minutes).
TRANSFERS = {
    ("hoe-street", "walthamstow-central"): 3, ("old-street-bus", "old-street"): 2,
    ("holborn-bus", "holborn"): 2, ("oxford-circus-bus", "oxford-circus"): 2,
    ("mare-street", "hackney-central"): 3, ("hackney-central", "hackney-downs"): 5,
}

SCENARIOS: dict[str, dict[str, str]] = {
    "normal": {},
    "victoria-severe": {"victoria": SEVERE},
    "victoria-suspended": {"victoria": SUSPENDED},
    "central-minor": {"central": MINOR},
    "weaver-suspended": {"weaver": SUSPENDED},
    "mixed": {"victoria": MINOR, "northern": SEVERE, "elizabeth": MINOR},
}
_AUTO_ROTATION = ["normal", "victoria-severe", "central-minor", "normal", "weaver-suspended", "mixed", "normal"]

REASONS = {
    MINOR: "Minor delays due to train cancellations.",
    SEVERE: "Severe delays due to an earlier signal failure at {station}. Tickets are being accepted on local buses.",
    PART_SUSPENDED: "No service between {station} and the end of the line while engineers fix a track fault.",
    SUSPENDED: "No service due to a faulty train at {station}. Use alternative routes.",
}

WALK_M_PER_MIN = 75.0  # ~4.5 km/h incl. crossings
WALK_DETOUR = 1.3


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def walk_min(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(1.0, round(haversine_m(a, b) * WALK_DETOUR / WALK_M_PER_MIN, 1))


def _rng(*parts) -> random.Random:
    h = hashlib.blake2b("|".join(map(str, parts)).encode(), digest_size=8).digest()
    return random.Random(int.from_bytes(h, "big"))


def _phase(line_id: str, direction: int, headway_s: float) -> float:
    return _rng("phase", line_id, direction).random() * headway_s


EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


class SimProvider:
    name = "sim"

    def __init__(self, scenario: str = "auto"):
        self.scenario = scenario

    # ---- disruption state -------------------------------------------------
    def disruptions(self, now: datetime) -> dict[str, str]:
        name = self.scenario
        if name == "auto":
            loc = local(now)
            mins = loc.hour * 60 + loc.minute
            peak = loc.weekday() < 5 and (420 <= mins <= 600 or 990 <= mins <= 1140)
            name = _AUTO_ROTATION[loc.toordinal() % len(_AUTO_ROTATION)] if peak else "normal"
        return dict(SCENARIOS.get(name, {}))

    def _category(self, line_id: str, now: datetime) -> str:
        return self.disruptions(now).get(line_id, GOOD)

    # ---- vehicles -----------------------------------------------------------
    def _headway_s(self, line: SimLine, cat: str) -> float:
        mult = {GOOD: 1.0, MINOR: 1.4, SEVERE: 3.0, PART_SUSPENDED: 3.0}.get(cat, 1.0)
        return line.headway_min * 60 * mult

    def _true_arrival(self, line: SimLine, direction: int, k: int, idx: int, cat: str) -> float:
        """Seconds since EPOCH at which vehicle k reaches stop position idx (0 = terminus)."""
        hw = self._headway_s(line, cat)
        depart = k * hw + _phase(line.id, direction, hw)
        r = _rng("delay", line.id, direction, k)
        typical = {GOOD: 25, MINOR: 150, SEVERE: 600, PART_SUSPENDED: 600}.get(cat, 25)
        per_stop = abs(r.gauss(typical, typical * 0.6)) / max(1, len(line.stops) - 1)
        return depart + idx * line.inter_min * 60 + per_stop * idx

    def _vehicles_at(self, line: SimLine, stop_id: str, now: datetime, horizon_s: float = 1800):
        cat = self._category(line.id, now)
        if cat == SUSPENDED or stop_id not in line.stops:
            return []
        t = (now - EPOCH).total_seconds()
        out = []
        for direction in (0, 1):
            stops = line.stops if direction == 0 else tuple(reversed(line.stops))
            idx = stops.index(stop_id)
            if idx == len(stops) - 1:
                continue  # terminating here; no departures in this direction
            hw = self._headway_s(line, cat)
            base = int((t - idx * line.inter_min * 60 - 900) // hw)
            for k in range(base, base + int(horizon_s // hw) + 12):
                arr = self._true_arrival(line, direction, k, idx, cat)
                if t < arr <= t + horizon_s:
                    out.append((direction, k, arr, stops[-1], cat))
        return out

    def true_arrival_time(self, line_id: str, stop_id: str, vehicle_id: str, now: datetime) -> datetime | None:
        """Exact ground truth. Only for tests/evaluation; the real world never gives us this."""
        line = LINES[line_id]
        _, d, k = vehicle_id.rsplit("-", 2)
        direction, k = int(d), int(k)
        stops = line.stops if direction == 0 else tuple(reversed(line.stops))
        arr = self._true_arrival(line, direction, k, stops.index(stop_id), self._category(line_id, now))
        return EPOCH + timedelta(seconds=arr)

    def arrivals(self, stop_id: str, now: datetime) -> FetchResult:
        items: list[Arrival] = []
        t = (now - EPOCH).total_seconds()
        name = STATIONS[stop_id][0] if stop_id in STATIONS else stop_id
        for line in LINES.values():
            for direction, k, arr, terminus, cat in self._vehicles_at(line, stop_id, now):
                lead = arr - t
                r = _rng("pred", line.id, direction, k, stop_id, int(t // 30))
                bias = line.bias + (0.12 if cat in (SEVERE, PART_SUSPENDED) else 0.05 if cat == MINOR else 0.0)
                pred = lead * (1 - bias) + r.gauss(0, 12 + 0.03 * lead)
                tts = max(0, int(round(pred)))
                items.append(Arrival(
                    vehicle_id=f"{line.id}-{direction}-{k}", stop_id=stop_id, stop_name=name,
                    line_id=line.id, line_name=line.name, mode=line.mode,
                    direction=STATIONS[terminus][0], destination=STATIONS[terminus][0],
                    expected_arrival=now + timedelta(seconds=tts), time_to_station_s=tts,
                    feed_timestamp=now, platform=None,
                ))
        items.sort(key=lambda a: a.time_to_station_s)
        raw = json.dumps([{**a.__dict__, "expected_arrival": a.expected_arrival.isoformat(),
                           "feed_timestamp": a.feed_timestamp.isoformat()} for a in items])
        return FetchResult(items=items, raw=raw, endpoint=f"sim:/StopPoint/{stop_id}/Arrivals")

    def mode_arrivals(self, mode: str, now: datetime) -> FetchResult:
        stops = sorted({sid for line in LINES.values() if line.mode == mode for sid in line.stops})
        items: list[Arrival] = []
        for sid in stops:
            items += [a for a in self.arrivals(sid, now).items if a.mode == mode]
        raw = json.dumps([{"stop": a.stop_id, "vehicle": a.vehicle_id, "tts": a.time_to_station_s} for a in items])
        return FetchResult(items=items, raw=raw, endpoint=f"sim:/Mode/{mode}/Arrivals")

    # ---- status ---------------------------------------------------------------
    def line_statuses(self, now: datetime, line_ids: list[str] | None = None) -> FetchResult:
        dis = self.disruptions(now)
        out = []
        for line in LINES.values():
            if line_ids and line.id not in line_ids:
                continue
            cat = dis.get(line.id, GOOD)
            desc = {GOOD: "Good service", MINOR: "Minor delays", SEVERE: "Severe delays",
                    PART_SUSPENDED: "Part suspended", SUSPENDED: "Suspended"}[cat]
            reason = None
            if cat != GOOD:
                station = STATIONS[line.stops[len(line.stops) // 2]][0]
                reason = REASONS[cat].format(station=station)
            out.append(LineStatus(line.id, line.name, line.mode, cat, desc, reason))
        raw = json.dumps([s.__dict__ for s in out])
        return FetchResult(items=out, raw=raw, endpoint="sim:/Line/Status")

    # ---- journey planning ---------------------------------------------------------
    def journeys(self, origin, dest, depart_at, max_options: int = 5) -> list[Journey]:
        dis = self.disruptions(depart_at)
        banned_all = {lid for lid, c in dis.items() if c == SUSPENDED}
        results: list = []
        seen: set[tuple] = set()
        tried: set[frozenset] = set()
        queue: list[frozenset] = [frozenset()]
        calls = 0
        while queue and len(results) < max_options and calls < 16:
            bans = queue.pop(0)
            if bans in tried:
                continue
            tried.add(bans)
            calls += 1
            path = self._route(origin, dest, banned_all | bans)
            if not path:
                continue
            key = tuple(e[2] for e in path[1] if e[0] == "ride")
            if key not in seen:
                seen.add(key)
                results.append(path)
            for lid in key:
                queue.append(bans | {lid})
        journeys = [self._to_journey(origin, dest, depart_at, p[1]) for p in results]
        direct = walk_min(origin, dest)
        if direct <= 30:
            journeys.append(Journey([Leg("walking", direct, "Start", "Destination", depart_at,
                                         depart_at + timedelta(minutes=direct))], direct, depart_at,
                                    depart_at + timedelta(minutes=direct), source="sim"))
        journeys.sort(key=lambda j: j.duration_min)
        return journeys

    def _route(self, origin, dest, banned: set[str]):
        """Dijkstra over stations. Ride edges include half-headway expected wait."""
        ORIGIN, DEST = "__origin__", "__dest__"
        dist = {ORIGIN: 0.0}
        prev: dict[str, tuple] = {}
        pq = [(0.0, ORIGIN, None)]
        while pq:
            d, node, via_line = heapq.heappop(pq)
            if d > dist.get(node, math.inf) + 1e-9:
                continue
            if node == DEST:
                break
            edges = []
            if node == ORIGIN:
                for sid, (_, lat, lon) in STATIONS.items():
                    w = walk_min(origin, (lat, lon))
                    if w <= 22:
                        edges.append((sid, w, ("walk", node, sid, w)))
            else:
                pos = (STATIONS[node][1], STATIONS[node][2])
                w = walk_min(pos, dest)
                if w <= 22:
                    edges.append((DEST, w, ("walk", node, DEST, w)))
                for (a, b), w in TRANSFERS.items():
                    if node in (a, b):
                        other = b if node == a else a
                        edges.append((other, float(w), ("walk", node, other, float(w))))
                for line in LINES.values():
                    if line.id in banned or node not in line.stops or line.id == via_line:
                        continue
                    i = line.stops.index(node)
                    for j, sid in enumerate(line.stops):
                        if j == i:
                            continue
                        ride = abs(j - i) * line.inter_min
                        wait = line.headway_min / 2
                        penalty = 0.0 if node == ORIGIN else 2.0  # interchange friction
                        edges.append((sid, ride + wait + penalty, ("ride", node, line.id, sid, ride, wait)))
            for nxt, cost, edge in edges:
                nd = d + cost
                if nd < dist.get(nxt, math.inf) - 1e-9:
                    dist[nxt] = nd
                    prev[nxt] = (node, edge)
                    heapq.heappush(pq, (nd, nxt, edge[2] if edge[0] == "ride" else None))
        if DEST not in dist:
            return None
        edges, n = [], DEST
        while n != ORIGIN:
            p, e = prev[n]
            edges.append(e)
            n = p
        edges.reverse()
        if not any(e[0] == "ride" for e in edges):
            return None
        return dist[DEST], edges

    def _to_journey(self, origin, dest, depart_at, edges) -> Journey:
        t = depart_at
        legs: list[Leg] = []
        for e in edges:
            if e[0] == "walk":
                _, a, b, w = e
                from_name = "Start" if a == "__origin__" else STATIONS[a][0]
                to_name = "Destination" if b == "__dest__" else STATIONS[b][0]
                if legs and legs[-1].mode == "walking":
                    prev = legs.pop()
                    w += prev.duration_min
                    from_name, t = prev.from_name, prev.departure
                legs.append(Leg("walking", round(w, 1), from_name, to_name, t, t + timedelta(minutes=w)))
                t = t + timedelta(minutes=w)
            else:
                _, a, line_id, b, ride, wait = e
                line = LINES[line_id]
                i, j = line.stops.index(a), line.stops.index(b)
                terminus = line.stops[-1] if j > i else line.stops[0]
                dep = t + timedelta(minutes=wait)
                legs.append(Leg(
                    line.mode, round(ride, 1), STATIONS[a][0], STATIONS[b][0], dep, dep + timedelta(minutes=ride),
                    line_id=line.id, line_name=line.name, from_stop_id=a, to_stop_id=b,
                    direction=STATIONS[terminus][0], headway_min=line.headway_min, stops=abs(j - i),
                ))
                t = dep + timedelta(minutes=ride)
        return Journey(legs, round((t - depart_at).total_seconds() / 60, 1), depart_at, t, source="sim")

    # ---- places ---------------------------------------------------------------------
    def search_places(self, query: str) -> list[PlaceResult]:
        q = query.strip().lower()
        extra = [
            PlaceResult("Orford Road, Walthamstow Village", 51.5826, -0.0128, "address", detail="E17"),
            PlaceResult("Regent Street office (W1B)", 51.5141, -0.1405, "address", detail="W1B"),
            PlaceResult("Canary Wharf, One Canada Square", 51.5049, -0.0195, "address", detail="E14"),
            PlaceResult("Hackney, Mare Street", 51.5450, -0.0553, "address", detail="E8"),
        ]
        stations = [PlaceResult(n, lat, lon, "station", stop_id=sid) for sid, (n, lat, lon) in STATIONS.items()
                    if sid not in {l for line in LINES.values() if line.mode == "bus" for l in line.stops}]
        found = [p for p in extra + stations if q in p.name.lower() or (p.detail and q in p.detail.lower())]
        return found[:10]
