from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, create_engine, inspect, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import normalise_db_url, settings
from .timeutil import naive_utc, utcnow


def _id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return naive_utc(utcnow())


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------- users & routine
class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    name: Mapped[str | None] = mapped_column(String(80))
    push_token: Mapped[str | None] = mapped_column(String(255))  # Expo (a future native app)
    web_push: Mapped[dict | None] = mapped_column(JSON)  # the browser's push subscription (paxen/webpush.py)
    quiet_start: Mapped[str] = mapped_column(String(5), default="22:00")
    quiet_end: Mapped[str] = mapped_column(String(5), default="06:30")
    monitoring_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    alert_threshold_min: Mapped[int] = mapped_column(Integer, default=8)  # how much slower than normal before we alert
    min_gain_min: Mapped[int] = mapped_column(Integer, default=5)  # how much better an alternative must be
    places = relationship("Place", cascade="all, delete-orphan", back_populates="user")
    commutes = relationship("Commute", cascade="all, delete-orphan", back_populates="user")


class Place(Base):
    __tablename__ = "places"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(20))  # home | work | other
    name: Mapped[str] = mapped_column(String(120))
    lat: Mapped[float] = mapped_column(Float)  # stored at ~11 m precision (data minimisation)
    lon: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | pin | saved | inferred
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    # Stations/stops the user chose for this place: [{stop_id, name, kind, lat, lon, walk_min, hub, modes, lines}]
    preferred_stops: Mapped[list | None] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user = relationship("User", back_populates="places")


class Commute(Base):
    __tablename__ = "commutes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    origin_id: Mapped[str] = mapped_column(ForeignKey("places.id", ondelete="CASCADE"))
    dest_id: Mapped[str] = mapped_column(ForeignKey("places.id", ondelete="CASCADE"))
    days: Mapped[list] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4])  # Mon=0
    window_start: Mapped[str] = mapped_column(String(5), default="08:00")
    window_end: Mapped[str] = mapped_column(String(5), default="08:45")
    preference: Mapped[str] = mapped_column(String(20), default="balanced")
    usual_signature: Mapped[str | None] = mapped_column(Text)
    usual_summary: Mapped[str | None] = mapped_column(String(200))
    usual_nominal_min: Mapped[float | None] = mapped_column(Float)
    alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user = relationship("User", back_populates="commutes")
    origin = relationship("Place", foreign_keys=[origin_id])
    dest = relationship("Place", foreign_keys=[dest_id])


class Trip(Base):
    """What actually happened: the learning loop's ground truth for personal baselines."""
    __tablename__ = "trips"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    commute_id: Mapped[str | None] = mapped_column(ForeignKey("commutes.id", ondelete="SET NULL"), index=True)
    signature: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_min: Mapped[float | None] = mapped_column(Float)
    forecast_p10: Mapped[float | None] = mapped_column(Float)
    forecast_p50: Mapped[float | None] = mapped_column(Float)
    forecast_p90: Mapped[float | None] = mapped_column(Float)
    followed_alert_id: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(20), default="app")  # app | manual | detected
    # Live trips: the route as chosen (legs, stops, shape) and how the trip ended. Positions are never stored.
    plan: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str | None] = mapped_column(String(20))  # active | arrived | auto_closed


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    commute_id: Mapped[str | None] = mapped_column(ForeignKey("commutes.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    kind: Mapped[str] = mapped_column(String(30))  # better_route | leave_earlier | usual_unavailable
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(10))
    delta_min: Mapped[float | None] = mapped_column(Float)
    gain_min: Mapped[float | None] = mapped_column(Float)
    recommended_signature: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    delivered: Mapped[str] = mapped_column(String(20), default="inbox")  # inbox | push | push_failed
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    feedback: Mapped[str | None] = mapped_column(String(20))  # useful | not_useful | inaccurate
    feedback_note: Mapped[str | None] = mapped_column(Text)


# ------------------------------------------------------------------- data recorder
class RawSnapshot(Base):
    __tablename__ = "raw_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(10))
    endpoint: Mapped[str] = mapped_column(String(300))
    polled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[str | None] = mapped_column(Text)
    archive_key: Mapped[str | None] = mapped_column(String(300))  # where the full raw response was archived
    error: Mapped[str | None] = mapped_column(Text)


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(10))
    # Plain id, deliberately not a foreign key: with one, every raw snapshot deleted by retention made Postgres
    # scan the whole predictions table (no index on raw_id), so pruning a day took hours.
    raw_id: Mapped[int | None] = mapped_column(Integer)
    polled_at: Mapped[datetime] = mapped_column(DateTime)
    feed_ts: Mapped[datetime | None] = mapped_column(DateTime)
    stop_id: Mapped[str] = mapped_column(String(40))
    line_id: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str | None] = mapped_column(String(120))
    vehicle_id: Mapped[str] = mapped_column(String(60))
    expected_arrival: Mapped[datetime] = mapped_column(DateTime)
    tts_s: Mapped[int] = mapped_column(Integer)
    line_category: Mapped[str] = mapped_column(String(20), default="good")
    platform: Mapped[str | None] = mapped_column(String(60))  # e.g. "Southbound - Platform 1"
    # Context at prediction time, from the full board (before storage sampling): this train's place in the queue
    # at this stop/platform (1 = next), and seconds behind the train ahead of it.
    queue_rank: Mapped[int | None] = mapped_column(Integer)
    gap_s: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (
        Index("ix_pred_vehicle", "source", "stop_id", "line_id", "vehicle_id", "polled_at"),
        Index("ix_pred_polled", "polled_at"),
    )


class ObservedArrival(Base):
    """An arrival we believe happened. `method` says how we know — never treat inferred as measured."""
    __tablename__ = "observed_arrivals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(10))
    stop_id: Mapped[str] = mapped_column(String(40))
    line_id: Mapped[str] = mapped_column(String(40))
    vehicle_id: Mapped[str] = mapped_column(String(60))
    # TfL reuses a train's id in both directions (and when a terminating train forms a departure),
    # so direction is part of an arrival's identity.
    direction: Mapped[str | None] = mapped_column(String(120))
    arrived_at: Mapped[datetime] = mapped_column(DateTime)
    earliest: Mapped[datetime] = mapped_column(DateTime)
    latest: Mapped[datetime] = mapped_column(DateTime)
    method: Mapped[str] = mapped_column(String(30))  # countdown_inferred | feed_reported | avl_position
    quality: Mapped[float] = mapped_column(Float)
    __table_args__ = (Index("ix_obs_vehicle", "source", "stop_id", "line_id", "vehicle_id", "arrived_at"),
                      Index("ix_obs_arrived", "arrived_at"))


class LineStatusSnapshot(Base):
    __tablename__ = "line_status_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(10))
    polled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    line_id: Mapped[str] = mapped_column(String(40), index=True)
    line_name: Mapped[str] = mapped_column(String(80))
    mode: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str | None] = mapped_column(Text)


class WatchedStop(Base):
    """Stops the recorder polls: boarding points of users' candidate routes, plus pilot corridor stops."""
    __tablename__ = "watched_stops"
    stop_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(120))
    last_needed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AppSecret(Base):
    """Server-generated secrets that must survive restarts and be shared by the API and worker (VAPID keys)."""
    __tablename__ = "app_secrets"
    name: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class ContextEvent(Base):
    """A run of something seen in the live context: a line status, station disruption, lift outage or planned
    works. One row per run (first seen to last seen), so it can be kept permanently. See paxen/context.py."""
    __tablename__ = "context_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(30))
    key: Mapped[str] = mapped_column(String(220))
    first_seen: Mapped[datetime] = mapped_column(DateTime)
    last_seen: Mapped[datetime] = mapped_column(DateTime)
    line_id: Mapped[str | None] = mapped_column(String(40))
    stop_id: Mapped[str | None] = mapped_column(String(40))
    category: Mapped[str | None] = mapped_column(String(40))
    summary: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON)
    __table_args__ = (Index("ix_ctx_kind_key", "kind", "key", "last_seen"), Index("ix_ctx_first", "first_seen"),
                      Index("ix_ctx_kind_line", "kind", "line_id", "last_seen"))


class WeatherHour(Base):
    """Hourly central-London weather (Open-Meteo), kept permanently: tiny, and needed to learn weather effects."""
    __tablename__ = "weather_hours"
    hour: Mapped[str] = mapped_column(String(13), primary_key=True)  # YYYY-MM-DDTHH, London time
    temp_c: Mapped[float | None] = mapped_column(Float)
    precip_mm: Mapped[float | None] = mapped_column(Float)
    snow_cm: Mapped[float | None] = mapped_column(Float)
    gust_kmh: Mapped[float | None] = mapped_column(Float)
    humidity: Mapped[float | None] = mapped_column(Float)
    weather_code: Mapped[int | None] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class StationCrowding(Base):
    """TfL's live busyness at a Tube station (share of its usual peak), every 15 minutes."""
    __tablename__ = "station_crowding"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    polled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    stop_id: Mapped[str] = mapped_column(String(40))
    pct_of_baseline: Mapped[float] = mapped_column(Float)


class AirQualityDay(Base):
    """TfL's London air-quality band, one row per day: the history behind 'today vs usual'."""
    __tablename__ = "air_quality_days"
    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD (London)
    band: Mapped[str] = mapped_column(String(20))
    level: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    kind: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)


def make_engine(url: str | None = None):
    url = normalise_db_url(url or settings.database_url)
    kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    return create_engine(url, **kw)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


# Additive column changes for databases created by earlier versions (no migration framework yet).
_ADDED_COLUMNS = [("observed_arrivals", "direction", "VARCHAR(120)"),
                  ("raw_snapshots", "archive_key", "VARCHAR(300)"),
                  ("places", "preferred_stops", "JSON"),
                  ("trips", "plan", "JSON"),
                  ("trips", "status", "VARCHAR(20)"),
                  ("predictions", "platform", "VARCHAR(60)"),
                  ("predictions", "queue_rank", "INTEGER"),
                  ("predictions", "gap_s", "INTEGER"),
                  ("users", "web_push", "JSON")]


# Indexes added after a table existed (create_all doesn't add indexes to existing tables).
_ADDED_INDEXES = [("ix_obs_arrived", "observed_arrivals", "arrived_at")]


def init_db(eng=None) -> None:
    eng = eng or engine
    Base.metadata.create_all(eng)
    insp = inspect(eng)
    with eng.begin() as conn:
        for table, column, ddl in _ADDED_COLUMNS:
            if column not in {c["name"] for c in insp.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        for name, table, column in _ADDED_INDEXES:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"))
        if eng.dialect.name == "postgresql":  # see Prediction.raw_id
            conn.execute(text("ALTER TABLE predictions DROP CONSTRAINT IF EXISTS predictions_raw_id_fkey"))
