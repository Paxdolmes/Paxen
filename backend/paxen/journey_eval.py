"""The journey model and its pre-registered evaluation (docs/journey-model.md).

Predicts door-to-door minutes for a panel journey's departure T, issued h minutes earlier, from what was known
then. Candidates: rules (what the app does today), usual, persistence, journey_gbm. Rolling days; scored on
replayed journey times (paxen/replay.py) read from the history store.
"""
from __future__ import annotations

import bisect
import logging
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from .timeutil import LONDON

log = logging.getLogger("paxen.journey_eval")

HORIZONS = (60, 30, 10)
EVAL_STEP_MIN = 15  # departures scored every 15 minutes (replayed every 5: the finer grid feeds persistence)
SLOT_MIN = 15
MIN_TRAIN_DAYS = 7
MIN_TEST_DAYS_TO_PROMOTE = 7
MAE_GAIN = 0.05
WIN_SHARE = 2 / 3
COVERAGE = (0.70, 0.90)
SLOW_MIN = 5.0
PEAKS = ((7 * 60, 10 * 60), (16 * 60 + 30, 19 * 60 + 30))
NETWORK_WINDOW_MIN = 30
MAX_TRAIN_ROWS = 300_000
CATS = {"good": 0, "minor": 1, "severe": 2, "part_suspended": 3, "suspended": 4}
# England bank holidays (gov.uk)
BANK_HOLIDAYS = {date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6), date(2026, 5, 4), date(2026, 5, 25),
                 date(2026, 8, 31), date(2026, 12, 25), date(2026, 12, 28), date(2027, 1, 1), date(2027, 3, 26),
                 date(2027, 3, 29), date(2027, 5, 3), date(2027, 5, 31), date(2027, 8, 30), date(2027, 12, 27),
                 date(2027, 12, 28)}


def daytype(day: str) -> str:
    d = datetime.strptime(day, "%Y-%m-%d").date()
    return "weekend" if d.weekday() >= 5 or d in BANK_HOLIDAYS else "weekday"


def local_min(t: datetime) -> int:
    """Minutes after London midnight for a naive UTC time."""
    loc = t.replace(tzinfo=timezone.utc).astimezone(LONDON)
    return loc.hour * 60 + loc.minute


# ------------------------------------------------------------------ data
class Day:
    """One replayed day: per journey, departures (minutes after midnight, 5-minute grid) and real minutes."""

    def __init__(self, day: str, rows: dict):
        self.day = day
        self.by_journey: dict[str, dict] = defaultdict(lambda: {"dep": [], "y": [], "dep_utc": []})
        self.planned: dict[str, float] = {}
        n = len(rows["journey"])
        for i in range(n):
            y, gap = rows["minutes"][i], rows["gap"][i]
            if y is None or gap:
                continue
            j = rows["journey"][i]
            rec = self.by_journey[j]
            rec["dep"].append(local_min(rows["depart"][i]))
            rec["dep_utc"].append(rows["depart"][i])
            rec["y"].append(float(y))
            self.planned[j] = float(rows["planned_min"][i])

    def y(self, journey: str, minute: int) -> float | None:
        rec = self.by_journey.get(journey)
        if not rec:
            return None
        k = bisect.bisect_left(rec["dep"], minute)
        return rec["y"][k] if k < len(rec["dep"]) and rec["dep"][k] == minute else None


def load_day(archive, source: str, day: str) -> Day:
    from .history import read_day

    t = read_day(archive, source, "journey_times", day, columns=["journey", "depart", "planned_min", "minutes", "gap"])
    return Day(day, {c: t.column(c).to_pylist() for c in t.column_names})


class Usual:
    """Median real minutes per (journey, day type, 15-minute slot), from the days given (earlier days only)."""

    def __init__(self, days: list[Day]):
        vals: dict[tuple, list[float]] = defaultdict(list)
        for d in days:
            dt = daytype(d.day)
            for j, rec in d.by_journey.items():
                for m, y in zip(rec["dep"], rec["y"]):
                    vals[(j, dt, m // SLOT_MIN)].append(y)
        self.med = {k: statistics.median(v) for k, v in vals.items()}

    def get(self, journey: str, day: str, minute: int, planned: float) -> float:
        return self.med.get((journey, daytype(day), minute // SLOT_MIN), planned)


# ------------------------------------------------------------------ context at issue time
class Context:
    """Line statuses (context_events runs) and weather (weather_hours) as they stood at a given time."""

    def __init__(self, status_runs: dict[str, list[tuple]], weather: dict[str, dict]):
        self.runs = {k: sorted(v) for k, v in status_runs.items()}  # line -> [(first_seen, last_seen, category, ev)]
        self.starts = {k: [r[0] for r in v] for k, v in self.runs.items()}
        self.weather = weather  # "YYYY-MM-DDTHH" London -> {temp_c, precip_mm, snow_cm, gust_kmh}

    def status(self, line: str, t: datetime) -> tuple[str, float, dict | None]:
        """(category, minutes it has lasted, the run's data) at time t; good when nothing was recorded."""
        runs = self.runs.get(line)
        if not runs:
            return "good", 0.0, None
        k = bisect.bisect_right(self.starts[line], t) - 1
        if k < 0 or runs[k][1] < t - timedelta(minutes=3):
            return "good", 0.0, None
        cat = runs[k][2] or "good"
        begin = runs[k][0]
        while k > 0 and (runs[k - 1][2] or "good") != "good" and cat != "good" \
                and runs[k][0] - runs[k - 1][1] <= timedelta(minutes=3):
            k -= 1
            begin = runs[k][0]  # the disruption began at the first non-good run in an unbroken stretch
        return cat, (t - begin).total_seconds() / 60, runs[k][3] if len(runs[k]) > 3 else None

    def weather_before(self, t: datetime) -> dict:
        """The last hour that had ended by t."""
        loc = (t.replace(tzinfo=timezone.utc).astimezone(LONDON) - timedelta(hours=1))
        return self.weather.get(loc.strftime("%Y-%m-%dT%H"), {})


def load_context(s, since: datetime, until: datetime) -> Context:
    from sqlalchemy import select

    from .db import ContextEvent, WeatherHour

    runs: dict[str, list] = defaultdict(list)
    for ev in s.scalars(select(ContextEvent).where(ContextEvent.kind == "line_status",
                                                   ContextEvent.last_seen >= since, ContextEvent.first_seen <= until)):
        runs[ev.line_id].append((ev.first_seen, ev.last_seen, ev.category, ev.data or {}))
    weather = {w.hour: {"temp_c": w.temp_c, "precip_mm": w.precip_mm, "snow_cm": w.snow_cm, "gust_kmh": w.gust_kmh}
               for w in s.scalars(select(WeatherHour))}
    return Context(runs, weather)


# ------------------------------------------------------------------ candidates and features
def journey_lines(j: dict) -> list[str]:
    return [l["line_id"] for l in j["legs"] if "line_id" in l]


def finished_deviations(day: Day, usual: Usual, journey: str, issue_utc: datetime, planned: float,
                        n: int = 3) -> list[tuple[float, float]]:
    """(deviation from usual, minutes since it finished) of this journey's latest departures that had finished by
    the issue time, newest first."""
    rec = day.by_journey.get(journey)
    if not rec:
        return []
    out = []
    for k in range(len(rec["dep"]) - 1, -1, -1):
        end = rec["dep_utc"][k] + timedelta(minutes=rec["y"][k])
        if end > issue_utc:
            continue
        dev = rec["y"][k] - usual.get(journey, day.day, rec["dep"][k], planned)
        out.append((dev, (issue_utc - end).total_seconds() / 60))
        if len(out) >= n:
            break
    return out


class NetworkState:
    """For each line, when each panel journey using it finished and how far off its usual it was."""

    def __init__(self, day: Day, usual: Usual, panel: dict[str, dict]):
        ev: dict[str, list] = defaultdict(list)
        for j, rec in day.by_journey.items():
            lines = journey_lines(panel[j]) if j in panel else []
            for m, y, t in zip(rec["dep"], rec["y"], rec["dep_utc"]):
                dev = y - usual.get(j, day.day, m, day.planned.get(j, y))
                for line in lines:
                    ev[line].append((t + timedelta(minutes=y), dev))
        self.ev = {k: sorted(v) for k, v in ev.items()}
        self.ends = {k: [x[0] for x in v] for k, v in self.ev.items()}

    def median_dev(self, lines: list[str], issue_utc: datetime) -> float:
        vals = []
        for line in lines:
            ends = self.ends.get(line)
            if not ends:
                continue
            lo = bisect.bisect_left(ends, issue_utc - timedelta(minutes=NETWORK_WINDOW_MIN))
            hi = bisect.bisect_right(ends, issue_utc)
            vals += [d for _, d in self.ev[line][lo:hi]]
        return statistics.median(vals) if vals else math.nan


FEATURES = ["usual", "planned", "changes", "dev1", "dev2", "dev3", "age1", "net_dev", "horizon", "hour", "weekend",
            "worst_cat", "worst_age", "n_disrupted", "precip", "temp", "gust", "snow", "first_line"]
CATEGORICAL = [f == "first_line" for f in FEATURES]


class DayRows:
    """Every scored (journey, departure, horizon) of one day, as arrays: features (only from before the issue
    time), the real minutes, usual and persistence."""

    def __init__(self, day: str, journeys: list[str], minute, horizon, y, usual, persistence, X, issue):
        self.day, self.journeys = day, journeys
        self.minute, self.horizon, self.y, self.usual, self.persistence, self.X, self.issue = (
            minute, horizon, y, usual, persistence, X, issue)

    def __len__(self):
        return len(self.y)


def rows_for_day(day: Day, usual: Usual, ctx: Context, panel: dict[str, dict], lines_index: dict[str, int],
                 step: int = EVAL_STEP_MIN) -> DayRows:
    import numpy as np

    net = NetworkState(day, usual, panel)
    weekend = 1.0 if daytype(day.day) == "weekend" else 0.0
    js, mins, hs, ys, us, ps, xs, issues = [], [], [], [], [], [], [], []
    nan = math.nan
    for jid, rec in day.by_journey.items():
        j = panel.get(jid)
        if not j:
            continue
        lines = journey_lines(j)
        planned = day.planned[jid]
        first = float(lines_index.get(lines[0], len(lines_index)))
        for m, y, dep_utc in zip(rec["dep"], rec["y"], rec["dep_utc"]):
            if m % step:
                continue
            u = usual.get(jid, day.day, m, planned)
            for h in HORIZONS:
                issue = dep_utc - timedelta(minutes=h)
                devs = finished_deviations(day, usual, jid, issue, planned)
                st = [ctx.status(line, issue) for line in lines]
                worst = max(st, key=lambda x: CATS.get(x[0], 0))
                w = ctx.weather_before(issue)

                def wv(k):
                    v = w.get(k)
                    return nan if v is None else float(v)

                xs.append((u, planned, float(max(0, len(lines) - 1)),
                           devs[0][0] if devs else nan, devs[1][0] if len(devs) > 1 else nan,
                           devs[2][0] if len(devs) > 2 else nan, devs[0][1] if devs else nan,
                           net.median_dev(lines, issue), float(h), m / 60, weekend, float(CATS.get(worst[0], 0)),
                           worst[1] if worst[0] != "good" else 0.0, float(sum(1 for c, _, _ in st if c != "good")),
                           wv("precip_mm"), wv("temp_c"), wv("gust_kmh"), wv("snow_cm"), first))
                js.append(jid)
                mins.append(m)
                hs.append(h)
                ys.append(y)
                us.append(u)
                ps.append(u + (devs[0][0] if devs else 0.0))
                issues.append(issue)
    return DayRows(day.day, js, np.array(mins), np.array(hs), np.array(ys, dtype=float), np.array(us, dtype=float),
                   np.array(ps, dtype=float), np.array(xs, dtype=np.float32).reshape(-1, len(FEATURES)), issues)


# ------------------------------------------------------------------ the rules (what the app does today)
class _NoLive:
    name = "tfl"

    def arrivals(self, stop_id, now):
        raise RuntimeError("no live data in a replay")


def rules_prediction(j: dict, dep_utc: datetime, issue: datetime, st: list[tuple], lines: list[str], cache: dict):
    """engine.forecast_journey for the panel journey with the statuses as they stood at the issue time and no live
    countdowns: what the app would have said."""
    from .domain import Journey, Leg, LineStatus, StatusSection
    from .engine import NetworkContext, forecast_journey
    from .forecast import CorrectionModel

    disrupted = any(c != "good" for c, _, _ in st)
    key = (j["id"], local_min(dep_utc) // SLOT_MIN, dep_utc.weekday() >= 5,
           tuple((c, int(age // 15) if c != "good" else 0) for c, age, _ in st),
           (dep_utc - issue).total_seconds() // 60 if disrupted else None)  # the horizon only matters then
    if key in cache:
        return cache[key]
    depart = dep_utc.replace(tzinfo=timezone.utc)
    now = issue.replace(tzinfo=timezone.utc)
    statuses, since = {}, {}
    for line, (cat, age, data) in zip(lines, st):
        stops = frozenset((data or {}).get("stops") or [])
        statuses[line] = LineStatus(line, line, "tube", cat, (data or {}).get("description") or "", None,
                                    sections=[StatusSection(cat, stops)] if cat != "good" else [])
        if cat != "good":
            since[line] = now - timedelta(minutes=age)
    legs, t = [], depart
    for leg in j["legs"]:
        if "walk" in leg:
            legs.append(Leg("walking", leg["walk"], "", "", t, t + timedelta(minutes=leg["walk"])))
        else:
            legs.append(Leg("tube", leg["minutes"], "", "", t, t + timedelta(minutes=leg["minutes"]),
                            line_id=leg["line_id"], line_name=leg["line_id"], from_stop_id=leg["from"],
                            to_stop_id=leg["to"], stop_ids=leg.get("stop_ids") or []))
        t = t + timedelta(minutes=leg.get("walk", leg.get("minutes", 0)))
    total = sum(l.duration_min for l in legs)
    ctx = NetworkContext(_NoLive(), now, statuses, CorrectionModel(), disrupted_since=since)
    try:
        p50 = forecast_journey(Journey(legs, total, depart, depart + timedelta(minutes=total), "tfl"), ctx, depart).p50
    except Exception:
        p50 = total
    cache[key] = p50
    return p50


# ------------------------------------------------------------------ the model
def fit_gbm(parts: list[DayRows], seed: int = 0) -> dict:
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingRegressor

    X = np.concatenate([p.X for p in parts])
    yd = np.concatenate([p.y - p.usual for p in parts])
    if len(yd) > MAX_TRAIN_ROWS:
        keep = np.random.default_rng(seed).choice(len(yd), MAX_TRAIN_ROWS, replace=False)
        X, yd = X[keep], yd[keep]
    # a column with no values at all (e.g. no weather recorded yet) can't be binned: left out, here and when predicting
    cols = np.flatnonzero(~np.all(np.isnan(X), axis=0))
    cat = [CATEGORICAL[c] for c in cols]
    models: dict = {"cols": cols}
    for q in (0.1, 0.5, 0.9):
        m = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=200, learning_rate=0.08,
                                          max_leaf_nodes=31, min_samples_leaf=50, categorical_features=cat,
                                          random_state=seed)
        m.fit(X[:, cols], yd)
        models[q] = m
    return models


def predict_gbm(models: dict, rows: DayRows):
    X = rows.X[:, models["cols"]]
    return {q: rows.usual + models[q].predict(X) for q in (0.1, 0.5, 0.9)}


# ------------------------------------------------------------------ scoring
def score(rows: DayRows, idx, pred, lo=None, hi=None) -> dict:
    import numpy as np

    y, u, p, minute = rows.y[idx], rows.usual[idx], pred[idx], rows.minute[idx]
    err = np.abs(p - y)
    peak = np.array([any(a <= m < b for a, b in PEAKS) for m in minute], dtype=bool)
    slow, said = (y - u) >= SLOW_MIN, (p - u) >= SLOW_MIN
    tp = int((slow & said).sum())
    prec = tp / said.sum() if said.sum() else None
    rec = tp / slow.sum() if slow.sum() else None
    f1 = (2 * prec * rec / (prec + rec)) if prec and rec else (0.0 if slow.sum() else None)
    out = {"n": int(len(y)), "mae": round(float(err.mean()), 3) if len(y) else None,
           "peak_mae": round(float(err[peak].mean()), 3) if peak.any() else None, "slow": int(slow.sum()),
           "precision": round(prec, 3) if prec is not None else None,
           "recall": round(rec, 3) if rec is not None else None, "f1": round(f1, 3) if f1 is not None else None}
    if lo is not None:
        out["coverage"] = round(float(((lo[idx] <= y) & (y <= hi[idx])).mean()), 3)
    return out


def evaluate(days: list[Day], ctx: Context, panel: list[dict], done: dict | None = None) -> dict:
    """The rolling-day protocol. days: every replayed day, oldest first. done: per-day results already computed
    (a test day's result never changes: it only uses days before it), so only new test days are run."""
    import numpy as np

    pmap = {j["id"]: j for j in panel}
    lines_index = {l: i for i, l in enumerate(sorted({l for j in panel for l in journey_lines(j)}))}
    per_day: dict[str, dict] = dict(done or {})
    cache: dict = {}
    built: dict[str, DayRows] = {}
    for i, d in enumerate(days):
        built[d.day] = rows_for_day(d, Usual(days[:i]), ctx, pmap, lines_index)
    for i, d in enumerate(days):
        if i < MIN_TRAIN_DAYS or d.day in per_day or not len(built[d.day]):
            continue
        test = built[d.day]
        models = fit_gbm([built[dd.day] for dd in days[:i] if len(built[dd.day])])
        g = predict_gbm(models, test)
        rules = np.empty(len(test))
        for k in range(len(test)):
            j = pmap[test.journeys[k]]
            lines = journey_lines(j)
            st = [ctx.status(line, test.issue[k]) for line in lines]
            dep = test.issue[k] + timedelta(minutes=int(test.horizon[k]))
            rules[k] = rules_prediction(j, dep, test.issue[k], st, lines, cache)
        res: dict = {}
        for h in HORIZONS:
            idx = np.flatnonzero(test.horizon == h)
            res[str(h)] = {"rules": score(test, idx, rules), "usual": score(test, idx, test.usual),
                           "persistence": score(test, idx, test.persistence),
                           "journey_gbm": score(test, idx, g[0.5], g[0.1], g[0.9])}
        per_day[d.day] = res
    return {"days": [d.day for d in days], "test_days": sorted(per_day), "per_day": per_day,
            "decision": decide(per_day), "registered": "docs/journey-model.md (17 Nov 2026)"}


def decide(per_day: dict) -> dict:
    """The registered rule: journey_gbm replaces the rules only if it clearly beats the best baseline."""
    test_days = list(per_day)
    summary: dict = {}
    for h in map(str, HORIZONS):
        summary[h] = {}
        for c in ("rules", "usual", "persistence", "journey_gbm"):
            maes = [per_day[d][h][c]["mae"] for d in test_days if per_day[d][h][c]["mae"] is not None]
            f1s = [per_day[d][h][c]["f1"] for d in test_days if per_day[d][h][c]["f1"] is not None]
            summary[h][c] = {"mae": round(statistics.fmean(maes), 3) if maes else None,
                             "f1": round(statistics.fmean(f1s), 3) if f1s else None}
        covs = [per_day[d][h]["journey_gbm"].get("coverage") for d in test_days]
        summary[h]["journey_gbm"]["coverage"] = round(statistics.fmean([c for c in covs if c is not None]), 3) \
            if any(c is not None for c in covs) else None
    if len(test_days) < MIN_TEST_DAYS_TO_PROMOTE:
        return {"status": "waiting", "summary": summary,
                "message": f"{len(test_days)} test days; {MIN_TEST_DAYS_TO_PROMOTE} needed before any change."}
    checks = {}
    for h in ("30", "60"):
        best = min(("rules", "usual", "persistence"), key=lambda c: summary[h][c]["mae"] or math.inf)
        wins = sum(per_day[d][h]["journey_gbm"]["mae"] < per_day[d][h][best]["mae"] for d in test_days)
        checks[h] = {"best_baseline": best,
                     "mae_gain": summary[h]["journey_gbm"]["mae"] <= summary[h][best]["mae"] * (1 - MAE_GAIN),
                     "wins": wins >= len(test_days) * WIN_SHARE}
    best30 = checks["30"]["best_baseline"]
    f1_ok = (summary["30"]["journey_gbm"]["f1"] or 0) >= (summary["30"][best30]["f1"] or 0)
    cov = summary["30"]["journey_gbm"]["coverage"]
    cov_ok = cov is not None and COVERAGE[0] <= cov <= COVERAGE[1]
    if all(c["mae_gain"] and c["wins"] for c in checks.values()) and f1_ok and cov_ok:
        return {"status": "winner", "winner": "journey_gbm", "checks": checks, "summary": summary}
    # otherwise the best baseline may replace the rules if it beats them on the same terms
    for c in sorted(("persistence", "usual"), key=lambda c: summary["30"][c]["mae"] or math.inf):
        ok = all(summary[h][c]["mae"] is not None and summary[h]["rules"]["mae"] is not None
                 and summary[h][c]["mae"] <= summary[h]["rules"]["mae"] * (1 - MAE_GAIN)
                 and sum(per_day[d][h][c]["mae"] < per_day[d][h]["rules"]["mae"] for d in test_days)
                 >= len(test_days) * WIN_SHARE for h in ("30", "60"))
        if ok and (summary["30"][c]["f1"] or 0) >= (summary["30"]["rules"]["f1"] or 0):
            return {"status": "baseline", "winner": c, "checks": checks, "summary": summary}
    return {"status": "no_change", "winner": "rules", "checks": checks, "summary": summary}


REPORT = "journey_eval"  # an AppSecret row: the latest evaluation (per-day results are kept and reused)


def run(s, source: str, archive) -> dict:
    """Worker, daily: load every replayed day from the history store and run the protocol on new test days."""
    import json

    from sqlalchemy import select

    from .db import AppSecret, ExportedDay
    from .replay import VERSION, load_panel

    panel = load_panel()
    days = [d for (d,) in s.execute(select(ExportedDay.day).where(
        ExportedDay.source == source, ExportedDay.table == "journey_times", ExportedDay.rows > 0)
        .order_by(ExportedDay.day))]
    row = s.get(AppSecret, REPORT)
    prev = json.loads(row.value) if row else {}
    if prev.get("replay_version") != VERSION:
        prev = {}  # the ground truth was replayed under new rules: every test day is scored again
    if len(days) <= MIN_TRAIN_DAYS or not panel or archive is None:
        rep = {"status": "collecting", "days": days,
               "message": f"{len(days)} replayed days; testing starts after {MIN_TRAIN_DAYS}."}
    else:
        loaded = [load_day(archive, source, d) for d in days]
        lo = datetime.strptime(days[0], "%Y-%m-%d") - timedelta(days=1)
        hi = datetime.strptime(days[-1], "%Y-%m-%d") + timedelta(days=2)
        rep = evaluate(loaded, load_context(s, lo, hi), panel, done=prev.get("per_day"))
        rep["status"] = rep["decision"]["status"]
    rep["evaluated_at"] = datetime.now(timezone.utc).isoformat()
    rep["replay_version"] = VERSION
    value = json.dumps(rep)
    if row:
        row.value = value
    else:
        s.add(AppSecret(name=REPORT, value=value))
    s.commit()
    return {k: rep.get(k) for k in ("status", "test_days")} | {"decision": rep.get("decision", {}).get("status")}
