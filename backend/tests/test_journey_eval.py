"""The journey model's evaluation (paxen/journey_eval.py, docs/journey-model.md)."""
import random
from datetime import datetime, timedelta

import numpy as np

from paxen import journey_eval as je

PANEL = [{"id": "A>B", "legs": [{"line_id": "district", "from": "940GZZLUAAA", "to": "940GZZLUBBB", "minutes": 20}]},
         {"id": "C>B", "legs": [{"line_id": "district", "from": "940GZZLUCCC", "to": "940GZZLUBBB", "minutes": 12},
                                {"walk": 3},
                                {"line_id": "victoria", "from": "940GZZLUBBB", "to": "940GZZLUDDD", "minutes": 8}]}]


def make_day(day: str, slow_from=None, slow_by=0.0, seed=0) -> je.Day:
    """Departures every 5 minutes 06:00-22:00; from `slow_from` (minutes after midnight) the District is slow."""
    rng = random.Random(seed)
    d = datetime.strptime(day, "%Y-%m-%d")
    rows = {"journey": [], "depart": [], "planned_min": [], "minutes": [], "gap": []}
    for j, planned in (("A>B", 20.0), ("C>B", 23.0)):
        for m in range(360, 1321, 5):
            y = planned + rng.uniform(0, 4) + (slow_by if slow_from is not None and m >= slow_from else 0.0)
            rows["journey"].append(j)
            rows["depart"].append(d + timedelta(minutes=m))  # naive UTC = London in November
            rows["planned_min"].append(planned)
            rows["minutes"].append(y)
            rows["gap"].append(False)
    return je.Day(day, rows)


def ctx():
    return je.Context({}, {})


def test_nothing_after_the_issue_time_changes_a_prediction():
    days = [make_day(f"2026-11-{2 + i:02d}", seed=i) for i in range(3)]
    usual = je.Usual(days[:2])
    pmap = {j["id"]: j for j in PANEL}
    li = {"district": 0, "victoria": 1}
    base = je.rows_for_day(days[2], usual, ctx(), pmap, li)
    k = next(i for i in range(len(base)) if base.journeys[i] == "A>B" and base.minute[i] == 8 * 60 + 30
             and base.horizon[i] == 30)
    issue = base.issue[k]
    later = make_day("2026-11-04", seed=2)
    rec = later.by_journey["A>B"]
    for n, t in enumerate(rec["dep_utc"]):
        if t >= issue - timedelta(minutes=1):  # departures that can't have finished by the issue time
            rec["y"][n] += 30.0
    after = je.rows_for_day(later, usual, ctx(), pmap, li)
    assert np.array_equal(base.X[k], after.X[k], equal_nan=True)
    assert after.y[k] == base.y[k] + 30.0  # only the answer changed


def test_persistence_and_the_model_pick_up_a_slow_afternoon():
    days = []
    for i in range(10):
        slow = (i % 2 == 0)  # every other day the District slows by 10 minutes from 15:00
        days.append(make_day(f"2026-11-{2 + i:02d}", slow_from=15 * 60 if slow else None, slow_by=10.0, seed=i))
    out = je.evaluate(days, ctx(), PANEL)
    assert out["test_days"] == [d.day for d in days[7:]]
    s = out["decision"]["summary"]["30"]
    # usual can't tell a slow afternoon from a normal one; knowing the last finished journey can
    assert s["persistence"]["mae"] < s["usual"]["mae"]
    assert s["journey_gbm"]["mae"] < s["usual"]["mae"]
    assert out["decision"]["status"] == "waiting"  # 3 test days: no change before 7
    again = je.evaluate(days, ctx(), PANEL, done=out["per_day"])
    assert again["per_day"] == out["per_day"]  # earlier test days are not recomputed


def test_scores_and_the_decision_rule():
    rows = je.DayRows("2026-11-10", ["A>B"] * 4, np.array([480, 485, 900, 905]), np.array([30] * 4),
                      np.array([20.0, 30.0, 20.0, 31.0]), np.array([20.0] * 4), np.array([20.0] * 4),
                      np.zeros((4, len(je.FEATURES)), dtype=np.float32), [datetime(2026, 11, 10)] * 4)
    sc = je.score(rows, np.arange(4), np.array([21.0, 28.0, 20.0, 20.0]), np.array([18.0] * 4), np.array([25.0] * 4))
    assert sc["mae"] == 3.5 and sc["slow"] == 2 and sc["precision"] == 1.0 and sc["recall"] == 0.5
    assert sc["coverage"] == 0.5 and sc["peak_mae"] == 1.5

    def day(gbm, best, f1=0.5):
        return {h: {"rules": {"mae": 5.0, "f1": 0.3}, "usual": {"mae": best, "f1": f1},
                    "persistence": {"mae": best + 0.1, "f1": f1},
                    "journey_gbm": {"mae": gbm, "f1": f1, "coverage": 0.8}} for h in ("60", "30", "10")}

    win = {f"d{i}": day(3.0, 3.5) for i in range(7)}
    assert je.decide(win)["status"] == "winner"
    close = {f"d{i}": day(3.45, 3.5) for i in range(7)}  # under 5% better
    assert je.decide(close)["winner"] == "usual"  # the best baseline beats the rules by far
    assert je.decide({f"d{i}": day(3.0, 3.5) for i in range(6)})["status"] == "waiting"


def test_the_daily_run_reads_the_store_and_keeps_its_report(session, tmp_path, monkeypatch):
    import io
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq

    from paxen import replay
    from paxen.archive import LocalArchive
    from paxen.db import AppSecret, ExportedDay
    from paxen.history import key_for

    archive = LocalArchive(str(tmp_path / "store"))
    monkeypatch.setenv("PAXEN_HISTORY_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(replay, "load_panel", lambda: PANEL)
    assert je.run(session, "tfl", archive)["status"] == "collecting"
    for i in range(9):
        day = f"2026-11-{2 + i:02d}"
        rows = []
        for j, planned in (("A>B", 20.0), ("C>B", 23.0)):
            for m in range(360, 1321, 5):
                rows.append({"journey": j, "depart": datetime(2026, 11, 2 + i) + timedelta(minutes=m),
                             "planned_min": planned, "minutes": planned + (i % 3), "gap": False})
        buf = io.BytesIO()
        pq.write_table(pa.Table.from_pylist(rows), buf)
        archive.put_bytes(key_for("tfl", "journey_times", day), buf.getvalue())
        session.add(ExportedDay(source="tfl", table="journey_times", day=day, key="", rows=len(rows), bytes=0))
    session.commit()
    out = je.run(session, "tfl", archive)
    assert out["test_days"] == ["2026-11-09", "2026-11-10"] and out["decision"] == "waiting"
    rep = json.loads(session.get(AppSecret, je.REPORT).value)
    assert rep["decision"]["summary"]["30"]["usual"]["mae"] is not None


def test_amendment3_scores_only_new_days_and_uses_the_status_minutes():
    """Usual plus the minutes the rules add for a disruption, the model with that as an input, and "slow around
    this time"; only on test days from AMEND3_FROM."""
    days, runs = [], []
    for i in range(12):  # 8-19 November; the District is severely delayed from 15:00 every other day
        day = f"2026-11-{8 + i:02d}"
        slow = i % 2 == 0
        days.append(make_day(day, slow_from=15 * 60 if slow else None, slow_by=10.0, seed=i))
        if slow:
            d = datetime.strptime(day, "%Y-%m-%d")
            runs.append((d + timedelta(hours=14, minutes=45), d + timedelta(hours=22), "severe",
                         {"description": "Severe delays"}))
    c = je.Context({"district": runs}, {})
    out = je.evaluate(days, c, PANEL)
    old, new = out["per_day"]["2026-11-16"]["30"], out["per_day"]["2026-11-17"]["30"]
    assert "usual_status" not in old  # before the amendment: the registered candidates only
    assert {"usual_status", "journey_gbm_status"} <= set(new) and "f1_sys" in new["rules"]
    a3 = out["amendment3"]
    assert a3["status"] == "waiting" and a3["test_days"] == ["2026-11-17", "2026-11-18", "2026-11-19"]
    s = a3["summary"]["30"]
    # on a disrupted afternoon the rules add minutes that usual alone doesn't have
    slow_day = out["per_day"]["2026-11-18"]["30"]
    assert slow_day["usual_status"]["mae"] < slow_day["usual"]["mae"]
    assert s["usual_status"]["f1_sys"] > s["usual"]["f1_sys"]
    assert s["journey_gbm_status"]["coverage"] is not None


def test_amendment3_decision_rule():
    def day(us, gs, rules=5.0, f1=0.4, rules_f1=0.3, cov=0.8):
        base = {"mae": rules, "f1": 0.3, "f1_sys": rules_f1}
        return {h: {"rules": dict(base), "usual": {"mae": 3.3, "f1": 0.0, "f1_sys": 0.0},
                    "persistence": {"mae": 4.3, "f1": 0.1, "f1_sys": 0.1},
                    "journey_gbm": {"mae": 3.2, "f1": 0.05, "f1_sys": 0.05, "coverage": cov},
                    "usual_status": {"mae": us, "f1": f1, "f1_sys": f1},
                    "journey_gbm_status": {"mae": gs, "f1": f1, "f1_sys": f1, "coverage": cov}}
                for h in ("60", "30", "10")}

    week = [f"2026-11-{17 + i}" for i in range(7)]
    assert je.decide_amendment3({d: day(3.3, 3.1) for d in week})["winner"] == "journey_gbm_status"
    assert je.decide_amendment3({d: day(3.3, 3.1, cov=0.6) for d in week})["winner"] == "usual_status"
    # spotting slow journeys worse than the rules: no change, however good the average
    assert je.decide_amendment3({d: day(3.3, 3.1, f1=0.2) for d in week})["status"] == "no_change"
    # days before the amendment don't count
    assert je.decide_amendment3({f"2026-11-{10 + i}": day(3.3, 3.1) for i in range(7)})["status"] == "waiting"
