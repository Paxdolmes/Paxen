"""Candidate arrival-correction models (model v2). See docs/model-evaluation.md for how one is chosen.

Every candidate has the same interface:
    fit(samples) -> model
    predict(line, stop, lead_s, band, disrupted, **ctx) -> {"bias_s", "q10_s", "q90_s", "support"}
    to_params() / from_params(params)
where ctx may hold: category, queue_rank, gap_s, feed_age_s, weekend. Unknown context is simply ignored.
"""
from __future__ import annotations

import base64
import io
import statistics
from collections import defaultdict

from .forecast import CorrectionModel, Sample, _quantile, lead_bucket

SIMPLICITY = {"provider": 0, "hier": 1, "hier_ctx": 2, "gbm": 3}


class ProviderModel:
    """TfL's countdown as-is: the baseline every candidate must beat."""
    kind = "provider"

    @classmethod
    def fit(cls, samples: list[Sample]) -> "ProviderModel":
        m = cls()
        errs = [x.error_s for x in samples]
        m.q10, m.q90 = (_quantile(errs, 0.1), _quantile(errs, 0.9)) if errs else (-60.0, 120.0)
        return m

    def predict(self, line, stop, lead_s, band, disrupted, **ctx) -> dict:
        return {"bias_s": 0.0, "q10_s": min(0.0, self.q10), "q90_s": max(0.0, self.q90), "support": 0}

    def to_params(self) -> dict:
        return {"model": self.kind, "q10": self.q10, "q90": self.q90}

    @classmethod
    def from_params(cls, p: dict) -> "ProviderModel":
        m = cls()
        m.q10, m.q90 = p.get("q10", -60.0), p.get("q90", 120.0)
        return m


class HierModel(CorrectionModel):
    """The current model: network -> line -> stop -> time-band median errors with shrinkage."""
    kind = "hier"

    def predict(self, line, stop, lead_s, band, disrupted, **ctx) -> dict:
        return super().predict(line, stop, lead_s, band, disrupted)

    def to_params(self) -> dict:
        return {"model": self.kind, **super().to_params()}


def _rank_bucket(r) -> str:
    return "r?" if r is None else ("r1" if r <= 1 else "r2" if r == 2 else "r3+")


class HierCtxModel:
    """Hierarchy that also splits by place in the queue and weekday/weekend, shrinking toward the parent."""
    kind = "hier_ctx"
    K = 25.0

    def __init__(self, groups: dict | None = None):
        self.groups = groups or {}

    @staticmethod
    def keys(line, stop, lead_s, band, disrupted, queue_rank=None, weekend=None, **_):
        lb, d = lead_bucket(lead_s), ("D" if disrupted else "N")
        rb, wk = _rank_bucket(queue_rank), ("we" if weekend else "wd")
        return [f"g|{lb}|{d}", f"l|{line}|{lb}|{d}", f"lr|{line}|{lb}|{rb}|{d}", f"ls|{line}|{stop}|{lb}|{d}",
                f"lsw|{line}|{stop}|{lb}|{wk}|{d}", f"lsb|{line}|{stop}|{lb}|{band}|{wk}|{d}"]

    @classmethod
    def fit(cls, samples: list[Sample]) -> "HierCtxModel":
        buckets: dict[str, list[float]] = defaultdict(list)
        for x in samples:
            for k in cls.keys(x.line_id, x.stop_id, x.lead_s, x.band, x.disrupted, x.queue_rank, x.weekend):
                buckets[k].append(x.error_s)
        return cls({k: {"n": len(v), "mean": statistics.median(v), "q10": _quantile(v, 0.1), "q90": _quantile(v, 0.9)}
                    for k, v in buckets.items()})

    def predict(self, line, stop, lead_s, band, disrupted, **ctx) -> dict:
        spread = 20 + 0.08 * lead_s + (60 if disrupted else 0)
        est = {"mean": 0.0, "q10": -spread * 0.6, "q90": spread}
        support = 0
        for k in self.keys(line, stop, lead_s, band, disrupted, ctx.get("queue_rank"), ctx.get("weekend")):
            g = self.groups.get(k)
            if not g:
                continue
            w = g["n"] / (g["n"] + self.K)
            est = {m: w * g[m] + (1 - w) * est[m] for m in ("mean", "q10", "q90")}
            support = g["n"]
        return {"bias_s": est["mean"], "q10_s": min(est["q10"], est["mean"]), "q90_s": max(est["q90"], est["mean"]),
                "support": support}

    def to_params(self) -> dict:
        return {"model": self.kind, "groups": self.groups}

    @classmethod
    def from_params(cls, p: dict) -> "HierCtxModel":
        return cls(p.get("groups", {}))


BANDS = ["am_peak", "interpeak", "pm_peak", "off_peak", "weekend"]
CATS = ["good", "minor", "severe", "part_suspended", "suspended"]


class GBMModel:
    """Gradient-boosted quantile regression (p10/p50/p90) over all prediction-time features."""
    kind = "gbm"
    MAX_TRAIN = 300_000
    MAX_STOPS = 250  # most frequent stops get their own category; the rest share one

    def __init__(self, models=None, lines=None, stops=None):
        self.models, self.lines, self.stops = models or {}, lines or [], stops or []

    def _row(self, line, stop, lead_s, band, disrupted, category=None, queue_rank=None, gap_s=None,
             feed_age_s=None, weekend=None):
        nan = float("nan")
        return [
            float(lead_s), BANDS.index(band) if band in BANDS else nan, 1.0 if weekend else 0.0,
            CATS.index(category) if category in CATS else (1.0 if disrupted else 0.0),
            float(queue_rank) if queue_rank is not None else nan, float(gap_s) if gap_s is not None else nan,
            float(feed_age_s) if feed_age_s is not None else nan,
            self.lines.index(line) if line in self.lines else nan,
            self.stops.index(stop) if stop in self.stops else len(self.stops),
        ]

    @classmethod
    def fit(cls, samples: list[Sample], seed: int = 0) -> "GBMModel":
        import random

        from sklearn.ensemble import HistGradientBoostingRegressor

        if len(samples) > cls.MAX_TRAIN:
            samples = random.Random(seed).sample(samples, cls.MAX_TRAIN)
        lines = sorted({x.line_id for x in samples})
        freq: dict[str, int] = defaultdict(int)
        for x in samples:
            freq[x.stop_id] += 1
        stops = [s for s, _ in sorted(freq.items(), key=lambda kv: -kv[1])[: cls.MAX_STOPS]]
        m = cls(None, lines, stops)
        import numpy as np

        X = np.array([m._row(x.line_id, x.stop_id, x.lead_s, x.band, x.disrupted, x.category, x.queue_rank, x.gap_s,
                             x.feed_age_s, x.weekend) for x in samples], dtype=float)
        y = np.array([x.error_s for x in samples], dtype=float)
        categorical = [False, True, True, True, False, False, False, True, True]
        m.models = {}
        for name, q in (("q10", 0.1), ("q50", 0.5), ("q90", 0.9)):
            est = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=200, learning_rate=0.08,
                                                max_leaf_nodes=31, min_samples_leaf=50, l2_regularization=1.0,
                                                categorical_features=categorical, random_state=seed)
            m.models[name] = est.fit(X, y)
        return m

    def predict(self, line, stop, lead_s, band, disrupted, **ctx) -> dict:
        import numpy as np

        row = np.array([self._row(line, stop, lead_s, band, disrupted, **{k: ctx.get(k) for k in
                        ("category", "queue_rank", "gap_s", "feed_age_s", "weekend")})], dtype=float)
        q10, q50, q90 = (float(self.models[n].predict(row)[0]) for n in ("q10", "q50", "q90"))
        return {"bias_s": q50, "q10_s": min(q10, q50), "q90_s": max(q90, q50), "support": 1}

    def predict_many(self, samples: list[Sample]) -> list[dict]:
        import numpy as np

        if not samples:
            return []
        X = np.array([self._row(x.line_id, x.stop_id, x.lead_s, x.band, x.disrupted, x.category, x.queue_rank,
                                x.gap_s, x.feed_age_s, x.weekend) for x in samples], dtype=float)
        q = {n: self.models[n].predict(X) for n in ("q10", "q50", "q90")}
        return [{"bias_s": float(b), "q10_s": float(min(a, b)), "q90_s": float(max(c, b)), "support": 1}
                for a, b, c in zip(q["q10"], q["q50"], q["q90"])]

    def to_params(self) -> dict:
        import pickle

        buf = io.BytesIO()
        pickle.dump(self.models, buf)
        return {"model": self.kind, "lines": self.lines, "stops": self.stops,
                "blob": base64.b64encode(buf.getvalue()).decode()}

    @classmethod
    def from_params(cls, p: dict) -> "GBMModel":
        import pickle

        return cls(pickle.loads(base64.b64decode(p["blob"])), p.get("lines", []), p.get("stops", []))


CANDIDATES = {"provider": ProviderModel, "hier": HierModel, "hier_ctx": HierCtxModel, "gbm": GBMModel}


def from_params(params: dict):
    """Load any stored model. Old rows (before v2) have no 'model' key and are the hierarchical model."""
    kind = params.get("model", "hier")
    cls = CANDIDATES[kind]
    return cls.from_params(params) if kind != "hier" else HierModel.from_params(params)
