"""Conditions around a commute that don't need the recorder: planned closures, rain, air quality.

Everything is fetched on demand and cached, so the cost is a handful of requests an hour and no growth in stored
data (air quality keeps one row per day). Any source failing just hides that piece of information.
"""
from __future__ import annotations

import logging
import os
import statistics
import threading
import time
from collections import Counter
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import AirQualityDay
from .providers.base import Provider
from .redact import redact
from .timeutil import local

log = logging.getLogger("paxen.conditions")

_cache: dict[tuple, tuple[float, object]] = {}
_lock = threading.Lock()


def _cached(key: tuple, ttl: float, fetch):
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
    try:
        val = fetch()
    except Exception as e:  # a conditions source being down must never break a commute view
        log.warning("conditions source failed (%s): %s", key[0], redact(e))
        val = None
    with _lock:
        _cache[key] = (time.monotonic(), val)
    return val


def clear_cache() -> None:
    with _lock:
        _cache.clear()


# ------------------------------------------------------------------ planned closures
def upcoming_disruptions(provider: Provider, line_ids: list[str], now: datetime, days: int = 7) -> list[dict]:
    """Planned disruption starting in the next `days` days on these lines (today's live status is shown elsewhere)."""
    fetch = getattr(provider, "future_statuses", None)
    if not fetch or not line_ids:
        return []
    start = now.replace(minute=0, second=0, microsecond=0)
    rows = _cached(("closures", tuple(sorted(set(line_ids))), start.strftime("%Y%m%d%H")), 3600,
                   lambda: fetch(line_ids, start, start + timedelta(days=days))) or []
    out, seen = [], set()
    for r in rows:
        try:
            frm = datetime.fromisoformat((r.get("from") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if frm <= now + timedelta(hours=1):
            continue  # already happening: that's live status, not "coming up"
        key = (r["line_id"], r["description"], frm.date())
        if key in seen:
            continue
        seen.add(key)
        out.append({**r, "starts_local": local(frm).strftime("%a %d %b, %H:%M")})
    out.sort(key=lambda r: r["from"])
    return out[:8]


# ------------------------------------------------------------------ rain
def weather_at(lat: float, lon: float, when: datetime) -> dict | None:
    """Hourly forecast at a place and time (Open-Meteo: free, no key). None if unavailable."""
    if os.getenv("PAXEN_WEATHER", "on").lower() == "off":
        return None
    base = os.getenv("OPEN_METEO_URL", "https://api.open-meteo.com")

    def fetch():
        r = httpx.get(f"{base}/v1/forecast", timeout=8, params={
            "latitude": f"{lat:.2f}", "longitude": f"{lon:.2f}", "timezone": "Europe/London", "forecast_days": 2,
            "hourly": "precipitation_probability,precipitation,temperature_2m,weather_code"})
        r.raise_for_status()
        return r.json()

    data = _cached(("weather", round(lat, 2), round(lon, 2), local(when).strftime("%Y%m%d%H")[:-1]), 1800, fetch)
    return weather_from_forecast(data, when) if data else None


def weather_from_forecast(data: dict, when: datetime) -> dict | None:
    h = data.get("hourly") or {}
    times = h.get("time") or []
    target = local(when).strftime("%Y-%m-%dT%H:00")
    if target not in times:
        return None
    i = times.index(target)
    prob = (h.get("precipitation_probability") or [None])[i]
    mm = (h.get("precipitation") or [None])[i]
    temp = (h.get("temperature_2m") or [None])[i]
    wet = (mm or 0) >= 0.3 or (prob or 0) >= 60
    if (mm or 0) >= 2:
        summary = "Heavy rain"
    elif wet:
        summary = "Rain likely"
    elif (prob or 0) >= 30:
        summary = "Chance of rain"
    else:
        summary = "Dry"
    return {"time": target[-5:], "rain_prob": prob, "rain_mm": mm, "temp_c": temp, "wet": wet, "summary": summary}


# ------------------------------------------------------------------ air quality
def record_air_quality(s: Session, provider: Provider, now: datetime) -> dict | None:
    """Store today's London band once a day (called by the worker)."""
    fetch = getattr(provider, "air_quality", None)
    if not fetch:
        return None
    aq = fetch()
    if not aq:
        return None
    day = local(now).strftime("%Y-%m-%d")
    row = s.get(AirQualityDay, day)
    if row:
        row.band, row.level, row.summary = aq["band"], aq["level"], aq["summary"]
    else:
        s.add(AirQualityDay(day=day, band=aq["band"], level=aq["level"], summary=aq["summary"]))
    s.commit()
    return aq


def air_quality(s: Session, provider: Provider, now: datetime) -> dict | None:
    """Today's band vs the usual band over the last 30 days of recorded history."""
    fetch = getattr(provider, "air_quality", None)
    if not fetch:
        return None
    aq = _cached(("aq", local(now).strftime("%Y%m%d%H")), 3600, fetch)
    if not aq:
        return None
    since = (local(now) - timedelta(days=30)).strftime("%Y-%m-%d")
    today = local(now).strftime("%Y-%m-%d")
    hist = [r for r in s.scalars(select(AirQualityDay).where(AirQualityDay.day >= since, AirQualityDay.day < today))]
    usual = Counter(r.band for r in hist).most_common(1)[0][0] if len(hist) >= 7 else None
    levels = [r.level for r in hist if r.level is not None]
    worse = usual is not None and aq["level"] is not None and levels and aq["level"] > statistics.median(levels)
    return {**aq, "usual_band": usual, "history_days": len(hist), "worse_than_usual": bool(worse),
            "label": (f"{aq['band']} today (usually {usual})" if usual
                      else f"{aq['band']} today · learning what's usual ({len(hist)}/7 days)")}


def walking_penalty(weather: dict | None, aq: dict | None) -> tuple[float, list[str]]:
    """Extra cost per walking minute when ranking routes, and why. Rain and poor air make long walks worse."""
    k, why = 0.0, []
    if weather and weather.get("wet"):
        k += 0.6 if (weather.get("rain_mm") or 0) >= 2 else 0.4
        why.append(f"{weather['summary'].lower()} around {weather['time']}")
    if aq and (aq.get("level") or 0) >= 2:
        k += 0.3
        why.append(f"{aq['band'].lower()} air pollution")
    return k, why
