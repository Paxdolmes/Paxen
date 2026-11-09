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

from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session

from .db import LineStatusSnapshot, ObservedArrival, Prediction, RawSnapshot, WatchedStop
from .domain import GOOD
from .archive import archive_raw
from .redact import redact
from .providers.base import Provider
from .timeutil import aware, naive_utc

log = logging.getLogger("paxen.recorder")

KEEP_RAW_PAYLOAD_DAYS = 2  # database copies of raw responses; the archive (R2) keeps the originals
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
        s.add(RawSnapshot(source=provider.name, endpoint="line_status", polled_at=polled, status=0, error=redact(e)[:500]))
        log.warning("status poll failed: %s",redact(e))
        return {}
    s.add(RawSnapshot(source=provider.name, endpoint=res.endpoint, polled_at=polled, status=res.status,
                      latency_ms=res.latency_ms, item_count=len(res.items), payload=res.raw))
    try:  # the permanent, compact status history (one row per change); never let it stop recording
        from .context import record_status_changes

        record_status_changes(s, res.items, now)
    except Exception as e:
        log.warning("status history not recorded: %s", e)
    cats = {}
    for st in res.items:
        cats[st.line_id] = st.category
        s.add(LineStatusSnapshot(source=provider.name, polled_at=polled, line_id=st.line_id, line_name=st.line_name,
                                 mode=st.mode, category=st.category, description=st.description, reason=st.reason))
    return cats


def queue_context(items) -> dict[int, tuple[int, int | None]]:
    """id(arrival) -> (place in queue, seconds behind the train ahead), per stop/line/platform-or-direction."""
    groups: dict[tuple, list] = defaultdict(list)
    for a in items:
        groups[(a.stop_id, a.line_id, a.platform or a.direction)].append(a)
    out = {}
    for g in groups.values():
        g.sort(key=lambda a: a.time_to_station_s)
        for i, a in enumerate(g):
            out[id(a)] = (i + 1, a.time_to_station_s - g[i - 1].time_to_station_s if i else None)
    return out


def record_arrivals(s: Session, provider: Provider, stop_id: str, now: datetime, cats: dict[str, str],
                    pending: list | None = None) -> int:
    """pending: if given, the raw response is held for one batched archive write instead of the database."""
    polled = naive_utc(now)
    try:
        try:
            res = provider.arrivals(stop_id, now, max_age_s=0)  # the recorder always wants a fresh snapshot
        except TypeError:  # providers without a cache
            res = provider.arrivals(stop_id, now)
    except Exception as e:
        s.add(RawSnapshot(source=provider.name, endpoint=f"arrivals:{stop_id}", polled_at=polled, status=0,
                          error=redact(e)[:500]))
        log.warning("arrivals poll failed for %s: %s", stop_id,redact(e))
        return 0
    raw = RawSnapshot(source=provider.name, endpoint=res.endpoint, polled_at=polled, status=res.status,
                      latency_ms=res.latency_ms, item_count=len(res.items),
                      payload=None if pending is not None else res.raw)
    if pending is not None:
        pending.append((raw, stop_id, res.raw))
    s.add(raw)
    s.flush()
    qc = queue_context(res.items)
    if res.items:
        s.execute(insert(Prediction), [dict(
            source=provider.name, raw_id=raw.id, polled_at=polled, feed_ts=naive_utc(a.feed_timestamp),
            stop_id=stop_id, line_id=a.line_id, mode=a.mode, direction=a.direction, vehicle_id=a.vehicle_id,
            expected_arrival=naive_utc(a.expected_arrival), tts_s=a.time_to_station_s,
            line_category=cats.get(a.line_id, GOOD), platform=(a.platform or None) and a.platform[:60],
            queue_rank=qc[id(a)][0], gap_s=qc[id(a)][1],
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
                          error=redact(e)[:500]))
        log.warning("network poll failed for %s: %s", mode,redact(e))
        return {"mode": mode, "seen": 0, "kept": 0}
    key = archive_raw(provider.name, f"mode-{mode}", now, res.raw, archive)
    raw = RawSnapshot(source=provider.name, endpoint=res.endpoint, polled_at=polled, status=res.status,
                      latency_ms=res.latency_ms, item_count=len(res.items), payload=None, archive_key=key)
    s.add(raw)
    s.flush()
    sampler.gc(now)
    qc = queue_context(res.items)
    rows = [dict(
        source=provider.name, raw_id=raw.id, polled_at=polled, feed_ts=naive_utc(a.feed_timestamp),
        stop_id=a.stop_id, line_id=a.line_id, mode=a.mode or mode, direction=a.direction, vehicle_id=a.vehicle_id,
        expected_arrival=naive_utc(a.expected_arrival), tts_s=a.time_to_station_s,
        line_category=cats.get(a.line_id, GOOD), platform=(a.platform or None) and a.platform[:60],
            queue_rank=qc[id(a)][0], gap_s=qc[id(a)][1],
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
    out = {"mode": mode, "seen": len(res.items), "kept": len(rows), "archived": bool(key)}
    meta = getattr(provider, "last_response_meta", None)
    if meta:  # diagnostics: what TfL actually sent (size, cache state)
        out.update(kb=meta["bytes"] // 1000, x_cache=meta["x_cache"], keyed=meta["keyed"],
                   stops=len({a.stop_id for a in res.items}))
    return out


def archive_network(s: Session, provider: Provider, mode: str, now: datetime, archive=None) -> dict:
    """Archive-only network poll (used for buses: too big for the database). Recorded in raw_snapshots
    with an endpoint that arrival inference ignores, because no predictions were stored from it."""
    polled = naive_utc(now)
    endpoint = f"/Mode/{mode}/Arrivals?archive-only"
    try:
        raw, status, latency = provider.mode_arrivals_raw(mode)
    except Exception as e:
        s.add(RawSnapshot(source=provider.name, endpoint=endpoint, polled_at=polled, status=0, error=redact(e)[:500]))
        s.commit()
        log.warning("archive-only poll failed for %s: %s", mode,redact(e))
        return {"mode": mode, "archived": False, "error": redact(e)[:120]}
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
    since, until = naive_utc(now - lookback), naive_utc(now)
    # Upper bound: when python -m paxen.reinfer replays history, everything after `now` is in the table too.
    # Without it each replay step loaded all later data: quadratic overall, gigabytes per step.
    rows = s.execute(
        select(Prediction.stop_id, Prediction.line_id, Prediction.vehicle_id, Prediction.direction,
               Prediction.polled_at, Prediction.expected_arrival, Prediction.tts_s, Prediction.mode)
        .where(Prediction.source == source, Prediction.polled_at >= since, Prediction.polled_at <= until)
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
                   RawSnapshot.polled_at <= until, RawSnapshot.endpoint.like("%/Mode/%/Arrivals"))):
        polls_by_mode[endpoint.rsplit("/Mode/", 1)[1].split("/")[0]].append(polled)

    existing: dict[tuple, list[datetime]] = defaultdict(list)
    for stop, line, veh, direction, arrived in s.execute(
            select(ObservedArrival.stop_id, ObservedArrival.line_id, ObservedArrival.vehicle_id,
                   ObservedArrival.direction, ObservedArrival.arrived_at)
            .where(ObservedArrival.source == source, ObservedArrival.arrived_at >= since - DEDUPE_WINDOW,
                   ObservedArrival.arrived_at <= until + DEDUPE_WINDOW)):
        existing[(stop, line, veh, direction)].append(arrived)
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


def record_trackernet(s: Session, tn, now: datetime, source: str = "tfl", archive=None) -> dict:
    """Measured Tube arrivals: every train first seen 'At Platform', timed by the signalling system."""
    import json
    import xml.etree.ElementTree as ET

    from .trackernet import LINE_CODES, bound_of

    since = naive_utc(now - DEDUPE_WINDOW * 3)
    existing: dict[tuple, list[datetime]] = defaultdict(list)
    for o in s.scalars(select(ObservedArrival).where(ObservedArrival.source == source,
                                                     ObservedArrival.method == "trackernet",
                                                     ObservedArrival.arrived_at >= since)):
        existing[(o.stop_id, o.line_id, o.vehicle_id, o.direction)].append(o.arrived_at)
    raws, created, unmapped, failed = {}, 0, 0, []
    for code, line_ids in LINE_CODES.items():
        try:
            _, trains, raw = tn.summary(code)
            raws[code] = raw.decode("utf-8", "replace")
            names = {st.get("Code"): st.get("N") for st in ET.fromstring(raw).findall("S")}
            stations = tn.station_map(code, names)
        except Exception as e:
            failed.append(code)
            log.warning("trackernet %s failed: %s", code,redact(e))
            continue
        for t in trains:
            naptan = stations.get(t.station_code)
            if not naptan:
                unmapped += 1
                continue
            arrived = naive_utc(t.seen_since)
            for line_id in line_ids:
                key = (naptan, line_id, t.set_no, bound_of(t.platform))
                if any(abs((arrived - x).total_seconds()) < DEDUPE_WINDOW.total_seconds() for x in existing[key]):
                    continue
                existing[key].append(arrived)
                s.add(ObservedArrival(source=source, stop_id=naptan, line_id=line_id, vehicle_id=t.set_no,
                                      direction=key[3], arrived_at=arrived,
                                      earliest=arrived - timedelta(seconds=15), latest=arrived + timedelta(seconds=15),
                                      method="trackernet", quality=1.0))
                created += 1
    if raws:  # one archive object per cycle for all lines (keeps storage requests low)
        archive_raw(source, "trackernet", now, json.dumps(raws), archive)
    s.commit()
    return {"measured_arrivals": created, "unmapped": unmapped, "failed_lines": failed}


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
    pending: list = []
    n = sum(record_arrivals(s, provider, stop, now, cats, pending) for stop in stops)
    if pending:  # one archive object per cycle; without an archive, keep the payloads in the database instead
        import json

        key = archive_raw(provider.name, "stops", now, json.dumps({stop: raw for _, stop, raw in pending}))
        for snap, _, raw in pending:
            if key:
                snap.archive_key = key
            else:
                snap.payload = raw
    s.flush()
    inferred = infer_arrivals(s, provider.name, now)
    s.commit()
    return {"network": network, "stops": len(stops), "predictions": n, "inferred_arrivals": inferred}


def prune(s: Session, now: datetime, prediction_days: int | None = None) -> None:
    """Retention. Predictions, arrivals, line-status snapshots and raw-snapshot rows go after
    PAXEN_PREDICTION_RETENTION_DAYS (default 60; 0 keeps forever). Raw payloads in the database go after
    KEEP_RAW_PAYLOAD_DAYS; the archive keeps every original, so history can be rebuilt."""
    import os

    days = prediction_days if prediction_days is not None else int(os.getenv("PAXEN_PREDICTION_RETENTION_DAYS", "60"))
    if days > 0:
        old = naive_utc(now - timedelta(days=days))
        s.query(Prediction).filter(Prediction.polled_at < old).delete(synchronize_session=False)
        # Arrivals are only useful alongside predictions (kept one extra day so late pairs still match).
        s.query(ObservedArrival).filter(ObservedArrival.arrived_at < old - timedelta(days=1)).delete(
            synchronize_session=False)
        s.query(LineStatusSnapshot).filter(LineStatusSnapshot.polled_at < old).delete(synchronize_session=False)
        s.query(RawSnapshot).filter(RawSnapshot.polled_at < old).delete(synchronize_session=False)
        from .db import StationCrowding

        s.query(StationCrowding).filter(StationCrowding.polled_at < old).delete(synchronize_session=False)
    cutoff = naive_utc(now - timedelta(days=KEEP_RAW_PAYLOAD_DAYS))
    s.query(RawSnapshot).filter(RawSnapshot.polled_at < cutoff, RawSnapshot.payload.is_not(None)).update(
        {RawSnapshot.payload: None}, synchronize_session=False)
    s.commit()


def _row_count(s: Session, model, source: str | None) -> int:
    """Exact on SQLite. On Postgres an exact count(*) reads the whole table: with weeks of history that is
    minutes per call, and this runs on every dashboard load. Use the planner's estimate there (refreshed by
    autovacuum; production holds a single source)."""
    if s.get_bind().dialect.name == "postgresql":
        est = s.scalar(text("SELECT reltuples::bigint FROM pg_class WHERE relname = :t"), {"t": model.__tablename__})
        return max(int(est or 0), 0)
    return s.scalar(select(func.count(model.id)).where((model.source == source) if source else True)) or 0


DATA_STATS_TTL_S = 600
_DATA_STATS: dict[str, tuple[datetime, dict]] = {}


def data_stats(s: Session, now: datetime, source: str) -> dict:
    """For /v1/health: how the ground truth is arriving (last 24 h, by method: trackernet, darwin, inferred...) and,
    on Postgres, how much space the database uses. Cached for 10 minutes: the counts read a day of rows."""
    hit = _DATA_STATS.get(source)
    if hit and (aware(now) - hit[0]).total_seconds() < DATA_STATS_TTL_S:
        return hit[1]
    pg = s.get_bind().dialect.name == "postgresql"
    if pg:
        s.execute(text("SET LOCAL statement_timeout = '15s'"))  # never let a slow count hold up the health check
    since = naive_utc(now - timedelta(hours=24))
    rows = s.execute(select(ObservedArrival.method, func.count()).where(
        ObservedArrival.source == source, ObservedArrival.arrived_at >= since).group_by(ObservedArrival.method)).all()
    out: dict = {"arrivals_24h": {m: n for m, n in sorted(rows)}}
    if pg:
        size = lambda sql: round(float(s.scalar(text(sql)) or 0) / 1e6)  # noqa: E731
        out["db_mb"] = size("SELECT pg_database_size(current_database())")
        out["predictions_mb"] = size("SELECT pg_total_relation_size('predictions')")
        out["arrivals_mb"] = size("SELECT pg_total_relation_size('observed_arrivals')")
        # Index sizes and how often each is used (scans since the statistics were last reset), to find dead weight.
        out["indexes"] = {name: {"mb": round(nbytes / 1e6), "scans": scans} for name, nbytes, scans in s.execute(text(
            "SELECT indexrelname, pg_relation_size(indexrelid), idx_scan FROM pg_stat_user_indexes "
            "WHERE relname IN ('predictions', 'observed_arrivals') ORDER BY indexrelname"))}
        try:  # the write-ahead log shares the disk (needs a superuser or pg_monitor role)
            with s.begin_nested():
                out["wal_mb"] = size("SELECT COALESCE(sum(size), 0)::bigint FROM pg_ls_waldir()")
        except Exception:
            out["wal_mb"] = None
    _DATA_STATS[source] = (aware(now), out)
    return out


def feed_health(s: Session, now: datetime, source: str | None = None, counts: bool = True) -> dict:
    src = (RawSnapshot.source == source) if source else True
    last = s.scalar(select(func.max(RawSnapshot.polled_at)).where(RawSnapshot.status > 0, src))
    last_err = s.scalar(select(func.max(RawSnapshot.polled_at)).where(RawSnapshot.status == 0, src))
    age = (aware(now) - aware(last)).total_seconds() if last else None
    out = {
        "last_success_at": aware(last).isoformat() if last else None,
        "last_error_at": aware(last_err).isoformat() if last_err else None,
        "age_s": round(age) if age is not None else None,
        "fresh": age is not None and age < 180,
    }
    if counts:
        out.update(predictions_recorded=_row_count(s, Prediction, source),
                   observed_arrivals=_row_count(s, ObservedArrival, source))
    return out


def purge_source(s: Session, source: str) -> dict:
    """Delete every recorded row from one data source (e.g. simulator data left in a production database)."""
    from .db import ModelVersion

    counts = {}
    for model in (Prediction, ObservedArrival, LineStatusSnapshot, RawSnapshot):
        counts[model.__tablename__] = s.query(model).filter(model.source == source).delete(synchronize_session=False)
    counts["model_versions"] = s.query(ModelVersion).filter(
        ModelVersion.kind.in_([f"arrival_correction:{source}", "arrival_correction"])).delete(synchronize_session=False)
    s.commit()
    return counts
