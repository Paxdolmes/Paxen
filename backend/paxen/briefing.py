"""The daily commute briefing: one push at a time the user picks, whatever the network is doing.

    To work: 6 min slower than normal
    About 38 min today (usually 32). Take the Victoria → Central instead: 7 min quicker than your usual route.
    Leave 08:00, arrive about 08:31.

"Normal" is the user's own typical journey time (engine.personal_baseline: their recorded trips, else the usual
route's timetable). A different route is advised only when it is at least the user's "minimum gain" (5 minutes
unless they changed it) quicker than their usual route today; otherwise the advice is to stick to the usual route.
The alerts in engine.maybe_alert still go out when things change during the travel window.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Alert, Commute
from .engine import CommuteEvaluation, evaluate_commute
from .timeutil import local, minutes_of_day, naive_utc, parse_hhmm

log = logging.getLogger("paxen.briefing")

KIND = "briefing"
LATE_MIN = 20  # if the worker was busy or restarting at the set time, still send it up to this much later
SAME_MIN = 1.0  # within a minute of normal counts as normal


def _day_start(now: datetime) -> datetime:
    return naive_utc(local(now).replace(hour=0, minute=0, second=0, microsecond=0))


def is_due(s: Session, c: Commute, now: datetime) -> bool:
    """The briefing time has just passed today, it's one of the commute's days, and none was sent yet today."""
    if not c.briefing_at or c.user.monitoring_paused or local(now).weekday() not in (c.days or []):
        return False
    late = minutes_of_day(now) - parse_hhmm(c.briefing_at)
    if not 0 <= late < LATE_MIN:
        return False
    sent = s.scalar(select(Alert.id).where(Alert.commute_id == c.id, Alert.kind == KIND,
                                           Alert.created_at >= _day_start(now)).limit(1))
    return sent is None


def _mins(x: float) -> str:
    n = max(1, round(abs(x)))
    return f"{n} min"


def compose(ev: CommuteEvaluation, now: datetime) -> tuple[str, str]:
    """(push title, body)."""
    c, usual, rec = ev.commute, ev.usual, ev.recommended
    normal, delta = ev.baseline.get("p50"), ev.delta_min
    hhmm = lambda dt: local(dt).strftime("%H:%M")  # noqa: E731
    leave = "now" if ev.depart_at <= now + timedelta(minutes=1) else hhmm(ev.depart_at)

    if usual is None or not usual.feasible:
        title = f"{c.name}: your usual route isn't running"
        if rec and rec.feasible:
            body = (f"Take the {rec.journey.summary} instead: about {round(rec.p50)} min. "
                    f"Leave {leave}, arrive about {hhmm(rec.arrive_p50)}.")
        else:
            body = "No route is running normally right now. Open Paxen for the latest."
        return title, _with_disruption(body, usual)

    if delta is None:
        title = f"{c.name}: about {round(usual.p50)} min today"
    elif abs(delta) < SAME_MIN:
        title = f"{c.name}: normal today"
    elif delta > 0:
        title = f"{c.name}: {_mins(delta)} slower than normal"
    else:
        title = f"{c.name}: {_mins(delta)} quicker than normal"

    today = f"About {round(usual.p50)} min today" + (f" (usually {round(normal)})" if normal else "") + "."
    if rec is not None and rec is not usual and (ev.gain_min or 0) >= c.user.min_gain_min:
        body = (f"{today} Take the {rec.journey.summary} instead: {_mins(ev.gain_min)} quicker than your usual "
                f"route. Leave {leave}, arrive about {hhmm(rec.arrive_p50)}.")
    else:
        body = (f"{today} Stick to your usual route ({usual.journey.summary}): leave {leave}, "
                f"arrive about {hhmm(usual.arrive_p50)}.")
    return title, _with_disruption(body, usual)


def _with_disruption(body: str, usual) -> str:
    if usual and usual.disruptions:
        d = usual.disruptions[0]
        body += f" {d['line_name']}: {d['description']}."
    return body


def make(s: Session, ev: CommuteEvaluation, now: datetime) -> Alert:
    title, body = compose(ev, now)
    rec = ev.recommended
    alert = Alert(user_id=ev.commute.user_id, commute_id=ev.commute.id, kind=KIND, title=title, body=body,
                  confidence=rec.confidence if rec else "low", delta_min=ev.delta_min, gain_min=ev.gain_min,
                  recommended_signature=rec.signature if rec else None,
                  data={"commute_name": ev.commute.name, "push_title": title,
                        "recommended_summary": rec.journey.summary if rec else None,
                        "arrive_p50": rec.arrive_p50.isoformat() if rec else None})
    s.add(alert)
    s.flush()
    return alert


def send_due(s: Session, provider, now: datetime, feed_fresh: bool, deliver) -> int:
    """Worker (every minute): send each briefing that has come due. Returns how many were sent."""
    sent = 0
    for c in s.scalars(select(Commute).where(Commute.briefing_at.is_not(None))):
        try:
            if not is_due(s, c, now):
                continue
            ev = evaluate_commute(s, provider, c, now, feed_fresh=feed_fresh)
            deliver(c.user, make(s, ev, now))
            s.commit()
            sent += 1
        except Exception:
            log.exception("briefing failed for commute %s", c.id)
            s.rollback()
    return sent


def recently_briefed(s: Session, commute_id: str, now: datetime, rec_sig: str | None, delta: float | None) -> bool:
    """A briefing just said the same thing: don't follow it with an alert (engine.maybe_alert)."""
    b = s.scalars(select(Alert).where(Alert.commute_id == commute_id, Alert.kind == KIND,
                                      Alert.created_at >= naive_utc(now - timedelta(minutes=30)))
                  .order_by(Alert.created_at.desc())).first()
    return bool(b and b.recommended_signature == rec_sig and abs((b.delta_min or 0) - (delta or 0)) < 5)
