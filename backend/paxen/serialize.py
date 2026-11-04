from __future__ import annotations

from datetime import timedelta

from .db import Alert, Commute, Place, Trip, User
from .engine import CommuteEvaluation, JourneyForecast, is_active_window, route_key
from .timeutil import aware


def iso(dt):
    return aware(dt).isoformat() if dt else None


def place(p: Place) -> dict:
    return {"id": p.id, "label": p.label, "name": p.name, "lat": p.lat, "lon": p.lon, "source": p.source,
            "confirmed": p.confirmed, "stops": p.preferred_stops or []}


def commute(c: Commute) -> dict:
    return {"id": c.id, "name": c.name, "origin": place(c.origin), "dest": place(c.dest), "days": c.days,
            "window_start": c.window_start, "window_end": c.window_end, "preference": c.preference,
            "alerts_enabled": c.alerts_enabled, "usual_summary": c.usual_summary,
            "usual_signature": c.usual_signature}


def user(u: User) -> dict:
    return {"id": u.id, "name": u.name, "quiet_start": u.quiet_start, "quiet_end": u.quiet_end,
            "monitoring_paused": u.monitoring_paused, "alert_threshold_min": u.alert_threshold_min,
            "min_gain_min": u.min_gain_min, "push_enabled": bool(u.push_token)}


def option(f: JourneyForecast, ev: CommuteEvaluation) -> dict:
    j = f.journey
    at = lambda m: iso(f.depart_at + timedelta(minutes=m))  # noqa: E731
    is_usual = ev.usual is f
    return {
        "id": f.signature,
        "summary": j.summary,
        "is_usual": is_usual,
        "is_recommended": ev.recommended is f,
        "feasible": f.feasible,
        "depart_at": iso(f.depart_at),
        "arrive_at": at(f.p50),
        "arrive_range": [at(f.p10), at(f.p90)],
        "duration": {"p10": f.p10, "p50": f.p50, "p90": f.p90},
        "nominal_min": j.duration_min,
        "vs_usual_min": round(f.p50 - ev.usual.p50, 1) if ev.usual and ev.usual.feasible and not is_usual else None,
        "walking_min": j.walking_min,
        "changes": j.changes,
        "confidence": f.confidence,
        "on_time_chance": f.on_time_chance,
        "reliability": f.reliability,
        "crowding": f.crowding,
        "disruptions": f.disruptions,
        "live_data": f.live_data,
        "legs": [{
            "mode": l.mode, "line_id": l.line_id, "line_name": l.line_name,
            "from": ev.commute.origin.name if l.from_name == "Start" else l.from_name,
            "to": ev.commute.dest.name if l.to_name == "Destination" else l.to_name,
            "direction": l.direction, "wait_min": l.wait_min, "ride_min": l.ride_min, "live": l.live,
            "status": l.category, "next_departures_min": l.next_departures_min,
        } for l in f.legs],
    }


def evaluation(ev: CommuteEvaluation, now, max_options: int | None = None) -> dict:
    opts = ev.options if max_options is None else ev.options[:max_options]
    if ev.usual and ev.usual not in opts:
        opts = opts + [ev.usual]
    return {
        "commute": commute(ev.commute),
        "active": is_active_window(ev.commute, now),
        "depart_at": iso(ev.depart_at),
        "status": ev.status,
        "headline": ev.headline,
        "detail": ev.detail,
        "delta_min": ev.delta_min,
        "gain_min": ev.gain_min,
        "preference": ev.preference,
        "chosen_stops_honoured": ev.chosen_stops_honoured,
        "baseline": ev.baseline,
        "usual": option(ev.usual, ev) if ev.usual else None,
        "recommended": option(ev.recommended, ev) if ev.recommended else None,
        "options": [option(f, ev) for f in opts],
    }


def alert(a: Alert) -> dict:
    return {"id": a.id, "commute_id": a.commute_id, "created_at": iso(a.created_at), "kind": a.kind,
            "title": a.title, "body": a.body, "confidence": a.confidence, "delta_min": a.delta_min,
            "gain_min": a.gain_min, "recommended_summary": (a.data or {}).get("recommended_summary"),
            "recommended_signature": a.recommended_signature, "read": a.read, "feedback": a.feedback,
            "delivered": a.delivered}


def trip(t: Trip) -> dict:
    return {"id": t.id, "commute_id": t.commute_id, "summary": t.summary, "signature": t.signature,
            "route_key": route_key(t.signature), "started_at": iso(t.started_at), "arrived_at": iso(t.arrived_at),
            "duration_min": t.duration_min, "forecast": {"p10": t.forecast_p10, "p50": t.forecast_p50,
                                                         "p90": t.forecast_p90},
            "followed_alert_id": t.followed_alert_id, "source": t.source}
