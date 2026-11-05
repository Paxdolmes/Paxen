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
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import ModelVersion, ObservedArrival, Prediction
from .timeutil import aware, hour_band, naive_utc

LEAD_BUCKETS = [(0, 120, "0-2m"), (120, 300, "2-5m"), (300, 600, "5-10m"), (600, 1200, "10-20m"), (1200, 1e9, "20m+")]
SHRINK_K = 25.0
MAX_LEAD_S = 1800


def lead_bucket(lead_s: float) -> str:
    for lo, hi, name in LEAD_BUCKETS:
        if lo <= lead_s < hi:
            return name
    return "20m+"


@dataclass(slots=True)
class Sample:
    polled_at: datetime
    line_id: str
    stop_id: str
    lead_s: float
    band: str
    disrupted: bool
    error_s: float  # observed - provider expected (positive = later than promised)
    quality: float = 1.0
    # extra context known at prediction time (model v2)
    category: str = "good"
    queue_rank: int | None = None
    gap_s: int | None = None
    feed_age_s: float | None = None
    method: str = "countdown_inferred"
    arrived_at: datetime | None = None  # the outcome's time (for purging at split boundaries)
    event: str | None = None  # which arrival this prediction was about (stop|line|vehicle|time)
    bound: str | None = None  # the platform's direction ("westbound"), when its name gives one (Amendment 2)

    @property
    def day(self) -> str:
        from .timeutil import local

        return local(self.polled_at).strftime("%Y-%m-%d")

    @property
    def weekend(self) -> bool:
        from .timeutil import local

        return local(self.polled_at).weekday() >= 5


def load_samples(s: Session, source: str, since: datetime | None = None, min_quality: float = 0.3,
                 methods: tuple[str, ...] | None = None, until: datetime | None = None,
                 stride: int = 1) -> list[Sample]:
    """Pair each recorded prediction with the arrival it was predicting.

    Matching uses the vehicle id plus direction: for measured (Trackernet) arrivals the platform's bound
    ("southbound"), otherwise the destination. If both a measured and an inferred arrival match, the measured one
    wins. `methods` restricts which kinds of ground truth are used (e.g. only "trackernet").
    `stride` > 1 keeps only every stride-th prediction (by id), sampled in the database to bound memory.
    """
    from .trackernet import bound_of

    q = (
        select(Prediction.id, Prediction.polled_at, Prediction.line_id, Prediction.stop_id, Prediction.tts_s,
               Prediction.vehicle_id,
               Prediction.expected_arrival, Prediction.line_category, Prediction.direction, Prediction.platform,
               Prediction.queue_rank, Prediction.gap_s, Prediction.feed_ts,
               ObservedArrival.arrived_at, ObservedArrival.quality, ObservedArrival.method, ObservedArrival.direction)
        .join(ObservedArrival, (ObservedArrival.source == Prediction.source)
              & (ObservedArrival.stop_id == Prediction.stop_id)
              & (ObservedArrival.line_id == Prediction.line_id)
              & (ObservedArrival.vehicle_id == Prediction.vehicle_id))
        .where(Prediction.source == source, ObservedArrival.quality >= min_quality,
               Prediction.polled_at <= ObservedArrival.arrived_at, Prediction.tts_s <= MAX_LEAD_S)
    )
    # A vehicle id recurs many times a day at the same stop, so without an upper bound on the arrival every
    # prediction pairs with every later visit of that vehicle (tens of millions of rows a day, which ran the
    # worker out of memory). Pairs further apart than this are discarded below anyway.
    max_gap = timedelta(seconds=MAX_LEAD_S + 900)
    if s.get_bind().dialect.name == "postgresql":
        q = q.where(ObservedArrival.arrived_at <= Prediction.polled_at + max_gap)
    if since:
        q = q.where(Prediction.polled_at >= naive_utc(since))
    if until:
        q = q.where(Prediction.polled_at < naive_utc(until), ObservedArrival.arrived_at < naive_utc(until) + max_gap)
    if methods:
        q = q.where(ObservedArrival.method.in_(methods))
    if stride > 1:
        q = q.where(Prediction.id % stride == 0)
    best: dict[int, tuple] = {}
    for (pid, polled, line, stop, tts, vehicle, exp, cat, p_dir, platform, rank_q, gap, feed_ts, arrived, quality,
         method, o_dir) in s.execute(q.execution_options(yield_per=10_000)):
        if method == "trackernet":
            b = bound_of(platform)
            if b and o_dir and b != o_dir:
                continue  # same train, other direction (e.g. after reversing at a terminus)
        elif not (p_dir == o_dir or (p_dir is None and o_dir is None)):
            continue
        err = (arrived - exp).total_seconds()
        if abs(err) > 1800 or (arrived - polled).total_seconds() > MAX_LEAD_S + 900:
            continue  # vehicle id reused by a later trip: not the same journey
        rank = (1 if method == "trackernet" else 0, quality, -abs(err))
        if pid not in best or rank > best[pid][0]:
            age = (polled - feed_ts).total_seconds() if feed_ts else None
            best[pid] = (rank, Sample(aware(polled), line, stop, float(tts), hour_band(aware(polled)), cat != "good",
                                      err, quality, cat or "good", rank_q, gap, age, method, aware(arrived),
                                      f"{stop}|{line}|{vehicle}|{arrived:%Y%m%d%H%M%S}", bound_of(platform)))
    out = [v[1] for v in best.values()]
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
        # "mean" is the group's typical error. A median: real feeds have rare huge errors (vehicle-id reuse,
        # unannounced short-forms) that would drag an average and make the correction worse than none.
        groups = {
            k: {"n": len(v), "mean": statistics.median(v), "q10": _quantile(v, 0.1), "q90": _quantile(v, 0.9)}
            for k, v in buckets.items()
        }
        return cls(groups)

    def predict(self, line: str, stop: str, lead_s: float, band: str, disrupted: bool, **_ctx) -> dict:
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
    mv = ModelVersion(kind=model_kind(source), params=final.to_params(),
                      metrics={**metrics, "train_n": len(train), "test_n": len(test)}, active=promote,
                      note="promoted" if promote else "shadow: did not beat provider baseline")
    if promote:
        s.query(ModelVersion).filter(ModelVersion.kind == model_kind(source), ModelVersion.active.is_(True)).update(
            {ModelVersion.active: False})
    s.add(mv)
    s.commit()
    return {"status": "promoted" if promote else "shadow", "version": mv.id, "provider_mae_s": prov,
            "corrected_mae_s": corr, "test_n": len(test)}


_cache: dict[str, tuple[int | None, CorrectionModel]] = {}


def model_kind(source: str) -> str:
    """Models are per data source: a model trained on simulated data must never correct live TfL data."""
    return f"arrival_correction:{source}"


def active_model(s: Session, source: str = "sim"):
    """The model the protocol promoted for this data source; with none active, no correction (TfL's numbers)."""
    mv = s.scalars(select(ModelVersion).where(ModelVersion.kind == model_kind(source), ModelVersion.active.is_(True))
                   .order_by(ModelVersion.id.desc())).first()
    if not mv:
        return CorrectionModel()
    cached = _cache.get(source)
    if cached and cached[0] == mv.id:
        return cached[1]
    from .models import from_params

    m = from_params(mv.params)
    m.version = mv.id
    _cache[source] = (mv.id, m)
    return m
