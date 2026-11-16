from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..domain import FetchResult, Journey, NearbyStop, PlaceResult


class Provider(Protocol):
    name: str

    def arrivals(self, stop_id: str, now: datetime) -> FetchResult: ...

    def line_statuses(self, now: datetime, line_ids: list[str] | None = None) -> FetchResult: ...

    def journeys(
        self, origin: tuple[float, float], dest: tuple[float, float], depart_at: datetime, *,
        step_free: bool = False
    ) -> list[Journey]: ...

    def search_places(self, query: str) -> list[PlaceResult]: ...

    def nearby_stops(self, lat: float, lon: float) -> list[NearbyStop]: ...
