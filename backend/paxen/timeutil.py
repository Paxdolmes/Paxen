from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    """Treat naive datetimes (as stored by SQLite) as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def naive_utc(dt: datetime) -> datetime:
    return aware(dt).astimezone(timezone.utc).replace(tzinfo=None)


def local(dt: datetime) -> datetime:
    return aware(dt).astimezone(LONDON)


def parse_hhmm(s: str) -> int:
    """'08:15' -> minutes after midnight."""
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def minutes_of_day(dt: datetime) -> int:
    d = local(dt)
    return d.hour * 60 + d.minute


def in_window(minute: int, start: int, end: int) -> bool:
    """Window may wrap midnight (e.g. quiet hours 22:00-06:30)."""
    if start <= end:
        return start <= minute <= end
    return minute >= start or minute <= end


def hour_band(dt: datetime) -> str:
    h = local(dt).hour
    if local(dt).weekday() >= 5:
        return "weekend"
    if 7 <= h < 10:
        return "am_peak"
    if 16 <= h < 19:
        return "pm_peak"
    if 10 <= h < 16:
        return "interpeak"
    return "off_peak"
