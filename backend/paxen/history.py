"""The history store: every recorded day kept permanently, outside the database.

The database is the live working copy and sits on a small, expensive disk. Each London day, once it is over, is
written to the archive's storage (Cloudflare R2) as one compressed Parquet file per table:

    history/<source>/<table>/<YYYY-MM-DD>.parquet

then read back and its row count checked, and recorded in `exported_days`. Parquet is columnar and compressed, so a
day takes about a tenth of its size in Postgres, and R2 storage costs a small fraction of Railway's.

Order of events for a day, which is what keeps nothing from being lost:
  1. the day ends; 2 hours later (late inferred arrivals) it is exported in full (export_pending);
  2. only then may the database copy be thinned to the evaluation's sample (evaluate.thin_history skips days not
     exported while the store is configured);
  3. only then, and only with PAXEN_DB_KEEP_DAYS set, is the database copy dropped after that many days
     (drop_exported). Unset or 0: the database keeps every day.

Days recorded before this existed had already been thinned in the database; they are exported as they are and
marked `partial`. Their raw responses are in the archive, so they can be rebuilt in full.

Models that learn from long history (the journey model) read these files (read_day), not the database.
"""
from __future__ import annotations

import io
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Float, Integer, delete, func, select
from sqlalchemy.orm import Session

from .db import DaySample, ExportedDay, ObservedArrival, Prediction, StationCrowding
from .timeutil import LONDON, aware, naive_utc

log = logging.getLogger("paxen.history")

# table name -> (model, the column that dates a row)
TABLES = {
    "predictions": (Prediction, Prediction.polled_at),
    "observed_arrivals": (ObservedArrival, ObservedArrival.arrived_at),
    "station_crowding": (StationCrowding, StationCrowding.polled_at),
}
READY_AFTER = timedelta(hours=2)  # a day is exported this long after it ends (arrivals inferred late, Darwin)
CHUNK = 50_000  # rows per Parquet row group, so memory stays small however big the day is
DAYS_PER_RUN = 3
DROP_SLICE = timedelta(minutes=30)
DROP_PAUSE_S = 2.0


def _of_source(model, source: str) -> list:
    """The filter for one data source, for tables that record it (station crowding is TfL's only)."""
    col = model.__table__.c.get("source")
    return [col == source] if col is not None else []


def key_for(source: str, table: str, day: str) -> str:
    return f"history/{source}/{table}/{day}.parquet"


def _day_bounds(day: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=LONDON)
    end = (start + timedelta(hours=36)).replace(hour=0)  # the next London midnight, across clock changes
    return naive_utc(start.astimezone(timezone.utc)), naive_utc(end.astimezone(timezone.utc))


def _schema(model):
    import pyarrow as pa

    def kind(col):
        t = col.type
        if isinstance(t, Integer):
            return pa.int64()
        if isinstance(t, Float):
            return pa.float64()
        if isinstance(t, Boolean):
            return pa.bool_()
        if isinstance(t, DateTime):
            return pa.timestamp("us")
        return pa.string()  # strings; JSON is stored as its text

    cols = list(model.__table__.columns)
    return cols, pa.schema([(c.name, kind(c)) for c in cols])


def export_table(s: Session, model, dated, source: str, day: str) -> tuple[bytes, int]:
    """One day of one table as Parquet bytes, streamed from the database in chunks."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    cols, schema = _schema(model)
    json_cols = {c.name for c in cols if c.type.__class__.__name__ == "JSON"}
    a, b = _day_bounds(day)
    q = (select(*cols).where(dated >= a, dated < b, *_of_source(model, source))
         .order_by(dated).execution_options(yield_per=CHUNK))
    buf, rows = io.BytesIO(), 0
    with pq.ParquetWriter(buf, schema, compression="zstd") as w:
        batch: list[tuple] = []

        def flush():
            data = {c.name: [r[i] for r in batch] for i, c in enumerate(cols)}
            for name in json_cols:
                data[name] = [None if v is None else json.dumps(v) for v in data[name]]
            w.write_table(pa.table(data, schema=schema))

        for r in s.execute(q):
            batch.append(tuple(r))
            if len(batch) >= CHUNK:
                flush()
                rows += len(batch)
                batch = []
        if batch:
            flush()
            rows += len(batch)
    return buf.getvalue(), rows


def _days_with_data(s: Session, source: str) -> list[str]:
    lo = s.scalar(select(func.min(Prediction.polled_at)).where(Prediction.source == source))
    lo_a = s.scalar(select(func.min(ObservedArrival.arrived_at)).where(ObservedArrival.source == source))
    first = min(x for x in (lo, lo_a) if x is not None) if (lo or lo_a) else None
    if first is None:
        return []
    day = aware(first).astimezone(LONDON).date()
    out = []
    while True:
        out.append(str(day))
        day = day + timedelta(days=1)
        if day > datetime.now(timezone.utc).astimezone(LONDON).date():
            return out


def exported_days(s: Session, source: str) -> set[str]:
    """Days with every table safely in the store."""
    have: dict[str, set] = {}
    for d, t in s.execute(select(ExportedDay.day, ExportedDay.table).where(ExportedDay.source == source)):
        have.setdefault(d, set()).add(t)
    return {d for d, ts in have.items() if ts >= set(TABLES)}


def export_pending(s: Session, source: str, now: datetime, archive, max_days: int = DAYS_PER_RUN,
                   on_table=None) -> dict:
    """Export every finished day not yet in the store (oldest first), and check each file by reading it back."""
    import pyarrow.parquet as pq

    out: dict = {"days": [], "rows": 0, "mb": 0.0}
    if archive is None:
        return out
    done = {(d, t) for d, t in s.execute(select(ExportedDay.day, ExportedDay.table)
                                          .where(ExportedDay.source == source))}
    thinned = {d for (d,) in s.execute(select(DaySample.day).where(DaySample.source == source,
                                                                     DaySample.thinned.is_(True)))}
    # Days still complete in the database go first: they hold the full detail, and thinning (which keeps the disk
    # in check) waits for them. Older, already-thinned days are backfilled after.
    days = sorted(_days_with_data(s, source), key=lambda d: (d in thinned, d))
    for day in days:
        if len(out["days"]) >= max_days:
            break
        _, end = _day_bounds(day)
        if aware(end) + READY_AFTER > aware(now):
            continue  # not over yet
        missing = [t for t in TABLES if (day, t) not in done]
        if not missing:
            continue
        for table in missing:
            if on_table:
                on_table(day, table)
            model, dated = TABLES[table]
            data, rows = export_table(s, model, dated, source, day)
            key = key_for(source, table, day)
            archive.put_bytes(key, data)
            back = pq.ParquetFile(io.BytesIO(archive.get_bytes(key))).metadata.num_rows
            if back != rows:
                raise RuntimeError(f"history check failed for {key}: wrote {rows} rows, read back {back}")
            s.add(ExportedDay(source=source, table=table, day=day, key=key, rows=rows, bytes=len(data),
                              partial=day in thinned))
            s.commit()
            out["rows"] += rows
            out["mb"] = round(out["mb"] + len(data) / 1e6, 1)
        out["days"].append(day)
    return out


def drop_exported(s: Session, source: str, now: datetime, keep_days: int | None = None,
                  pause_s: float = DROP_PAUSE_S) -> dict:
    """Free the database: drop the database copy of days older than PAXEN_DB_KEEP_DAYS whose every table is safely
    in the store. Unset or 0: nothing is dropped."""
    keep = keep_days if keep_days is not None else int(os.getenv("PAXEN_DB_KEEP_DAYS", "0") or 0)
    out: dict = {"days": [], "deleted": 0}
    if keep <= 0:
        return out
    cutoff = aware(now).astimezone(LONDON).date() - timedelta(days=keep)
    safe = exported_days(s, source)
    for day in sorted(safe):
        if datetime.strptime(day, "%Y-%m-%d").date() >= cutoff:
            break
        recs = s.scalars(select(ExportedDay).where(ExportedDay.source == source, ExportedDay.day == day)).all()
        if all(r.dropped for r in recs):
            continue
        a, b = _day_bounds(day)
        for model, dated in TABLES.values():
            t = a
            while t < b:  # a slice at a time, so the write-ahead log (on the same disk) stays small
                u = min(t + DROP_SLICE, b)
                res = s.execute(delete(model).where(*_of_source(model, source), dated >= t, dated < u))
                s.commit()
                out["deleted"] += res.rowcount or 0
                t = u
                if pause_s:
                    time.sleep(pause_s)
        for r in recs:
            r.dropped = True
        s.commit()
        out["days"].append(day)
    return out


def read_day(archive, source: str, table: str, day: str, columns: list[str] | None = None,
             cache_dir: str | None = None):
    """One day of one table from the store, as a pyarrow Table. Files are cached locally (they never change)."""
    import pyarrow.parquet as pq

    key = key_for(source, table, day)
    cache = Path(cache_dir or os.getenv("PAXEN_HISTORY_CACHE", "/tmp/paxen-history")) / key
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".part")
        tmp.write_bytes(archive.get_bytes(key))
        tmp.replace(cache)
    return pq.read_table(cache, columns=columns)


# ------------------------------------------------------------------ rebuilding thinned days from the raw archive
def prefetch(fetch, keys: list, workers: int = 8, ahead: int = 32):
    """fetch(key) for each key, in order, with up to `ahead` downloads running in the background: a day is
    thousands of small objects, and one at a time it is the round trips that take the time. Memory stays bounded."""
    from collections import deque
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(workers) as ex:
        it, queue = iter(keys), deque()
        for k in it:
            queue.append(ex.submit(fetch, k))
            if len(queue) >= ahead:
                break
        while queue:
            body = queue.popleft().result()
            k = next(it, None)
            if k is not None:
                queue.append(ex.submit(fetch, k))
            yield body


REBUILT = "trackernet_rebuild"  # exported_days marker: this day's measured arrivals were rebuilt (rows: how many)


def rebuild_trackernet_day(archive, tn, source: str, day: str) -> list[tuple] | None:
    """A day's measured Tube arrivals, rebuilt from the raw Trackernet responses in the archive by running them
    through the recorder's own logic (recorder.record_trackernet) in a scratch database. None: none archived."""
    import gzip
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from .db import Base
    from .recorder import record_trackernet
    from .trackernet import parse_summary

    a, b = _day_bounds(day)
    keys = []
    for utc_day in sorted({str(a.date()), str((b - timedelta(seconds=1)).date())}):
        keys += [k for k in archive.list_keys(f"raw/{source}/{utc_day}/") if "/trackernet-" in k]
    if not keys:
        return None
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    scratch = sessionmaker(bind=eng, expire_on_commit=False)()
    present: dict = {}

    class Replayed:
        """Stands in for the Trackernet client: answers each poll from the archived responses."""
        raws: dict = {}

        def summary(self, code):
            raw = self.raws[code].encode()  # a line missing from this poll: KeyError, logged as a failed line
            ts, trains = parse_summary(raw, code)
            return ts, trains, raw

        def station_map(self, code, names):
            return tn.station_map(code, names)

    def when_of(key):  # raw/<source>/<date>/<HH>/trackernet-<HHMMSS>.json.gz
        date, _, name = key.split("/")[-3:]
        return datetime.strptime(f"{date} {name.removesuffix('.json.gz').rsplit('-', 1)[-1]}", "%Y-%m-%d %H%M%S")

    poll = Replayed()
    wanted = [(when_of(k), k) for k in keys]
    wanted = sorted((w, k) for w, k in wanted if a - timedelta(minutes=30) <= w < b)
    for (when, _), body in zip(wanted, prefetch(archive.get_bytes, [k for _, k in wanted])):
        poll.raws = json.loads(gzip.decompress(body))
        record_trackernet(scratch, poll, when.replace(tzinfo=timezone.utc), source, present=present, keep_raw=False)
    rows = [(o.source, o.stop_id, o.line_id, o.vehicle_id, o.direction, o.arrived_at, o.earliest, o.latest)
            for o in scratch.query(ObservedArrival).filter(ObservedArrival.arrived_at >= a,
                                                           ObservedArrival.arrived_at < b)]
    scratch.close()
    eng.dispose()
    return rows


def rebuild_pending(s: Session, source: str, archive, tn, max_days: int = 1, on_day=None) -> dict:
    """Worker: for days exported `partial` (thinned before the store existed), rebuild every measured Tube arrival
    from the raw archive and replace the day's observed_arrivals file with them (Darwin and inferred arrivals
    that were kept are carried over). One day per run: about 3,000 archived responses each."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    out: dict = {"days": []}
    if archive is None or tn is None:
        return out
    done = {d for (d,) in s.execute(select(ExportedDay.day).where(ExportedDay.source == source,
                                                                  ExportedDay.table == REBUILT))}
    partial = s.scalars(select(ExportedDay).where(ExportedDay.source == source, ExportedDay.partial.is_(True),
                                                  ExportedDay.table == "observed_arrivals")
                        .order_by(ExportedDay.day)).all()
    for rec in [r for r in partial if r.day not in done][:max_days]:
        if on_day:
            on_day(rec.day)
        rows = rebuild_trackernet_day(archive, tn, source, rec.day)
        n = 0
        if rows:
            old = pq.read_table(io.BytesIO(archive.get_bytes(rec.key)))
            keep = old.filter(pa.compute.not_equal(old.column("method"), "trackernet"))
            cols = ("source", "stop_id", "line_id", "vehicle_id", "direction", "arrived_at", "earliest", "latest")
            new = pa.Table.from_pylist(
                [{**{c: None for c in keep.column_names}, **dict(zip(cols, r)), "method": "trackernet", "quality": 1.0}
                 for r in rows], schema=keep.schema)
            merged = pa.concat_tables([keep, new])
            buf = io.BytesIO()
            pq.write_table(merged, buf, compression="zstd")
            archive.put_bytes(rec.key, buf.getvalue())
            back = pq.ParquetFile(io.BytesIO(archive.get_bytes(rec.key))).metadata.num_rows
            if back != merged.num_rows:
                raise RuntimeError(f"rebuild check failed for {rec.key}")
            rec.rows, rec.bytes, rec.partial, n = merged.num_rows, len(buf.getvalue()), False, len(rows)
            cache = Path(os.getenv("PAXEN_HISTORY_CACHE", "/tmp/paxen-history")) / rec.key
            cache.unlink(missing_ok=True)
        s.add(ExportedDay(source=source, table=REBUILT, day=rec.day, key="", rows=n, bytes=0))
        s.commit()
        out["days"].append({"day": rec.day, "arrivals": n})
    return out
