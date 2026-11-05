"""Check the forecast's waits (the part used when there's no live countdown) against live TfL arrivals.

    python -m paxen.waitcheck [--pairs N] [--lead MIN] [--seed S]

For random single-line trips starting `lead` minutes from now (default 15, inside the countdown's reach), it compares
three ways of estimating the wait at the boarding stop with the wait TfL's live countdown then shows, i.e. the first
train that will call at the alighting stop (its destination lies beyond that stop on NUMBAT's network):

    typical    half a flat headway per mode (what Paxen did before NUMBAT)
    frequency  half TfL's scheduled headway for the leg, day and time (NUMBAT)
    paxen      what the forecast does now: the timetabled departure on services 8+ minutes apart, else frequency

The "truth" is TfL's own prediction 10-25 minutes ahead (about a minute out, per docs/live-data-findings.md), so this
judges the no-countdown estimates, not the countdown. One run is one moment of one day: repeat at other times.
"""
from __future__ import annotations

import json
import logging
import os
import random
import statistics
import sys
from collections import defaultdict
from datetime import timedelta

from . import numbat
from .domain import DEFAULT_HEADWAY_MIN, GOOD
from .engine import TIMETABLE_MIN_HEADWAY, timetable_wait
from .providers.tfl import TflProvider, _dt, dedupe_journeys, parse_journeys, parse_statuses
from .timeutil import LONDON, utcnow

log = logging.getLogger("paxen.waitcheck")

MODE_OF = {"elizabeth": "elizabeth-line", "dlr": "dlr", "liberty": "overground", "lioness": "overground",
           "mildmay": "overground", "suffragette": "overground", "weaver": "overground", "windrush": "overground"}


def _reachable(nb: numbat.Numbat, key: str, start: str, goal: str, direction: str) -> bool:
    """Can a train travelling in `direction` get from station `start` to `goal` (or is it already there)?"""
    seen, todo = {start}, [start]
    while todo:
        node = todo.pop()
        if node == goal:
            return True
        for to in nb.adj.get((key, node), ()):
            if to not in seen and nb.links[(key, node, to)][0] == direction:
                seen.add(to)
                todo.append(to)
    return False


def _summary(rows: list[dict], fields=("typical", "frequency", "paxen")) -> dict:
    if not rows:
        return {"n": 0}
    out = {"n": len(rows), "truth_mean_min": round(statistics.fmean(r["truth"] for r in rows), 2)}
    for f in fields:
        err = [r[f] - r["truth"] for r in rows]
        out[f] = {"mae_min": round(statistics.fmean(abs(e) for e in err), 2), "bias_min": round(statistics.fmean(err), 2)}
    return out


def run(pairs_per_line: int = 8, lead_min: float = 15, seed: int = 1) -> dict:
    nb = numbat.get()
    if nb is None:
        raise SystemExit("NUMBAT data file missing: run `python -m paxen.numbat build` first")
    p = TflProvider(os.getenv("TFL_BASE_URL", "https://api.tfl.gov.uk"), os.getenv("TFL_APP_KEY"))
    now = utcnow()
    depart = now + timedelta(minutes=lead_min)
    statuses = {s.line_id: s.category for s in parse_statuses(p._get(
        "/Line/Mode/tube,overground,elizabeth-line,dlr/Status", {"detail": "true"})[0])}
    rng = random.Random(seed)
    rows: list[dict] = []
    skipped: dict[str, int] = defaultdict(int)
    skipped_lines: dict[str, int] = defaultdict(int)
    for line_id, key in numbat.LINE_KEYS.items():
        if line_id == "tram":
            continue  # headway-managed, and the planner's tram times are not a timetable to test
        if statuses.get(line_id, GOOD) != GOOD:
            skipped["line not in good service"] += pairs_per_line
            continue
        stops = [sp["naptanId"] for sp in p._get(f"/Line/{line_id}/StopPoints")[0] if sp.get("naptanId")]
        for _ in range(pairs_per_line):
            a, b = rng.sample(stops, 2)
            loc = depart.astimezone(LONDON)
            try:
                data = p._get(f"/Journey/JourneyResults/{a}/to/{b}", {
                    "date": loc.strftime("%Y%m%d"), "time": loc.strftime("%H%M"), "timeIs": "Departing",
                    "mode": MODE_OF.get(line_id, "tube"), "journeyPreference": "LeastTime"})[0]
            except Exception:
                skipped["planner error"] += 1
                continue
            single = [j for j in parse_journeys(data)
                      if len(j.transit_legs) == 1 and j.transit_legs[0].line_id == line_id
                      and j.legs[0] is j.transit_legs[0]]
            if not single:
                skipped["no single-line journey"] += 1
                continue
            j = dedupe_journeys(single)
            j = min(j, key=lambda x: x.arrival)
            leg = j.transit_legs[0]
            ids = [i for i in ([leg.from_stop_id] + leg.stop_ids) if i]
            codes = [c for c in (nb.code_of(key, i) for i in ids) if c]
            codes = [c for k, c in enumerate(codes) if not k or codes[k - 1] != c]
            path = nb._path(key, codes[0], codes[1]) if len(codes) >= 2 else None
            if not path:
                skipped["leg not on NUMBAT network"] += 1
                continue
            direction = nb.links[(key, *path[0])][0]
            alight = codes[-1]
            board_at = depart
            # the truth: first train on the board that will call at the alighting stop
            arrivals = p._get(f"/StopPoint/{ids[0]}/Arrivals")[0]
            best = None
            for x in arrivals:
                if x.get("lineId") != line_id:
                    continue
                exp = _dt(x.get("expectedArrival"))
                dest = nb.code_of(key, x.get("destinationNaptanId"))
                if not exp or not dest or exp < board_at + timedelta(seconds=20):
                    continue
                if dest == alight or _reachable(nb, key, alight, dest, direction):
                    best = exp if best is None or exp < best else best
            if best is None:
                skipped["no train on the board for this trip"] += 1
                skipped_lines[line_id] += 1
                continue
            truth = (best - board_at).total_seconds() / 60
            default = DEFAULT_HEADWAY_MIN.get(leg.mode, 8.0)
            hw = nb.headway_min(line_id, ids, board_at)
            freq_wait = (hw or default) / 2
            timed = timetable_wait(leg, board_at, hw or default, GOOD, headway_known=hw is not None)
            rows.append({"line": line_id, "mode": leg.mode, "from": leg.from_name, "to": leg.to_name,
                         "headway": round(hw, 1) if hw else None, "truth": round(truth, 2),
                         "typical": default / 2, "frequency": round(freq_wait, 2),
                         "paxen": round(timed[0], 2) if timed else round(freq_wait, 2),
                         "basis": "timetable" if timed else ("frequency" if hw else "typical")})
    by_class = defaultdict(list)
    for r in rows:
        by_class["8+ min apart (timetable)" if (r["headway"] or 0) >= TIMETABLE_MIN_HEADWAY else
                 "under 8 min apart"].append(r)
    by_mode = defaultdict(list)
    for r in rows:
        by_mode[r["mode"]].append(r)
    return {"run_at": now.astimezone(LONDON).strftime("%a %d %b %Y %H:%M"), "lead_min": lead_min,
            "overall": _summary(rows), "by_service": {k: _summary(v) for k, v in sorted(by_class.items())},
            "by_mode": {k: _summary(v) for k, v in sorted(by_mode.items())}, "skipped": dict(skipped),
            "no_train_on_board_by_line": dict(skipped_lines), "rows": rows}


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # request lines include the app_key
    args = sys.argv[1:]
    get = lambda flag, d: type(d)(args[args.index(flag) + 1]) if flag in args else d  # noqa: E731
    rep = run(get("--pairs", 8), get("--lead", 15.0), get("--seed", 1))
    print(json.dumps({k: v for k, v in rep.items() if k != "rows" or "--rows" in args}, indent=1, default=str))


if __name__ == "__main__":
    main()
