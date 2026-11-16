"""The trip on the lock screen (an iOS Live Activity).

The app starts the activity when a trip starts and gives the server its push token. While the trip is active the
worker sends the current arrival time and next train to it once a minute, so the lock screen stays right with the
app closed; when the trip ends, the activity is ended too.

`props` is what the activity draws (mobile/src/widgets/trip-activity.tsx; the app builds the same shape in
mobile/src/lib/activity-props.ts). Times are epoch milliseconds: the lock screen counts down by itself.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import apns
from .db import Trip

log = logging.getLogger("paxen.activity")
NAME = "PaxenTrip"  # the Live Activity's name in the app
STALE_S = 5 * 60  # the lock screen greys the times if no update arrives for this long


def _ms(iso: str | None) -> int | None:
    return int(datetime.fromisoformat(iso).timestamp() * 1000) if iso else None


def props(live: dict) -> dict:
    """What the lock screen shows, from a live_status() answer."""
    if live.get("status") != "active":
        return {"status": live.get("status") or "ended", "summary": live.get("summary") or "", "eta": None,
                "headline": "You\u2019ve arrived" if live.get("status") == "arrived" else "Trip finished",
                "next": None, "nextAt": None, "note": None}
    legs = live.get("legs") or []
    leg = legs[live.get("current_leg") or 0] if legs else {}
    line = leg.get("line_name") or "service"
    headline = {"walking": f"Walk to {leg.get('to', '')}", "waiting": f"Wait for the {line} at {leg.get('from', '')}",
                "on_board": f"On the {line} to {leg.get('to', '')}"}.get(live.get("phase"), "")
    nd = live.get("next_departure") or {}
    trains = nd.get("trains") or []
    catch = trains[nd["catch_index"]] if nd.get("catch_index") is not None and nd["catch_index"] < len(trains) else None
    nxt = f"{nd.get('line_name') or 'Next service'} from {nd.get('stop')}" if nd and live.get("phase") != "on_board" else None
    dis = live.get("disruptions") or []
    return {"status": "active", "summary": live.get("summary") or "", "eta": _ms(live.get("eta")),
            "headline": headline.strip(), "next": nxt, "nextAt": _ms(catch["at"]) if catch and nxt else None,
            "note": f"{dis[0]['line_name']}: {dis[0]['description']}" if dis else None}


def push_all(s: Session, provider, now: datetime, live_status) -> int:
    """Worker, every minute: bring each showing activity up to date, and end those whose trip is over."""
    sent = 0
    for trip in s.scalars(select(Trip).where(Trip.activity_token.is_not(None))).all():
        try:
            live = live_status(s, provider, trip, now)
            ended = live.get("status") != "active"
            res = apns.send_activity(trip.activity_token, NAME, props(live), now, end=ended, stale_s=STALE_S)
            if ended or res == "gone":
                trip.activity_token = None  # nothing more to send
            sent += res == "sent"
            s.commit()
        except Exception:
            log.exception("live activity update failed for trip %s", trip.id)
            s.rollback()
    return sent

