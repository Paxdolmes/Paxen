"""Real journey times, replayed from measured train movements.

Trackernet records when each Tube train (by its set number) reaches each platform. So for any journey and any
departure time we can work out what really would have happened: get to the platform, board the first train that
actually came and went on to your stop, ride it, change, and so on. That is the ground truth the journey model
learns from and is judged against: door-to-door minutes, waits and changes included, for every departure of every
day, without needing anyone to have made the trip.

Rules (written down before any results were seen; see docs/journey-model.md):
- You can catch a train that reached the platform up to BOARD_SLACK_S before you did (it waits there a little).
- You board the first train that afterwards reaches your stop on the same line, before coming back through your
  boarding stop and within MAX_RIDE of planned ride time. Trains that turn short or go another way are let go.
- A train let go that the line map says should have reached your stop (seen later beyond it, same direction) means
  a gap in the tracking, not a train that didn't stop: that departure is marked `gap` and isn't used.
- Unidentified trains (placeholder set numbers) can't be followed, so they are never boarded; and if one reached
  your platform before the train you boarded, we can't tell whether it would have taken you, so that departure is
  marked `gap` too (otherwise lines with many of them, like the Metropolitan, would look slower than they are).
- No train within MAX_WAIT_MIN: no answer for that departure (service suspended, or no tracking).
- Amendment 1 (17 Nov 2026): if the whole network's tracking went silent for more than SILENT_MIN (no measured
  arrival on any line) at any point between leaving and arriving, the recorder or the feed was down: the
  departure is marked `outage` and isn't used. A suspension on one line doesn't silence the network, so real
  delays are kept.
- Amendment 2 (17 Nov 2026): Trackernet misses a train at about one station in eight, and some platforms
  altogether (Oxford Circus on the Victoria line). Where a train was seen at two stations a few stops apart,
  the stations between them on NUMBAT's map of the line are filled in (it passed them, at times spaced evenly
  between the two sightings). And a train is followed only until it comes back to a station it already passed
  on this ride: it turned round, so an arrival at your stop after that is on its way back, not your journey.
- Also in Amendment 2: a train can be boarded while it is still at the platform, not only if it arrived after
  you. When it leaves is estimated from where it was seen next, less the usual running time there (from trains
  passing through). This matters at the ends of lines, where trains stand for several minutes. Of the trains
  you could board, you take the one that gets you there first: at an end of the line, the one that leaves first
  is not always the one that came in first.
"""
from __future__ import annotations

import bisect
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .domain import PLACEHOLDER_VEHICLE_IDS
from .timeutil import LONDON, naive_utc

log = logging.getLogger("paxen.replay")

BOARD_SLACK_S = 20
MAX_WAIT_MIN = 60
MAX_RIDE_FACTOR, MAX_RIDE_EXTRA_MIN = 3.0, 15.0
SILENT_MIN = 3  # the whole Tube never goes this long without a train reaching some platform, while it runs
FILL_MAX_STATIONS = 3  # at most this many stations missed between two sightings of a train are filled in
FILL_MAX_MIN_PER_LINK = 4.0  # and only if it took no longer than this per link (no reversal or long stop between)
MAX_STAND_MIN = 30  # longest a train is taken to stand at a platform in service (longer: out of service)
VERSION = 3  # of these rules; days replayed under an older version are replayed again (and re-evaluated)


def fill_missed(arrivals: list, nb=None) -> list:
    """The arrivals plus the stations each train must have passed between two sightings without being seen there,
    on NUMBAT's map of the line: only along one direction (no reversing), at most FILL_MAX_STATIONS, and only
    when the time between the sightings fits. Times are spaced evenly between the two sightings."""
    if nb is None:
        from . import numbat

        nb = numbat.get()
    if nb is None:
        return list(arrivals)
    naptans: dict[tuple, list[str]] = defaultdict(list)
    for key, codes in nb.stations.items():
        for naptan, code in codes.items():
            naptans[(key, code)].append(naptan)
    trains: dict[tuple, list] = defaultdict(list)
    for a in arrivals:
        if a[2] is not None and a[2] not in PLACEHOLDER_VEHICLE_IDS:
            trains[(a[0], a[2])].append(a)
    paths: dict[tuple, list | None] = {}
    out = list(arrivals)
    for (line, veh), seen in trains.items():
        key = nb.key_of(line)
        if not key:
            continue
        seen.sort(key=lambda a: a[4])
        for (_, s1, _, d1, t1), (_, s2, _, d2, t2) in zip(seen, seen[1:]):
            c1, c2 = nb.code_of(key, s1), nb.code_of(key, s2)
            if not c1 or not c2 or c1 == c2:
                continue
            k = (key, c1, c2)
            if k not in paths:
                paths[k] = nb._path(key, c1, c2)
            path = paths[k]
            if not path or not 2 <= len(path) <= FILL_MAX_STATIONS + 1:
                continue  # next to each other, too far apart, or no way from one to the other without reversing
            if t2 - t1 > timedelta(minutes=FILL_MAX_MIN_PER_LINK * len(path)):
                continue
            for i, (_, x) in enumerate(path[:-1], start=1):
                tx = t1 + (t2 - t1) * i / len(path)
                for stop in naptans.get((key, x), ()):
                    out.append((line, stop, veh, d1 if d1 == d2 else None, tx))
    return out
DEPART_FROM, DEPART_TO, DEPART_STEP_MIN = "06:00", "22:00", 5


@dataclass
class Ride:
    board: datetime
    arrive: datetime
    vehicle: str
    let_go: int  # trains that came first but didn't go to your stop
    gap: bool  # one of those should have: a tracking gap


class Index:
    """One day's measured arrivals: by platform (line, stop) and by train (line, set number), sorted by time."""

    def __init__(self, arrivals, fill: bool = True, nb=None):
        """arrivals: (line_id, stop_id, vehicle_id, direction, arrived_at naive UTC). With `fill`, stations a
        train was missed at are filled in (fill_missed)."""
        if fill:
            arrivals = fill_missed(arrivals, nb)
        by_train: dict[tuple, list] = defaultdict(list)
        unknown: dict[tuple, list] = defaultdict(list)
        every: list[datetime] = []
        for line, stop, veh, direction, t in arrivals:
            every.append(t)
            if veh is None or veh in PLACEHOLDER_VEHICLE_IDS:
                unknown[(line, stop)].append(t)
                continue
            by_train[(line, veh)].append((t, stop, direction))

        def order(x):  # by time; ties by the rest, where a missing direction sorts first (and can't break a sort)
            return x[0], x[1] or "", x[2] or ""

        self.by_train = {k: sorted(v, key=order) for k, v in by_train.items()}
        self.train_times = {k: [x[0] for x in v] for k, v in self.by_train.items()}
        self.unknown = {k: sorted(v) for k, v in unknown.items()}
        # When each train left each station: where it was seen next, less the usual running time there (median
        # of trains passing through, neither starting nor turning round; into an end of the line, the run the
        # other way). A train that seems to stand longer than MAX_STAND_MIN was out of service: it left on arrival.
        import statistics

        runs: dict[tuple, list[float]] = defaultdict(list)
        for (line, _), traj in self.by_train.items():
            for (_, s0, _), (t1, s1, _), (t2, s2, _) in zip(traj, traj[1:], traj[2:]):
                if s0 != s1 and s1 != s2 and s0 != s2:
                    runs[(line, s1, s2)].append((t2 - t1).total_seconds())
        run = {k: statistics.median(v) for k, v in runs.items() if len(v) >= 3}
        stand = timedelta(minutes=MAX_STAND_MIN)
        at_stop: dict[tuple, list] = defaultdict(list)
        for (line, veh), traj in self.by_train.items():
            n, j = len(traj), 0
            for i, (t1, s1, direction) in enumerate(traj):
                j = max(j, i + 1)
                while j < n and traj[j][1] == s1:
                    j += 1  # (seen again at the same station: still there)
                leave = t1
                if j < n:
                    r = run.get((line, s1, traj[j][1]), run.get((line, traj[j][1], s1)))
                    if r is not None:
                        est = traj[j][0] - timedelta(seconds=r)
                        leave = max(t1, est) if est - t1 <= stand else t1
                at_stop[(line, s1)].append((t1, veh, direction, leave))
        self.at_stop = {k: sorted(v, key=order) for k, v in at_stop.items()}
        self.times = {k: [x[0] for x in v] for k, v in self.at_stop.items()}
        # Silences: stretches longer than SILENT_MIN with no measured arrival anywhere (before the first and after
        # the last arrival of the data included)
        every.sort()
        quiet = timedelta(minutes=SILENT_MIN)
        self.silences = ([(datetime.min, every[0])] if every else [(datetime.min, datetime.max)]) + \
            [(a, b) for a, b in zip(every, every[1:]) if b - a > quiet] + ([(every[-1], datetime.max)] if every else [])
        self._silence_ends = [b for _, b in self.silences]
        self.first, self.last = (every[0], every[-1]) if every else (None, None)

    def silent_between(self, a: datetime, b: datetime) -> bool:
        """Was the whole network's tracking silent (for more than SILENT_MIN) at any point in [a, b]?"""
        k = bisect.bisect_right(self._silence_ends, a)
        return k < len(self.silences) and self.silences[k][0] < b

    def unknown_between(self, line: str, stop: str, a: datetime, b: datetime) -> bool:
        """Did an unidentified train reach this platform in [a, b)?"""
        ts = self.unknown.get((line, stop))
        return bool(ts) and bisect.bisect_left(ts, a) < bisect.bisect_left(ts, b)

    def covers(self, line: str, stop: str) -> bool:
        return (line, stop) in self.at_stop


def _serves(line, a, b, last_stop, bound) -> bool | None:
    try:
        from . import numbat

        return numbat.serves(line, a, b, last_stop, bound)
    except Exception:
        return None


def ride(idx: Index, line: str, a: str, b: str, t: datetime, planned_min: float) -> Ride | None:
    """The train you'd take from a to b, reaching a's platform at t: of the trains still there or yet to come,
    the one that gets to b first. None: none within MAX_WAIT_MIN."""
    plats = idx.at_stop.get((line, a))
    if not plats:
        return None
    times = idx.times[(line, a)]
    max_ride = timedelta(minutes=planned_min * MAX_RIDE_FACTOR + MAX_RIDE_EXTRA_MIN)
    slack = timedelta(seconds=BOARD_SLACK_S)
    best: Ride | None = None
    passed_over: list[tuple[datetime, bool]] = []  # trains not taken: when they were at a, and a tracking gap
    for k in range(bisect.bisect_left(times, t - timedelta(minutes=MAX_STAND_MIN)), len(plats)):
        ta, veh, direction, leave = plats[k]
        if leave < t - slack:
            continue  # it had left before you got there
        if ta - t > timedelta(minutes=MAX_WAIT_MIN) or (best is not None and ta >= best.arrive):
            break  # nothing later can get you there sooner
        arrive, last = _follow(idx, line, veh, ta, a, b, max_ride)
        if arrive is not None:
            if best is None or arrive < best.arrive:
                best = Ride(ta, arrive, veh, 0, False)
        else:
            passed_over.append((ta, bool(last and _serves(line, a, b, last, direction))))
    if best is None:
        return None
    before = [g for when, g in passed_over if when < best.board]
    gap = any(before) or idx.unknown_between(line, a, t - slack, best.board)
    return Ride(best.board, best.arrive, best.vehicle, len(before), gap)


def _follow(idx: Index, line: str, veh: str, ta: datetime, a: str, b: str,
            max_ride: timedelta) -> tuple[datetime | None, str | None]:
    """Where train `veh`, at a at ta, went next: (when it reached b, None), or (None, the last station it was
    seen at before turning round or running out of time)."""
    traj = idx.by_train[(line, veh)]
    i = bisect.bisect_right(idx.train_times[(line, veh)], ta)
    last, prev, passed = None, a, {a}
    for tt, stop, _ in traj[i:]:
        if tt - ta > max_ride or (stop in passed and stop != prev):
            break  # too long, or back at a station it already passed (your stop included): it turned round
        passed.add(stop)
        prev = stop  # (seen twice in a row at one station is a train standing there, not turning round)
        if stop == b:
            return tt, None
        if stop != a:
            last = stop
    return None, last


def journey_time(idx: Index, legs: list[dict], depart: datetime) -> dict | None:
    """Door-to-door (first platform to last) for one departure: minutes, time waiting, riding and walking."""
    t, wait, riding, walking, let_go, gap = depart, 0.0, 0.0, 0.0, 0, False
    for leg in legs:
        if "walk" in leg:
            t += timedelta(minutes=leg["walk"])
            walking += leg["walk"]
            continue
        r = ride(idx, leg["line_id"], leg["from"], leg["to"], t, leg["minutes"])
        if r is None:
            return None
        wait += max(0.0, (r.board - t).total_seconds() / 60)
        riding += (r.arrive - max(r.board, t)).total_seconds() / 60  # (a train already standing there: from now)
        let_go += r.let_go
        gap = gap or r.gap
        t = max(t, r.arrive)
    outage = idx.silent_between(depart - timedelta(seconds=BOARD_SLACK_S), t)
    return {"minutes": round((t - depart).total_seconds() / 60, 2), "wait": round(wait, 2),
            "ride": round(riding, 2), "walk": round(walking, 2), "let_go": let_go, "gap": gap or outage,
            "outage": outage}


def departures(day: str) -> list[datetime]:
    """Every DEPART_STEP_MIN between DEPART_FROM and DEPART_TO, London time, as naive UTC."""
    d = datetime.strptime(day, "%Y-%m-%d")
    h0, m0 = map(int, DEPART_FROM.split(":"))
    h1, m1 = map(int, DEPART_TO.split(":"))
    t = d.replace(hour=h0, minute=m0, tzinfo=LONDON)
    end = d.replace(hour=h1, minute=m1, tzinfo=LONDON)
    out = []
    while t <= end:
        out.append(naive_utc(t.astimezone(timezone.utc)))
        t = (t.astimezone(timezone.utc) + timedelta(minutes=DEPART_STEP_MIN)).astimezone(LONDON)
    return out


def replay_day(idx: Index, panel: list[dict], day: str) -> list[dict]:
    rows = []
    for j in panel:
        rides = [l for l in j["legs"] if "line_id" in l]
        if not all(idx.covers(l["line_id"], l["from"]) and idx.covers(l["line_id"], l["to"]) for l in rides):
            continue  # a platform Trackernet doesn't report on that day
        planned = sum(l.get("minutes", 0) for l in rides) + sum(l.get("walk", 0) for l in j["legs"])
        for dep in departures(day):
            res = journey_time(idx, j["legs"], dep)
            rows.append({"day": day, "journey": j["id"], "depart": dep, "planned_min": planned,
                         **(res or {"minutes": None, "wait": None, "ride": None, "walk": None, "let_go": None,
                                    "gap": None, "outage": None})})
    return rows


def _spread(xs: list[float]) -> dict | None:
    import statistics

    if not xs:
        return None
    s = sorted(xs)
    return {"p10": round(s[len(s) // 10], 1), "p50": round(statistics.median(s), 1), "p90": round(s[len(s) * 9 // 10], 1)}


def summarise(rows: list[dict], panel: list[dict], idx: Index | None = None, day: str | None = None) -> dict:
    """A day's replay at a glance: how much was measured, and real minutes against planned, overall and by the
    journey's first line. With the day's Index: when tracking ran, and how long it was silent in service hours."""
    import statistics

    good = [r for r in rows if r["minutes"] is not None and not r["gap"]]
    first_line = {j["id"]: next((l["line_id"] for l in j["legs"] if "line_id" in l), None) for j in panel}
    by_line: dict[str, list[float]] = defaultdict(list)
    for r in good:
        by_line[first_line.get(r["journey"])].append(r["minutes"] - r["planned_min"])
    out = {
        "version": VERSION,
        "journeys_in_panel": len(panel), "journeys_measured": len({r["journey"] for r in rows}),
        "departures": len(rows), "answered": len([r for r in rows if r["minutes"] is not None]),
        "gaps": len([r for r in rows if r["gap"] and not r.get("outage")]),
        "outages": len([r for r in rows if r.get("outage")]), "usable": len(good),
        "minutes_over_planned": _spread([r["minutes"] - r["planned_min"] for r in good]),
        "wait_median": round(statistics.median(r["wait"] for r in good), 1) if good else None,
        "by_first_line": {k: {"usable": len(v), **(_spread(v) or {})} for k, v in sorted(by_line.items(), key=str)},
    }
    if idx is not None and day is not None and idx.first is not None:
        deps = departures(day)
        lo, hi = deps[0], deps[-1]
        silent = sum(max(timedelta(0), min(b, hi) - max(a, lo)).total_seconds() for a, b in idx.silences) / 60

        def clock(t):
            return t.replace(tzinfo=timezone.utc).astimezone(LONDON).strftime("%H:%M")

        out["tracked"] = {"from": clock(idx.first), "to": clock(idx.last),
                          "silent_min_06_22": round(silent, 1)}
    return out


def load_panel() -> list[dict]:
    from .journey_panel import PANEL_FILE

    return json.loads(PANEL_FILE.read_text()) if PANEL_FILE.exists() else []


REPORT = "replay_report"  # an AppSecret row (the small key-value store the API and worker share); not secret


def _arrivals_from_store(archive, source: str, day: str):
    from .history import read_day

    t = read_day(archive, source, "observed_arrivals", day,
                 columns=["line_id", "stop_id", "vehicle_id", "direction", "arrived_at", "method"])
    cols = {c: t.column(c).to_pylist() for c in t.column_names}
    return [(cols["line_id"][i], cols["stop_id"][i], cols["vehicle_id"][i], cols["direction"][i], cols["arrived_at"][i])
            for i in range(t.num_rows) if cols["method"][i] == "trackernet"]


def _forget_cached(key: str) -> None:
    """A replayed day's file can be replaced (new rules): drop any local copy history.read_day cached."""
    import os
    from pathlib import Path

    (Path(os.getenv("PAXEN_HISTORY_CACHE", "/tmp/paxen-history")) / key).unlink(missing_ok=True)


def replay_pending(s, source: str, archive, max_days: int = 2, on_day=None) -> dict:
    """Worker (after each history export): replay the panel on every fully exported day not yet replayed, store
    the journey times (history/<source>/journey_times/<day>.parquet) and update the report."""
    import io

    import pyarrow as pa
    import pyarrow.parquet as pq
    from sqlalchemy import select

    from .db import AppSecret, ExportedDay
    from .history import key_for

    panel = load_panel()
    out: dict = {"days": []}
    if archive is None or not panel:
        return out
    full = [d for (d,) in s.execute(select(ExportedDay.day).where(
        ExportedDay.source == source, ExportedDay.table == "observed_arrivals", ExportedDay.partial.is_(False),
        ExportedDay.rows > 0)
        .order_by(ExportedDay.day))]
    row = s.get(AppSecret, REPORT)
    report = json.loads(row.value) if row else {"days": {}}
    if report.get("version") != VERSION:  # the rules changed: every day is replayed again under the new ones
        s.query(ExportedDay).filter(ExportedDay.source == source, ExportedDay.table == "journey_times").delete()
        report = {"version": VERSION, "days": {}}
        if row is None:
            row = AppSecret(name=REPORT, value="")
            s.add(row)
        row.value = json.dumps(report)
        s.commit()
    done = {d for (d,) in s.execute(select(ExportedDay.day).where(
        ExportedDay.source == source, ExportedDay.table == "journey_times"))}
    for day in [d for d in full if d not in done][:max_days]:
        if on_day:
            on_day(day)
        idx = Index(_arrivals_from_store(archive, source, day))
        rows = replay_day(idx, panel, day)
        buf = io.BytesIO()
        pq.write_table(pa.Table.from_pylist(rows), buf, compression="zstd")
        key = key_for(source, "journey_times", day)
        archive.put_bytes(key, buf.getvalue())
        _forget_cached(key)
        s.add(ExportedDay(source=source, table="journey_times", day=day, key=key, rows=len(rows),
                          bytes=len(buf.getvalue())))
        report["days"][day] = summarise(rows, panel, idx, day)
        out["days"].append(day)
        if row is None:
            row = AppSecret(name=REPORT, value="")
            s.add(row)
        row.value = json.dumps(report)
        s.commit()  # a day at a time: a run cut short keeps the days it finished
    return out
