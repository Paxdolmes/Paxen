from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("PAXEN_DATABASE_URL", "sqlite:///./paxen.db"))
    # "sim" = built-in simulated London network (works offline); "tfl" = TfL Unified API.
    provider: str = field(default_factory=lambda: os.getenv("PAXEN_PROVIDER", "sim"))
    tfl_app_key: str | None = field(default_factory=lambda: os.getenv("TFL_APP_KEY"))
    tfl_base_url: str = field(default_factory=lambda: os.getenv("TFL_BASE_URL", "https://api.tfl.gov.uk"))
    run_workers: bool = field(default_factory=lambda: _bool("PAXEN_RUN_WORKERS", True))
    poll_interval_s: int = field(default_factory=lambda: int(os.getenv("PAXEN_POLL_INTERVAL", "30")))
    monitor_interval_s: int = field(default_factory=lambda: int(os.getenv("PAXEN_MONITOR_INTERVAL", "60")))
    train_interval_s: int = field(default_factory=lambda: int(os.getenv("PAXEN_TRAIN_INTERVAL", "21600")))
    sim_scenario: str = field(default_factory=lambda: os.getenv("PAXEN_SIM_SCENARIO", "auto"))
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.getenv("PAXEN_CORS_ORIGINS", "*").split(",") if o.strip()]
    )
    expo_push_url: str = "https://exp.host/--/api/v2/push/send"
    timezone: str = "Europe/London"


settings = Settings()
