from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..domain import FetchResult, Journey, PlaceResult


class Provider(Protocol):
    name: str

    def arrivals(self, stop_id: str, now: datetime) -> FetchResult: ...

    def line_statuses(self, now: datetime, line_ids: list[str] | None = None) -> FetchResult: ...

    def journeys(
        self, origin: tuple[float, float], dest: tuple[float, float], depart_at: datetime
    ) -> list[Journey]: ...

    def search_places(self, query: str) -> list[PlaceResult]: ...
