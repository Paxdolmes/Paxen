"""Paxen API. Run: uvicorn paxen.main:app --reload"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import serialize as ser
from .config import settings
from .db import Alert, Commute, Place, SessionLocal, Trip, User, init_db
from .domain import SEVERITY_ORDER
from .engine import (
    clear_status_cache, current_statuses, default_depart_at, evaluate_commute, maybe_alert, route_key,
    set_usual,
)
from .insights import insights as build_insights
from .notify import deliver
from .providers import get_provider
from .providers.sim import SCENARIOS, SimProvider
from .recorder import feed_health
from .timeutil import aware, local, naive_utc, utcnow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


class _NoQueryStrings(logging.Filter):
    """Access logs keep the path but never the query string (positions, home coordinates, address searches)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and "?" in args[2]:
            record.args = args[:2] + (args[2].split("?", 1)[0],) + args[3:]
        return True


logging.getLogger("uvicorn.access").addFilter(_NoQueryStrings())
# Request URLs carry the TfL app_key: never log them.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.database_url.startswith("sqlite") and os.getenv("RAILWAY_ENVIRONMENT"):
        logging.getLogger("paxen").warning(
            "No DATABASE_URL set: using a temporary SQLite file. Add a Postgres database and set "
            "DATABASE_URL=${{Postgres.DATABASE_URL}} so data survives redeploys.")
    init_db()
    tasks: list[asyncio.Task] = []
    if settings.run_workers:
        from . import workers

        workers.start(tasks)
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Paxen API", version="0.1.0", lifespan=lifespan,
              description="Commute intelligence: know when your normal commute is not normal.")
# The iPhone app (web/ios, Capacitor) serves its screens from capacitor://localhost: always allow it.
_origins = settings.cors_origins if "*" in settings.cors_origins else [*settings.cors_origins, "capacitor://localhost"]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------------ plumbing
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(authorization: str = Header(default=""), s: Session = Depends(db)) -> User:
    token = authorization.removeprefix("Bearer ").strip()
    u = s.scalar(select(User).where(User.token_hash == _hash(token))) if token else None
    if not u:
        raise HTTPException(401, "Missing or invalid token")
    return u


def now() -> datetime:
    return utcnow()


HHMM = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
Pref = Literal["balanced", "fastest", "reliable", "least_walking", "fewest_changes"]


def _round(x: float) -> float:
    return round(x, 4)  # ~11 m: enough for routing, less precise than a front door


class StopIn(BaseModel):
    stop_id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["station", "bus"] = "station"
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    walk_min: float | None = Field(default=None, ge=0, le=90)
    hub: str | None = None
    modes: list[str] = []
    lines: list[str] = []
    indicator: str | None = None


class PlaceIn(BaseModel):
    label: Literal["home", "work", "other"] = "other"
    name: str = Field(min_length=1, max_length=120)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    source: Literal["manual", "pin", "saved", "inferred"] = "manual"
    stops: list[StopIn] = Field(default=[], max_length=6)


class PlacePatch(BaseModel):
    label: Literal["home", "work", "other"] | None = None
    name: str | None = None
    lat: float | None = None
    lon: float | None = None
    confirmed: bool | None = None
    stops: list[StopIn] | None = Field(default=None, max_length=6)


class CommuteIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    origin_id: str
    dest_id: str
    days: list[int] = [0, 1, 2, 3, 4]
    window_start: str = HHMM
    window_end: str = HHMM
    preference: Pref = "balanced"
    alerts_enabled: bool = True

    @field_validator("days")
    @classmethod
    def _days(cls, v):
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("days are 0 (Mon) .. 6 (Sun)")
        return sorted(set(v))


class CommutePatch(BaseModel):
    name: str | None = None
    days: list[int] | None = None
    window_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    window_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    preference: Pref | None = None
    alerts_enabled: bool | None = None


class Window(BaseModel):
    start: str = HHMM
    end: str = HHMM


class OnboardingIn(BaseModel):
    name: str | None = None
    home: PlaceIn
    work: PlaceIn
    days: list[int] = [0, 1, 2, 3, 4]
    morning: Window = Window(start="08:00", end="08:45")
    evening: Window = Window(start="17:30", end="18:15")
    preference: Pref = "balanced"


class MePatch(BaseModel):
    name: str | None = None
    push_token: str | None = None
    quiet_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    monitoring_paused: bool | None = None
    alert_threshold_min: int | None = Field(default=None, ge=2, le=60)
    min_gain_min: int | None = Field(default=None, ge=1, le=60)


class TripIn(BaseModel):
    commute_id: str | None = None
    signature: str | None = None
    summary: str | None = None
    started_at: datetime | None = None
    arrived_at: datetime | None = None
    forecast_p10: float | None = None
    forecast_p50: float | None = None
    forecast_p90: float | None = None
    followed_alert_id: str | None = None


class ArriveIn(BaseModel):
    arrived_at: datetime | None = None


class FeedbackIn(BaseModel):
    feedback: Literal["useful", "not_useful", "inaccurate"]
    note: str | None = Field(default=None, max_length=1000)


class UsualIn(BaseModel):
    signature: str


def _own(s: Session, model, id_: str, u: User):
    obj = s.get(model, id_)
    if not obj or obj.user_id != u.id:
        raise HTTPException(404, "Not found")
    return obj


def _feed_fresh(s: Session, t: datetime) -> bool:
    h = feed_health(s, t, get_provider().name)
    return h["fresh"] or h["last_success_at"] is None  # before the recorder's first poll, don't penalise


# --------------------------------------------------------------------------- meta
@app.get("/v1/health")
def health(s: Session = Depends(db)):
    p = get_provider()
    return {"ok": True, "provider": p.name, "simulated": isinstance(p, SimProvider),
            "scenario": getattr(p, "scenario", None), "feed": feed_health(s, now(), p.name)}


# ------------------------------------------------------------------------ account
@app.post("/v1/users", status_code=201)
def create_user(s: Session = Depends(db)):
    """Anonymous device account. The token is shown once; store it on the device."""
    token = secrets.token_urlsafe(32)
    u = User(token_hash=_hash(token))
    s.add(u)
    s.commit()
    return {"user_id": u.id, "token": token}


@app.get("/v1/me")
def me(u: User = Depends(current_user)):
    return ser.user(u)


# ---- web push (paxen/webpush.py) ----
class PushSubscriptionIn(BaseModel):
    subscription: dict


@app.get("/v1/push/key")
def push_key(s: Session = Depends(db)):
    """The server's public VAPID key, for the browser's pushManager.subscribe()."""
    from .webpush import public_key

    return {"public_key": public_key(s)}


@app.post("/v1/push/subscribe")
def push_subscribe(body: PushSubscriptionIn, u: User = Depends(current_user), s: Session = Depends(db)):
    from .webpush import valid_subscription

    if not valid_subscription(body.subscription):
        raise HTTPException(422, "That isn't a valid push subscription.")
    sub = body.subscription
    u.web_push = {"endpoint": sub["endpoint"], "keys": {k: sub["keys"][k] for k in ("p256dh", "auth")}}
    s.commit()
    return ser.user(u)


@app.delete("/v1/push/subscribe")
def push_unsubscribe(u: User = Depends(current_user), s: Session = Depends(db)):
    u.web_push = None
    s.commit()
    return ser.user(u)


@app.post("/v1/push/test")
def push_test(u: User = Depends(current_user), s: Session = Depends(db)):
    """A test notification to this user's device: the iPhone app (APNs) or the web app (web push)."""
    title, body = "Paxen", "Notifications are working. We'll tell you when your commute isn't normal."
    if (u.push_token or "").startswith("apns:"):
        from .apns import send as apns_send

        res = apns_send(u.push_token, title, body, {"url": "/?tab=alerts"})
        if res == "gone":
            u.push_token = None
    elif u.web_push:
        from .webpush import send

        res = send(s, u.web_push, title, body, {"url": "/?tab=alerts"})
        if res == "gone":
            u.web_push = None
    else:
        raise HTTPException(409, "Push notifications aren't turned on for this device.")
    s.commit()
    return {"result": res}


@app.patch("/v1/me")
def patch_me(body: MePatch, u: User = Depends(current_user), s: Session = Depends(db)):
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(u, k, v)
    s.add(u)
    s.commit()
    return ser.user(u)


@app.delete("/v1/me", status_code=204)
def delete_me(u: User = Depends(current_user), s: Session = Depends(db)):
    for model in (Trip, Alert):
        s.query(model).filter(model.user_id == u.id).delete()
    s.delete(s.merge(u))
    s.commit()


@app.delete("/v1/me/history")
def clear_history(u: User = Depends(current_user), s: Session = Depends(db)):
    """Clear journey history and alerts; learned usual routes are reset too."""
    trips = s.query(Trip).filter(Trip.user_id == u.id).delete()
    alerts = s.query(Alert).filter(Alert.user_id == u.id).delete()
    for c in s.scalars(select(Commute).where(Commute.user_id == u.id)):
        c.usual_signature = c.usual_summary = c.usual_nominal_min = None
    s.commit()
    return {"trips_deleted": trips, "alerts_deleted": alerts}


@app.post("/v1/onboarding", status_code=201)
def onboarding(body: OnboardingIn, u: User = Depends(current_user), s: Session = Depends(db)):
    """One call to set Home, Work and the two daily commutes."""
    u = s.merge(u)
    if body.name:
        u.name = body.name
    places = {}
    for key, p in (("home", body.home), ("work", body.work)):
        existing = s.scalar(select(Place).where(Place.user_id == u.id, Place.label == key))
        stops = [st.model_dump() for st in p.stops]
        if existing:
            existing.name, existing.lat, existing.lon, existing.source = p.name, _round(p.lat), _round(p.lon), p.source
            existing.preferred_stops = stops
            places[key] = existing
        else:
            places[key] = Place(user_id=u.id, label=key, name=p.name, lat=_round(p.lat), lon=_round(p.lon),
                                source=p.source, confirmed=True, preferred_stops=stops)
            s.add(places[key])
    s.flush()
    for c in s.scalars(select(Commute).where(Commute.user_id == u.id)):
        s.delete(c)
    s.flush()
    commutes = [
        Commute(user_id=u.id, name="To work", origin_id=places["home"].id, dest_id=places["work"].id,
                days=body.days, window_start=body.morning.start, window_end=body.morning.end,
                preference=body.preference),
        Commute(user_id=u.id, name="Home", origin_id=places["work"].id, dest_id=places["home"].id,
                days=body.days, window_start=body.evening.start, window_end=body.evening.end,
                preference=body.preference),
    ]
    s.add_all(commutes)
    s.commit()
    return {"places": [ser.place(p) for p in places.values()], "commutes": [ser.commute(c) for c in commutes]}


# ------------------------------------------------------------------------- places
class SearchIn(BaseModel):
    q: str = Field(min_length=2, max_length=80)


class PointIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class LiveIn(BaseModel):
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


# Personal data (addresses, home coordinates, live position) goes in request bodies: URLs end up in access logs
# and the hosting provider's HTTP logs. The GET forms remain for older app versions.
@app.post("/v1/places/search")
def search_places_post(body: SearchIn, u: User = Depends(current_user)):
    return search_places(body.q, u)


@app.post("/v1/places/nearby-stops")
def nearby_stops_post(body: PointIn, u: User = Depends(current_user)):
    return nearby_stops(body.lat, body.lon, u)


@app.get("/v1/places/search")
def search_places(q: str = Query(min_length=2, max_length=80), _: User = Depends(current_user)):
    """Addresses and postcodes (geocoded) first, then matching stations/stops."""
    from .geocode import geocode

    addresses = list(geocode(q)) if not isinstance(get_provider(), SimProvider) else []
    try:
        stations = get_provider().search_places(q)
    except Exception as e:
        if not addresses:
            raise HTTPException(502, "Place search is unavailable right now. Try again shortly.") from e
        stations = []
    return [r.__dict__ for r in addresses[:6] + stations[:8]]


@app.get("/v1/places/nearby-stops")
def nearby_stops(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180),
                 _: User = Depends(current_user)):
    """Stations (~1.2 km) and bus/tram stops (~400 m) near a point, nearest first, for the user to choose from."""
    try:
        return [n.__dict__ for n in get_provider().nearby_stops(lat, lon)]
    except Exception as e:
        raise HTTPException(502, "Nearby stations are unavailable right now. Try again shortly.") from e


@app.get("/v1/places")
def list_places(u: User = Depends(current_user), s: Session = Depends(db)):
    return [ser.place(p) for p in s.scalars(select(Place).where(Place.user_id == u.id))]


@app.post("/v1/places", status_code=201)
def create_place(body: PlaceIn, u: User = Depends(current_user), s: Session = Depends(db)):
    p = Place(user_id=u.id, label=body.label, name=body.name, lat=_round(body.lat), lon=_round(body.lon),
              source=body.source, confirmed=body.source != "inferred",  # inferred places need explicit confirmation
              preferred_stops=[st.model_dump() for st in body.stops])
    s.add(p)
    s.commit()
    return ser.place(p)


@app.patch("/v1/places/{place_id}")
def patch_place(place_id: str, body: PlacePatch, u: User = Depends(current_user), s: Session = Depends(db)):
    p = _own(s, Place, place_id, u)
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "stops":
            p.preferred_stops = v or []
            continue
        setattr(p, k, _round(v) if k in ("lat", "lon") and v is not None else v)
    if body.lat is not None or body.lon is not None or body.stops is not None:  # usual route must be re-learned
        for c in s.scalars(select(Commute).where((Commute.origin_id == p.id) | (Commute.dest_id == p.id))):
            c.usual_signature = c.usual_summary = c.usual_nominal_min = None
    s.commit()
    return ser.place(p)


@app.delete("/v1/places/{place_id}", status_code=204)
def delete_place(place_id: str, u: User = Depends(current_user), s: Session = Depends(db)):
    p = _own(s, Place, place_id, u)
    for c in s.scalars(select(Commute).where((Commute.origin_id == p.id) | (Commute.dest_id == p.id))):
        s.delete(c)
    s.delete(p)
    s.commit()


# ----------------------------------------------------------------------- commutes
@app.get("/v1/commutes")
def list_commutes(u: User = Depends(current_user), s: Session = Depends(db)):
    return [ser.commute(c) for c in s.scalars(select(Commute).where(Commute.user_id == u.id))]


@app.post("/v1/commutes", status_code=201)
def create_commute(body: CommuteIn, u: User = Depends(current_user), s: Session = Depends(db)):
    _own(s, Place, body.origin_id, u)
    _own(s, Place, body.dest_id, u)
    c = Commute(user_id=u.id, **body.model_dump())
    s.add(c)
    s.commit()
    return ser.commute(c)


@app.patch("/v1/commutes/{commute_id}")
def patch_commute(commute_id: str, body: CommutePatch, u: User = Depends(current_user), s: Session = Depends(db)):
    c = _own(s, Commute, commute_id, u)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    s.commit()
    return ser.commute(c)


@app.delete("/v1/commutes/{commute_id}", status_code=204)
def delete_commute(commute_id: str, u: User = Depends(current_user), s: Session = Depends(db)):
    s.delete(_own(s, Commute, commute_id, u))
    s.commit()


@app.put("/v1/commutes/{commute_id}/usual")
def set_usual_route(commute_id: str, body: UsualIn, u: User = Depends(current_user), s: Session = Depends(db)):
    """'This is my usual route' — sets the route today's journey is compared against."""
    c = _own(s, Commute, commute_id, u)
    t = now()
    ev = evaluate_commute(s, get_provider(), c, t, feed_fresh=_feed_fresh(s, t))
    match = next((f for f in ev.options if f.signature == body.signature), None) or \
        next((f for f in ev.options if route_key(f.signature) == route_key(body.signature)), None)
    if not match:
        raise HTTPException(404, "Route not in current options")
    set_usual(c, match.journey)
    s.commit()
    return ser.commute(c)


def _warm_journeys(commutes: list[Commute], t: datetime) -> None:
    """Plan every commute's journeys in parallel; the provider caches them for the evaluations that follow."""
    if len(commutes) < 2:
        return
    p = get_provider()
    # Read everything from the database here: the session is not thread-safe, so worker threads only get plain values.
    jobs = [((c.origin.lat, c.origin.lon), (c.dest.lat, c.dest.lon), default_depart_at(c, t)) for c in commutes]

    def plan(job):
        try:
            p.journeys(*job)
        except Exception:
            pass  # evaluation will retry and report unavailability properly

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        list(pool.map(plan, jobs))


def _conditions(s, c, t, depart_at=None) -> dict:
    """Rain at the start of the journey and London air quality. Cached; missing sources are simply omitted."""
    from .conditions import air_quality, weather_at

    when = depart_at or default_depart_at(c, t)
    return {"weather": weather_at(c.origin.lat, c.origin.lon, when) if not isinstance(get_provider(), SimProvider)
            else None,
            "air_quality": air_quality(s, get_provider(), t)}


def _eval_dict(s, c, t, depart_at=None, preference=None, max_options=None, with_paths=False):
    ev = evaluate_commute(s, get_provider(), c, t, depart_at=depart_at, preference=preference,
                          feed_fresh=_feed_fresh(s, t), conditions=_conditions(s, c, t, depart_at))
    s.commit()  # persists learned usual route + watched stops
    return ser.evaluation(ev, t, max_options, with_paths)


def _upcoming(evals: list[dict], t: datetime) -> list[dict]:
    """Planned closures in the next week on lines the user's usual and recommended routes use."""
    from .conditions import upcoming_disruptions

    lines: dict[str, set[str]] = {}
    for e in evals:
        for key in ("usual", "recommended"):
            o = e.get(key)
            for leg in (o or {}).get("legs", []):
                if leg.get("line_id"):
                    lines.setdefault(leg["line_id"], set()).add(e["commute"]["name"])
    items = upcoming_disruptions(get_provider(), list(lines), t)
    return [{**i, "commutes": sorted(lines.get(i["line_id"], []))} for i in items]


@app.get("/v1/commutes/{commute_id}/compare")
def compare(commute_id: str, preference: Pref | None = None, depart_at: datetime | None = None,
            u: User = Depends(current_user), s: Session = Depends(db)):
    c = _own(s, Commute, commute_id, u)
    return _eval_dict(s, c, now(), aware(depart_at) if depart_at else None, preference, with_paths=True)


@app.get("/v1/dashboard")
def dashboard(u: User = Depends(current_user), s: Session = Depends(db)):
    t = now()
    commutes = list(s.scalars(select(Commute).where(Commute.user_id == u.id).order_by(Commute.window_start)))
    _warm_journeys(commutes, t)
    evals = [_eval_dict(s, c, t, max_options=3) for c in commutes]
    # The "current" commute: the one in its window, else the next one today, else the first.
    m = local(t).hour * 60 + local(t).minute
    upcoming = [e for e in evals if int(e["commute"]["window_end"][:2]) * 60 + int(e["commute"]["window_end"][3:]) >= m]
    active = next((e for e in evals if e["active"]), None) or (upcoming[0] if upcoming else evals[0] if evals else None)
    unread = s.query(Alert).filter(Alert.user_id == u.id, Alert.read.is_(False)).count()
    p = get_provider()
    return {
        "generated_at": t.isoformat(), "user": ser.user(u), "provider": p.name,
        "simulated": isinstance(p, SimProvider), "feed": feed_health(s, t, p.name),
        "active_commute_id": active["commute"]["id"] if active else None,
        "commutes": evals, "network": _network(t, evals), "unread_alerts": unread,
        "upcoming": _upcoming(evals, t),
    }


# ------------------------------------------------------------------------ network
def _network(t: datetime, evals: list[dict] | None = None) -> list[dict]:
    statuses = current_statuses(get_provider(), t)
    mine = set()
    for e in evals or []:
        for o in e["options"]:
            mine |= {l["line_id"] for l in o["legs"] if l["line_id"]}
    out = [{"line_id": st.line_id, "line_name": st.line_name, "mode": st.mode, "category": st.category,
            "description": st.description, "reason": st.reason, "on_my_routes": st.line_id in mine}
           for st in statuses.values()]
    out.sort(key=lambda x: (not x["on_my_routes"], -SEVERITY_ORDER[x["category"]], x["mode"] == "bus", x["line_name"]))
    return out


@app.get("/v1/network/status")
def network_status(u: User = Depends(current_user), s: Session = Depends(db)):
    t = now()
    commutes = list(s.scalars(select(Commute).where(Commute.user_id == u.id)))
    lines = set()
    for c in commutes:
        if c.usual_signature:
            lines |= {p.split(":")[-1] for p in route_key(c.usual_signature).split(">")}
    net = _network(t)
    for n in net:
        n["on_my_routes"] = n["line_id"] in lines
    net.sort(key=lambda x: (not x["on_my_routes"], -SEVERITY_ORDER[x["category"]], x["line_name"]))
    return {"generated_at": t.isoformat(), "lines": net, "feed": feed_health(s, t, get_provider().name)}


# -------------------------------------------------------------------------- trips
@app.get("/v1/trips")
def list_trips(limit: int = Query(50, le=500), u: User = Depends(current_user), s: Session = Depends(db)):
    q = select(Trip).where(Trip.user_id == u.id).order_by(Trip.started_at.desc()).limit(limit)
    return [ser.trip(t) for t in s.scalars(q)]


@app.post("/v1/trips", status_code=201)
def start_trip(body: TripIn, u: User = Depends(current_user), s: Session = Depends(db)):
    if body.commute_id:
        _own(s, Commute, body.commute_id, u)
    started = aware(body.started_at) if body.started_at else now()
    t = Trip(user_id=u.id, commute_id=body.commute_id, signature=body.signature, summary=body.summary,
             started_at=naive_utc(started), forecast_p10=body.forecast_p10, forecast_p50=body.forecast_p50,
             forecast_p90=body.forecast_p90, followed_alert_id=body.followed_alert_id,
             source="manual" if body.arrived_at else "app")
    if body.arrived_at:
        _finish(t, aware(body.arrived_at))
    elif body.commute_id and body.signature:
        # Live trip: remember the chosen route (stops and shape) so progress can be tracked.
        from .live import plan_from_option

        c = s.get(Commute, body.commute_id)
        ev = _eval_dict(s, c, started, depart_at=started, with_paths=True)
        opt = next((o for o in ev["options"] if o["id"] == body.signature), None) or next(
            (o for o in ev["options"] if route_key(o["id"]) == route_key(body.signature)), None)
        if opt:
            t.plan = plan_from_option(opt, {"name": c.origin.name, "lat": c.origin.lat, "lon": c.origin.lon},
                                      {"name": c.dest.name, "lat": c.dest.lat, "lon": c.dest.lon})
            t.summary = t.summary or opt["summary"]
            t.forecast_p10 = t.forecast_p10 or opt["duration"]["p10"]
            t.forecast_p50 = t.forecast_p50 or opt["duration"]["p50"]
            t.forecast_p90 = t.forecast_p90 or opt["duration"]["p90"]
        t.status = "active"
    s.add(t)
    s.commit()
    return ser.trip(t)


@app.post("/v1/trips/{trip_id}/live")
def trip_live_post(trip_id: str, body: LiveIn, u: User = Depends(current_user), s: Session = Depends(db)):
    """Live trip with the phone's position in the body. The position is used for this response only."""
    return trip_live(trip_id, body.lat, body.lon, u, s)


@app.get("/v1/trips/{trip_id}/live")
def trip_live(trip_id: str, lat: float | None = Query(None, ge=-90, le=90), lon: float | None = Query(None, ge=-180, le=180),
              u: User = Depends(current_user), s: Session = Depends(db)):
    """Progress, time remaining and next departure. lat/lon (optional, from the phone) are used, never stored."""
    from .live import live_status

    t = _own(s, Trip, trip_id, u)
    pos = (lat, lon) if lat is not None and lon is not None else None
    return live_status(s, get_provider(), t, now(), pos)


def _finish(t: Trip, arrived: datetime) -> None:
    dur = (arrived - aware(t.started_at)).total_seconds() / 60
    if dur <= 0 or dur > 240:
        raise HTTPException(422, "Arrival must be within 4 hours after the start")
    t.arrived_at, t.duration_min = naive_utc(arrived), round(dur, 1)


@app.post("/v1/trips/{trip_id}/arrive")
def arrive(trip_id: str, body: ArriveIn, u: User = Depends(current_user), s: Session = Depends(db)):
    t = _own(s, Trip, trip_id, u)
    _finish(t, aware(body.arrived_at) if body.arrived_at else now())
    t.status = "arrived"
    s.commit()
    return ser.trip(t)


@app.delete("/v1/trips/{trip_id}", status_code=204)
def delete_trip(trip_id: str, u: User = Depends(current_user), s: Session = Depends(db)):
    s.delete(_own(s, Trip, trip_id, u))
    s.commit()


# ------------------------------------------------------------------------- alerts
@app.get("/v1/alerts")
def list_alerts(limit: int = Query(50, le=200), u: User = Depends(current_user), s: Session = Depends(db)):
    q = select(Alert).where(Alert.user_id == u.id).order_by(Alert.created_at.desc()).limit(limit)
    return [ser.alert(a) for a in s.scalars(q)]


@app.post("/v1/alerts/read")
def mark_read(u: User = Depends(current_user), s: Session = Depends(db)):
    n = s.query(Alert).filter(Alert.user_id == u.id, Alert.read.is_(False)).update({Alert.read: True})
    s.commit()
    return {"marked": n}


@app.post("/v1/alerts/{alert_id}/feedback")
def alert_feedback(alert_id: str, body: FeedbackIn, u: User = Depends(current_user), s: Session = Depends(db)):
    a = _own(s, Alert, alert_id, u)
    a.feedback, a.feedback_note, a.read = body.feedback, body.note, True
    s.commit()
    return ser.alert(a)


# ----------------------------------------------------------------------- insights
@app.get("/v1/insights")
def get_insights(u: User = Depends(current_user), s: Session = Depends(db)):
    return build_insights(s, u.id, now(), get_provider().name)


# ---------------------------------------------------------- demo / simulator controls
def _sim() -> SimProvider:
    p = get_provider()
    if not isinstance(p, SimProvider):
        raise HTTPException(404, "Only available with the simulated provider")
    return p


@app.get("/v1/dev/scenarios")
def scenarios():
    p = _sim()
    return {"current": p.scenario, "available": ["auto", *SCENARIOS.keys()],
            "disruptions": p.disruptions(now())}


class ScenarioIn(BaseModel):
    scenario: str


@app.post("/v1/dev/scenario")
def set_scenario(body: ScenarioIn):
    p = _sim()
    if body.scenario != "auto" and body.scenario not in SCENARIOS:
        raise HTTPException(422, f"Unknown scenario. Use one of: auto, {', '.join(SCENARIOS)}")
    p.scenario = body.scenario
    clear_status_cache()
    return {"current": p.scenario, "disruptions": p.disruptions(now())}


@app.post("/v1/dev/check-now")
def check_now(u: User = Depends(current_user), s: Session = Depends(db)):
    """Run the alert monitor for this user immediately, ignoring time windows (demo)."""
    t = now()
    out = []
    for c in s.scalars(select(Commute).where(Commute.user_id == u.id)):
        ev = evaluate_commute(s, get_provider(), c, t, depart_at=t, feed_fresh=_feed_fresh(s, t))
        a = maybe_alert(s, ev, t, force=True)
        if a:
            deliver(c.user, a)
            out.append(ser.alert(a))
    s.commit()
    return {"alerts": out}


@app.post("/v1/dev/seed")
def seed(hours: float = Query(2, ge=0.5, le=12), u: User = Depends(current_user), s: Session = Depends(db)):
    """Backfill simulated history: recorder replay -> model training, plus three weeks of past trips."""
    from .seed import seed_model, seed_trips

    p = _sim()
    t = now()
    commutes = list(s.scalars(select(Commute).where(Commute.user_id == u.id)))
    for c in commutes:  # make sure the usual route is known before synthesising trips on it
        evaluate_commute(s, p, c, t)
    s.commit()
    model = seed_model(s, p, t, hours=hours)
    trips = sum(seed_trips(s, p, c, t) for c in commutes)
    return {"model": model, "trips_created": trips}
