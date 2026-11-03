"""Phase 1 — the data recorder.

Polls live feeds, keeps every raw payload alongside normalised rows, and infers
observed arrivals from vehicles dropping off a stop's countdown. Inferred
arrivals carry bounds and a quality score; they are labelled as inferred and
never presented as measured ground truth.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from .db import LineStatusSnapshot, ObservedArrival, Prediction, RawSnapshot, WatchedStop
from .domain import GOOD
from .providers.base import Provider
from .timeutil import aware, naive_utc

log = logging.getLogger("paxen.recorder")

KEEP_RAW_PAYLOAD_DAYS = 14
ARRIVAL_COUNTDOWN_MAX_S = 120  # last sighting must be this close to arrival to infer an arrival
WATCH_TTL = timedelta(days=7)


def watch_stops(s: Session, stops: dict[str, str], now: datetime) -> None:
    for stop_id, name in stops.items():
        if not stop_id:
            continue
        w = s.get(WatchedStop, stop_id)
        if w:
            w.last_needed_at = naive_utc(now)
        else:
            s.add(WatchedStop(stop_id=stop_id, name=name, last_needed_at=naive_utc(now)))


def active_stops(s: Session, now: datetime) -> list[str]:
    cutoff = naive_utc(now - WATCH_TTL)
    return list(s.scalars(select(WatchedStop.stop_id).where(WatchedStop.last_needed_at >= cutoff)))


def record_statuses(s: Session, provider: Provider, now: datetime) -> dict[str, str]:
    polled = naive_utc(now)
    try:
        res = provider.line_statuses(now)
    except Exception as e:  # keep a record of feed failures: they matter for freshness/confidence
        s.add(RawSnapshot(source=provider.name, endpoint="line_status", polled_at=polled, status=0, error=str(e)))
        log.warning("status poll failed: %s", e)
        return {}
    s.add(RawSnapshot(source=provider.name, endpoint=res.endpoint, polled_at=polled, status=res.status,
                      latency_ms=res.latency_ms, item_count=len(res.items), payload=res.raw))
    cats = {}
    for st in res.items:
        cats[st.line_id] = st.category
        s.add(LineStatusSnapshot(source=provider.name, polled_at=polled, line_id=st.line_id, line_name=st.line_name,
                                 mode=st.mode, category=st.category, description=st.description, reason=st.reason))
    return cats


def record_arrivals(s: Session, provider: Provider, stop_id: str, now: datetime, cats: dict[str, str]) -> int:
    polled = naive_utc(now)
    try:
        res = provider.arrivals(stop_id, now)
    except Exception as e:
        s.add(RawSnapshot(source=provider.name, endpoint=f"arrivals:{stop_id}", polled_at=polled, status=0,
                          error=str(e)))
        log.warning("arrivals poll failed for %s: %s", stop_id, e)
        return 0
    raw = RawSnapshot(source=provider.name, endpoint=res.endpoint, polled_at=polled, status=res.status,
                      latency_ms=res.latency_ms, item_count=len(res.items), payload=res.raw)
    s.add(raw)
    s.flush()
    if res.items:
        s.execute(insert(Prediction), [dict(
            source=provider.name, raw_id=raw.id, polled_at=polled, feed_ts=naive_utc(a.feed_timestamp),
            stop_id=stop_id, line_id=a.line_id, mode=a.mode, direction=a.direction, vehicle_id=a.vehicle_id,
            expected_arrival=naive_utc(a.expected_arrival), tts_s=a.time_to_station_s,
            line_category=cats.get(a.line_id, GOOD),
        ) for a in res.items])
    return len(res.items)


def infer_arrivals(s: Session, source: str, now: datetime, lookback: timedelta = timedelta(minutes=20)) -> int:
    """A vehicle that was about to arrive and then vanished from the countdown has (probably) arrived.

    arrived_at is bounded by [last poll it was seen, first poll it was missing]; the point estimate is the
    final predicted time clamped into that interval. Quality falls with the width of the interval.
    """
    since = naive_utc(now - lookback)
    rows = s.execute(
        select(Prediction.stop_id, Prediction.line_id, Prediction.vehicle_id, Prediction.polled_at,
               Prediction.expected_arrival, Prediction.tts_s)
        .where(Prediction.source == source, Prediction.polled_at >= since)
        .order_by(Prediction.polled_at)
    ).all()
    if not rows:
        return 0
    polls_by_stop: dict[str, list[datetime]] = defaultdict(list)
    last_seen: dict[tuple, tuple] = {}
    for stop, line, veh, polled, exp, tts in rows:
        lst = polls_by_stop[stop]
        if not lst or lst[-1] != polled:
            lst.append(polled)
        last_seen[(stop, line, veh)] = (polled, exp, tts)

    existing = {
        (o.stop_id, o.line_id, o.vehicle_id)
        for o in s.scalars(select(ObservedArrival).where(ObservedArrival.source == source,
                                                         ObservedArrival.arrived_at >= since))
    }
    created = 0
    for key, (polled, exp, tts) in last_seen.items():
        if key in existing or tts > ARRIVAL_COUNTDOWN_MAX_S:
            continue
        later = [p for p in polls_by_stop[key[0]] if p > polled]
        if not later:
            continue  # still on the board (or no newer poll yet)
        missing_at = later[0]
        gap = (missing_at - polled).total_seconds()
        if gap > 300:
            continue  # feed gap — too uncertain to call
        est = min(max(exp, polled), missing_at)
        quality = round(max(0.0, 1 - gap / 300) * (1 - tts / (ARRIVAL_COUNTDOWN_MAX_S * 2)), 3)
        s.add(ObservedArrival(source=source, stop_id=key[0], line_id=key[1], vehicle_id=key[2], arrived_at=est,
                              earliest=polled, latest=missing_at, method="countdown_inferred", quality=quality))
        created += 1
    return created


def record_once(s: Session, provider: Provider, now: datetime, extra_stops: list[str] | None = None) -> dict:
    cats = record_statuses(s, provider, now)
    stops = sorted(set(active_stops(s, now)) | set(extra_stops or []))
    n = sum(record_arrivals(s, provider, stop, now, cats) for stop in stops)
    s.flush()
    inferred = infer_arrivals(s, provider.name, now)
    s.commit()
    return {"stops": len(stops), "predictions": n, "inferred_arrivals": inferred}


def prune(s: Session, now: datetime) -> None:
    """Retention: drop bulky raw payloads after KEEP_RAW_PAYLOAD_DAYS (normalised rows are kept)."""
    cutoff = naive_utc(now - timedelta(days=KEEP_RAW_PAYLOAD_DAYS))
    s.query(RawSnapshot).filter(RawSnapshot.polled_at < cutoff, RawSnapshot.payload.is_not(None)).update(
        {RawSnapshot.payload: None}, synchronize_session=False)
    s.commit()


def feed_health(s: Session, now: datetime) -> dict:
    last = s.scalar(select(func.max(RawSnapshot.polled_at)).where(RawSnapshot.status > 0))
    last_err = s.scalar(select(func.max(RawSnapshot.polled_at)).where(RawSnapshot.status == 0))
    age = (aware(now) - aware(last)).total_seconds() if last else None
    return {
        "last_success_at": aware(last).isoformat() if last else None,
        "last_error_at": aware(last_err).isoformat() if last_err else None,
        "age_s": round(age) if age is not None else None,
        "fresh": age is not None and age < 180,
        "predictions_recorded": s.scalar(select(func.count(Prediction.id))) or 0,
        "observed_arrivals": s.scalar(select(func.count(ObservedArrival.id))) or 0,
    }
