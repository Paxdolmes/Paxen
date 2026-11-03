from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


def normalise_db_url(url: str) -> str:
    """Hosts hand out postgres:// URLs; SQLAlchemy needs the driver named (psycopg 3)."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@dataclass
class Settings:
    # PAXEN_DATABASE_URL wins; DATABASE_URL is what Railway/Render/Heroku-style hosts inject.
    database_url: str = field(default_factory=lambda: normalise_db_url(
        os.getenv("PAXEN_DATABASE_URL") or os.getenv("DATABASE_URL") or "sqlite:///./paxen.db"))
    # "sim" = built-in simulated London network (works offline); "tfl" = TfL Unified API.
    provider: str = field(default_factory=lambda: os.getenv("PAXEN_PROVIDER", "sim"))
    tfl_app_key: str | None = field(default_factory=lambda: os.getenv("TFL_APP_KEY"))
    tfl_base_url: str = field(default_factory=lambda: os.getenv("TFL_BASE_URL", "https://api.tfl.gov.uk"))
    run_workers: bool = field(default_factory=lambda: _bool("PAXEN_RUN_WORKERS", True))
    poll_interval_s: int = field(default_factory=lambda: int(os.getenv("PAXEN_POLL_INTERVAL", "30")))
    monitor_interval_s: int = field(default_factory=lambda: int(os.getenv("PAXEN_MONITOR_INTERVAL", "60")))
    train_interval_s: int = field(default_factory=lambda: int(os.getenv("PAXEN_TRAIN_INTERVAL", "21600")))
    sim_scenario: str = field(default_factory=lambda: os.getenv("PAXEN_SIM_SCENARIO", "auto"))
    # Whole-network recording: modes polled with one request each (TfL /Mode/{mode}/Arrivals).
    # Defaults to London rail when using TfL; set to "" to record only the stops users' commutes use.
    record_modes: list[str] = field(default_factory=lambda: [m.strip() for m in os.getenv(
        "PAXEN_RECORD_MODES",
        "tube,overground,elizabeth-line,dlr,tram" if os.getenv("PAXEN_PROVIDER", "sim") == "tfl" else "",
    ).split(",") if m.strip()])
    # Modes too large for the database (buses: ~100 MB per poll) are archived whole on a slower cycle.
    # Needs PAXEN_ARCHIVE_URL; buses on users' routes are still recorded in detail in the database.
    archive_only_modes: list[str] = field(default_factory=lambda: [m.strip() for m in os.getenv(
        "PAXEN_ARCHIVE_ONLY_MODES", "bus" if os.getenv("PAXEN_PROVIDER", "sim") == "tfl" else "",
    ).split(",") if m.strip()])
    archive_only_interval_s: int = field(default_factory=lambda: int(os.getenv("PAXEN_ARCHIVE_ONLY_INTERVAL", "120")))
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.getenv("PAXEN_CORS_ORIGINS", "*").split(",") if o.strip()]
    )
    expo_push_url: str = "https://exp.host/--/api/v2/push/send"
    timezone: str = "Europe/London"


settings = Settings()
