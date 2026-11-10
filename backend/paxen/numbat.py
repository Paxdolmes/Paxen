"""TfL NUMBAT: scheduled train frequencies and typical passenger demand, per 15 minutes (historical data).

NUMBAT is TfL's model of a typical day on the Underground, Overground, Elizabeth line, DLR and trams, calibrated
to ticketing data and counts, with abnormal days removed. For every link between two adjacent stations it gives
the *scheduled* trains per quarter hour (from TfL's working timetable) and the typical passenger load; for every
platform, the typical boarders and alighters. There are five day types: Monday, Tuesday-Thursday, Friday,
Saturday and Sunday. Paxen uses the latest edition (NUMBAT 2025, published July 2026).

What Paxen uses it for:
- **Scheduled headways.** How long you'd wait for a train when there's no live countdown (planned trips, later
  legs of a journey, feed outages), instead of one flat guess per mode (see engine.forecast_journey).
- **Context for the arrival-correction candidate `gbm_numbat`** (docs/model-evaluation.md, Amendment 2).

It describes a typical day, not what happened on any particular day: it contains no delays, and Paxen never
presents it as live.

Build the committed data file (needs TfL's open-data bucket and the Unified API to be reachable):

    python -m paxen.numbat build [--cache DIR]

Contains public sector information licensed under the Open Government Licence v2.0 (TfL open data).
Powered by TfL Open Data.
"""
from __future__ import annotations

import base64
import gzip
import json
import logging
import math
import sys
import threading
from array import array
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from .timeutil import local

log = logging.getLogger("paxen.numbat")

DATA_FILE = Path(__file__).with_name("data") / "numbat_2025.json.gz"
DAY_TYPES = ("MON", "TWT", "FRI", "SAT", "SUN")
SLOTS = 96  # quarter hours
SLOT_MIN = 15
DAY_START_MIN = 5 * 60  # a NUMBAT day runs 05:00 to 05:00 (so 01:00 Saturday is Friday night's service)
WINDOW_SLOTS = 4  # frequencies and demand are read over the hour around the time asked about

# England & Wales bank holidays, when TfL runs a Sunday-style service. (Christmas Day has no service; the planner
# knows that, and the forecast never relies on NUMBAT alone to say a train exists.)
BANK_HOLIDAYS = {
    date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6), date(2026, 5, 4), date(2026, 5, 25), date(2026, 8, 31),
    date(2026, 12, 25), date(2026, 12, 28),
    date(2027, 1, 1), date(2027, 3, 26), date(2027, 3, 29), date(2027, 5, 3), date(2027, 5, 31), date(2027, 8, 30),
    date(2027, 12, 27), date(2027, 12, 28),
}

# TfL Unified API line id -> NUMBAT line code. NUMBAT models the Hammersmith & City and Circle lines together.
LINE_KEYS = {
    "bakerloo": "BAK", "central": "CEN", "district": "DIS", "hammersmith-city": "HAM", "circle": "HAM",
    "jubilee": "JUB", "metropolitan": "MET", "northern": "NOR", "piccadilly": "PIC", "victoria": "VIC",
    "waterloo-city": "WAC", "elizabeth": "EZL", "dlr": "DLR", "liberty": "URL", "lioness": "WEL",
    "mildmay": "NLL", "suffragette": "GOB", "weaver": "WAG", "windrush": "ELL", "tram": "TRM",
}

# Platform names in TfL's feeds ("Westbound - Platform 1") -> NUMBAT direction codes, and compass bearings used
# when a line's NUMBAT directions are named differently (the Circle's inner/outer rail vs east/westbound platforms).
BOUND_DIR = {"northbound": "NB", "southbound": "SB", "eastbound": "EB", "westbound": "WB",
             "inner rail": "IR", "outer rail": "OR"}
BOUND_DEG = {"northbound": 0.0, "eastbound": 90.0, "southbound": 180.0, "westbound": 270.0}
MAX_BEARING_MISMATCH = 60.0


def service_slot(when: datetime) -> tuple[str, int]:
    """(day type, quarter-hour slot 0-95) of NUMBAT's service day that `when` falls in."""
    loc = local(when)
    minutes = loc.hour * 60 + loc.minute
    day = loc.date()
    if minutes < DAY_START_MIN:
        day -= timedelta(days=1)
        minutes += 24 * 60
    dt = "SUN" if day in BANK_HOLIDAYS else ("MON", "TWT", "TWT", "TWT", "FRI", "SAT", "SUN")[day.weekday()]
    return dt, min(SLOTS - 1, (minutes - DAY_START_MIN) // SLOT_MIN)


def _decode(s: str, typecode: str) -> array:
    a = array(typecode)
    a.frombytes(base64.b64decode(s))
    if sys.byteorder != "little":
        a.byteswap()
    return a


def _encode(values: list[int], typecode: str) -> str:
    a = array(typecode, values)
    if sys.byteorder != "little":
        a.byteswap()
    return base64.b64encode(a.tobytes()).decode()


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Compass bearing in degrees from a to b (lat, lon)."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    x = math.sin(lo2 - lo1) * math.cos(la2)
    y = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _angle(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


class Series:
    """One quantity for every day type and slot, stored compactly (480 values)."""
    __slots__ = ("values",)

    def __init__(self, values: array):
        self.values = values

    def window(self, dt: str, slot: int, width: int = WINDOW_SLOTS) -> float:
        """Sum over `width` quarter hours around `slot` (with width 4: per hour), kept inside the service day."""
        base = DAY_TYPES.index(dt) * SLOTS
        lo = max(0, min(SLOTS - width, slot - width // 2))
        return float(sum(self.values[base + lo: base + lo + width]))


class Numbat:
    def __init__(self, data: dict):
        self.meta: dict = data["meta"]
        self.line_keys: dict[str, str] = data.get("lines") or LINE_KEYS
        self.stations: dict[str, dict[str, str]] = data["stations"]  # key -> {naptan: station code}
        self.links: dict[tuple[str, str, str], tuple[str, Series, Series]] = {}
        self.adj: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.out: dict[tuple[str, str, str], list[tuple[Series, Series]]] = defaultdict(list)
        self.inn: dict[tuple[str, str, str], list[tuple[Series, Series]]] = defaultdict(list)
        self.feeds: dict[tuple[str, str, str], list[tuple[str, Series]]] = defaultdict(list)  # into b, from a
        for key, links in data["links"].items():
            for name, (d, freq, load) in links.items():
                a, b = name.split(">")
                f, l = Series(_decode(freq, "B")), Series(_decode(load, "H"))
                self.links[(key, a, b)] = (d, f, l)
                self.adj[(key, a)].append(b)
                self.out[(key, a, d)].append((f, l))
                self.inn[(key, b, d)].append((f, l))
                self.feeds[(key, b, d)].append((a, f))
        self.platforms: dict[tuple[str, str, str], tuple[Series, Series]] = {}
        for key, plats in data["platforms"].items():
            for name, (board, alight) in plats.items():
                code, d = name.split("|")
                self.platforms[(key, code, d)] = (Series(_decode(board, "H")), Series(_decode(alight, "H")))
        self.headings: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
        for key, hs in data["headings"].items():
            for name, deg in hs.items():
                code, d = name.split("|")
                self.headings[(key, code)][d] = float(deg)
        self._stop_context = lru_cache(maxsize=200_000)(self._stop_context_uncached)

    # ------------------------------------------------------------------ lookups
    def key_of(self, line_id: str | None) -> str | None:
        return self.line_keys.get(line_id or "")

    def code_of(self, key: str, stop_id: str | None) -> str | None:
        return self.stations.get(key, {}).get(stop_id or "")

    def _path(self, key: str, a: str, b: str, max_depth: int = 25) -> list[tuple[str, str]] | None:
        """Links from station a to station b along NUMBAT's network: adjacent stations, or several apart when a
        planner leg lists only the stations a fast train calls at. A train keeps its direction, so the path does
        too (no reversing at a junction onto another branch)."""
        if (key, a, b) in self.links:
            return [(a, b)]
        best: list[tuple[str, str]] | None = None
        for d in sorted({self.links[(key, a, x)][0] for x in self.adj.get((key, a), ())}):
            prev: dict[str, str] = {a: ""}
            frontier = [a]
            for _ in range(max_depth):
                nxt = []
                for node in frontier:
                    for to in self.adj.get((key, node), ()):
                        if to not in prev and self.links[(key, node, to)][0] == d:
                            prev[to] = node
                            nxt.append(to)
                if b in prev or not nxt:
                    break
                frontier = nxt
            if b in prev:
                path, cur = [], b
                while cur != a:
                    path.append((prev[cur], cur))
                    cur = prev[cur]
                if best is None or len(path) < len(best):
                    best = path[::-1]
        return best

    def leg_trains_per_hour(self, line_id: str | None, stop_ids: list[str], when: datetime) -> float | None:
        """Scheduled trains per hour that run a whole journey leg (boarding stop first): the least-served link along
        it, so a branch's own service counts, not the busier trunk. None when the leg can't be placed."""
        key = self.key_of(line_id)
        if not key or len(stop_ids) < 2:
            return None
        codes: list[str] = []
        for sid in stop_ids:
            c = self.code_of(key, sid)
            if c and (not codes or codes[-1] != c):
                codes.append(c)
        if len(codes) < 2:
            return None
        dt, slot = service_slot(when)
        tph = None
        for a, b in zip(codes, codes[1:]):
            path = self._path(key, a, b)
            if path is None:
                return None  # the stops don't follow NUMBAT's network in this order: don't guess
            for x, y in path:
                f = self.links[(key, x, y)][1].window(dt, slot)
                tph = f if tph is None else min(tph, f)
        return tph

    def headway_min(self, line_id: str | None, stop_ids: list[str], when: datetime) -> float | None:
        """Scheduled minutes between trains for a leg, or None (unknown, or no service in NUMBAT at that time;
        the journey planner then knows better than a typical-day table)."""
        tph = self.leg_trains_per_hour(line_id, stop_ids, when)
        if not tph or tph <= 0:
            return None
        return min(60.0, 60.0 / tph)

    def direction(self, key: str, code: str, bound: str | None) -> str | None:
        """NUMBAT direction at a station for a platform's bound ("westbound"), or None if it can't be told."""
        if not bound:
            return None
        dirs = self.headings.get((key, code), {})
        d = BOUND_DIR.get(bound)
        if d in dirs:
            return d
        if bound in BOUND_DEG and dirs:
            best = min(dirs, key=lambda x: _angle(dirs[x], BOUND_DEG[bound]))
            if _angle(dirs[best], BOUND_DEG[bound]) <= MAX_BEARING_MISMATCH:
                return best
        return None

    def upstream(self, line_id: str | None, stop_id: str | None, bound: str | None, when: datetime,
                 n: int = 2) -> list[str]:
        """NaPTAN ids of the n stations a train calls at before this one, in that direction (nearest first).
        At a junction the branch most trains come from is followed. Empty when the direction can't be told."""
        key = self.key_of(line_id)
        code = self.code_of(key, stop_id) if key else None
        d = self.direction(key, code, bound) if code else None
        if not d:
            return []
        dt, slot = service_slot(when)
        naptans: dict[str, list[str]] = defaultdict(list)
        for naptan, c in self.stations.get(key, {}).items():
            naptans[c].append(naptan)
        out, seen, cur = [], {code}, code
        for _ in range(n):
            feeds = [(f.window(dt, slot), a) for a, f in self.feeds.get((key, cur, d), ()) if a not in seen]
            if not feeds:
                break
            cur = max(feeds)[1]
            seen.add(cur)
            if naptans.get(cur):
                out.append(sorted(naptans[cur])[0])
        return out

    def stop_context(self, line_id: str | None, stop_id: str | None, bound: str | None,
                     when: datetime) -> dict | None:
        """Typical service and demand where a train is arriving, at the time it is due:
        sched_headway_s (scheduled seconds between trains in that direction), activity_per_train (passengers
        boarding plus alighting per train: what stretches dwell times) and load_per_train (passengers on board
        when trains arrive). Directional when the platform's bound is known, otherwise averaged over directions."""
        key = self.key_of(line_id)
        code = self.code_of(key, stop_id) if key else None
        if not code:
            return None
        dt, slot = service_slot(when)
        return self._stop_context(key, code, bound, dt, slot)

    def _stop_context_uncached(self, key: str, code: str, bound: str | None, dt: str, slot: int) -> dict | None:
        d = self.direction(key, code, bound)
        dirs = [d] if d else sorted(self.headings.get((key, code), {}))
        rows = []
        for x in dirs:
            out = sum(f.window(dt, slot) for f, _ in self.out.get((key, code, x), ()))
            inn = sum(f.window(dt, slot) for f, _ in self.inn.get((key, code, x), ()))
            tph = max(out, inn)  # trains starting or terminating here count too
            if tph <= 0:
                continue
            load = sum(l.window(dt, slot) for _, l in self.inn.get((key, code, x), ()))
            leaving = sum(l.window(dt, slot) for _, l in self.out.get((key, code, x), ()))
            plat = self.platforms.get((key, code, x))
            act = (plat[0].window(dt, slot) + plat[1].window(dt, slot)) if plat else None
            rows.append((tph, act, load / inn if inn > 0 else None, leaving / out if out > 0 else None))
        if not rows:
            return None
        tph = sum(r[0] for r in rows) / len(rows)
        acts = [r[1] / r[0] for r in rows if r[1] is not None]
        loads = [r[2] for r in rows if r[2] is not None]
        departs = [r[3] for r in rows if r[3] is not None]
        return {"sched_headway_s": round(3600.0 / tph, 1),
                "activity_per_train": round(sum(acts) / len(acts), 2) if acts else None,
                "load_per_train": round(sum(loads) / len(loads), 1) if loads else None,
                # passengers on board as trains pull out (after this stop's alighters and boarders): how full the
                # train you'd squeeze onto is. Not a model feature; train fullness uses it.
                "depart_load_per_train": round(sum(departs) / len(departs), 1) if departs else None,
                "directional": d is not None}


_lock = threading.Lock()
_loaded: dict[str, Numbat | None] = {}


def get(path: Path | None = None) -> Numbat | None:
    """The NUMBAT table (loaded once), or None when the data file is missing: callers fall back gracefully."""
    p = path or DATA_FILE
    k = str(p)
    if k in _loaded:
        return _loaded[k]
    with _lock:
        if k not in _loaded:
            try:
                with gzip.open(p, "rt", encoding="utf-8") as fh:
                    _loaded[k] = Numbat(json.load(fh))
            except FileNotFoundError:
                log.warning("NUMBAT data file not found (%s): using flat headways and no NUMBAT features", p)
                _loaded[k] = None
    return _loaded[k]


def headway_min(line_id: str | None, stop_ids: list[str], when: datetime) -> float | None:
    nb = get()
    return nb.headway_min(line_id, stop_ids, when) if nb else None


def stop_context(line_id: str | None, stop_id: str | None, bound: str | None, when: datetime) -> dict | None:
    nb = get()
    return nb.stop_context(line_id, stop_id, bound, when) if nb else None


# ====================================================================== building the data file
BUCKET = "https://s3-eu-west-1.amazonaws.com/crowding.data.tfl.gov.uk/"
OUTPUT_FILES = {dt: f"NUMBAT/NUMBAT 2025/NBT25{dt}_Outputs.xlsx" for dt in DAY_TYPES}
DEFINITIONS_FILE = "NUMBAT/NUMBAT 2024/PTSP Oasis for NUMBAT definitions.xlsx"
NUMBAT_LINES = {  # NUMBAT's line names on link sheets -> line code
    "Bakerloo": "BAK", "Central": "CEN", "District": "DIS", "H&C and Circle": "HAM", "Jubilee": "JUB",
    "Metropolitan": "MET", "Northern": "NOR", "Piccadilly": "PIC", "Victoria": "VIC", "Waterloo & City": "WAC",
    "Elizabeth Line": "EZL", "DLR": "DLR", "LO Liberty": "URL", "LO Lioness": "WEL", "LO Mildmay": "NLL",
    "LO Suffragette": "GOB", "LO Weaver": "WAG", "LO Windrush": "ELL", "London Trams": "TRM",
}
MAX_MATCH_M = 500  # a TfL stop is matched to the nearest NUMBAT station on its line within this distance
MERGE_M = 400  # a NUMBAT station no TfL stop matched is merged into a matched one this close on the same line
# Stops the automatic matching gets wrong: NUMBAT models Bank and Monument as one station, placed at Bank, which
# leaves Monument nearer to Cannon Street.
MANUAL_MATCHES = {("DIS", "940GZZLUMMT"): "BNKu", ("HAM", "940GZZLUMMT"): "BNKu"}


def _download(key: str, cache: Path) -> Path:
    import urllib.parse

    import httpx

    dest = cache / Path(key).name
    if not dest.exists():
        url = BUCKET + urllib.parse.quote(key)
        log.info("downloading %s", url)
        with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
            r.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)
    return dest


def _sheet(wb, name: str) -> tuple[list, list[list]]:
    """(header, rows) of a NUMBAT output sheet: two title rows, then the header."""
    rows = [list(r) for r in wb[name].iter_rows(values_only=True)]
    return rows[2], [r for r in rows[3:] if r and r[0] is not None]


def _qhr_columns(header: list) -> list[int]:
    import re

    cols = [i for i, c in enumerate(header) if isinstance(c, str) and re.fullmatch(r"\d{4}-\d{4}", c)]
    if len(cols) != SLOTS or header[cols[0]] != "0500-0515":
        raise ValueError(f"unexpected NUMBAT layout: {len(cols)} quarter-hour columns from {header[cols[0]]!r}")
    return cols


def _norm(name: str) -> str:
    n = name.lower()
    for a, b in ((" underground station", ""), (" rail station", ""), (" dlr station", ""), (" tram stop", ""),
                 (" station", ""), ("&", " and "), ("'", ""), ("st.", "st"), ("-", " "), (" lu", ""), (" nr", ""),
                 (" el", ""), (" dlr", ""), (" tfl", "")):
        n = n.replace(a, b)
    return " ".join(n.split())


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def _tfl_line_stops(line_id: str) -> list[dict]:
    import os

    import httpx

    params = {"app_key": os.environ["TFL_APP_KEY"]} if os.getenv("TFL_APP_KEY") else {}
    r = httpx.get(f"https://api.tfl.gov.uk/Line/{line_id}/StopPoints", params=params, timeout=60,
                  headers={"User-Agent": "paxen-commute/0.1"})
    r.raise_for_status()
    return [{"naptan": sp["naptanId"], "name": sp.get("commonName", ""), "lat": sp["lat"], "lon": sp["lon"]}
            for sp in r.json() if sp.get("naptanId") and "lat" in sp]


CENTRAL_LONDON = (51.5074, -0.1278)  # Charing Cross: "up" means towards London
NOMINAL_DEG = {"NB": 0.0, "EB": 90.0, "SB": 180.0, "WB": 270.0}


def _relabel_platforms(plats: dict, headings: dict, station_coords) -> tuple[dict, int]:
    """Give each platform record the link direction it belongs to. Returns (platforms, how many were relabelled)."""
    out: dict = {}
    relabelled = 0
    by_station: dict[tuple[str, str], list[str]] = defaultdict(list)
    for (key, code, d) in plats:
        by_station[(key, code)].append(d)
    for (key, code), pdirs in by_station.items():
        ldirs = {k.split("|")[1]: v for k, v in headings.get(key, {}).items() if k.split("|")[0] == code}
        mapping = {d: d for d in pdirs if d in ldirs}
        todo = [d for d in pdirs if d not in ldirs]
        here = station_coords(code)
        for d in todo:
            if d in NOMINAL_DEG:
                target = NOMINAL_DEG[d]
            elif d in ("UP", "DN") and here:
                target = _bearing(here, CENTRAL_LONDON) + (0 if d == "UP" else 180)
            else:
                continue
            free = [x for x in ldirs if x not in mapping.values()] or list(ldirs)
            if not free:
                continue
            best = min(free, key=lambda x: _angle(ldirs[x], target))
            if _angle(ldirs[best], target) <= 100:
                mapping[d] = best
                relabelled += 1
        for d in pdirs:
            if d not in mapping:
                continue
            nk = (key, code, mapping[d])
            rec = plats[(key, code, d)]
            if nk in out:  # two platform records for one direction: add them up
                for f in rec:
                    for dt, vals in rec[f].items():
                        out[nk][f][dt] = [x + y for x, y in zip(out[nk][f].get(dt, [0.0] * SLOTS), vals)]
            else:
                out[nk] = {f: {dt: list(v) for dt, v in by_dt.items()} for f, by_dt in rec.items()}
    return out, relabelled


def build(cache: Path, out: Path = DATA_FILE) -> dict:
    """Download NUMBAT 2025 and its definitions, map stations to TfL stop ids, write the compact data file.
    Returns a summary of how well everything matched."""
    import openpyxl

    cache.mkdir(parents=True, exist_ok=True)
    # --- definitions: station codes -> master station, primary NaPTAN, coordinates
    wb = openpyxl.load_workbook(_download(DEFINITIONS_FILE, cache), read_only=True, data_only=True)
    master = {r[0]: r[2] for r in list(wb["NLC-MNLC"].iter_rows(values_only=True))[1:] if r[0]}
    primary = {r[0]: r[3] for r in list(wb["Stn-Naptan"].iter_rows(values_only=True))[1:] if r[0] and r[3]}
    st_rows = list(wb["Stations"].iter_rows(values_only=True))
    h = st_rows[0]
    i_lat, i_lon = h.index("Latitude"), h.index("Longitude")
    coords = {r[0]: (float(r[i_lat]), float(r[i_lon])) for r in st_rows[1:]
              if r[0] and isinstance(r[i_lat], (int, float)) and isinstance(r[i_lon], (int, float))}

    # --- NUMBAT outputs, per day type
    links: dict[tuple[str, str, str, str], dict] = {}  # (key, from, to, dir) -> {"f": {dt: [96]}, "l": {...}}
    plats: dict[tuple[str, str, str], dict] = {}  # (key, code, dir) -> {"b": {dt: [96]}, "a": {...}}
    station_nlc: dict[str, int] = {}  # station code (ASC) -> NLC
    station_name: dict[str, str] = {}
    for dt, key_name in OUTPUT_FILES.items():
        wb = openpyxl.load_workbook(_download(key_name, cache), read_only=True, data_only=True)
        for sheet, field in (("Link_Frequencies", "f"), ("Link_Loads", "l")):
            header, rows = _sheet(wb, sheet)
            q = _qhr_columns(header)
            ix = {c: header.index(c) for c in ("Line", "Dir", "From NLC", "From ASC", "From Station", "To NLC",
                                              "To ASC", "To Station")}
            for r in rows:
                key = NUMBAT_LINES.get(r[ix["Line"]])
                if not key:
                    continue
                a, b = r[ix["From ASC"]], r[ix["To ASC"]]
                if a == b:
                    continue
                for code, nlc, name in ((a, r[ix["From NLC"]], r[ix["From Station"]]),
                                        (b, r[ix["To NLC"]], r[ix["To Station"]])):
                    station_nlc.setdefault(code, nlc)
                    if "(" not in name or code not in station_name:
                        station_name[code] = name
                rec = links.setdefault((key, a, b, r[ix["Dir"]]), {"f": {}, "l": {}})
                vals = [float(r[i] or 0) for i in q]
                prev = rec[field].get(dt)
                # NUMBAT models fast and slow tracks between the same two stations as separate links: add them up
                rec[field][dt] = vals if prev is None else [x + y for x, y in zip(prev, vals)]
        for sheet, field in (("Station_Boarders", "b"), ("Station_Alighters", "a")):
            header, rows = _sheet(wb, sheet)
            q = _qhr_columns(header)
            ix = {c: header.index(c) for c in ("ASC", "Line", "Dir")}
            for r in rows:
                key = r[ix["Line"]]
                if key not in NUMBAT_LINES.values():
                    continue
                rec = plats.setdefault((key, r[ix["ASC"]], r[ix["Dir"]]), {"b": {}, "a": {}})
                vals = [float(r[i] or 0) for i in q]
                prev = rec[field].get(dt)
                rec[field][dt] = vals if prev is None else [x + y for x, y in zip(prev, vals)]

    # --- match TfL stop ids to NUMBAT stations, line by line
    tfl_lines_of: dict[str, list[str]] = defaultdict(list)
    for tfl_id, key in LINE_KEYS.items():
        tfl_lines_of[key].append(tfl_id)
    stop_lists = {tfl_id: _tfl_line_stops(tfl_id) for tfl_id in LINE_KEYS}
    tfl_coords = {s["naptan"]: (s["lat"], s["lon"]) for ss in stop_lists.values() for s in ss}

    def station_coords(code: str) -> tuple[float, float] | None:
        nlc = station_nlc.get(code)
        m = master.get(nlc, nlc)
        return coords.get(m) or coords.get(nlc) or tfl_coords.get(primary.get(m) or "")

    stations: dict[str, dict[str, str]] = {}
    canon: dict[tuple[str, str], str] = {}  # (key, code) -> the code it is merged into
    report = {"far_matches": [], "merged": [], "unmatched_numbat": [], "unmatched_tfl": []}
    for key, tfl_ids in tfl_lines_of.items():
        codes = sorted({c for (k, a, b, _) in links if k == key for c in (a, b)})
        by_primary = defaultdict(list)
        for c in codes:
            nlc = station_nlc.get(c)
            p = primary.get(master.get(nlc, nlc))
            if p:
                by_primary[p].append(c)
        cmap: dict[str, str] = {}
        seen = set()
        for tfl_id in tfl_ids:
            for s in stop_lists[tfl_id]:
                if s["naptan"] in seen:
                    continue
                seen.add(s["naptan"])
                if (key, s["naptan"]) in MANUAL_MATCHES:
                    cmap[s["naptan"]] = MANUAL_MATCHES[(key, s["naptan"])]
                    continue
                here = (s["lat"], s["lon"])
                cands = [(c, _haversine_m(here, station_coords(c))) for c in codes if station_coords(c)]
                exact = by_primary.get(s["naptan"])
                if exact:
                    best = min(exact, key=lambda c: next((d for cc, d in cands if cc == c), 0.0))
                    cmap[s["naptan"]] = best
                    continue
                named = [c for c in codes if _norm(station_name.get(c, "")) == _norm(s["name"])]
                if named:
                    cmap[s["naptan"]] = named[0]
                    continue
                if not cands:
                    report["unmatched_tfl"].append((tfl_id, s["naptan"], s["name"]))
                    continue
                c, dist = min(cands, key=lambda cd: cd[1])
                if dist <= MAX_MATCH_M:
                    cmap[s["naptan"]] = c
                    if dist > 250:
                        report["far_matches"].append((tfl_id, s["name"], station_name.get(c), round(dist)))
                else:
                    report["unmatched_tfl"].append((tfl_id, s["naptan"], s["name"], station_name.get(c), round(dist)))
        stations[key] = dict(sorted(cmap.items()))
        matched = set(cmap.values())
        # A station NUMBAT splits in two (Elizabeth line Paddington: the core platforms and the main-line ones)
        # while TfL's stop data has one stop: merge the unmatched half into the matched one.
        for c in codes:
            if c in matched:
                continue
            here = station_coords(c)
            near = sorted((_haversine_m(here, station_coords(m)), m) for m in matched
                          if here and station_coords(m)) if here else []
            if near and near[0][0] <= MERGE_M:
                canon[(key, c)] = near[0][1]
                report["merged"].append((key, station_name.get(c), station_name.get(near[0][1]), round(near[0][0])))
            else:
                report["unmatched_numbat"].append((key, c, station_name.get(c)))

    def merged(series_by_key: dict, keyfn) -> dict:
        out: dict = {}
        for k, rec in series_by_key.items():
            nk = keyfn(k)
            if nk is None:
                continue
            tgt = out.setdefault(nk, {f: {} for f in rec})
            for f, by_dt in rec.items():
                for dt, vals in by_dt.items():
                    prev = tgt[f].get(dt)
                    tgt[f][dt] = list(vals) if prev is None else [x + y for x, y in zip(prev, vals)]
        return out

    def c_of(key: str, code: str) -> str:
        return canon.get((key, code), code)

    links = merged(links, lambda k: None if c_of(k[0], k[1]) == c_of(k[0], k[2])
                   else (k[0], c_of(k[0], k[1]), c_of(k[0], k[2]), k[3]))
    plats = merged(plats, lambda k: (k[0], c_of(k[0], k[1]), k[2]))
    report["stops_per_line"] = {tfl_id: sum(1 for s in stop_lists[tfl_id] if s["naptan"] in stations[LINE_KEYS[tfl_id]])
                                for tfl_id in LINE_KEYS}
    report["stops_per_line_total"] = {tfl_id: len(stop_lists[tfl_id]) for tfl_id in LINE_KEYS}

    # --- direction bearings at each station (to tell e.g. which Circle direction is "eastbound" there)
    headings: dict[str, dict[str, float]] = defaultdict(dict)
    vec: dict[tuple[str, str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    inn_vec: dict[tuple[str, str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for (key, a, b, d), rec in links.items():
        ca, cb = station_coords(a), station_coords(b)
        if not ca or not cb:
            continue
        w = sum(sum(v) for v in rec["f"].values()) or 1.0
        brg = math.radians(_bearing(ca, cb))
        for store, code in ((vec, a), (inn_vec, b)):
            store[(key, code, d)][0] += w * math.sin(brg)
            store[(key, code, d)][1] += w * math.cos(brg)
    for k in set(vec) | set(inn_vec):
        x, y = vec[k] if k in vec else inn_vec[k]  # leaving the station; at a terminus, arriving
        headings[k[0]][f"{k[1]}|{k[2]}"] = round((math.degrees(math.atan2(x, y)) + 360) % 360, 1)

    # --- platforms are sometimes labelled differently from links (Circle links run on the inner/outer rail but its
    # platforms say east/westbound; some Overground platforms say up/down): relabel them by bearing
    plats, report["platform_dirs_relabelled"] = _relabel_platforms(plats, headings, station_coords)

    # --- write
    def ints(series: dict[str, list[float]], top: int) -> list[int]:
        out = []
        for dt in DAY_TYPES:
            out += [min(top, int(round(v))) for v in series.get(dt, [0.0] * SLOTS)]
        return out

    data = {
        "meta": {
            "source": "TfL NUMBAT 2025 (typical autumn 2025 day), outputs for Mon, Tue-Thu, Fri, Sat, Sun; "
                      "station definitions from NUMBAT 2024 (PTSP Oasis); stop ids from the TfL Unified API",
            "url": BUCKET + "NUMBAT/",
            "licence": "Contains public sector information licensed under the Open Government Licence v2.0. "
                       "Powered by TfL Open Data.",
            "built": datetime.now().date().isoformat(),
            "day_types": list(DAY_TYPES), "slot_minutes": SLOT_MIN, "day_starts": "05:00",
            "units": {"freq": "trains per quarter hour", "load": "passengers per quarter hour on the link",
                      "board/alight": "passengers per quarter hour at the platform"},
        },
        "lines": LINE_KEYS,
        "stations": stations,
        "links": defaultdict(dict),
        "platforms": defaultdict(dict),
        "headings": headings,
    }
    for (key, a, b, d), rec in sorted(links.items()):
        data["links"][key][f"{a}>{b}"] = [d, _encode(ints(rec["f"], 255), "B"), _encode(ints(rec["l"], 65535), "H")]
    for (key, code, d), rec in sorted(plats.items()):
        data["platforms"][key][f"{code}|{d}"] = [_encode(ints(rec["b"], 65535), "H"),
                                                 _encode(ints(rec["a"], 65535), "H")]
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(out, "wb", mtime=0) as fh:
        fh.write(json.dumps(data, sort_keys=True, separators=(",", ":")).encode())
    summary = {"links": len(links), "platforms": len(plats),
               "stops_matched": sum(len(v) for v in stations.values()), **{k: v for k, v in report.items()},
               "bytes": out.stat().st_size}
    _loaded.pop(str(out), None)
    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its request lines include the app_key
    if len(sys.argv) >= 2 and sys.argv[1] == "build":
        cache = Path(sys.argv[sys.argv.index("--cache") + 1]) if "--cache" in sys.argv else Path(".numbat-cache")
        print(json.dumps(build(cache), indent=1, default=str))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
