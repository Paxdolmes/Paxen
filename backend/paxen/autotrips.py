"""Automatic trips: the phone notices the commute, the server decides whether it's worth learning from.

With automatic trips on, the iPhone app watches a geofence around Home and around Work (iOS region monitoring:
low power, wakes the app briefly in the background). It sends only "left <place> at <time>" and "reached <place> at
<time>": never a position. Here:

* Leaving a commute's origin starts a *pending* trip, with Paxen's forecast for leaving at that moment (the
  recommended route's p10/p50/p90, and the p90 of the slowest route someone might reasonably take).
* Reaching that commute's destination within MAX_TRIP finishes it. live.judge() then decides: a sensible time is
  recorded and feeds the personal baseline, route reliability and "trips as predicted"; a time far beyond the slowest
  likely route (a stop at the shops, a detour, an errand on the way) or impossibly fast is deleted, never learned from.
* Coming back to where it started, or never reaching the other end, drops the pending trip.
* If a live trip (started with "I'm leaving now") is running for that commute, reaching the destination ends it, and
  no second trip is created.

Geofence crossings are timed at the edge of the area, so GEOFENCE_RADIUS_M of walking is added at each end.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .db import Commute, Place, Trip, User
from .live import finish
from .timeutil import aware, naive_utc

GEOFENCE_RADIUS_M = 150  # the app's geofence radius (mobile/src/lib/autotrips.ts)
WALK_M_PER_MIN = 80
EDGE_MIN = round(GEOFENCE_RADIUS_M / WALK_M_PER_MIN, 1)  # door to the edge of the area, at each end
MAX_TRIP = timedelta(hours=3)  # a departure not followed by an arrival within this is dropped
ALTERNATIVE_SLACK_MIN = 15  # routes this much slower than the best still count as ones someone might take


def _stats(u: User, outcome: str, reason: str | None = None, minutes: float | None = None, at: datetime | None = None):
    st = dict(u.auto_trip_stats or {})
    if outcome == "recorded":
        st["recorded"] = st.get("recorded", 0) + 1
    else:
        skipped = dict(st.get("skipped") or {})
        skipped[reason or outcome] = skipped.get(reason or outcome, 0) + 1
        st["skipped"] = skipped
    st["last"] = {"outcome": outcome, "reason": reason, "minutes": minutes, "at": at.isoformat() if at else None}
    u.auto_trip_stats = st


def _forecast(evaluate: Callable[[Commute, datetime], dict], c: Commute, at: datetime) -> dict:
    try:
        ev = evaluate(c, at)
    except Exception:
        return {}
    rec = ev.get("recommended")
    if not rec:
        return {}
    best = rec["duration"]["p50"]
    plausible = [o for o in ev.get("options", []) if o.get("feasible") and o["duration"]["p50"] <= best + ALTERNATIVE_SLACK_MIN]
    return {"p10": rec["duration"]["p10"], "p50": best, "p90": rec["duration"]["p90"],
            "slowest_p90": max([o["duration"]["p90"] for o in plausible], default=rec["duration"]["p90"]),
            "summary": rec.get("summary"), "signature": rec.get("id")}


def handle(s: Session, u: User, place: Place, event: str, at: datetime,
           evaluate: Callable[[Commute, datetime], dict]) -> dict:
    """One geofence crossing. Returns what happened, for the app (and tests)."""
    commutes = s.scalars(select(Commute).where(Commute.user_id == u.id)).all()
    pending = s.scalars(select(Trip).where(Trip.user_id == u.id, Trip.status == "pending")
                        .order_by(Trip.started_at.desc())).all()
    by_id = {c.id: c for c in commutes}

    if event == "exit":
        starting = [c for c in commutes if c.origin_id == place.id]
        if not starting:
            return {"action": "ignored"}
        live = s.scalars(select(Trip).where(Trip.user_id == u.id, Trip.status == "active",
                                            Trip.commute_id.in_([c.id for c in starting]))).first()
        if live:
            return {"action": "ignored", "reason": "live trip running"}
        for t in pending:  # a new departure replaces any earlier one that never arrived
            s.delete(t)
        c = starting[0]
        started = at - timedelta(minutes=EDGE_MIN)
        fc = _forecast(evaluate, c, started)
        assumed = c.usual_signature or fc.get("signature")  # the route most likely taken
        t = Trip(user_id=u.id, commute_id=c.id, source="detected", status="pending", started_at=naive_utc(started),
                 signature=assumed, summary=c.usual_summary or fc.get("summary"),
                 forecast_p10=fc.get("p10"), forecast_p50=fc.get("p50"), forecast_p90=fc.get("p90"),
                 plan={"auto": {"slowest_p90": fc.get("slowest_p90"), "from": place.label}})
        s.add(t)
        s.commit()
        return {"action": "started", "trip_id": t.id, "commute": c.name}

    # event == "enter"
    live = s.scalars(select(Trip).where(Trip.user_id == u.id, Trip.status == "active")).all()
    for t in live:  # a live trip reaching its destination ends itself
        c = by_id.get(t.commute_id)
        if c and c.dest_id == place.id:
            finish(t, at)
            s.commit()
            return {"action": "live trip ended", "trip_id": t.id, "status": t.status}
    for t in pending:
        c = by_id.get(t.commute_id)
        if not c:
            continue
        started = aware(t.started_at)
        if at - started > MAX_TRIP:
            s.delete(t)
            continue
        if c.origin_id == place.id:  # back where it started: not a commute
            s.delete(t)
            _stats(u, "skipped", "returned", at=at)
            s.commit()
            return {"action": "dropped", "reason": "returned"}
        if c.dest_id == place.id:
            finish(t, at + timedelta(minutes=EDGE_MIN))
            if t.status == "arrived":
                _stats(u, "recorded", minutes=t.duration_min, at=at)
                s.commit()
                return {"action": "recorded", "trip_id": t.id, "duration_min": t.duration_min}
            reason = t.status
            minutes = round(((at - started).total_seconds() / 60) + EDGE_MIN, 1)
            s.delete(t)  # invalid data isn't kept
            _stats(u, "skipped", reason, minutes=minutes, at=at)
            s.commit()
            return {"action": "discarded", "reason": reason, "minutes": minutes}
    s.commit()
    return {"action": "ignored"}


def forget(s: Session, u: User) -> None:
    """Automatic trips turned off: drop any departure still waiting for its arrival."""
    s.execute(delete(Trip).where(Trip.user_id == u.id, Trip.status == "pending"))
