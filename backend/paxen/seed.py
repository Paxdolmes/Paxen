"""Backfill for sim mode: replay the recorder over past simulated hours, train the model, add past trips."""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .db import Commute, Trip
from .engine import NetworkContext, clear_status_cache, forecast_journey, route_key
from .forecast import CorrectionModel, train_and_maybe_promote
from .providers.sim import SimProvider
from .recorder import record_once
from .timeutil import local, naive_utc

PILOT = ["walthamstow-central", "liverpool-street", "oxford-circus", "highbury-islington", "stratford",
         "hoe-street", "bakers-arms"]


def backfill_recorder(s: Session, provider: SimProvider, end: datetime, hours: float = 3, step_s: int = 45,
                      stops: list[str] | None = None) -> dict:
    t = end - timedelta(hours=hours)
    totals = {"polls": 0, "predictions": 0, "inferred_arrivals": 0}
    while t <= end:
        r = record_once(s, provider, t, stops or PILOT)
        totals["polls"] += 1
        totals["predictions"] += r["predictions"]
        totals["inferred_arrivals"] += r["inferred_arrivals"]
        t += timedelta(seconds=step_s)
    return totals


def seed_trips(s: Session, provider: SimProvider, commute: Commute, end: datetime, days: int = 21,
               rng: random.Random | None = None) -> int:
    """Synthesise past trips on the usual route, using the sim's own forecast at that past time + noise."""
    rng = rng or random.Random(commute.id)
    made = 0
    for back in range(days, 0, -1):
        day = local(end) - timedelta(days=back)
        if day.weekday() not in (commute.days or []):
            continue
        h, m = map(int, commute.window_start.split(":"))
        start = day.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(minutes=rng.randint(-5, 20))
        journeys = provider.journeys((commute.origin.lat, commute.origin.lon), (commute.dest.lat, commute.dest.lon),
                                     start)
        usual = next((j for j in journeys if route_key(j.signature) == route_key(commute.usual_signature)), None)
        j = usual or (journeys[0] if journeys else None)
        if not j:
            continue
        ctx = NetworkContext(provider, start, {st.line_id: st for st in provider.line_statuses(start).items},
                             CorrectionModel())
        f = forecast_journey(j, ctx, start)
        dur = max(5.0, f.p50 + rng.gauss(0, max(1.0, (f.p90 - f.p50) / 1.28)))
        s.add(Trip(user_id=commute.user_id, commute_id=commute.id, signature=j.signature, summary=j.summary,
                   started_at=naive_utc(start), arrived_at=naive_utc(start + timedelta(minutes=dur)),
                   duration_min=round(dur, 1), forecast_p10=f.p10, forecast_p50=f.p50, forecast_p90=f.p90,
                   source="seed"))
        made += 1
    s.commit()
    clear_status_cache()
    return made


def seed_model(s: Session, provider: SimProvider, end: datetime, hours: float = 2) -> dict:
    rec = backfill_recorder(s, provider, end, hours=hours)
    return {"recorder": rec, "training": train_and_maybe_promote(s, provider.name)}
