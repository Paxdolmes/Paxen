"""Success metrics from the brief §10: prediction quality, recommendation quality, notification quality, trust."""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import Alert, ModelVersion, Trip
from .engine import route_key
from .forecast import model_kind
from .recorder import feed_health
from .timeutil import naive_utc


def model_summary(s: Session, source: str = "sim") -> dict:
    mv = s.scalars(select(ModelVersion).where(ModelVersion.kind == model_kind(source))
                   .order_by(ModelVersion.id.desc())).first()
    active = s.scalars(select(ModelVersion).where(ModelVersion.kind == model_kind(source),
                                                  ModelVersion.active.is_(True)).order_by(ModelVersion.id.desc())).first()
    if not mv:
        return {"status": "no_model", "message": "Collecting data — the correction model trains once enough arrivals "
                                                 "have been observed."}
    m = (active or mv).metrics
    return {
        "status": "active" if active else "shadow",
        "version": (active or mv).id,
        "trained_at": (active or mv).created_at.isoformat() + "Z",
        "provider": m.get("provider"), "corrected": m.get("corrected"),
        "interval_coverage": m.get("interval_coverage_p10_p90"),
        "by_lead": m.get("by_lead"), "by_line": m.get("by_line"),
        "note": (active or mv).note,
    }


def personal_summary(s: Session, user_id: str, now: datetime) -> dict:
    since = naive_utc(now - timedelta(days=30))
    trips = s.scalars(select(Trip).where(Trip.user_id == user_id, Trip.duration_min.is_not(None),
                                         Trip.started_at >= since)).all()
    alerts = s.scalars(select(Alert).where(Alert.user_id == user_id, Alert.created_at >= since)).all()
    rated = [a for a in alerts if a.feedback]
    followed = [t for t in trips if t.followed_alert_id]
    saved = []
    for t in followed:
        a = next((a for a in alerts if a.id == t.followed_alert_id), None)
        if a and a.gain_min and t.forecast_p50:
            # minutes saved vs usual = forecast gain adjusted by how the chosen route actually performed
            saved.append(a.gain_min - (t.duration_min - t.forecast_p50))
    calib = [t for t in trips if t.forecast_p10 is not None and t.forecast_p90 is not None]
    inside = sum(t.forecast_p10 <= t.duration_min <= t.forecast_p90 for t in calib)
    errs = [abs(t.duration_min - t.forecast_p50) for t in trips if t.forecast_p50 is not None]
    commute_days = len({t.started_at.date() for t in trips})
    return {
        "window_days": 30,
        "trips": len(trips),
        "commute_days": commute_days,
        "alerts": len(alerts),
        "alerts_rated_useful": sum(a.feedback == "useful" for a in rated),
        "alerts_rated": len(rated),
        "alerts_followed": len(followed),
        "minutes_saved": round(sum(saved), 1) if saved else 0,
        "journey_forecast_mae_min": round(statistics.fmean(errs), 1) if errs else None,
        "interval_hit_rate": round(inside / len(calib), 2) if calib else None,
        "routes_used": len({route_key(t.signature) for t in trips if t.signature}),
    }


def insights(s: Session, user_id: str, now: datetime, source: str = "sim") -> dict:
    return {"personal": personal_summary(s, user_id, now), "model": model_summary(s, source),
            "feed": feed_health(s, now, source),
            "alerts_total": s.scalar(select(func.count(Alert.id)).where(Alert.user_id == user_id)) or 0}
