"""Provider-neutral transport model. Every feed is mapped into these types."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Severity categories, normalised from provider codes.
GOOD, MINOR, SEVERE, PART_SUSPENDED, SUSPENDED = "good", "minor", "severe", "part_suspended", "suspended"
SEVERITY_ORDER = {GOOD: 0, MINOR: 1, SEVERE: 2, PART_SUSPENDED: 3, SUSPENDED: 4}

DEFAULT_HEADWAY_MIN = {"tube": 4.0, "elizabeth-line": 5.0, "overground": 8.0, "national-rail": 10.0, "dlr": 6.0, "bus": 9.0}
TRANSIT_MODES = set(DEFAULT_HEADWAY_MIN) | {"tram", "river-bus", "cable-car"}


@dataclass
class Arrival:
    vehicle_id: str
    stop_id: str
    stop_name: str
    line_id: str
    line_name: str
    mode: str
    direction: str  # destination-ish label used to match a journey leg
    destination: str
    expected_arrival: datetime
    time_to_station_s: int
    feed_timestamp: datetime
    platform: str | None = None
    # True when the vehicle terminates at this stop and will reverse to form a departure (e.g. a line's end).
    terminates_here: bool = False


@dataclass
class StatusSection:
    """One disruption on a line. Empty `stops` means the provider didn't say where: assume the whole line."""
    category: str
    stops: frozenset[str] = frozenset()


@dataclass
class LineStatus:
    line_id: str
    line_name: str
    mode: str
    category: str  # worst category anywhere on the line
    description: str
    reason: str | None = None
    severity_code: int | None = None
    sections: list[StatusSection] = field(default_factory=list)

    def category_for(self, stop_ids: list[str] | None) -> str:
        """Worst category affecting a journey leg that calls at `stop_ids`.

        A disruption limited to listed stops only applies if the leg calls at one of them. With no
        section detail (or no stop ids for the leg) we stay conservative and apply the line-wide status.
        """
        if not self.sections or not stop_ids:
            return self.category
        legs = set(stop_ids)
        worst = GOOD
        for sec in self.sections:
            if not sec.stops or sec.stops & legs:
                if SEVERITY_ORDER[sec.category] > SEVERITY_ORDER[worst]:
                    worst = sec.category
        return worst


@dataclass
class Leg:
    mode: str  # "walking" or a transit mode
    duration_min: float
    from_name: str
    to_name: str
    departure: datetime
    arrival: datetime
    line_id: str | None = None
    line_name: str | None = None
    from_stop_id: str | None = None
    to_stop_id: str | None = None
    direction: str | None = None
    headway_min: float | None = None
    stops: int | None = None
    stop_ids: list[str] = field(default_factory=list)  # every stop the leg calls at, boarding stop first
    path: list[tuple[float, float]] = field(default_factory=list)  # route shape (lat, lon), simplified for maps

    @property
    def is_transit(self) -> bool:
        return self.mode != "walking" and self.line_id is not None


@dataclass
class Journey:
    legs: list[Leg]
    duration_min: float
    departure: datetime
    arrival: datetime
    source: str = "sim"
    fare_pence: int | None = None  # the fare TfL quotes for this time of travel
    fare_peak_pence: int | None = None
    fare_off_peak_pence: int | None = None

    @property
    def transit_legs(self) -> list[Leg]:
        return [l for l in self.legs if l.is_transit]

    @property
    def walking_min(self) -> float:
        return round(sum(l.duration_min for l in self.legs if l.mode == "walking"), 1)

    @property
    def changes(self) -> int:
        return max(0, len(self.transit_legs) - 1)

    @property
    def signature(self) -> str:
        """Stable identity for a route: the ordered transit lines and boarding points."""
        parts = [f"{l.mode}:{l.line_id}@{l.from_stop_id or l.from_name}" for l in self.transit_legs]
        return ">".join(parts) or "walk"

    @property
    def summary(self) -> str:
        names = [l.line_name or l.line_id for l in self.transit_legs]
        return " → ".join(names) if names else "Walk"


@dataclass
class PlaceResult:
    name: str
    lat: float
    lon: float
    kind: str = "place"
    stop_id: str | None = None
    detail: str | None = None


@dataclass
class FetchResult:
    """Normalised records plus the raw payload, so the recorder can keep both."""
    items: list = field(default_factory=list)
    raw: str = ""
    endpoint: str = ""
    status: int = 200
    latency_ms: int = 0


@dataclass
class NearbyStop:
    """A station or stop near a place, offered so the user can pick the ones they actually use."""
    stop_id: str
    name: str
    kind: str  # "station" | "bus"
    lat: float
    lon: float
    distance_m: int
    walk_min: float
    modes: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    hub: str | None = None  # interchange group, e.g. HUBVIC for the Tube and rail stations at Victoria
    indicator: str | None = None  # bus stop letter, e.g. "Stop K"
    towards: str | None = None


def simplify_path(points: list[tuple[float, float]], max_points: int = 60) -> list[tuple[float, float]]:
    """Keep first, last and evenly spaced points: enough to draw a route, small enough to send to phones."""
    if len(points) <= max_points:
        return [(round(a, 5), round(b, 5)) for a, b in points]
    step = (len(points) - 1) / (max_points - 1)
    return [(round(points[round(i * step)][0], 5), round(points[round(i * step)][1], 5)) for i in range(max_points)]
