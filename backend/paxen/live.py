"""Live trip: where the traveller is along their chosen route, and what's left of it.

Position (from the phone, only while the app is open) is used for this calculation and never stored. Without a
position, progress follows the clock. The rest of the journey is re-forecast with live arrivals and the same
correction model as everywhere else. A trip ends by itself on reaching the destination.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .db import Trip
from .domain import Journey, Leg
from .engine import NetworkContext, current_statuses, forecast_journey
from .forecast import active_model
from .providers.base import Provider
from .timeutil import aware, naive_utc

ARRIVED_M = 150  # within this of the destination = arrived
ON_ROUTE_M = 300  # further than this from the route: fall back to the clock
STALE_AFTER_MIN = 45  # open this long past the latest expected arrival: close it without an arrival time


def _dist_m(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def plan_from_option(option: dict, origin: dict, dest: dict) -> dict:
    """What a live trip needs to remember about the chosen route (from the serialized RouteOption)."""
    keep = ("mode", "line_id", "line_name", "from", "to", "direction", "wait_min", "ride_min", "path",
            "from_stop_id", "stop_ids")
    return {
        "summary": option["summary"], "signature": option["id"],
        "legs": [{k: leg.get(k) for k in keep} for leg in option["legs"]],
        "forecast": option["duration"], "origin": origin, "dest": dest,
    }


def _locate(plan: dict, pos: tuple[float, float]) -> tuple[int, float, float] | None:
    """(leg index, fraction along that leg, distance from route in metres) for the nearest route point."""
    best = None
    for i, leg in enumerate(plan["legs"]):
        path = leg.get("path") or []
        for j, pt in enumerate(path):
            d = _dist_m(pos, pt)
            if best is None or d < best[2]:
                best = (i, j / max(1, len(path) - 1), d)
    return best


def _by_clock(plan: dict, elapsed_min: float) -> tuple[int, float]:
    t = 0.0
    for i, leg in enumerate(plan["legs"]):
        dur = (leg.get("wait_min") or 0) + (leg.get("ride_min") or 0)
        if elapsed_min <= t + dur or i == len(plan["legs"]) - 1:
            return i, min(1.0, max(0.0, (elapsed_min - t) / dur)) if dur else 1.0
        t += dur
    return len(plan["legs"]) - 1, 1.0


def finish(trip: Trip, arrived: datetime, status: str = "arrived") -> None:
    if status == "arrived":
        dur = (arrived - aware(trip.started_at)).total_seconds() / 60
        trip.arrived_at, trip.duration_min = naive_utc(arrived), round(max(0.5, dur), 1)
    trip.status = status


def live_status(s: Session, provider: Provider, trip: Trip, now: datetime,
                pos: tuple[float, float] | None = None) -> dict:
    plan = trip.plan or {}
    started = aware(trip.started_at)
    elapsed = (now - started).total_seconds() / 60
    base = {"trip_id": trip.id, "summary": plan.get("summary"), "started_at": started.isoformat(),
            "elapsed_min": round(elapsed, 1), "legs": plan.get("legs", []), "dest": plan.get("dest"),
            "origin": plan.get("origin"), "forecast_at_start": plan.get("forecast")}

    if trip.status in ("arrived", "auto_closed"):
        return {**base, "status": trip.status, "duration_min": trip.duration_min,
                "vs_forecast_min": _vs(trip)}
    dest = plan.get("dest") or {}
    if pos and dest.get("lat") is not None and _dist_m(pos, (dest["lat"], dest["lon"])) <= ARRIVED_M:
        finish(trip, now)
        s.commit()
        return {**base, "status": "arrived", "duration_min": trip.duration_min, "vs_forecast_min": _vs(trip)}
    p90 = (plan.get("forecast") or {}).get("p90") or trip.forecast_p90 or 90
    if not pos and elapsed > p90 + STALE_AFTER_MIN:
        finish(trip, now, "auto_closed")
        s.commit()
        return {**base, "status": "auto_closed", "duration_min": None, "vs_forecast_min": None}

    located = _locate(plan, pos) if pos else None
    if located and located[2] <= ON_ROUTE_M:
        idx, frac, used = located[0], located[1], "position"
    else:
        (idx, frac), used = _by_clock(plan, elapsed), "clock"
    legs = plan.get("legs", [])
    cur = legs[idx] if legs else {}
    phase = "walking" if cur.get("mode") == "walking" else ("waiting" if frac < 0.05 else "on_board")

    # Re-forecast what's left: the current leg's remainder, then the rest as planned.
    rest: list[Leg] = []
    for i, leg in enumerate(legs[idx:], start=idx):
        ride = float(leg.get("ride_min") or 0)
        transit = leg.get("mode") != "walking" and leg.get("line_id")
        if i == idx and (phase in ("walking", "on_board")):
            rest.append(Leg("walking", round(ride * (1 - frac), 1), leg.get("from", ""), leg.get("to", ""), now, now))
            continue
        rest.append(Leg(leg.get("mode") if transit else "walking", ride, leg.get("from", ""), leg.get("to", ""),
                        now, now, line_id=leg.get("line_id") if transit else None, line_name=leg.get("line_name"),
                        from_stop_id=leg.get("from_stop_id"), direction=leg.get("direction"),
                        stop_ids=leg.get("stop_ids") or []))
    ctx = NetworkContext(provider, now, current_statuses(provider, now), active_model(s, provider.name))
    fc = forecast_journey(Journey(rest, sum(l.duration_min for l in rest), now, now, provider.name), ctx, now)
    nxt = next(((rest_i, lf) for rest_i, lf in enumerate(fc.legs) if lf.line_id), None)
    next_dep = None
    if nxt:
        lf = nxt[1]
        next_dep = {"line_name": lf.line_name, "line_id": lf.line_id, "stop": lf.from_name, "direction": lf.direction,
                    "wait_min": lf.wait_min, "departures_min": lf.next_departures_min, "live": lf.live,
                    "leg_index": idx + nxt[0]}
    return {
        **base, "status": "active", "located_by": used, "current_leg": idx, "phase": phase,
        "progress": round(frac, 2), "remaining_min": {"p10": fc.p10, "p50": fc.p50, "p90": fc.p90},
        "eta": (now + timedelta(minutes=fc.p50)).isoformat(),
        "eta_range": [(now + timedelta(minutes=fc.p10)).isoformat(), (now + timedelta(minutes=fc.p90)).isoformat()],
        "confidence": fc.confidence, "next_departure": next_dep, "disruptions": fc.disruptions,
    }


def _vs(trip: Trip) -> float | None:
    if trip.duration_min is None or trip.forecast_p50 is None:
        return None
    return round(trip.duration_min - trip.forecast_p50, 1)


def close_stale(s: Session, now: datetime) -> int:
    """Worker: close trips that were never seen to arrive (app closed). They're kept out of the learning data."""
    from sqlalchemy import select

    n = 0
    for t in s.scalars(select(Trip).where(Trip.status == "active")):
        p90 = ((t.plan or {}).get("forecast") or {}).get("p90") or t.forecast_p90 or 90
        if (now - aware(t.started_at)).total_seconds() / 60 > p90 + STALE_AFTER_MIN:
            finish(t, now, "auto_closed")
            n += 1
    s.commit()
    return n
