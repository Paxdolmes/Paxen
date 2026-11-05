"""Candidate arrival-correction models (model v2). See docs/model-evaluation.md for how one is chosen.

Every candidate has the same interface:
    fit(samples) -> model
    predict(line, stop, lead_s, band, disrupted, **ctx) -> {"bias_s", "q10_s", "q90_s", "support"}
    to_params() / from_params(params)
where ctx may hold: category, queue_rank, gap_s, feed_age_s, weekend, bound (the platform's direction) and
polled_at (when the prediction was made). Unknown context is simply ignored.
"""
from __future__ import annotations

import base64
import io
import statistics
from collections import defaultdict
from datetime import timedelta

from .forecast import CorrectionModel, Sample, _quantile, lead_bucket

SIMPLICITY = {"provider": 0, "hier": 1, "hier_ctx": 2, "gbm": 3, "gbm_numbat": 4}
CTX_KEYS = ("category", "queue_rank", "gap_s", "feed_age_s", "weekend", "bound", "polled_at")


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
    CATEGORICAL = [False, True, True, True, False, False, False, True, True]  # one flag per feature column

    def __init__(self, models=None, lines=None, stops=None, keep=None):
        self.models, self.lines, self.stops = models or {}, lines or [], stops or []
        # Feature columns used: a column with no observed values (e.g. recorded before that signal existed)
        # can't be binned, so it's dropped at fit time and the same columns are used when predicting.
        self.keep = keep

    def _row(self, line, stop, lead_s, band, disrupted, category=None, queue_rank=None, gap_s=None,
             feed_age_s=None, weekend=None, **_):
        nan = float("nan")
        return [
            float(lead_s), BANDS.index(band) if band in BANDS else nan, 1.0 if weekend else 0.0,
            CATS.index(category) if category in CATS else (1.0 if disrupted else 0.0),
            float(queue_rank) if queue_rank is not None else nan, float(gap_s) if gap_s is not None else nan,
            float(feed_age_s) if feed_age_s is not None else nan,
            self.lines.index(line) if line in self.lines else nan,
            self.stops.index(stop) if stop in self.stops else len(self.stops),
        ]

    def _sample_row(self, x: Sample) -> list[float]:
        return self._row(x.line_id, x.stop_id, x.lead_s, x.band, x.disrupted, x.category, x.queue_rank, x.gap_s,
                         x.feed_age_s, x.weekend, bound=x.bound, polled_at=x.polled_at)

    def _ctx_row(self, line, stop, lead_s, band, disrupted, ctx: dict) -> list[float]:
        return self._row(line, stop, lead_s, band, disrupted, **{k: ctx.get(k) for k in CTX_KEYS})

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

        X = np.array([m._sample_row(x) for x in samples], dtype=float)
        y = np.array([x.error_s for x in samples], dtype=float)
        categorical = list(cls.CATEGORICAL)
        m.keep = [i for i in range(X.shape[1]) if not np.isnan(X[:, i]).all()]
        X, categorical = X[:, m.keep], [categorical[i] for i in m.keep]
        m.models = {}
        for name, q in (("q10", 0.1), ("q50", 0.5), ("q90", 0.9)):
            est = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=200, learning_rate=0.08,
                                                max_leaf_nodes=31, min_samples_leaf=50, l2_regularization=1.0,
                                                categorical_features=categorical, random_state=seed)
            m.models[name] = est.fit(X, y)
        return m

    def predict(self, line, stop, lead_s, band, disrupted, **ctx) -> dict:
        import numpy as np

        row = np.array([self._ctx_row(line, stop, lead_s, band, disrupted, ctx)], dtype=float)
        if self.keep is not None:
            row = row[:, self.keep]
        q10, q50, q90 = (float(self.models[n].predict(row)[0]) for n in ("q10", "q50", "q90"))
        return {"bias_s": q50, "q10_s": min(q10, q50), "q90_s": max(q90, q50), "support": 1}

    def predict_many(self, samples: list[Sample]) -> list[dict]:
        import numpy as np

        if not samples:
            return []
        X = np.array([self._sample_row(x) for x in samples], dtype=float)
        if self.keep is not None:
            X = X[:, self.keep]
        q = {n: self.models[n].predict(X) for n in ("q10", "q50", "q90")}
        return [{"bias_s": float(b), "q10_s": float(min(a, b)), "q90_s": float(max(c, b)), "support": 1}
                for a, b, c in zip(q["q10"], q["q50"], q["q90"])]

    def to_params(self) -> dict:
        import pickle

        buf = io.BytesIO()
        pickle.dump(self.models, buf)
        return {"model": self.kind, "lines": self.lines, "stops": self.stops, "keep": self.keep,
                "blob": base64.b64encode(buf.getvalue()).decode()}

    @classmethod
    def from_params(cls, p: dict) -> "GBMModel":
        import pickle

        return cls(pickle.loads(base64.b64decode(p["blob"])), p.get("lines", []), p.get("stops", []), p.get("keep"))


class GBMNumbatModel(GBMModel):
    """`gbm` plus typical service and demand from TfL's NUMBAT where the train is arriving (Amendment 2):
    scheduled headway, gap ahead relative to it, boarders+alighters per train, passengers on board."""
    kind = "gbm_numbat"
    CATEGORICAL = GBMModel.CATEGORICAL + [False, False, False, False]

    @staticmethod
    def _numbat(line, stop, lead_s, gap_s, bound, polled_at) -> list[float]:
        from . import numbat

        nan = float("nan")
        c = numbat.stop_context(line, stop, bound, polled_at + timedelta(seconds=float(lead_s))) if polled_at else None
        if not c:
            return [nan, nan, nan, nan]
        h = c["sched_headway_s"]
        return [h, float(gap_s) / h if gap_s is not None and h else nan,
                nan if c["activity_per_train"] is None else c["activity_per_train"],
                nan if c["load_per_train"] is None else c["load_per_train"]]

    def _sample_row(self, x: Sample) -> list[float]:
        return super()._sample_row(x) + self._numbat(x.line_id, x.stop_id, x.lead_s, x.gap_s, x.bound, x.polled_at)

    def _ctx_row(self, line, stop, lead_s, band, disrupted, ctx: dict) -> list[float]:
        return super()._ctx_row(line, stop, lead_s, band, disrupted, ctx) + self._numbat(
            line, stop, lead_s, ctx.get("gap_s"), ctx.get("bound"), ctx.get("polled_at"))


CANDIDATES = {"provider": ProviderModel, "hier": HierModel, "hier_ctx": HierCtxModel, "gbm": GBMModel,
              "gbm_numbat": GBMNumbatModel}

COVERAGE_TARGET = 0.8  # p10-p90
MIN_BUCKET_SCORES = 50


def _predict_all(model, samples: list[Sample]) -> list[dict]:
    if hasattr(model, "predict_many"):
        return model.predict_many(samples)
    return [model.predict(x.line_id, x.stop_id, x.lead_s, x.band, x.disrupted, category=x.category,
                          queue_rank=x.queue_rank, gap_s=x.gap_s, feed_age_s=x.feed_age_s, weekend=x.weekend,
                          bound=x.bound, polled_at=x.polled_at)
            for x in samples]


def conformal_quantile(scores: list[float], target: float = COVERAGE_TARGET) -> float:
    """Split-conformal quantile with the finite-sample correction: the ceil((n+1)*target)-th smallest score."""
    import math

    n = len(scores)
    k = math.ceil((n + 1) * target)
    xs = sorted(scores)
    return xs[min(k, n) - 1]


class Conformal:
    """Conformalized quantile regression (Romano et al., 2019), per lead bucket. See Amendment 1 (A1.3).

    Fit: base model on all training days but the last; conformity scores max(q10 - y, y - q90) on the last
    day; per-bucket quantile Q_b (pooled fallback for small buckets). Serve: base refitted on all training days,
    interval [q10 - Q_b, q90 + Q_b]. Point predictions are the base model's, unchanged."""

    def __init__(self, base, q: dict[str, float], kind: str):
        self.base, self.q, self.kind = base, q, kind

    @classmethod
    def fit_with(cls, base_cls, samples: list[Sample]) -> "Conformal | object":
        days = sorted({x.day for x in samples})
        if len(days) < 2:
            return base_cls.fit(samples)  # can't calibrate on a held-out day: serve the base model as-is
        proper = [x for x in samples if x.day < days[-1]]
        cal = [x for x in samples if x.day == days[-1]]
        preds = _predict_all(base_cls.fit(proper), cal)
        scores: dict[str, list[float]] = defaultdict(list)
        for x, p in zip(cal, preds):
            sc = max(p["q10_s"] - x.error_s, x.error_s - p["q90_s"])
            scores[lead_bucket(x.lead_s)].append(sc)
            scores["*"].append(sc)
        q = {b: conformal_quantile(v) for b, v in scores.items() if b == "*" or len(v) >= MIN_BUCKET_SCORES}
        return cls(base_cls.fit(samples), q, base_cls.kind)

    def _widen(self, p: dict, lead_s: float) -> dict:
        qb = self.q.get(lead_bucket(lead_s), self.q.get("*", 0.0))
        lo, hi = p["q10_s"] - qb, p["q90_s"] + qb
        if lo > hi:  # a negative Q can't invert the interval
            lo = hi = p["bias_s"]
        return {**p, "q10_s": min(lo, p["bias_s"]), "q90_s": max(hi, p["bias_s"])}

    def predict(self, line, stop, lead_s, band, disrupted, **ctx) -> dict:
        return self._widen(self.base.predict(line, stop, lead_s, band, disrupted, **ctx), lead_s)

    def predict_many(self, samples: list[Sample]) -> list[dict]:
        return [self._widen(p, x.lead_s) for x, p in zip(samples, _predict_all(self.base, samples))]

    def to_params(self) -> dict:
        return {"model": "conformal", "base": self.base.to_params(), "q": self.q, "kind": self.kind}

    @classmethod
    def from_params(cls, p: dict) -> "Conformal":
        return cls(from_params(p["base"]), p.get("q", {}), p.get("kind", "?"))


def from_params(params: dict):
    """Load any stored model. Old rows (before v2) have no 'model' key and are the hierarchical model."""
    kind = params.get("model", "hier")
    if kind == "conformal":
        return Conformal.from_params(params)
    cls = CANDIDATES[kind]
    return cls.from_params(params) if kind != "hier" else HierModel.from_params(params)
