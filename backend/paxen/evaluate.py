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

from sqlalchemy.orm import Session

from .db import ModelVersion
from .forecast import Sample, lead_bucket, load_samples, model_kind
from .models import CANDIDATES, SIMPLICITY

log = logging.getLogger("paxen.evaluate")

MIN_TRAIN_DAYS = 7
MIN_TEST_DAYS = 3
MAX_TEST_DAYS = 7
MAE_GAIN = 0.03  # beat the provider's mean MAE by at least 3%
WIN_SHARE = 2 / 3  # ... and on at least two-thirds of test days
COVERAGE = (0.70, 0.90)  # honest 80% interval
TIE = 0.01  # within 1%: the simpler model wins


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
                          queue_rank=x.queue_rank, gap_s=x.gap_s, feed_age_s=x.feed_age_s, weekend=x.weekend)
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
        "win_share": WIN_SHARE, "coverage": COVERAGE}}
    n_test = min(MAX_TEST_DAYS, len(days) - MIN_TRAIN_DAYS)
    if n_test < MIN_TEST_DAYS:
        report.update(status="not_enough_data", winner=None,
                      message=f"Need {MIN_TRAIN_DAYS + MIN_TEST_DAYS} days of data; have {len(days)}.")
        return report

    per_day: dict[str, dict] = {}
    for d in days[-n_test:]:
        train = [x for day in days if day < d for x in by_day[day]]
        test = by_day[d]
        per_day[d] = {}
        for name, cls in candidates.items():
            preds = _predict(cls.fit(train), test)
            per_day[d][name] = _metrics(test, preds)
            if name in ("provider",) or d == days[-1]:
                per_day[d][name]["by_lead"] = _breakdown(test, preds, lambda x: lead_bucket(x.lead_s))
                per_day[d][name]["by_line"] = _breakdown(test, preds, lambda x: x.line_id)
    report["per_day"] = per_day

    summary, eligible = {}, []
    prov = [per_day[d]["provider"]["mae_s"] for d in per_day]
    for name in candidates:
        maes = [per_day[d][name]["mae_s"] for d in per_day]
        cov = statistics.fmean(per_day[d][name]["coverage"] for d in per_day)
        wins = sum(m < p for m, p in zip(maes, prov))
        mean_mae, mean_prov = statistics.fmean(maes), statistics.fmean(prov)
        checks = {"mae_gain": mean_mae <= mean_prov * (1 - MAE_GAIN), "wins": wins >= len(maes) * WIN_SHARE,
                  "coverage": COVERAGE[0] <= cov <= COVERAGE[1]}
        summary[name] = {"mean_mae_s": round(mean_mae, 1), "win_days": wins, "test_days": len(maes),
                         "coverage": round(cov, 3), "checks": checks}
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


def run(s: Session, source: str, promote: bool = True) -> dict:
    """Evaluate on the database's history. Ground truth: measured (Trackernet) when it exists, else inferred."""
    measured = load_samples(s, source, methods=("trackernet",))
    samples = measured if measured else load_samples(s, source)
    report = evaluate(samples)
    report["ground_truth"] = "measured (Trackernet)" if measured else "inferred from countdowns"
    if promote:
        kind = model_kind(source)
        s.query(ModelVersion).filter(ModelVersion.kind == kind, ModelVersion.active.is_(True)).update(
            {ModelVersion.active: False})
        if report["winner"]:
            final = CANDIDATES[report["winner"]].fit(samples)
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
