"""Measured arrivals for the Overground and Elizabeth line from National Rail's Darwin feed (Push Port v18).

Darwin (Rail Data Marketplace, "Darwin Real Time Train Information", Kafka) streams every train status change in
Britain, ~28 messages a second. Each TS (train status) message carries, per station (TIPLOC), the scheduled times,
estimates (`et`) and, once it has happened, the actual time (`at`) from the signalling and TRUST systems.

Two facts make the match with TfL exact, no inference needed:
- TfL's vehicle ids for Overground and Elizabeth line trains ARE Darwin's train ids (`rid`, e.g. 202611066711177);
- TfL's rail stop ids are Darwin's TIPLOCs with "910G" in front (910GDALSKLD = Dalston Kingsland).

So each actual arrival at a London Overground or Elizabeth line station becomes an ObservedArrival with
method="darwin" (measured), attached to the line and direction of the TfL predictions for the same train. Trains
TfL doesn't predict (other operators) are dropped, as are actual times at stations Paxen doesn't record.

Configure the worker with DARWIN_BOOTSTRAP, DARWIN_USERNAME, DARWIN_PASSWORD, DARWIN_TOPIC, DARWIN_GROUP.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .timeutil import LONDON, naive_utc

log = logging.getLogger("paxen.darwin")
METHOD = "darwin"
FLUSH_EVERY_S = 15
LINE_LOOKBACK = timedelta(hours=6)


@dataclass(frozen=True)
class Actual:
    rid: str
    tiploc: str
    arrived_at: datetime  # UTC
    source: str  # Darwin's own source tag: TD, TRUST, ...


def configured() -> bool:
    return all(os.getenv(k) for k in ("DARWIN_BOOTSTRAP", "DARWIN_USERNAME", "DARWIN_PASSWORD", "DARWIN_TOPIC"))


def _when(hhmm: str, ssd: str, ref: datetime) -> datetime | None:
    """A Darwin local time ("10:38" or "10:38:30") on the right day: the one nearest the message's timestamp
    (a train that started yesterday can arrive after midnight)."""
    try:
        parts = [int(p) for p in hhmm.split(":")]
        base = date.fromisoformat(ssd)
    except ValueError:
        return None
    h, m, s = (parts + [0, 0])[:3]
    best = None
    for shift in (-1, 0, 1):
        cand = datetime.combine(base + timedelta(days=shift), datetime.min.time()).replace(
            hour=h, minute=m, second=s, tzinfo=LONDON).astimezone(timezone.utc)
        if best is None or abs((cand - ref).total_seconds()) < abs((best - ref).total_seconds()):
            best = cand
    return best


def parse(raw: bytes | str, keep: set[str] | None = None) -> list[Actual]:
    """Actual arrivals in one Kafka message (envelope JSON whose `bytes` is the Push Port JSON)."""
    try:
        env = json.loads(raw)
        body = json.loads(env["bytes"]) if isinstance(env.get("bytes"), str) else env
    except (ValueError, KeyError, TypeError):
        return []
    ts = body.get("ts")
    try:
        ref = datetime.fromisoformat(ts) if ts else datetime.now(timezone.utc)
    except ValueError:
        ref = datetime.now(timezone.utc)
    out: list[Actual] = []
    for section in ("uR", "sR"):
        ts_list = (body.get(section) or {}).get("TS")
        for t in ts_list if isinstance(ts_list, list) else [ts_list] if ts_list else []:
            rid, ssd = t.get("rid"), t.get("ssd")
            locs = t.get("Location")
            for loc in locs if isinstance(locs, list) else [locs] if locs else []:
                tpl, arr = loc.get("tpl"), loc.get("arr")
                if not rid or not ssd or not tpl or not isinstance(arr, dict) or not arr.get("at"):
                    continue
                if keep is not None and tpl not in keep:
                    continue
                when = _when(arr["at"], ssd, ref)
                if when:
                    out.append(Actual(rid, tpl, when, arr.get("src", "")))
    return out


def london_tiplocs() -> set[str]:
    """TIPLOCs of the Overground and Elizabeth line stations Paxen records (from TfL's 910G stop ids)."""
    from . import numbat

    nb = numbat.get()
    keys = {"EZL", "URL", "WEL", "NLL", "GOB", "WAG", "ELL"}
    if not nb:
        return set()
    return {sid[4:] for k in keys for sid in nb.stations.get(k, {}) if sid.startswith("910G")}


def store(s: Session, actuals: list[Actual], source: str = "tfl") -> int:
    """Attach actual arrivals to the TfL train they belong to (same vehicle id) and save them as measured."""
    from .db import ObservedArrival, Prediction

    if not actuals:
        return 0
    rids = sorted({a.rid for a in actuals})
    since = naive_utc(min(a.arrived_at for a in actuals) - LINE_LOOKBACK)
    trains: dict[tuple[str, str], tuple[str, str | None]] = {}  # (rid, stop) -> (line, direction)
    by_rid: dict[str, tuple[str, str | None]] = {}
    for vid, stop, line, direction in s.execute(
            select(Prediction.vehicle_id, Prediction.stop_id, Prediction.line_id, Prediction.direction)
            .where(Prediction.source == source, Prediction.vehicle_id.in_(rids), Prediction.polled_at >= since)
            .distinct()):
        trains[(vid, stop)] = (line, direction)
        by_rid.setdefault(vid, (line, direction))
    n = 0
    seen: set[tuple[str, str]] = set()
    for a in actuals:
        stop = f"910G{a.tiploc}"
        info = trains.get((a.rid, stop)) or by_rid.get(a.rid)
        if not info or (a.rid, stop) in seen:
            continue  # not a train TfL predicts (another operator), or already stored from this batch
        seen.add((a.rid, stop))
        t = naive_utc(a.arrived_at)
        exists = s.scalar(select(ObservedArrival.id).where(
            ObservedArrival.source == source, ObservedArrival.stop_id == stop, ObservedArrival.vehicle_id == a.rid,
            ObservedArrival.method == METHOD, ObservedArrival.arrived_at >= t - timedelta(minutes=30),
            ObservedArrival.arrived_at <= t + timedelta(minutes=30)))
        if exists:
            continue  # Darwin repeats a train's earlier actual times in later messages
        line, direction = info
        # Darwin's actual times are to the minute (sometimes the half-minute): the true time lies within it
        s.add(ObservedArrival(source=source, stop_id=stop, line_id=line, vehicle_id=a.rid, direction=direction,
                              arrived_at=t, earliest=t, latest=t + timedelta(seconds=59), method=METHOD,
                              quality=1.0))
        n += 1
    return n


class DarwinRecorder(threading.Thread):
    """Runs inside the worker: consumes Darwin continuously and saves London actual arrivals every few seconds.
    Reconnects after errors and never takes the worker down."""

    def __init__(self, session_factory, source: str = "tfl"):
        super().__init__(name="darwin", daemon=True)
        self.session_factory, self.source = session_factory, source
        self.keep = london_tiplocs()
        self.stats = {"messages": 0, "actuals": 0, "stored": 0, "errors": 0}

    def _consumer(self):
        from confluent_kafka import Consumer

        c = Consumer({
            "bootstrap.servers": os.environ["DARWIN_BOOTSTRAP"], "security.protocol": "SASL_SSL",
            "sasl.mechanisms": "PLAIN", "sasl.username": os.environ["DARWIN_USERNAME"],
            "sasl.password": os.environ["DARWIN_PASSWORD"], "group.id": os.getenv("DARWIN_GROUP") or "paxen",
            "auto.offset.reset": "latest", "enable.auto.commit": True})
        c.subscribe([os.environ["DARWIN_TOPIC"]])
        return c

    def run(self) -> None:
        while True:
            try:
                self._consume()
            except Exception as e:  # keep the worker alive whatever the feed does
                self.stats["errors"] += 1
                log.warning("darwin: %s; reconnecting in 30 s", type(e).__name__)
                time.sleep(30)

    def _consume(self) -> None:
        c = self._consumer()
        pending: list[Actual] = []
        last_flush = last_log = time.monotonic()
        try:
            while True:
                m = c.poll(1.0)
                if m is not None and not m.error():
                    self.stats["messages"] += 1
                    found = parse(m.value() or b"", self.keep)
                    self.stats["actuals"] += len(found)
                    pending += found
                if pending and time.monotonic() - last_flush >= FLUSH_EVERY_S:
                    with self.session_factory() as s:
                        self.stats["stored"] += store(s, pending, self.source)
                        s.commit()
                    pending, last_flush = [], time.monotonic()
                if time.monotonic() - last_log >= 600:
                    log.info("darwin: %s", self.stats)
                    last_log = time.monotonic()
        finally:
            c.close()


def start(session_factory, source: str = "tfl") -> DarwinRecorder | None:
    if not configured():
        return None
    try:
        import confluent_kafka  # noqa: F401
    except ImportError:
        log.error("darwin: confluent-kafka isn't installed; measured rail arrivals are off")
        return None
    rec = DarwinRecorder(session_factory, source)
    rec.start()
    log.info("darwin: recording measured arrivals at %d Overground/Elizabeth line stations", len(rec.keep))
    return rec
