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
from .archive import archive_raw
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
        try:
            res = provider.arrivals(stop_id, now, max_age_s=0)  # the recorder always wants a fresh snapshot
        except TypeError:  # providers without a cache
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


# ---------------------------------------------------------------- network-wide recording
NETWORK_MAX_LEAD_S = 1800  # the network feed lists trains up to ~2h out (timetable); keep the live 30 min
DENSE_WINDOW_S = 120  # last 2 min before arrival: keep every snapshot (arrival inference needs full detail)
SAMPLE_BUCKETS_S = [(1200, 10**9), (600, 1200), (300, 600), (120, 300)]  # earlier: one per lead-time group


# TfL stop-id prefixes per network-polled mode (Underground 940G…, Overground/Elizabeth line 910G…).
NAPTAN_PREFIX_BY_MODE = {"tube": ("940G",), "overground": ("910G",), "elizabeth-line": ("910G",), "dlr": ("940G",),
                         "tram": ("940G",)}


class LeadSampler:
    """Keeps the first snapshot of each vehicle/stop/direction in each early lead-time group, and every
    snapshot in the last DENSE_WINDOW_S. Consecutive far-out snapshots are near-duplicates, so this cuts
    storage ~5-10x while keeping what the model learns from. State is per process; after a restart a group
    may be stored twice, which is harmless."""

    def __init__(self, ttl: timedelta = timedelta(hours=2)):
        self.ttl = ttl
        self.seen: dict[tuple, tuple[datetime, set[int]]] = {}
        self._last_gc: datetime | None = None

    def keep(self, key: tuple, tts: int, now: datetime) -> bool:
        if tts <= DENSE_WINDOW_S:
            return True
        b = next(i for i, (lo, hi) in enumerate(SAMPLE_BUCKETS_S) if lo <= tts < hi or i == len(SAMPLE_BUCKETS_S) - 1)
        _, buckets = self.seen.get(key, (now, set()))
        self.seen[key] = (now, buckets)
        if b in buckets:
            return False
        buckets.add(b)
        return True

    def gc(self, now: datetime) -> None:
        if self._last_gc and now - self._last_gc < timedelta(minutes=10):
            return
        self.seen = {k: v for k, v in self.seen.items() if now - v[0] < self.ttl}
        self._last_gc = now


SAMPLER = LeadSampler()
_NETWORK_PEAK: dict[str, float] = {}


def record_network(s: Session, provider: Provider, mode: str, now: datetime, cats: dict[str, str],
                   sampler: LeadSampler = SAMPLER, archive=None) -> dict:
    """One request for every live prediction on a mode; raw response to the archive, sampled rows to the DB."""
    polled = naive_utc(now)
    try:
        res = provider.mode_arrivals(mode, now)
    except Exception as e:
        s.add(RawSnapshot(source=provider.name, endpoint=f"/Mode/{mode}/Arrivals", polled_at=polled, status=0,
                          error=str(e)[:500]))
        log.warning("network poll failed for %s: %s", mode, e)
        return {"mode": mode, "seen": 0, "kept": 0}
    key = archive_raw(provider.name, f"mode-{mode}", now, res.raw, archive)
    raw = RawSnapshot(source=provider.name, endpoint=res.endpoint, polled_at=polled, status=res.status,
                      latency_ms=res.latency_ms, item_count=len(res.items), payload=None, archive_key=key)
    s.add(raw)
    s.flush()
    sampler.gc(now)
    rows = [dict(
        source=provider.name, raw_id=raw.id, polled_at=polled, feed_ts=naive_utc(a.feed_timestamp),
        stop_id=a.stop_id, line_id=a.line_id, mode=a.mode or mode, direction=a.direction, vehicle_id=a.vehicle_id,
        expected_arrival=naive_utc(a.expected_arrival), tts_s=a.time_to_station_s,
        line_category=cats.get(a.line_id, GOOD),
    ) for a in res.items
        if a.time_to_station_s <= NETWORK_MAX_LEAD_S
        and sampler.keep((a.stop_id, a.line_id, a.vehicle_id, a.direction), a.time_to_station_s, now)]
    if rows:
        s.execute(insert(Prediction), rows)
    # A whole network suddenly reporting far fewer trains usually means a stale/partial upstream response.
    peak = _NETWORK_PEAK.get(mode, 0)
    _NETWORK_PEAK[mode] = max(peak * 0.999, len(res.items))
    if peak > 200 and len(res.items) < peak * 0.4:
        log.warning("network poll for %s returned %d predictions (recent peak %d): partial upstream data?",
                    mode, len(res.items), int(peak))
    return {"mode": mode, "seen": len(res.items), "kept": len(rows), "archived": bool(key)}


def archive_network(s: Session, provider: Provider, mode: str, now: datetime, archive=None) -> dict:
    """Archive-only network poll (used for buses: too big for the database). Recorded in raw_snapshots
    with an endpoint that arrival inference ignores, because no predictions were stored from it."""
    polled = naive_utc(now)
    endpoint = f"/Mode/{mode}/Arrivals?archive-only"
    try:
        raw, status, latency = provider.mode_arrivals_raw(mode)
    except Exception as e:
        s.add(RawSnapshot(source=provider.name, endpoint=endpoint, polled_at=polled, status=0, error=str(e)[:500]))
        s.commit()
        log.warning("archive-only poll failed for %s: %s", mode, e)
        return {"mode": mode, "archived": False, "error": str(e)[:120]}
    key = archive_raw(provider.name, f"mode-{mode}", now, raw, archive)
    s.add(RawSnapshot(source=provider.name, endpoint=endpoint, polled_at=polled, status=status, latency_ms=latency,
                      item_count=0, payload=None, archive_key=key))
    s.commit()
    return {"mode": mode, "mb": round(len(raw) / 1e6, 1), "archived": bool(key)}


AT_PLATFORM_S = 30  # countdown at/below this means the vehicle is arriving now
MAX_DWELL_S = 300  # shown as "due" longer than this = terminus layover / id reuse, not an arrival
GONE_POLLS = 2  # vehicles flicker on and off TfL boards; must be missing this many polls in a row
DEDUPE_WINDOW = timedelta(minutes=10)


def infer_arrivals(s: Session, source: str, now: datetime, lookback: timedelta = timedelta(minutes=20)) -> int:
    """Infer that a vehicle arrived, from how its countdown behaved. Never treated as measured.

    * Primary signal: the first poll where the countdown reached the platform (<= AT_PLATFORM_S). The
      arrival is that poll's predicted time; bounds are [previous poll, that time + AT_PLATFORM_S].
    * Fallback: the vehicle was <= 2 min away and then vanished from the board before the next poll.
    * Rejected: vehicles that sit at "due" for more than MAX_DWELL_S (a train laying over at a
      terminus, or a vehicle id reused by a later trip) — their arrival time is unknowable from this.
    A vehicle is only judged once it has left the board.
    """
    since = naive_utc(now - lookback)
    rows = s.execute(
        select(Prediction.stop_id, Prediction.line_id, Prediction.vehicle_id, Prediction.direction,
               Prediction.polled_at, Prediction.expected_arrival, Prediction.tts_s, Prediction.mode)
        .where(Prediction.source == source, Prediction.polled_at >= since)
        .order_by(Prediction.polled_at)
    ).all()
    if not rows:
        return 0
    polls_by_stop: dict[str, list[datetime]] = defaultdict(list)
    seen: dict[tuple, list[tuple]] = defaultdict(list)
    mode_of: dict[tuple, str] = {}
    for stop, line, veh, direction, polled, exp, tts, mode in rows:
        lst = polls_by_stop[stop]
        if not lst or lst[-1] != polled:
            lst.append(polled)
        seen[(stop, line, veh, direction)].append((polled, exp, tts))
        mode_of[(stop, line, veh, direction)] = mode
    # A network-wide poll covers every stop of its mode, even stops where nothing was stored (sampling).
    polls_by_mode: dict[str, list[datetime]] = defaultdict(list)
    for endpoint, polled in s.execute(
            select(RawSnapshot.endpoint, RawSnapshot.polled_at)
            .where(RawSnapshot.source == source, RawSnapshot.status > 0, RawSnapshot.polled_at >= since,
                   RawSnapshot.endpoint.like("%/Mode/%/Arrivals"))):
        polls_by_mode[endpoint.rsplit("/Mode/", 1)[1].split("/")[0]].append(polled)

    existing: dict[tuple, list[datetime]] = defaultdict(list)
    for o in s.scalars(select(ObservedArrival).where(ObservedArrival.source == source,
                                                     ObservedArrival.arrived_at >= since - DEDUPE_WINDOW)):
        existing[(o.stop_id, o.line_id, o.vehicle_id, o.direction)].append(o.arrived_at)
    created = 0

    def record(key, est, earliest, latest, quality):
        nonlocal created
        if any(abs((est - t).total_seconds()) < DEDUPE_WINDOW.total_seconds() for t in existing[key]):
            return
        existing[key].append(est)
        s.add(ObservedArrival(source=source, stop_id=key[0], line_id=key[1], vehicle_id=key[2], direction=key[3],
                              arrived_at=est, earliest=earliest, latest=latest, method="countdown_inferred",
                              quality=quality))
        created += 1

    for key, seq in seen.items():
        last_polled = seq[-1][0]
        polls = set(polls_by_stop[key[0]]) | set(polls_by_mode.get(mode_of[key], ()))
        later = sorted(p for p in polls if p > last_polled)
        if len(later) < GONE_POLLS:
            continue  # still on the board, or may just be flickering
        at_platform = [x for x in seq if x[2] <= AT_PLATFORM_S]
        if at_platform:
            first_p, first_exp, _ = at_platform[0]
            if (at_platform[-1][0] - first_p).total_seconds() > MAX_DWELL_S:
                continue
            idx = seq.index(at_platform[0])
            prev = seq[idx - 1][0] if idx > 0 else first_p - timedelta(seconds=60)
            est = max(first_exp, first_p)
            latest = est + timedelta(seconds=AT_PLATFORM_S)
            gap = (first_p - prev).total_seconds()
            record(key, est, prev, latest, round(max(0.0, 1 - gap / 300), 3))
            continue
        polled, exp, tts = seq[-1]
        if tts > ARRIVAL_COUNTDOWN_MAX_S:
            continue
        missing_at = later[0]
        gap = (missing_at - polled).total_seconds()
        if gap > 300:
            continue  # feed gap — too uncertain to call
        est = min(max(exp, polled), missing_at)
        quality = round(max(0.0, 1 - gap / 300) * (1 - tts / (ARRIVAL_COUNTDOWN_MAX_S * 2)), 3)
        record(key, est, polled, missing_at, quality)
    return created


def record_once(s: Session, provider: Provider, now: datetime, extra_stops: list[str] | None = None,
                modes: list[str] | None = None) -> dict:
    """One recorder cycle: line status, whole-network polls for `modes`, then individual polls for the
    remaining stops users' routes need (e.g. bus stops), then arrival inference."""
    cats = record_statuses(s, provider, now)
    network = []
    covered: set[str] = set()
    for mode in modes or []:
        if hasattr(provider, "mode_arrivals"):
            network.append(record_network(s, provider, mode, now, cats))
    if network:
        covered = set(s.scalars(select(Prediction.stop_id).where(
            Prediction.polled_at == naive_utc(now), Prediction.source == provider.name)).all())
    stops = sorted((set(active_stops(s, now)) | set(extra_stops or [])) - covered)
    # Stops on a network-polled mode that simply had no trains this cycle don't need their own poll.
    prefixes = tuple(p for m in modes or [] for p in NAPTAN_PREFIX_BY_MODE.get(m, ()))
    if network and prefixes:
        stops = [st for st in stops if not st.startswith(prefixes)]
    n = sum(record_arrivals(s, provider, stop, now, cats) for stop in stops)
    s.flush()
    inferred = infer_arrivals(s, provider.name, now)
    s.commit()
    return {"network": network, "stops": len(stops), "predictions": n, "inferred_arrivals": inferred}


def prune(s: Session, now: datetime, prediction_days: int | None = None) -> None:
    """Retention. Raw payloads in the DB go after KEEP_RAW_PAYLOAD_DAYS. Predictions go after
    PAXEN_PREDICTION_RETENTION_DAYS (default 60; 0 keeps forever): the raw archive keeps every original, and
    inferred arrivals are kept, so the model's history isn't lost."""
    import os

    days = prediction_days if prediction_days is not None else int(os.getenv("PAXEN_PREDICTION_RETENTION_DAYS", "60"))
    if days > 0:
        s.query(Prediction).filter(Prediction.polled_at < naive_utc(now - timedelta(days=days))).delete(
            synchronize_session=False)
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
