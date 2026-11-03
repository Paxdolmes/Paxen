"""Arrival correction model (prediction layer "Arrival/journey correction").

Learns how wrong the provider countdown is, as a function of features that are
known at prediction time: line, stop, lead time, time-of-day band and whether
the line was disrupted. Deliberately interpretable: a hierarchy of empirical
error distributions with shrinkage toward the parent group, so sparse stops
borrow strength from their line, and lines from the network.

Output is an *adjustment plus an interval* on top of the provider estimate —
the provider feed is never blindly overwritten.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import ModelVersion, ObservedArrival, Prediction
from .timeutil import aware, hour_band

LEAD_BUCKETS = [(0, 120, "0-2m"), (120, 300, "2-5m"), (300, 600, "5-10m"), (600, 1200, "10-20m"), (1200, 1e9, "20m+")]
SHRINK_K = 25.0
MAX_LEAD_S = 1800


def lead_bucket(lead_s: float) -> str:
    for lo, hi, name in LEAD_BUCKETS:
        if lo <= lead_s < hi:
            return name
    return "20m+"


@dataclass
class Sample:
    polled_at: datetime
    line_id: str
    stop_id: str
    lead_s: float
    band: str
    disrupted: bool
    error_s: float  # observed - provider expected (positive = later than promised)
    quality: float = 1.0


def load_samples(s: Session, source: str, since: datetime | None = None, min_quality: float = 0.3) -> list[Sample]:
    q = (
        select(Prediction.polled_at, Prediction.line_id, Prediction.stop_id, Prediction.tts_s,
               Prediction.expected_arrival, Prediction.line_category, ObservedArrival.arrived_at,
               ObservedArrival.quality)
        .join(ObservedArrival, (ObservedArrival.source == Prediction.source)
              & (ObservedArrival.stop_id == Prediction.stop_id)
              & (ObservedArrival.line_id == Prediction.line_id)
              & (ObservedArrival.vehicle_id == Prediction.vehicle_id))
        .where(Prediction.source == source, ObservedArrival.quality >= min_quality,
               Prediction.polled_at <= ObservedArrival.arrived_at, Prediction.tts_s <= MAX_LEAD_S)
    )
    if since:
        q = q.where(Prediction.polled_at >= since)
    out = []
    for polled, line, stop, tts, exp, cat, arrived, quality in s.execute(q):
        err = (arrived - exp).total_seconds()
        if abs(err) > 1800:  # vehicle id reused hours later — not the same trip
            continue
        out.append(Sample(aware(polled), line, stop, float(tts), hour_band(aware(polled)), cat != "good", err, quality))
    out.sort(key=lambda x: x.polled_at)
    return out


def _quantile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    pos = (len(xs) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


@dataclass
class CorrectionModel:
    groups: dict[str, dict] = field(default_factory=dict)  # key -> {n, mean, q10, q90}
    version: int | None = None

    # Hierarchy, most general first. Each key also includes the lead bucket.
    @staticmethod
    def keys(line: str, stop: str, lead_s: float, band: str, disrupted: bool) -> list[str]:
        lb = lead_bucket(lead_s)
        d = "D" if disrupted else "N"
        return [f"g|{lb}|{d}", f"l|{line}|{lb}|{d}", f"ls|{line}|{stop}|{lb}|{d}", f"lsb|{line}|{stop}|{lb}|{band}|{d}"]

    @classmethod
    def fit(cls, samples: list[Sample]) -> "CorrectionModel":
        buckets: dict[str, list[float]] = defaultdict(list)
        for x in samples:
            for k in cls.keys(x.line_id, x.stop_id, x.lead_s, x.band, x.disrupted):
                buckets[k].append(x.error_s)
        groups = {
            k: {"n": len(v), "mean": statistics.fmean(v), "q10": _quantile(v, 0.1), "q90": _quantile(v, 0.9)}
            for k, v in buckets.items()
        }
        return cls(groups)

    def predict(self, line: str, stop: str, lead_s: float, band: str, disrupted: bool) -> dict:
        """Return {bias_s, q10_s, q90_s, support}. With no data: zero adjustment and a lead-scaled interval."""
        spread = 20 + 0.08 * lead_s + (60 if disrupted else 0)
        est = {"mean": 0.0, "q10": -spread * 0.6, "q90": spread}
        support = 0
        for k in self.keys(line, stop, lead_s, band, disrupted):
            g = self.groups.get(k)
            if not g:
                continue
            w = g["n"] / (g["n"] + SHRINK_K)
            est = {m: w * g[m] + (1 - w) * est[m] for m in ("mean", "q10", "q90")}
            support = g["n"]
        return {"bias_s": est["mean"], "q10_s": min(est["q10"], est["mean"]), "q90_s": max(est["q90"], est["mean"]),
                "support": support}

    def to_params(self) -> dict:
        return {"groups": self.groups, "shrink_k": SHRINK_K}

    @classmethod
    def from_params(cls, params: dict, version: int | None = None) -> "CorrectionModel":
        return cls(params.get("groups", {}), version)


def _metrics(errors: list[float]) -> dict:
    if not errors:
        return {"n": 0}
    abs_e = [abs(e) for e in errors]
    return {
        "n": len(errors),
        "mae_s": round(statistics.fmean(abs_e), 1),
        "bias_s": round(statistics.fmean(errors), 1),
        "within_2m": round(sum(e <= 120 for e in abs_e) / len(abs_e), 3),
        "within_5m": round(sum(e <= 300 for e in abs_e) / len(abs_e), 3),
    }


def evaluate(model: CorrectionModel, test: list[Sample]) -> dict:
    prov, corr, inside = [], [], 0
    by_lead: dict[str, tuple[list, list]] = defaultdict(lambda: ([], []))
    by_line: dict[str, tuple[list, list]] = defaultdict(lambda: ([], []))
    for x in test:
        p = model.predict(x.line_id, x.stop_id, x.lead_s, x.band, x.disrupted)
        residual = x.error_s - p["bias_s"]
        prov.append(x.error_s)
        corr.append(residual)
        inside += p["q10_s"] <= x.error_s <= p["q90_s"]
        for d, k in ((by_lead, lead_bucket(x.lead_s)), (by_line, x.line_id)):
            d[k][0].append(x.error_s)
            d[k][1].append(residual)
    return {
        "provider": _metrics(prov),
        "corrected": _metrics(corr),
        "interval_coverage_p10_p90": round(inside / len(test), 3) if test else None,
        "by_lead": {k: {"provider": _metrics(a), "corrected": _metrics(b)} for k, (a, b) in sorted(by_lead.items())},
        "by_line": {k: {"provider": _metrics(a), "corrected": _metrics(b)} for k, (a, b) in sorted(by_line.items())},
    }


def train_and_maybe_promote(s: Session, source: str, min_test: int = 200, holdout: float = 0.3) -> dict:
    """Time-ordered split (no leakage from the future), fit on the past, test on the most recent slice.
    Promote only if corrected MAE beats the provider by a margin."""
    samples = load_samples(s, source)
    if len(samples) < min_test * 2:
        return {"status": "insufficient_data", "samples": len(samples)}
    cut = int(len(samples) * (1 - holdout))
    train, test = samples[:cut], samples[cut:]
    candidate = CorrectionModel.fit(train)
    metrics = evaluate(candidate, test)
    prov, corr = metrics["provider"]["mae_s"], metrics["corrected"]["mae_s"]
    promote = len(test) >= min_test and corr < prov * 0.97
    # The served model is re-fit on all data once it has proven itself out-of-sample.
    final = CorrectionModel.fit(samples) if promote else candidate
    mv = ModelVersion(kind="arrival_correction", params=final.to_params(),
                      metrics={**metrics, "train_n": len(train), "test_n": len(test)}, active=promote,
                      note="promoted" if promote else "shadow: did not beat provider baseline")
    if promote:
        s.query(ModelVersion).filter(ModelVersion.kind == "arrival_correction", ModelVersion.active.is_(True)).update(
            {ModelVersion.active: False})
    s.add(mv)
    s.commit()
    return {"status": "promoted" if promote else "shadow", "version": mv.id, "provider_mae_s": prov,
            "corrected_mae_s": corr, "test_n": len(test)}


_cache: dict[str, tuple[int | None, CorrectionModel]] = {}


def active_model(s: Session) -> CorrectionModel:
    mv = s.scalars(select(ModelVersion).where(ModelVersion.kind == "arrival_correction", ModelVersion.active.is_(True))
                   .order_by(ModelVersion.id.desc())).first()
    if not mv:
        return CorrectionModel()
    cached = _cache.get("arrival")
    if cached and cached[0] == mv.id:
        return cached[1]
    m = CorrectionModel.from_params(mv.params, mv.id)
    _cache["arrival"] = (mv.id, m)
    return m
