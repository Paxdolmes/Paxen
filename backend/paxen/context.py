"""Recording the live context around journeys, so future models can learn from it.

Paxen only builds signals into its models when it can also get them live. This module records the live sources
that could matter but weren't being kept:

    line status history     every status change, kept permanently (one row per change, not per poll). The
                            30-second snapshots are pruned after 60 days; this is what rebuilds the
                            disruption-duration and risk models from Paxen's own data, Overground and
                            Elizabeth line included.
    weather                 hourly London weather (Open-Meteo). TfL's history shows new disruptions start
                            1.7x as often at 30C+, 1.4x below freezing, 1.2x in 60-80 km/h gusts
                            (docs/historical-data.md).
    station disruptions     closures, stations trains skip, exits shut (TfL /StopPoint/.../Disruption)
    lift outages            for step-free journeys (TfL /Disruptions/Lifts/v2)
    planned works           the week ahead, once a day: how planned closures compare with what happens
    station crowding        TfL's live busyness for every Tube station, every 15 minutes
    road disruptions        raw, to the archive (bus delays), when an archive is configured

Events (statuses, disruptions, lifts, planned works) are stored as runs: first seen, last seen.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import ContextEvent, StationCrowding, WeatherHour
from .timeutil import LONDON, aware, naive_utc

log = logging.getLogger("paxen.context")

CENTRAL_LONDON = (51.5074, -0.1278)
WEATHER_VARS = "temperature_2m,precipitation,snowfall,wind_gusts_10m,relative_humidity_2m,weather_code"
CROWDING_EVERY = timedelta(minutes=15)
PLANNED_EVERY = timedelta(hours=24)
ROADS_EVERY = timedelta(minutes=15)


def _key(*parts) -> str:
    raw = "|".join("" if p is None else str(p) for p in parts)
    return raw if len(raw) <= 200 else raw[:150] + "#" + hashlib.sha1(raw.encode()).hexdigest()[:16]


def touch(s: Session, kind: str, key: str, now: datetime, gap: timedelta, **fields) -> ContextEvent:
    """Extend the open run of this event if it was seen within `gap`, else start a new run."""
    t = naive_utc(now)
    ev = s.scalars(select(ContextEvent).where(ContextEvent.kind == kind, ContextEvent.key == key,
                                              ContextEvent.last_seen >= t - gap)
                   .order_by(ContextEvent.last_seen.desc())).first()
    if ev:
        ev.last_seen = t
        return ev
    ev = ContextEvent(kind=kind, key=key, first_seen=t, last_seen=t, **fields)
    s.add(ev)
    return ev


# ------------------------------------------------------------------ line status (called by the recorder)
def record_status_changes(s: Session, statuses, now: datetime, poll_s: int = 30) -> None:
    """One run per line per distinct status: a run ends as soon as the line shows anything else. Good service is
    recorded too, so gaps in recording show up."""
    t, gap = naive_utc(now), timedelta(seconds=max(120, 4 * poll_s))
    for st in statuses:
        key = _key(st.line_id, st.category, st.description, st.reason)
        latest = s.scalars(select(ContextEvent).where(ContextEvent.kind == "line_status",
                                                      ContextEvent.line_id == st.line_id)
                           .order_by(ContextEvent.last_seen.desc())).first()
        if latest and latest.key == key and latest.last_seen >= t - gap:
            latest.last_seen = t
            continue
        s.add(ContextEvent(kind="line_status", key=key, first_seen=t, last_seen=t, line_id=st.line_id,
                           category=st.category, summary=(st.reason or st.description or "")[:500],
                           data={"description": st.description, "mode": st.mode, "severity": st.severity_code,
                                 "stops": sorted({x for sec in st.sections for x in sec.stops})}))
        s.flush()


# ------------------------------------------------------------------ weather
def record_weather(s: Session, now: datetime) -> int:
    if os.getenv("PAXEN_WEATHER", "on").lower() == "off":
        return 0
    base = os.getenv("OPEN_METEO_URL", "https://api.open-meteo.com")
    r = httpx.get(f"{base}/v1/forecast", timeout=15, params={
        "latitude": CENTRAL_LONDON[0], "longitude": CENTRAL_LONDON[1], "timezone": "Europe/London",
        "past_days": 1, "forecast_days": 1, "hourly": WEATHER_VARS})
    r.raise_for_status()
    return store_weather(s, r.json(), now)


def store_weather(s: Session, data: dict, now: datetime) -> int:
    """Keep hours up to now (past hours are refined by later runs, so they're overwritten)."""
    h = data.get("hourly") or {}
    n = 0
    for i, t in enumerate(h.get("time") or []):
        hour = datetime.fromisoformat(t).replace(tzinfo=LONDON)
        if hour > aware(now):
            break
        key = hour.strftime("%Y-%m-%dT%H")
        row = s.get(WeatherHour, key) or WeatherHour(hour=key)
        val = lambda name: (h.get(name) or [None] * (i + 1))[i]  # noqa: E731
        row.temp_c, row.precip_mm, row.snow_cm = val("temperature_2m"), val("precipitation"), val("snowfall")
        row.gust_kmh, row.humidity, row.weather_code = val("wind_gusts_10m"), val("relative_humidity_2m"), val("weather_code")
        row.recorded_at = naive_utc(now)
        s.merge(row)
        n += 1
    return n


# ------------------------------------------------------------------ TfL context
def _get(provider, path: str, **params):
    data, *_ = provider._get(path, params)
    return data


def record_station_disruptions(s: Session, provider, now: datetime, gap: timedelta) -> int:
    data = _get(provider, "/StopPoint/Mode/tube,overground,elizabeth-line,dlr,tram/Disruption",
                includeRouteBlockedStops="true")
    for d in data or []:
        stop = d.get("atcoCode") or d.get("stationAtcoCode") or d.get("naptanId")
        touch(s, "station_disruption", _key(stop, d.get("type"), d.get("description")), now, gap, stop_id=stop,
              category=(d.get("type") or "")[:40], summary=(d.get("description") or "")[:500],
              data={k: d.get(k) for k in ("commonName", "appearance", "fromDate", "toDate", "mode")})
    return len(data or [])


def record_lifts(s: Session, provider, now: datetime, gap: timedelta) -> int:
    data = _get(provider, "/Disruptions/Lifts/v2/")
    for d in data if isinstance(data, list) else []:
        stop = d.get("stationUniqueId") or d.get("icsCode")
        touch(s, "lift_outage", _key(stop, d.get("disruptedLiftUniqueIds") or d.get("message")), now, gap,
              stop_id=stop, category="lift", summary=(d.get("message") or "")[:500], data=d)
    return len(data) if isinstance(data, list) else 0


def record_planned(s: Session, provider, now: datetime) -> int:
    from .numbat import LINE_KEYS
    from .providers.tfl import parse_future_statuses

    f = "%Y-%m-%dT%H:%M:%S"
    start, end = now.astimezone(LONDON), now.astimezone(LONDON) + timedelta(days=7)
    lines = ",".join(sorted(k for k in LINE_KEYS if k != "tram"))  # date ranges need named lines, not a mode
    data = _get(provider, f"/Line/{lines}/Status/{start.strftime(f)}/to/{end.strftime(f)}", detail="true")
    items = parse_future_statuses(data)
    for it in items:
        touch(s, "planned_works", _key(it["line_id"], it["category"], it["from"], it["to"], it["reason"]), now,
              PLANNED_EVERY * 2, line_id=it["line_id"], category=it["category"],
              summary=(it["reason"] or it["description"] or "")[:500], data={"from": it["from"], "to": it["to"]})
    return len(items)


def tube_stations() -> list[str]:
    from . import numbat

    nb = numbat.get()
    if not nb:
        return []
    return sorted({sid for key, m in nb.stations.items() for sid in m if sid.startswith("940GZZLU")})


def record_crowding(s: Session, provider, now: datetime) -> int:
    stops = tube_stations()

    def one(stop):
        try:
            return stop, _get(provider, f"/crowding/{stop}/Live")
        except Exception:
            return stop, None

    n = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for stop, d in pool.map(one, stops):
            if d and d.get("dataAvailable"):
                s.add(StationCrowding(polled_at=naive_utc(now), stop_id=stop,
                                      pct_of_baseline=float(d.get("percentageOfBaseline") or 0)))
                n += 1
    return n


def archive_roads(provider, now: datetime) -> str | None:
    from .archive import archive_raw, get_archive

    if get_archive() is None:
        return None
    _, raw, *_ = provider._get("/Road/all/Disruption", {})
    return archive_raw(provider.name, "road_disruptions", now, raw)


# ------------------------------------------------------------------ the worker loop
_last: dict[str, datetime] = {}


def _due(name: str, now: datetime, every: timedelta) -> bool:
    if name in _last and now - _last[name] < every:
        return False
    _last[name] = now
    return True


def record_context(s: Session, provider, now: datetime, interval_s: int = 300) -> dict:
    """One context cycle. Each source is independent: one failing never stops the others."""
    out: dict = {}
    gap = timedelta(seconds=interval_s * 3)
    jobs = [("weather", timedelta(minutes=55), lambda: record_weather(s, now)),
            ("station_disruptions", timedelta(0), lambda: record_station_disruptions(s, provider, now, gap)),
            ("lifts", timedelta(0), lambda: record_lifts(s, provider, now, gap)),
            ("planned_works", PLANNED_EVERY, lambda: record_planned(s, provider, now)),
            ("crowding", CROWDING_EVERY, lambda: record_crowding(s, provider, now)),
            ("roads", ROADS_EVERY, lambda: archive_roads(provider, now))]
    for name, every, job in jobs:
        if every and not _due(name, now, every):
            continue
        try:
            out[name] = job()
            s.commit()
        except Exception as e:
            s.rollback()
            out[name] = f"failed: {type(e).__name__}"
            log.warning("context %s failed: %s", name, e)
    return out


def summary(s: Session) -> dict:
    from sqlalchemy import func

    return {"events": dict(s.execute(select(ContextEvent.kind, func.count()).group_by(ContextEvent.kind)).all()),
            "weather_hours": s.scalar(select(func.count()).select_from(WeatherHour)),
            "crowding_rows": s.scalar(select(func.count()).select_from(StationCrowding))}


if __name__ == "__main__":
    from .db import SessionLocal, init_db

    init_db()
    with SessionLocal() as s:
        print(json.dumps(summary(s), indent=1))
