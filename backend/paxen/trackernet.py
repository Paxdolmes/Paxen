"""Measured Tube arrivals from TfL Trackernet (train positions from the signalling system).

The countdown feeds only *predict* arrivals; Paxen previously inferred the actual arrival from how a countdown
behaved, which breaks at termini, on flickering boards and when train ids are reused. Trackernet reports where
each train physically is ("At Platform", "Between X and Y") and when that last changed, so the first time a train
is "At Platform" at a station gives its arrival time to the second.

Trackernet set numbers are the same vehicle ids the Unified API uses for Tube trains, so these measured arrivals
pair directly with recorded predictions. Requires the TrackernetFeedPublic subscription key (TFL_TRACKERNET_KEY).
"""
from __future__ import annotations

import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from .redact import check

from .timeutil import LONDON

log = logging.getLogger("paxen.trackernet")

# Trackernet line codes -> Unified API line ids (H carries both Hammersmith & City and Circle trains).
LINE_CODES: dict[str, list[str]] = {
    "B": ["bakerloo"], "C": ["central"], "D": ["district"], "H": ["hammersmith-city", "circle"], "J": ["jubilee"],
    "M": ["metropolitan"], "N": ["northern"], "P": ["piccadilly"], "V": ["victoria"], "W": ["waterloo-city"],
}
# Names Trackernet spells differently from TfL's stop data.
ALIASES = {"paddington circle": "940GZZLUPAH", "heathrow terminals 123": "940GZZLUHRC"}
BOUNDS = ("northbound", "southbound", "eastbound", "westbound", "inner rail", "outer rail")


def norm_name(n: str) -> str:
    n = n.lower().strip().rstrip(".")
    n = re.sub(r"\(.*?\)", "", n)
    for a, b in ((" underground station", ""), (" station", ""), ("&", " and "), ("'", ""), ("st.", "st"), ("-", " ")):
        n = n.replace(a, b)
    return " ".join(n.split())


def bound_of(platform: str | None) -> str | None:
    """'Southbound - Platform 1' -> 'southbound'. Platform direction is the robust way to tell trips apart."""
    p = (platform or "").lower()
    return next((b for b in BOUNDS if b in p), None)


@dataclass
class TrainAtPlatform:
    line_code: str
    station_code: str
    station_name: str
    platform: str
    set_no: str
    destination: str
    seen_since: datetime  # when the train's location last changed (= arrival at this platform), UTC


def _parse_dt(hhmmss: str, poll_local: datetime) -> datetime | None:
    try:
        h, m, s = (int(x) for x in hhmmss.split(":"))
    except (ValueError, AttributeError):
        return None
    t = poll_local.replace(hour=h, minute=m, second=s, microsecond=0)
    if t > poll_local + timedelta(hours=1):  # DT just before midnight, polled just after
        t -= timedelta(days=1)
    return t


def parse_summary(xml_bytes: bytes, line_code: str) -> tuple[datetime | None, list[TrainAtPlatform]]:
    """Trains currently at a platform, from a PredictionSummary/{line} response."""
    root = ET.fromstring(xml_bytes)
    ts = root.find("Time")
    poll_local = None
    if ts is not None and ts.get("TimeStamp"):
        poll_local = datetime.strptime(ts.get("TimeStamp"), "%Y/%m/%d %H:%M:%S").replace(tzinfo=LONDON)
    out = []
    for s in root.findall("S"):
        for p in s.findall("P"):
            for t in p.findall("T"):
                if (t.get("L") or "").strip().lower() != "at platform" or not t.get("S") or not poll_local:
                    continue
                since = _parse_dt(t.get("DT", ""), poll_local)
                if since is None:
                    continue
                out.append(TrainAtPlatform(line_code, s.get("Code", ""), s.get("N", ""), p.get("N", ""), t.get("S"),
                                           (t.get("DE") or "").strip(), since.astimezone(timezone.utc)))
    return (poll_local.astimezone(timezone.utc) if poll_local else None), out


class Trackernet:
    def __init__(self, key: str, base_url: str = "https://api.tfl.gov.uk", app_key: str | None = None):
        self.key, self.base, self.app_key = key, base_url.rstrip("/"), app_key
        self.client = httpx.Client(timeout=20, headers={"User-Agent": "paxen-commute/0.1"})
        self._stations: dict[str, dict[str, str]] = {}  # line code -> trackernet station code -> naptan
        self._stations_at = 0.0

    def summary(self, line_code: str) -> tuple[datetime | None, list[TrainAtPlatform], bytes]:
        r = self.client.get(f"{self.base}/trackernet/PredictionSummary/{line_code}", params={"app_key": self.key})
        check(r, f"Trackernet {line_code}")
        ts, trains = parse_summary(r.content, line_code)
        return ts, trains, r.content

    def station_map(self, line_code: str, names: dict[str, str]) -> dict[str, str]:
        """Trackernet station code -> NaPTAN id, matched by name against TfL's stop list (refreshed daily)."""
        if time.monotonic() - self._stations_at > 86400:
            self._stations, self._stations_at = {}, time.monotonic()
        if line_code not in self._stations:
            by_name: dict[str, str] = {}
            for lid in LINE_CODES[line_code]:
                params = {"app_key": self.app_key} if self.app_key else {}
                r = self.client.get(f"{self.base}/Line/{lid}/StopPoints", params=params)
                check(r, f"TfL /Line/{lid}/StopPoints")
                for sp in r.json():
                    nid = sp.get("naptanId") or sp.get("stationNaptan")
                    if nid:
                        by_name.setdefault(norm_name(sp.get("commonName", "")), nid)
            self._stations[line_code] = {"__by_name__": by_name}  # type: ignore[assignment]
        m = self._stations[line_code]
        by_name = m["__by_name__"]  # type: ignore[index]
        for code, name in names.items():
            if code not in m:
                n = norm_name(name)
                m[code] = ALIASES.get(n) or by_name.get(n)  # type: ignore[assignment]
        return {c: v for c, v in m.items() if c != "__by_name__" and v}  # type: ignore[misc]


def from_env() -> Trackernet | None:
    key = os.getenv("TFL_TRACKERNET_KEY")
    if not key or os.getenv("PAXEN_TRACKERNET", "on").lower() == "off":
        return None
    return Trackernet(key, os.getenv("TFL_BASE_URL", "https://api.tfl.gov.uk"), os.getenv("TFL_APP_KEY"))
