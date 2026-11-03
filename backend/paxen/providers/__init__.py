from __future__ import annotations

from functools import lru_cache

from ..config import settings
from .base import Provider


@lru_cache(maxsize=1)
def get_provider() -> Provider:
    if settings.provider == "tfl":
        from .tfl import TflProvider

        return TflProvider(settings.tfl_base_url, settings.tfl_app_key)
    from .sim import SimProvider

    return SimProvider(scenario=settings.sim_scenario)
