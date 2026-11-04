"""Address search for onboarding: postcodes via postcodes.io, street addresses via OpenStreetMap Nominatim.

Both are free and keyless. Nominatim's usage policy asks for an identifying User-Agent, at most one request per
second and no bulk use; Paxen only geocodes when a person searches, caches results and throttles itself.
Configure with PAXEN_GEOCODER=off (disable), POSTCODES_URL, NOMINATIM_URL, PAXEN_GEOCODER_UA.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from functools import lru_cache

import httpx

from .domain import PlaceResult

log = logging.getLogger("paxen.geocode")

FULL_POSTCODE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.I)
PARTIAL_POSTCODE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?(\s*\d[A-Z]?)?$", re.I)
# Greater London and a margin, so "High Street" finds London ones first.
LONDON_VIEWBOX = "-0.60,51.75,0.40,51.25"

_nominatim_lock = threading.Lock()
_last_nominatim = 0.0


def _client() -> httpx.Client:
    ua = os.getenv("PAXEN_GEOCODER_UA", "paxen-commute/0.1 (commute planner; low volume)")
    return httpx.Client(timeout=10, headers={"User-Agent": ua, "Accept-Language": "en-GB"})


def _postcode_result(r: dict) -> PlaceResult:
    area = ", ".join(x for x in (r.get("admin_ward"), r.get("admin_district")) if x)
    return PlaceResult(r["postcode"], float(r["latitude"]), float(r["longitude"]), "address", detail=area or None)


def search_postcodes(q: str, client: httpx.Client) -> list[PlaceResult]:
    base = os.getenv("POSTCODES_URL", "https://api.postcodes.io")
    if FULL_POSTCODE.match(q):
        r = client.get(f"{base}/postcodes/{q.replace(' ', '')}")
        if r.status_code == 404:
            return []
        r.raise_for_status()
        res = r.json().get("result")
        return [_postcode_result(res)] if res and res.get("latitude") is not None else []
    r = client.get(f"{base}/postcodes", params={"q": q, "limit": 8})
    r.raise_for_status()
    return [_postcode_result(x) for x in (r.json().get("result") or []) if x.get("latitude") is not None]


def _short_address(a: dict, display: str) -> tuple[str, str | None]:
    addr = a.get("address") or {}
    street = " ".join(x for x in (addr.get("house_number"), addr.get("road")) if x)
    name = a.get("name") or ""
    title = street or name or display.split(",")[0]
    if name and street and name not in street:
        title = f"{name}, {street}"
    detail = ", ".join(x for x in (addr.get("suburb") or addr.get("city_district") or addr.get("neighbourhood"),
                                   addr.get("postcode")) if x)
    return title, detail or None


def search_addresses(q: str, client: httpx.Client) -> list[PlaceResult]:
    global _last_nominatim
    base = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org")
    with _nominatim_lock:  # Nominatim policy: max 1 request/second
        wait = 1.0 - (time.monotonic() - _last_nominatim)
        if wait > 0:
            time.sleep(wait)
        r = client.get(f"{base}/search", params={
            "q": q, "format": "jsonv2", "addressdetails": 1, "limit": 6, "countrycodes": "gb",
            "viewbox": LONDON_VIEWBOX, "bounded": 1,
        })
        _last_nominatim = time.monotonic()
    r.raise_for_status()
    out = []
    for a in r.json():
        title, detail = _short_address(a, a.get("display_name", ""))
        out.append(PlaceResult(title, float(a["lat"]), float(a["lon"]), "address", detail=detail))
    return out


@lru_cache(maxsize=512)
def geocode(query: str) -> tuple[PlaceResult, ...]:
    """Addresses and postcodes for a free-text query (cached). Failures return nothing rather than erroring."""
    q = " ".join(query.split())
    if os.getenv("PAXEN_GEOCODER", "auto").lower() == "off" or len(q) < 3:
        return ()
    try:
        with _client() as client:
            if PARTIAL_POSTCODE.match(q):
                return tuple(search_postcodes(q, client))
            return tuple(search_addresses(q, client))
    except Exception as e:
        log.warning("geocoding failed for %r: %s", q, e)
        return ()
