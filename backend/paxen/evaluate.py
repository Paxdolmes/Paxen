"""Rolling-day evaluation and promotion, exactly as pre-registered in docs/model-evaluation.md.

    python -m paxen.evaluate            # report + promote if a candidate is eligible
    python -m paxen.evaluate --dry-run  # report only
"""
from __future__ import annotations

import json
import logging
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import DaySample, ModelVersion, ObservedArrival, Prediction
from .forecast import MAX_LEAD_S, Sample, lead_bucket, load_samples, model_kind
from .models import CANDIDATES, SIMPLICITY, Conformal
from .timeutil import LONDON, aware, naive_utc

log = logging.getLogger("paxen.evaluate")

MIN_TRAIN_DAYS = 7
MIN_TEST_DAYS = 3
MAX_TEST_DAYS = 7
MAE_GAIN = 0.03  # beat the provider's mean MAE by at least 3%
WIN_SHARE = 2 / 3  # ... and on at least two-thirds of test days
COVERAGE = (0.70, 0.90)  # honest 80% interval
TIE = 0.01  # within 1%: the simpler model wins
DECISION_BUCKETS = ("2-5m", "5-10m", "10-20m")  # Amendment 1, A1.2: horizons for "should I leave now?"


def fit_candidate(name: str, cls, train: list[Sample]):
    """Challengers get conformalized intervals (Amendment 1, A1.3); the provider baseline doesn't."""
    return cls.fit(train) if name == "provider" else Conformal.fit_with(cls, train)


def decision_mae(samples: list[Sample], preds: list[dict]) -> float | None:
    """Amendment 1, A1.2: mean over the decision buckets of each bucket's MAE, where every arrival counts once
    per bucket (its predictions in that bucket are averaged first). None if no decision bucket has data."""
    per_bucket: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for x, p in zip(samples, preds):
        b = lead_bucket(x.lead_s)
        if b in DECISION_BUCKETS:
            per_bucket[b][x.event or str(id(x))].append(abs(x.error_s - p["bias_s"]))
    maes = [statistics.fmean(statistics.fmean(v) for v in events.values()) for events in per_bucket.values()]
    return statistics.fmean(maes) if maes else None


def _day_start_utc(day: str):
    from datetime import datetime, timezone

    from .timeutil import LONDON

    return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=LONDON).astimezone(timezone.utc)


def _metrics(samples: list[Sample], preds: list[dict]) -> dict:
    res = [x.error_s - p["bias_s"] for x, p in zip(samples, preds)]
    inside = [p["q10_s"] <= x.error_s <= p["q90_s"] for x, p in zip(samples, preds)]
    abs_r = [abs(r) for r in res]
    return {"n": len(res), "mae_s": round(statistics.fmean(abs_r), 1) if res else None,
            "within_2m": round(sum(a <= 120 for a in abs_r) / len(res), 3) if res else None,
            "coverage": round(sum(inside) / len(inside), 3) if inside else None}


def _predict(model, samples: list[Sample]) -> list[dict]:
    if hasattr(model, "predict_many"):
        return model.predict_many(samples)
    return [model.predict(x.line_id, x.stop_id, x.lead_s, x.band, x.disrupted, category=x.category,
                          queue_rank=x.queue_rank, gap_s=x.gap_s, feed_age_s=x.feed_age_s, weekend=x.weekend,
                          bound=x.bound, polled_at=x.polled_at)
            for x in samples]


def _breakdown(samples: list[Sample], preds: list[dict], key) -> dict:
    groups: dict[str, list[int]] = defaultdict(list)
    for i, x in enumerate(samples):
        groups[key(x)].append(i)
    return {k: _metrics([samples[i] for i in ix], [preds[i] for i in ix]) for k, ix in sorted(groups.items())}


def evaluate(samples: list[Sample], candidates: dict | None = None) -> dict:
    """Run the protocol. Returns a report with per-day results, eligibility and the winner (or None)."""
    candidates = candidates or CANDIDATES
    by_day: dict[str, list[Sample]] = defaultdict(list)
    for x in samples:
        by_day[x.day].append(x)
    days = sorted(by_day)
    report: dict = {"days": len(days), "samples": len(samples), "rules": {
        "min_train_days": MIN_TRAIN_DAYS, "min_test_days": MIN_TEST_DAYS, "mae_gain": MAE_GAIN,
        "win_share": WIN_SHARE, "coverage": COVERAGE, "decision_buckets": DECISION_BUCKETS,
        "amendments": ["A1.1 purge", "A1.2 decision-horizon MAE", "A1.3 conformalized intervals",
                       "A2 gbm_numbat candidate (TfL NUMBAT 2025 service and demand)"]}}
    n_test = min(MAX_TEST_DAYS, len(days) - MIN_TRAIN_DAYS)
    if n_test < MIN_TEST_DAYS:
        report.update(status="not_enough_data", winner=None,
                      message=f"Need {MIN_TRAIN_DAYS + MIN_TEST_DAYS} days of data; have {len(days)}.")
        return report

    per_day: dict[str, dict] = {}
    for d in days[-n_test:]:
        start = _day_start_utc(d)
        # Amendment 1, A1.1: purge training samples whose outcome falls on or after the test day's start.
        train = [x for day in days if day < d for x in by_day[day] if x.arrived_at is None or x.arrived_at < start]
        test = by_day[d]
        per_day[d] = {}
        for name, cls in candidates.items():
            preds = _predict(fit_candidate(name, cls, train), test)
            per_day[d][name] = _metrics(test, preds)
            per_day[d][name]["decision_mae_s"] = (lambda v: round(v, 1) if v is not None else None)(
                decision_mae(test, preds))
            if name in ("provider",) or d == days[-1]:
                per_day[d][name]["by_lead"] = _breakdown(test, preds, lambda x: lead_bucket(x.lead_s))
                per_day[d][name]["by_line"] = _breakdown(test, preds, lambda x: x.line_id)
    report["per_day"] = per_day

    summary, eligible = {}, []
    prov = [per_day[d]["provider"]["mae_s"] for d in per_day]
    prov_dec = [per_day[d]["provider"]["decision_mae_s"] for d in per_day]
    for name in candidates:
        maes = [per_day[d][name]["mae_s"] for d in per_day]
        decs = [per_day[d][name]["decision_mae_s"] for d in per_day]
        cov = statistics.fmean(per_day[d][name]["coverage"] for d in per_day)
        wins = sum(m < p for m, p in zip(maes, prov))
        mean_mae, mean_prov = statistics.fmean(maes), statistics.fmean(prov)
        paired = [(c, p) for c, p in zip(decs, prov_dec) if c is not None and p is not None]
        mean_dec = statistics.fmean(c for c, _ in paired) if paired else None
        mean_prov_dec = statistics.fmean(p for _, p in paired) if paired else None
        checks = {"mae_gain": mean_mae <= mean_prov * (1 - MAE_GAIN), "wins": wins >= len(maes) * WIN_SHARE,
                  "coverage": COVERAGE[0] <= cov <= COVERAGE[1],
                  # Amendment 1, A1.2 (no decision-horizon data at all counts as a fail: stricter, not looser)
                  "decision_gain": mean_dec is not None and mean_dec <= mean_prov_dec * (1 - MAE_GAIN)}
        summary[name] = {"mean_mae_s": round(mean_mae, 1), "win_days": wins, "test_days": len(maes),
                         "coverage": round(cov, 3), "checks": checks,
                         "mean_decision_mae_s": round(mean_dec, 1) if mean_dec is not None else None}
        if name != "provider" and all(checks.values()):
            eligible.append(name)
    report["summary"] = summary
    if not eligible:
        report.update(status="no_eligible_candidate", winner=None,
                      message="No candidate passed every rule: Paxen keeps showing TfL's own numbers.")
        return report
    best = min(summary[n]["mean_mae_s"] for n in eligible)
    close = [n for n in eligible if summary[n]["mean_mae_s"] <= best * (1 + TIE)]
    winner = min(close, key=lambda n: SIMPLICITY[n])
    report.update(status="winner", winner=winner,
                  message=f"{winner}: {summary[winner]['mean_mae_s']}s vs TfL {summary['provider']['mean_mae_s']}s "
                          f"mean error over {len(per_day)} unseen days.")
    return report


MAX_PER_DAY = 25_000  # memory guard: a fixed random sample of each day's training pairs
PRESAMPLE = 4  # the database pre-sample keeps ~this many times MAX_PER_DAY predictions (not all have a match)

# Storage (thin_history): a complete London day this many days old is reduced to the predictions load_daily reads.
KEEP_FULL_DAYS = 1  # yesterday (and today) stay complete: arrival inference reads 20 min back, Darwin matching 6 h
THIN_DAYS_PER_RUN = 3  # days thinned per training run, so the deletes are spread over several runs
THIN_SLICE = timedelta(minutes=10)  # each delete covers 10 minutes of polls (~12k rows) in its own transaction
THIN_PAUSE_S = 5.0  # between slices: keeps the database's write-ahead log (on the same disk) small


def day_windows(lo: datetime, hi: datetime):
    """The London days from lo's day to hi, as (start, end) aware datetimes: the windows load_daily samples."""
    day = aware(lo).astimezone(LONDON).replace(hour=0, minute=0, second=0, microsecond=0)
    end = aware(hi)
    while day <= end:
        nxt = (day + timedelta(days=1, hours=2)).replace(hour=0)  # DST-safe next local midnight
        yield day, nxt
        day = nxt


def presample_stride(n: int) -> int:
    """load_daily keeps every stride-th prediction (by id) of a day with n predictions."""
    return max(1, (n or 0) // (MAX_PER_DAY * PRESAMPLE))


def _day_count(s: Session, source: str, start: datetime, end: datetime) -> int:
    return s.scalar(select(func.count()).select_from(Prediction).where(
        Prediction.source == source, Prediction.polled_at >= naive_utc(start), Prediction.polled_at < naive_utc(end))) or 0


def _thinned_stride(s: Session, source: str, start: datetime, end: datetime) -> int | None:
    """For a day thinned before strides were recorded: thinning goes from the start of the day and keeps only ids
    divisible by the stride, so the gcd of the first busy hour's ids recovers it. None if that hour is untouched."""
    import math

    a, stop = naive_utc(start), naive_utc(end)
    while a < stop:
        b = min(a + timedelta(hours=1), stop)
        ids = s.scalars(select(Prediction.id).where(
            Prediction.source == source, Prediction.polled_at >= a, Prediction.polled_at < b)).all()
        if len(ids) >= 50:  # an untouched hour's ids are near-consecutive, so their gcd is 1
            g = math.gcd(*ids)
            return g if g > 1 else None
        a = b
    return None


def day_stride(s: Session, source: str, start: datetime, end: datetime) -> int:
    """The 1-in-k sample of this London day that load_daily reads: recorded when the day was thinned, recovered
    from the ids if thinning began before strides were recorded, otherwise from the day's count."""
    rec = s.get(DaySample, (source, str(start.date())))
    if rec:
        return rec.stride
    return _thinned_stride(s, source, start, end) or presample_stride(_day_count(s, source, start, end))


def load_daily(s: Session, source: str, methods: tuple[str, ...] | None, seed: int = 0) -> list[Sample]:
    """Load history one London day at a time, keeping at most MAX_PER_DAY pairs per day (same seed, same sample).

    Busy days are thinned in the database first (every n-th prediction by id), so memory stays bounded however
    much the recorder stores: a full day of the whole Tube network is ~13 million predictions."""
    import random

    lo, hi = s.execute(select(func.min(Prediction.polled_at), func.max(Prediction.polled_at))
                       .where(Prediction.source == source)).one()
    if not lo:
        return []
    out: list[Sample] = []
    for day, nxt in day_windows(lo, hi):
        batch = load_samples(s, source, since=day, until=nxt, methods=methods, stride=day_stride(s, source, day, nxt))
        if len(batch) > MAX_PER_DAY:
            batch = random.Random(f"{seed}-{day.date()}").sample(batch, MAX_PER_DAY)
        out += batch
    out.sort(key=lambda x: x.polled_at)
    return out


def thin_history(s: Session, source: str, now: datetime, keep_full_days: int = KEEP_FULL_DAYS,
                 max_days: int = THIN_DAYS_PER_RUN, pause_s: float = THIN_PAUSE_S) -> dict:
    """Storage. The recorder keeps ~1.8 million predictions a day, but load_daily only ever reads every stride-th one
    (by id) of a busy day. Once a day is old enough, delete the rest. The day's stride is recorded first, so
    load_daily goes on reading exactly the same predictions (no evaluation or training result changes; tests check
    this, including after an interrupted run), and the raw archive still holds every original response. Deletes go
    10 minutes of polls at a time, with pauses, at most `max_days` days per run."""
    import time

    lo = s.scalar(select(func.min(Prediction.polled_at)).where(Prediction.source == source))
    out: dict = {"days": [], "deleted": 0}
    if not lo:
        return out
    cutoff = aware(now).astimezone(LONDON).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=keep_full_days)
    for day, nxt in day_windows(lo, cutoff):
        if nxt > cutoff or len(out["days"]) >= max_days:
            break
        key = str(day.date())
        rec = s.get(DaySample, (source, key))
        if rec and rec.thinned:
            continue
        if not rec:
            rec = DaySample(source=source, day=key, stride=day_stride(s, source, day, nxt), thinned=False)
            s.add(rec)
            s.commit()  # recorded before anything is deleted
        k = rec.stride
        if k > 1:
            a, end = naive_utc(day), naive_utc(nxt)
            while a < end:
                b = min(a + THIN_SLICE, end)
                out["deleted"] += s.query(Prediction).filter(
                    Prediction.source == source, Prediction.polled_at >= a, Prediction.polled_at < b,
                    Prediction.id % k != 0).delete(synchronize_session=False)
                s.commit()
                a = b
                if pause_s:
                    time.sleep(pause_s)
            out["days"].append(f"{key} (kept 1 in {k})")
        rec.thinned = True
        s.commit()
    return out


PAIR_WINDOW = timedelta(seconds=MAX_LEAD_S + 900)  # load_samples pairs an arrival with predictions this far before it
TRIM_DELETE_BATCH = 1000


def trim_arrivals(s: Session, source: str, max_days: int = THIN_DAYS_PER_RUN, pause_s: float = THIN_PAUSE_S) -> dict:
    """Storage. After a day's predictions are thinned (thin_history), most of its arrivals have no stored prediction
    left to pair with, and load_samples, the only reader of old arrivals, can never use them. Delete exactly those:
    an arrival stays if any stored prediction of the same stop, line and vehicle was made within PAIR_WINDOW before it
    with a lead time load_samples accepts (a looser test than load_samples' own, so every pair it could form is kept
    and training and evaluation read exactly the same pairs; tests check this). Only days whose own and previous day's
    predictions are final (thinned) are trimmed; predictions are only ever added for the present, so the answer can't
    change later. The raw archive keeps every original response, so nothing is lost for good."""
    import bisect
    import time

    out: dict = {"days": [], "deleted": 0}
    recs = s.scalars(select(DaySample).where(DaySample.source == source).order_by(DaySample.day)).all()
    thinned = {r.day for r in recs if r.thinned}
    first = recs[0].day if recs else None
    for rec in recs:
        if not rec.thinned or rec.arrivals_trimmed or len(out["days"]) >= max_days:
            continue
        day = _day_start_utc(rec.day)
        prev = str((aware(day).astimezone(LONDON) - timedelta(hours=12)).date())
        if rec.day != first and prev not in thinned:
            continue  # the previous day's predictions (which pair with this day's early arrivals) aren't final yet
        nxt = _day_start_utc(str((aware(day).astimezone(LONDON) + timedelta(hours=36)).date()))
        a, end, deleted = naive_utc(day), naive_utc(nxt), 0
        while a < end:
            b = min(a + THIN_SLICE, end)
            seen: dict[tuple, list] = defaultdict(list)
            for stop, line, veh, polled in s.execute(
                    select(Prediction.stop_id, Prediction.line_id, Prediction.vehicle_id, Prediction.polled_at)
                    .where(Prediction.source == source, Prediction.polled_at >= a - PAIR_WINDOW,
                           Prediction.polled_at < b, Prediction.tts_s <= MAX_LEAD_S)):
                seen[(stop, line, veh)].append(polled)
            for v in seen.values():
                v.sort()
            gone = []
            for aid, stop, line, veh, arrived in s.execute(
                    select(ObservedArrival.id, ObservedArrival.stop_id, ObservedArrival.line_id,
                           ObservedArrival.vehicle_id, ObservedArrival.arrived_at)
                    .where(ObservedArrival.source == source, ObservedArrival.arrived_at >= a,
                           ObservedArrival.arrived_at < b)):
                times = seen.get((stop, line, veh), ())
                i = bisect.bisect_left(times, arrived - PAIR_WINDOW)
                if not (i < len(times) and times[i] <= arrived):
                    gone.append(aid)
            for i in range(0, len(gone), TRIM_DELETE_BATCH):
                deleted += s.query(ObservedArrival).filter(
                    ObservedArrival.id.in_(gone[i:i + TRIM_DELETE_BATCH])).delete(synchronize_session=False)
            s.commit()
            a = b
            if pause_s and gone:
                time.sleep(pause_s)
        rec.arrivals_trimmed = True
        s.commit()
        out["days"].append(f"{rec.day} (-{deleted} arrivals)")
        out["deleted"] += deleted
    return out


def run(s: Session, source: str, promote: bool = True) -> dict:
    """Evaluate on the database's history. Ground truth: measured (Trackernet) when it exists, else inferred."""
    measured = load_daily(s, source, ("trackernet",))
    samples = measured if measured else load_daily(s, source, None)
    report = evaluate(samples)
    report["ground_truth"] = "measured (Trackernet)" if measured else "inferred from countdowns"
    # Amendment 3: Overground and Elizabeth line, measured by Darwin, reported alongside (never decides promotion)
    rail = load_daily(s, source, ("darwin",))
    if rail:
        r = evaluate(rail)
        report["rail_measured"] = {k: r.get(k) for k in ("status", "days", "samples", "summary", "message")}
    if promote:
        kind = model_kind(source)
        s.query(ModelVersion).filter(ModelVersion.kind == kind, ModelVersion.active.is_(True)).update(
            {ModelVersion.active: False})
        if report["winner"]:
            final = fit_candidate(report["winner"], CANDIDATES[report["winner"]], samples)
            s.add(ModelVersion(kind=kind, params=final.to_params(), metrics=_slim(report), active=True,
                               note=f"promoted by rolling-day protocol: {report['message']}"))
        else:
            # Keep a record of the decision; nothing is active, so forecasts use TfL's numbers.
            s.add(ModelVersion(kind=kind, params={"model": "provider"}, metrics=_slim(report), active=False,
                               note=report.get("message")))
        s.commit()
    return report


def _slim(report: dict) -> dict:
    """What the app shows: headline per candidate, plus provider/winner breakdowns for the latest day."""
    return json.loads(json.dumps({k: v for k, v in report.items() if k != "per_day"}, default=str)) | {
        "latest_day": (lambda pd: {d: pd[d] for d in sorted(pd)[-1:]})(report.get("per_day", {}))}


def main() -> None:
    from .config import settings
    from .db import SessionLocal, init_db

    logging.basicConfig(level=logging.INFO)
    init_db()
    with SessionLocal() as s:
        rep = run(s, "tfl" if settings.provider == "tfl" else "sim", promote="--dry-run" not in sys.argv)
    print(json.dumps({k: v for k, v in rep.items() if k != "per_day"}, indent=2, default=str))


if __name__ == "__main__":
    main()
