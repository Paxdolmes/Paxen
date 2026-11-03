"""TfL Unified API provider (https://api.tfl.gov.uk).

Covers Underground, Overground, Elizabeth line, DLR, bus and the National Rail
services TfL's journey planner returns. Register for an app key and set
TFL_APP_KEY; anonymous access is heavily rate-limited.

Note: check TfL's transport data terms (attribution, caching, commercial use)
before production use — see docs/data-sources.md.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx

from ..domain import (
    GOOD, MINOR, PART_SUSPENDED, SEVERE, SEVERITY_ORDER, SUSPENDED,
    Arrival, FetchResult, Journey, Leg, LineStatus, PlaceResult,
)
from ..timeutil import LONDON

DEFAULT_MODES = "tube,overground,elizabeth-line,dlr,bus,national-rail,walking"
# TfL's planner tends to return near-identical variants of one route. Asking again without the Tube, and
# bus-only, surfaces the genuinely different alternatives a commuter would consider during disruption.
ALT_MODE_SETS = [DEFAULT_MODES, "overground,elizabeth-line,dlr,bus,national-rail,tram,walking", "bus,walking"]
JOURNEY_CACHE_S = 120
STATUS_MODES = "tube,overground,elizabeth-line,dlr,national-rail"

# TfL statusSeverity codes -> normalised categories.
_SEVERITY = {
    10: GOOD, 18: GOOD, 19: GOOD, 0: MINOR, 7: MINOR, 8: MINOR, 9: MINOR, 14: MINOR, 15: MINOR, 17: MINOR,
    6: SEVERE, 1: PART_SUSPENDED, 3: PART_SUSPENDED, 5: PART_SUSPENDED, 11: PART_SUSPENDED,
    2: SUSPENDED, 4: SUSPENDED, 16: SUSPENDED, 20: SUSPENDED, 12: MINOR, 13: MINOR,
}


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    if "." in s:  # TfL sometimes sends 7-digit fractions
        head, frac = s.split(".", 1)
        tz = ""
        for sep in ("+", "-"):
            if sep in frac:
                frac, tz = frac.split(sep, 1)
                tz = sep + tz
                break
        s = f"{head}.{frac[:6]}{tz}"
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=LONDON)  # journey planner times are London local


def parse_arrivals(payload: list[dict], stop_id: str) -> list[Arrival]:
    """Normalise TfL arrivals.

    At a terminus TfL lists each incoming train once per platform it might use; we keep one row per
    (line, vehicle) — the earliest — and flag trains that terminate here (they form the next departure).
    """
    best: dict[tuple[str, str], Arrival] = {}
    for a in payload:
        exp, ts = _dt(a.get("expectedArrival")), _dt(a.get("timestamp"))
        if not exp:
            continue
        naptan = a.get("naptanId") or stop_id
        dest_id = a.get("destinationNaptanId")
        terminates = bool(dest_id and dest_id == naptan)
        arr = Arrival(
            vehicle_id=str(a.get("vehicleId") or a.get("id")),
            stop_id=naptan,
            stop_name=a.get("stationName", ""),
            line_id=a.get("lineId", ""), line_name=a.get("lineName", ""), mode=a.get("modeName", ""),
            direction=a.get("destinationName") or a.get("direction") or "",
            destination=a.get("destinationName", ""),
            expected_arrival=exp, time_to_station_s=int(a.get("timeToStation", 0)),
            feed_timestamp=ts or datetime.now(timezone.utc), platform=a.get("platformName"),
            terminates_here=terminates,
        )
        key = (arr.line_id, arr.vehicle_id)
        if key not in best or arr.time_to_station_s < best[key].time_to_station_s:
            best[key] = arr
    return sorted(best.values(), key=lambda x: x.time_to_station_s)


def parse_statuses(payload: list[dict]) -> list[LineStatus]:
    out = []
    for line in payload:
        statuses = line.get("lineStatuses") or [{"statusSeverity": 10, "statusSeverityDescription": "Good Service"}]
        worst = max(statuses, key=lambda s: SEVERITY_ORDER[_SEVERITY.get(s.get("statusSeverity", 10), MINOR)])
        cat = _SEVERITY.get(worst.get("statusSeverity", 10), MINOR)
        out.append(LineStatus(
            line_id=line["id"], line_name=line.get("name", line["id"]), mode=line.get("modeName", ""),
            category=cat, description=worst.get("statusSeverityDescription", ""),
            reason=worst.get("reason"), severity_code=worst.get("statusSeverity"),
        ))
    return out


def parse_journeys(payload: dict) -> list[Journey]:
    out = []
    for j in payload.get("journeys", []):
        legs = []
        for l in j.get("legs", []):
            mode = (l.get("mode") or {}).get("id", "walking")
            route = (l.get("routeOptions") or [{}])[0]
            line = route.get("lineIdentifier") or {}
            dep, arr = _dt(l.get("departureTime")), _dt(l.get("arrivalTime"))
            dp, ap = l.get("departurePoint") or {}, l.get("arrivalPoint") or {}
            directions = route.get("directions") or []
            legs.append(Leg(
                mode=mode, duration_min=float(l.get("duration", 0)),
                from_name=dp.get("commonName", ""), to_name=ap.get("commonName", ""),
                departure=dep, arrival=arr,
                line_id=line.get("id") if mode != "walking" else None,
                line_name=line.get("name") or route.get("name") if mode != "walking" else None,
                from_stop_id=dp.get("naptanId"),  # icsCode is a planner id; it is not valid for arrivals
                to_stop_id=ap.get("naptanId"),
                direction=directions[0] if directions else None,
                stops=len((l.get("path") or {}).get("stopPoints") or []) or None,
            ))
        if not legs:
            continue
        out.append(Journey(legs, float(j.get("duration", 0)), _dt(j.get("startDateTime")),
                           _dt(j.get("arrivalDateTime")), source="tfl"))
    return out


def dedupe_journeys(journeys: list[Journey]) -> list[Journey]:
    """One journey per route signature (the quickest), ordered by duration."""
    best: dict[str, Journey] = {}
    for j in journeys:
        if j.signature not in best or j.duration_min < best[j.signature].duration_min:
            best[j.signature] = j
    return sorted(best.values(), key=lambda j: j.duration_min)


_NAME_SUFFIXES = (" underground station", " rail station", " dlr station", " station")


def _clean_name(name: str) -> str:
    low = name.lower()
    for suf in _NAME_SUFFIXES:
        if low.endswith(suf):
            return name[: -len(suf)]
    return name


def parse_place_search(payload: dict) -> list[PlaceResult]:
    out, seen = [], set()
    for m in payload.get("matches", []):
        if "lat" not in m:
            continue
        name = _clean_name(m.get("name", ""))
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(PlaceResult(name, m["lat"], m["lon"], "station", stop_id=m.get("id"),
                               detail=", ".join(m.get("modes", [])) or None))
    return out[:10]


class TflProvider:
    name = "tfl"

    def __init__(self, base_url: str, app_key: str | None, timeout: float = 15.0):
        self.base = base_url.rstrip("/")
        self.app_key = app_key
        self.client = httpx.Client(timeout=timeout, headers={"User-Agent": "paxen-commute/0.1"})
        self._journey_cache: dict[tuple, tuple[float, list[Journey]]] = {}

    def _get(self, path: str, params: dict | None = None) -> tuple[object, str, int, int]:
        params = dict(params or {})
        if self.app_key:
            params["app_key"] = self.app_key
        t0 = time.monotonic()
        r = self.client.get(f"{self.base}{path}", params=params)
        latency = int((time.monotonic() - t0) * 1000)
        r.raise_for_status()
        return r.json(), r.text, r.status_code, latency

    def arrivals(self, stop_id: str, now: datetime) -> FetchResult:
        path = f"/StopPoint/{stop_id}/Arrivals"
        data, raw, status, latency = self._get(path)
        return FetchResult(parse_arrivals(data, stop_id), raw, path, status, latency)

    def line_statuses(self, now: datetime, line_ids: list[str] | None = None) -> FetchResult:
        path = f"/Line/{','.join(line_ids)}/Status" if line_ids else f"/Line/Mode/{STATUS_MODES}/Status"
        data, raw, status, latency = self._get(path)
        return FetchResult(parse_statuses(data), raw, path, status, latency)

    def journeys(self, origin, dest, depart_at):
        loc = depart_at.astimezone(LONDON)
        key = (round(origin[0], 4), round(origin[1], 4), round(dest[0], 4), round(dest[1], 4),
               loc.strftime("%Y%m%d%H") + str(loc.minute // 5))
        hit = self._journey_cache.get(key)
        if hit and time.monotonic() - hit[0] < JOURNEY_CACHE_S:
            return list(hit[1])
        path = f"/Journey/JourneyResults/{origin[0]:.5f},{origin[1]:.5f}/to/{dest[0]:.5f},{dest[1]:.5f}"
        params = {"date": loc.strftime("%Y%m%d"), "time": loc.strftime("%H%M"), "timeIs": "Departing",
                  "journeyPreference": "LeastTime", "alternativeRoute": "true"}
        with ThreadPoolExecutor(max_workers=len(ALT_MODE_SETS)) as pool:
            futures = [pool.submit(self._get, path, {**params, "mode": m}) for m in ALT_MODE_SETS]
        found: list[Journey] = []
        for i, fut in enumerate(futures):
            try:
                data, *_ = fut.result()
            except httpx.HTTPError:
                if i == 0:
                    raise  # the main query must work; alternatives are best-effort
                continue
            found += parse_journeys(data)
        out = dedupe_journeys(found)
        self._journey_cache[key] = (time.monotonic(), out)
        return list(out)

    def search_places(self, query: str) -> list[PlaceResult]:
        data, *_ = self._get(f"/StopPoint/Search/{query}", {"maxResults": 15})
        return parse_place_search(data)
