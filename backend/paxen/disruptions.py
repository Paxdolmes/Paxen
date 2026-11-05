"""How long do Tube disruptions last? Learned from TfL's line-status history (April 2022 - October 2026).

TfL's "trains service status messages" record every status shown for each Underground line, with start and end
times and the message text. Consecutive messages (gap of a minute or less) form one disruption. From ~120,000
messages this learns, for a line that is disrupted right now:

    P(still disrupted Δ minutes from now | status now, cause, how long it has lasted so far)

Causes are read from the message text ("signal failure", "faulty train", "customer incident", "earlier ..."), the
same way for the history and for TfL's live status. Planned closures and the nightly "Service Closed" are not
disruptions in this sense: they last as scheduled, so Paxen keeps treating them as certain.

Paxen uses it so a disruption *now* weighs on a journey only as much as it's likely to still be there when you
reach that line (engine.forecast_journey). Before, a minor delay at 11:00 was applied in full to tomorrow's commute.

    python -m paxen.disruptions build <status-messages.csv>       # writes paxen/data/disruption_clearance.json
    python -m paxen.disruptions check <status-messages.csv>       # held-out year: Brier scores vs alternatives
"""
from __future__ import annotations

import csv
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DATA_FILE = Path(__file__).with_name("data") / "disruption_clearance.json"
HORIZONS = [5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360]  # minutes ahead
ELAPSED = [(0, 15, "0-15"), (15, 30, "15-30"), (30, 60, "30-60"), (60, 120, "60-120"), (120, 10 ** 9, "120+")]
SHRINK = 50.0  # observations before a group's own curve outweighs its parent's
UNPLANNED = {"Minor Delays": "minor", "Severe Delays": "severe", "Part Suspended": "part_suspended",
             "Suspended": "suspended"}
PLANNED_DESCRIPTIONS = {"part closure", "planned closure", "service closed", "special service"}
GAP_S = 60
MAX_MESSAGE = timedelta(hours=48)  # a single unplanned message can't really stand for longer

CAUSES = [  # first match wins; "earlier" means the incident is over and the line is recovering
    ("earlier", r"\bearlier\b"),
    ("strike", r"strike|industrial action"),
    ("signal", r"signal"),
    ("train_fault", r"faulty train|train fault|failed train|defective train|broken.down train"),
    ("customer", r"customer|person|passenger|someone|ill\b"),
    ("police_security", r"police|security|suspect|emergency services|fire brigade"),
    ("staff_cancellations", r"staff|train operator|cancellation|crew"),
    ("track_power", r"track|points|power|flood|fire|tree|weather|heat|snow|cable|lineside"),
]


def cause_of(text: str | None) -> str:
    t = (text or "").lower()
    for name, pat in CAUSES:
        if re.search(pat, t):
            return name
    return "other"


def elapsed_bucket(minutes: float | None) -> str:
    if minutes is None:
        return "?"
    for lo, hi, name in ELAPSED:
        if lo <= minutes < hi:
            return name
    return "120+"


# ====================================================================== learning from the history
def _parse(path: Path) -> list[dict]:
    fmt = "%d/%m/%Y %H:%M:%S"
    out = []
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            try:
                out.append({"line": r["Line"], "start": datetime.strptime(r["Start Date/Time"], fmt),
                            "end": datetime.strptime(r["End Date/Time"], fmt), "status": r["Service Status"],
                            "text": r["Status Message Details"]})
            except (KeyError, ValueError):
                continue
    return out


def observations(rows: list[dict]) -> list[dict]:
    """One observation per message in an unplanned disruption: its status, cause, how long the disruption had
    lasted when it was shown, and how much longer the disruption went on."""
    by_line: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_line[r["line"]].append(r)
    obs = []
    for line, rs in by_line.items():
        rs.sort(key=lambda r: r["start"])
        episode: list[dict] = []

        def close():
            if episode:
                start, end = episode[0]["start"], max(r["end"] for r in episode)
                for r in episode:
                    obs.append({"line": line, "at": r["start"], "category": UNPLANNED[r["status"]],
                                "cause": cause_of(r["text"]), "elapsed": (r["start"] - start).total_seconds() / 60,
                                "remaining": (end - r["start"]).total_seconds() / 60})
            episode.clear()

        for r in rs:
            if r["end"] < r["start"] or (r["status"] in UNPLANNED and r["end"] - r["start"] > MAX_MESSAGE):
                close()  # recording glitches (e.g. a gap over Christmas 2024 left messages "on" for days)
                continue
            if r["status"] not in UNPLANNED:
                close()  # planned closure, service closed overnight, good service: not part of an incident
                continue
            if episode and (r["start"] - max(x["end"] for x in episode)).total_seconds() > GAP_S:
                close()
            episode.append(r)
        close()
    return obs


def _survival(rem: list[float]) -> list[float]:
    n = len(rem)
    return [round(sum(x > h for x in rem) / n, 4) for h in HORIZONS]


def fit(obs: list[dict]) -> dict:
    groups: dict[str, list[float]] = defaultdict(list)
    for o in obs:
        e = elapsed_bucket(o["elapsed"])
        for k in (f"c|{o['category']}", f"ce|{o['category']}|{e}", f"cxe|{o['category']}|{o['cause']}|{e}"):
            groups[k].append(o["remaining"])
    return {k: {"n": len(v), "s": _survival(v), "median": round(statistics.median(v), 1)} for k, v in groups.items()}


# TfL status-history line names -> Unified API line ids
HISTORY_LINES = {"Bakerloo": ["bakerloo"], "C&H": ["circle", "hammersmith-city"], "Central": ["central"],
                 "District": ["district"], "Jubilee": ["jubilee"], "Metropolitan": ["metropolitan"],
                 "Northern": ["northern"], "Piccadilly": ["piccadilly"], "Victoria": ["victoria"],
                 "Waterloo & City": ["waterloo-city"]}
RECENT_DAYS = 365  # lines' disruption levels drift (Central's doubled 2023-2026): take the level from the last year


def _day_type(d: datetime) -> str:
    return "sat" if d.weekday() == 5 else "sun" if d.weekday() == 6 else "fri" if d.weekday() == 4 else "wd"


def fit_onsets(obs: list[dict]) -> dict:
    """How often a new disruption starts on each line, per hour. Level per line from the most recent year; the
    shape over hour of day and day type from the whole history, pooled across lines (held-out checks: line and
    hour predict the next year; season didn't, so it's left out)."""
    starts = [o for o in obs if o["elapsed"] == 0]
    first, last = min(o["at"] for o in starts), max(o["at"] for o in starts)
    service_hours = lambda a, b: sum(1 for i in range(int((b - a).total_seconds() // 3600))  # noqa: E731
                                     if ((a + timedelta(hours=i)).hour >= 5 or (a + timedelta(hours=i)).hour < 1))
    recent_from = last - timedelta(days=RECENT_DAYS)
    hrs_recent = service_hours(recent_from, last)
    level = {}
    for name, ids in HISTORY_LINES.items():
        n = sum(1 for o in starts if o["line"] == name and o["at"] >= recent_from)
        for lid in ids:
            level[lid] = round(n / hrs_recent, 5)
    # shape: starts per (day type, hour) relative to the average service hour
    counts: dict[str, int] = defaultdict(int)
    exposure: dict[str, int] = defaultdict(int)
    t = first.replace(minute=0, second=0, microsecond=0)
    while t < last:
        if t.hour >= 5 or t.hour < 1:
            exposure[f"{_day_type(t)}|{t.hour}"] += 1
        t += timedelta(hours=1)
    for o in starts:
        counts[f"{_day_type(o['at'])}|{o['at'].hour}"] += 1
    total = sum(counts.values()) / max(1, sum(exposure.values()))
    shape = {k: round((counts[k] / exposure[k]) / total, 3) for k in exposure if exposure[k]}
    return {"level_per_hour": level, "shape": shape, "recent_from": recent_from.date().isoformat()}


# ====================================================================== using it
class Clearance:
    def __init__(self, data: dict):
        self.groups = data["groups"]
        self.meta = data.get("meta", {})
        self.onsets = data.get("onsets")

    def onset_risk(self, line_id: str, start: datetime, end: datetime) -> float | None:
        """Chance a new disruption starts on a line between start and end (London local times), or None if the
        line isn't in the history (only Underground lines are)."""
        if not self.onsets or line_id not in self.onsets["level_per_hour"] or end <= start:
            return None
        level = self.onsets["level_per_hour"][line_id]
        survive, t = 1.0, start
        while t < end:
            step = min(end, (t + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)) - t
            frac = step.total_seconds() / 3600
            rate = level * self.onsets["shape"].get(f"{_day_type(t)}|{t.hour}", 0.0)
            survive *= (1 - min(1.0, rate)) ** frac
            t += step
        return 1 - survive

    def _curve(self, category: str, cause: str, elapsed: float | None) -> list[float] | None:
        e = elapsed_bucket(elapsed)
        keys = [f"c|{category}"] + ([f"ce|{category}|{e}", f"cxe|{category}|{cause}|{e}"] if e != "?" else [])
        est = None
        for k in keys:
            g = self.groups.get(k)
            if not g:
                continue
            if est is None:
                est = list(g["s"])
            else:
                w = g["n"] / (g["n"] + SHRINK)
                est = [w * a + (1 - w) * b for a, b in zip(g["s"], est)]
        return est

    def p_ongoing(self, category: str, reason: str | None, elapsed_min: float | None, ahead_min: float) -> float:
        """Chance the disruption is still on `ahead_min` minutes from now (1.0 if it can't be told)."""
        curve = self._curve(category, cause_of(reason), elapsed_min)
        if curve is None or ahead_min <= 0:
            return 1.0
        pts = [(0.0, 1.0)] + list(zip(HORIZONS, curve))
        for (h0, s0), (h1, s1) in zip(pts, pts[1:]):
            if ahead_min <= h1:
                if s0 <= 0 or s1 <= 0:
                    return max(0.0, s0 + (s1 - s0) * (ahead_min - h0) / (h1 - h0))
                return math.exp(math.log(s0) + (math.log(s1) - math.log(s0)) * (ahead_min - h0) / (h1 - h0))
        last = curve[-1]  # beyond the last horizon: keep halving every further six hours
        return last * 0.5 ** ((ahead_min - HORIZONS[-1]) / 360)


_cache: dict[str, Clearance | None] = {}


def get(path: Path | None = None) -> Clearance | None:
    p = str(path or DATA_FILE)
    if p not in _cache:
        try:
            _cache[p] = Clearance(json.loads(Path(p).read_text()))
        except FileNotFoundError:
            _cache[p] = None
    return _cache[p]


def onset_risk(line_id: str | None, start: datetime, end: datetime) -> float | None:
    from .timeutil import local

    c = get()
    if not c or not line_id:
        return None
    return c.onset_risk(line_id, local(start).replace(tzinfo=None), local(end).replace(tzinfo=None))


def is_planned(description: str | None) -> bool:
    return (description or "").strip().lower() in PLANNED_DESCRIPTIONS


def p_ongoing(category: str, description: str | None, reason: str | None, elapsed_min: float | None,
              ahead_min: float) -> float:
    """Chance a current disruption still applies `ahead_min` from now. Planned closures and anything the history
    can't speak to count as certain, as before."""
    if is_planned(description) or category not in UNPLANNED.values():
        return 1.0
    c = get()
    return c.p_ongoing(category, reason, elapsed_min, ahead_min) if c else 1.0


# ====================================================================== build and check
def build(csv_path: Path, out: Path = DATA_FILE) -> dict:
    obs = observations(_parse(csv_path))
    data = {"meta": {"source": "TfL trains service status messages (Underground), "
                               f"{min(o['at'] for o in obs):%d %b %Y} to {max(o['at'] for o in obs):%d %b %Y}",
                     "observations": len(obs), "horizons_min": HORIZONS,
                     "built": datetime.now().date().isoformat()},
            "groups": fit(obs), "onsets": fit_onsets(obs)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")))
    _cache.pop(str(out), None)
    return {"observations": len(obs), "groups": len(data["groups"]), "bytes": out.stat().st_size}


def check(csv_path: Path, split: datetime = datetime(2025, 11, 1)) -> dict:
    """Fit on messages before `split`, score the year after: Brier score of P(still disrupted at +Δ) for
    Paxen's old assumption (it always is), status alone, status + time so far, and status + cause + time so far."""
    obs = observations(_parse(csv_path))
    train, test = [o for o in obs if o["at"] < split], [o for o in obs if o["at"] >= split]
    model = Clearance({"groups": fit(train)})
    only_cat = Clearance({"groups": {k: v for k, v in fit(train).items() if k.startswith("c|")}})
    no_cause = Clearance({"groups": {k: v for k, v in fit(train).items() if not k.startswith("cxe|")}})
    out: dict = {"train": len(train), "test": len(test), "split": split.date().isoformat(), "by_horizon": {}}
    for h in (15, 30, 60, 120):
        y = [1.0 if o["remaining"] > h else 0.0 for o in test]
        variants = {
            "always_on (before)": [1.0] * len(test),
            "status only": [only_cat.p_ongoing(o["category"], "", None, h) for o in test],
            "status + time so far": [no_cause.p_ongoing(o["category"], "", o["elapsed"], h) for o in test],
            "status + cause + time so far": [model._curve(o["category"], o["cause"], o["elapsed"]) and
                                             _interp(model, o, h) for o in test],
        }
        out["by_horizon"][f"+{h} min"] = {
            "still_on_share": round(sum(y) / len(y), 3),
            **{k: round(statistics.fmean((p - t) ** 2 for p, t in zip(v, y)), 4) for k, v in variants.items()}}
    return out


def _interp(model: Clearance, o: dict, h: float) -> float:
    curve = model._curve(o["category"], o["cause"], o["elapsed"])
    pts = [(0.0, 1.0)] + list(zip(HORIZONS, curve))
    for (h0, s0), (h1, s1) in zip(pts, pts[1:]):
        if h <= h1:
            return s0 + (s1 - s0) * (h - h0) / (h1 - h0)
    return curve[-1]


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] in ("build", "check"):
        fn = build if sys.argv[1] == "build" else check
        print(json.dumps(fn(Path(sys.argv[2])), indent=1, default=str))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
