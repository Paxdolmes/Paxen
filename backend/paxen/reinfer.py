"""Rebuild inferred arrivals from stored predictions (after changing the inference rules), then retrain.

    python -m paxen.reinfer            # uses PAXEN_DATABASE_URL / DATABASE_URL and PAXEN_PROVIDER
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, func, select

from .config import settings
from .db import ModelVersion, ObservedArrival, Prediction, SessionLocal, init_db
from .forecast import train_and_maybe_promote
from .recorder import infer_arrivals
from .timeutil import aware


def reinfer(s, source: str, step_s: int = 30) -> int:
    s.execute(delete(ObservedArrival).where(ObservedArrival.source == source))
    s.commit()
    lo = s.scalar(select(func.min(Prediction.polled_at)).where(Prediction.source == source))
    hi = s.scalar(select(func.max(Prediction.polled_at)).where(Prediction.source == source))
    if not lo:
        return 0
    t, end, n = aware(lo) + timedelta(minutes=1), aware(hi) + timedelta(minutes=2), 0
    while t <= end:  # replay poll by poll, exactly as the live recorder would have
        n += infer_arrivals(s, source, t)
        s.commit()
        t += timedelta(seconds=step_s)
    return n


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    source = "tfl" if settings.provider == "tfl" else "sim"
    with SessionLocal() as s:
        n = reinfer(s, source)
        s.execute(delete(ModelVersion).where(ModelVersion.kind == "arrival_correction"))
        s.commit()
        print(f"re-inferred {n} arrivals; training:", train_and_maybe_promote(s, source))


if __name__ == "__main__":
    main()
