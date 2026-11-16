"""Run a fitted gradient-boosted model without scikit-learn.

The training process (a child of the worker) fits scikit-learn's HistGradientBoostingRegressor. The API and the
worker only ever need to *use* the result, a few hundred small decision trees, and importing scikit-learn for that
costs each of them about 95 MB of memory and several seconds on first use. So a fitted model is exported once
(`pack`) to plain lists, stored as compressed JSON, and evaluated here in pure Python (`predict`), which gives
the same numbers as scikit-learn's own `predict` (tests compare them row by row) and is quicker for the single rows
a request needs.

Stored this way a model also survives library upgrades, and nothing is unpickled from the database.
"""
from __future__ import annotations

import base64
import json
import zlib

FORMAT = "trees-v1"


def _bits(words) -> int:
    """scikit-learn keeps a set of category values as 8 unsigned 32-bit words; as one integer, bit c = value c."""
    return sum(int(w) << (32 * i) for i, w in enumerate(words))


def pack(est) -> dict:
    """Export a fitted HistGradientBoostingRegressor (called where scikit-learn is already loaded)."""
    import numpy as np

    # With categorical features scikit-learn first rearranges each row: the categorical columns come first, each
    # value replaced by its position among the (sorted) values seen in training, then the numerical columns.
    pre = est._preprocessor
    if pre is None:
        cat_cols, num_cols, categories = [], list(range(est.n_features_in_)), []
    else:
        masks = {name: np.flatnonzero(np.asarray(cols, dtype=bool)) for name, _, cols in pre.transformers_
                 if name in ("encoder", "numerical")}
        cat_cols, num_cols = [int(c) for c in masks["encoder"]], [int(c) for c in masks["numerical"]]
        categories = [[float(v) for v in cats] for cats in pre.named_transformers_["encoder"].categories_]
    known, f_idx_map = est._bin_mapper.make_known_categories_bitsets()
    known_by_feature = {f: _bits(known[int(f_idx_map[f])]) for f in range(len(cat_cols))}
    trees = []
    for stage in est._predictors:
        for pred in stage:
            n = pred.nodes
            leaf = n["is_leaf"].astype(bool)
            trees.append({
                "f": [-1 if lf else int(x) for lf, x in zip(leaf, n["feature_idx"])],
                "t": [float(x) for x in n["num_threshold"]],
                "l": [int(x) for x in n["left"]],
                "r": [int(x) for x in n["right"]],
                "v": [float(x) for x in n["value"]],
                "m": [int(x) for x in n["missing_go_to_left"]],
                "c": [int(b) if cat and not lf else -1 for cat, lf, b in zip(n["is_categorical"], leaf, n["bitset_idx"])],
                "cats": [str(_bits(row)) for row in pred.raw_left_cat_bitsets],  # as text: JSON has no big integers
            })
    base = est._baseline_prediction
    return {"format": FORMAT, "base": float(np.ravel(base)[0]), "cat_cols": cat_cols, "num_cols": num_cols,
            "categories": categories, "known": {str(f): str(b) for f, b in known_by_feature.items()}, "trees": trees}


def dumps(packed: dict) -> str:
    return base64.b64encode(zlib.compress(json.dumps(packed, separators=(",", ":")).encode(), 9)).decode()


class Trees:
    """A packed model, ready to evaluate."""

    __slots__ = ("base", "known", "trees", "cat_cols", "num_cols", "codes")

    def __init__(self, packed: dict):
        if packed.get("format") != FORMAT:
            raise ValueError(f"unknown tree format {packed.get('format')!r}")
        self.base = packed["base"]
        self.cat_cols, self.num_cols = packed["cat_cols"], packed["num_cols"]
        self.codes = [{v: float(i) for i, v in enumerate(cats)} for cats in packed["categories"]]
        self.known = {int(f): int(b) for f, b in packed["known"].items()}
        self.trees = [(t["f"], t["t"], t["l"], t["r"], t["v"], t["m"], t["c"], [int(b) for b in t["cats"]])
                      for t in packed["trees"]]

    @classmethod
    def loads(cls, blob: str) -> "Trees":
        return cls(json.loads(zlib.decompress(base64.b64decode(blob))))

    def predict(self, row: list[float]) -> float:
        """One row of features in the order the model was fitted with (NaN = missing). Same rules as scikit-learn:
        a missing value, or a category the model never saw, follows the node's missing-value branch."""
        nan = float("nan")
        x_row = [codes.get(row[c], nan) for c, codes in zip(self.cat_cols, self.codes)] + [row[c] for c in self.num_cols]
        total = self.base
        known = self.known
        for f, t, left, right, v, m, c, cats in self.trees:
            i = 0
            while f[i] >= 0:
                x = x_row[f[i]]
                if x != x:  # NaN
                    i = left[i] if m[i] else right[i]
                elif c[i] >= 0:
                    xi = int(x)
                    if (cats[c[i]] >> xi) & 1:
                        i = left[i]
                    elif (known.get(f[i], 0) >> xi) & 1:
                        i = right[i]
                    else:
                        i = left[i] if m[i] else right[i]
                else:
                    i = left[i] if x <= t[i] else right[i]
            total += v[i]
        return total
