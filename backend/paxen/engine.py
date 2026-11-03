"""Journey forecasting, personal baselines, route ranking and alert decisions.

Prediction layers (see the concept brief §4C) as implemented here:

    provider baseline   -> planner leg durations + live countdowns
    feed quality        -> freshness checks downgrade confidence
    arrival correction  -> forecast.CorrectionModel adjusts live waits
    disruption impact   -> line status lengthens headways / ride times, widens intervals
    personal commute    -> personal_baseline(): the user's own normal
    route decision      -> rank(): preference-weighted, uncertainty-aware score
    outcome learning    -> trips store forecast vs actual (see insights)
"""
from __future__ import annotations

import math
import statistics
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Alert, Commute, Trip, User
from .domain import (
    DEFAULT_HEADWAY_MIN, GOOD, MINOR, PART_SUSPENDED, SEVERE, SUSPENDED, Arrival, Journey, LineStatus,
)
from .forecast import CorrectionModel, active_model
from .providers.base import Provider
from .recorder import watch_stops
from .timeutil import aware, hour_band, in_window, local, minutes_of_day, naive_utc, parse_hhmm

LIVE_HORIZON_MIN = 25
HEADWAY_MULT = {GOOD: 1.0, MINOR: 1.4, SEVERE: 3.0, PART_SUSPENDED: 2.0}
RIDE_MULT = {GOOD: 1.0, MINOR: 1.15, SEVERE: 1.6, PART_SUSPENDED: 1.3}
RIDE_SD = {GOOD: 0.05, MINOR: 0.12, SEVERE: 0.3, PART_SUSPENDED: 0.25}
PREFERENCES = ("balanced", "fastest", "reliable", "least_walking", "fewest_changes")

# ------------------------------------------------------------------- network context
_status_cache: dict[str, tuple[float, dict[str, LineStatus]]] = {}


def current_statuses(provider: Provider, now: datetime, max_age_s: float = 60) -> dict[str, LineStatus]:
    key = f"{provider.name}:{getattr(provider, 'scenario', '')}"
    hit = _status_cache.get(key)
    if hit and time.monotonic() - hit[0] < max_age_s:
        return hit[1]
    try:
        statuses = {s.line_id: s for s in provider.line_statuses(now).items}
    except Exception:
        statuses = hit[1] if hit else {}
    _status_cache[key] = (time.monotonic(), statuses)
    return statuses


def clear_status_cache() -> None:
    _status_cache.clear()


@dataclass
class NetworkContext:
    provider: Provider
    now: datetime
    statuses: dict[str, LineStatus]
    model: CorrectionModel
    feed_fresh: bool = True
    _arrivals: dict[str, list[Arrival] | None] = field(default_factory=dict)

    def arrivals(self, stop_id: str | None) -> list[Arrival] | None:
        if not stop_id:
            return None
        if stop_id not in self._arrivals:
            try:
                self._arrivals[stop_id] = self.provider.arrivals(stop_id, self.now).items
            except Exception:
                self._arrivals[stop_id] = None
        return self._arrivals[stop_id]

    def category(self, line_id: str | None) -> str:
        st = self.statuses.get(line_id or "")
        return st.category if st else GOOD

    def leg_category(self, leg) -> str:
        """Status for the stretch of line this leg actually uses."""
        st = self.statuses.get(leg.line_id or "")
        return st.category_for(leg.stop_ids) if st else GOOD


# ------------------------------------------------------------------- journey forecast
@dataclass
class LegForecast:
    mode: str
    line_id: str | None
    line_name: str | None
    from_name: str
    to_name: str
    direction: str | None
    wait_min: float
    ride_min: float
    sd_min: float
    live: bool
    category: str
    next_departures_min: list[float] = field(default_factory=list)


@dataclass
class JourneyForecast:
    journey: Journey
    depart_at: datetime
    p10: float
    p50: float
    p90: float
    feasible: bool
    confidence: str
    legs: list[LegForecast]
    on_time_chance: float
    disruptions: list[dict]
    crowding: dict
    live_data: bool
    model_support: int = 0
    reliability: dict | None = None
    score: float = 0.0

    @property
    def signature(self) -> str:
        return self.journey.signature

    @property
    def arrive_p50(self) -> datetime:
        return self.depart_at + timedelta(minutes=self.p50)


TERMINUS_TURNAROUND_S = 150  # a train terminating at the boarding stop departs again after reversing


def _matches_direction(a: Arrival, leg_direction: str | None) -> bool:
    if not leg_direction or a.terminates_here:
        return True
    d = leg_direction.lower()
    return a.direction.lower() in d or d in a.direction.lower() or a.destination.lower() in d


def forecast_journey(j: Journey, ctx: NetworkContext, depart_at: datetime) -> JourneyForecast:
    t = 0.0  # minutes after depart_at
    var = 0.0
    feasible = True
    legs: list[LegForecast] = []
    disruptions: dict[str, dict] = {}
    live_any, support, partial = False, 0, False
    band = hour_band(depart_at)
    for leg in j.legs:
        if not leg.is_transit:
            t += leg.duration_min
            var += (0.08 * leg.duration_min) ** 2
            legs.append(LegForecast("walking", None, None, leg.from_name, leg.to_name, None, 0, leg.duration_min,
                                    0.08 * leg.duration_min, False, GOOD))
            continue
        cat = ctx.leg_category(leg)
        if cat != GOOD:
            st = ctx.statuses[leg.line_id]
            disruptions[leg.line_id] = {"line_id": leg.line_id, "line_name": st.line_name, "category": cat,
                                        "description": st.description, "reason": st.reason}
        if cat == SUSPENDED:
            feasible = False
        partial |= cat == PART_SUSPENDED
        headway = (leg.headway_min or DEFAULT_HEADWAY_MIN.get(leg.mode, 8.0)) * HEADWAY_MULT.get(cat, 1.0)
        board_at = depart_at + timedelta(minutes=t)
        wait, wait_sd, live, upcoming = headway / 2, headway / math.sqrt(12), False, []
        if (board_at - ctx.now) <= timedelta(minutes=LIVE_HORIZON_MIN) and cat != SUSPENDED:
            arr = ctx.arrivals(leg.from_stop_id)
            if arr:
                cands = []
                for a in arr:
                    if a.line_id != leg.line_id or not _matches_direction(a, leg.direction):
                        continue
                    p = ctx.model.predict(a.line_id, a.stop_id, a.time_to_station_s, band, cat != GOOD)
                    when = aware(a.expected_arrival) + timedelta(seconds=p["bias_s"])
                    if a.terminates_here:
                        when += timedelta(seconds=TERMINUS_TURNAROUND_S)
                    cands.append((when, p))
                cands.sort(key=lambda c: c[0])
                upcoming = [round((w - board_at).total_seconds() / 60, 1) for w, _ in cands
                            if w >= board_at][:3]
                for when, p in cands:
                    if when >= board_at + timedelta(seconds=20):
                        wait = (when - board_at).total_seconds() / 60
                        wait_sd = max(0.3, (p["q90_s"] - p["q10_s"]) / 2.56 / 60)
                        live, support = True, max(support, p["support"])
                        break
        live_any |= live
        ride = leg.duration_min * RIDE_MULT.get(cat, 1.0)
        ride_sd = ride * RIDE_SD.get(cat, 0.05)
        if cat == PART_SUSPENDED:
            ride += 8
            ride_sd += 6
        t += wait + ride
        var += wait_sd ** 2 + ride_sd ** 2
        legs.append(LegForecast(leg.mode, leg.line_id, leg.line_name, leg.from_name, leg.to_name, leg.direction,
                                round(wait, 1), round(ride, 1), round(math.sqrt(wait_sd ** 2 + ride_sd ** 2), 2),
                                live, cat, upcoming))
    sd = math.sqrt(var)
    p50 = t
    p10, p90 = max(p50 - 1.28 * sd, p50 * 0.85), p50 + 1.28 * sd
    nominal = j.duration_min
    on_time = 0.5 * (1 + math.erf(((nominal + 5) - p50) / (max(sd, 0.5) * math.sqrt(2))))

    conf = "high" if sd <= 3 else "medium" if sd <= 6 else "low"
    if not ctx.feed_fresh or partial:
        conf = {"high": "medium", "medium": "low", "low": "low"}[conf]
    if j.transit_legs and not live_any and (depart_at - ctx.now) <= timedelta(minutes=LIVE_HORIZON_MIN):
        conf = {"high": "medium", "medium": "medium", "low": "low"}[conf]

    return JourneyForecast(
        journey=j, depart_at=depart_at, p10=round(p10, 1), p50=round(p50, 1), p90=round(p90, 1), feasible=feasible,
        confidence=conf if feasible else "low", legs=legs, on_time_chance=round(on_time, 2) if feasible else 0.0,
        disruptions=list(disruptions.values()), crowding=crowding_estimate(j, ctx, depart_at), live_data=live_any,
        model_support=support,
    )


CROWD_LEVELS = ["quiet", "typical", "busy", "busier", "very_busy"]
STATION_BASIS = ("TfL station crowding data for {station} ({when}). This is how busy the station is, "
                 "not a measure of train occupancy.")


def _bump(level: str, by: int) -> str:
    return CROWD_LEVELS[max(0, min(len(CROWD_LEVELS) - 1, CROWD_LEVELS.index(level) + by))]


def crowding_estimate(j: Journey, ctx: NetworkContext, depart_at: datetime) -> dict:
    """Evidence-led only. Prefer TfL's measured station busyness at the boarding station; fall back to
    time of day + disruption. Never claims measured train occupancy."""
    if not j.transit_legs:
        return {"level": "n/a", "label": "No public transport", "basis": None}
    band = hour_band(depart_at)
    peak = band in ("am_peak", "pm_peak")
    cats = [ctx.leg_category(l) for l in j.transit_legs]
    disrupted_peak = peak and any(c in (SEVERE, PART_SUSPENDED) for c in cats)

    first = j.transit_legs[0]
    walk_before = sum(l.duration_min for l in j.legs[: j.legs.index(first)])
    board_at = depart_at + timedelta(minutes=walk_before)
    station = None
    lookup = getattr(ctx.provider, "station_crowding", None)
    if lookup:
        try:
            station = lookup(first.from_stop_id, board_at, live=(board_at - ctx.now) <= timedelta(minutes=20))
        except Exception:
            station = None
    if station:
        r = station["ratio"]
        level = "busy" if r >= 0.6 else "typical" if r >= 0.3 else "quiet"
        label = {"busy": f"Busy at {first.from_name}" if r < 0.85 else f"Peak time at {first.from_name}",
                 "typical": f"Typical for {first.from_name}", "quiet": f"Quiet at {first.from_name}"}[level]
        when = f"typical for a {station['day']} at {station['band']}"
        lv = station.get("live_vs_typical")
        if lv is not None:
            when = f"live reading, {int(round(lv * 100))}% of usual for now"
            if lv >= 1.3:
                level, label = _bump(level, 1), "Busier than usual right now"
            elif lv <= 0.7:
                level, label = _bump(level, -1), "Quieter than usual right now"
        if disrupted_peak:
            level, label = "very_busy", "Likely very busy (disruption)"
        return {"level": level, "label": label, "basis": STATION_BASIS.format(station=first.from_name, when=when)}

    rail = [l for l in j.transit_legs if l.mode != "bus"]
    if disrupted_peak:
        level, label = "very_busy", "Likely very busy"
    elif peak and rail and any(st.category in (SEVERE, PART_SUSPENDED, SUSPENDED)
                               and not any(sec.stops for sec in st.sections)  # local problems don't spill over
                               for st in ctx.statuses.values()):
        # A nearby line is badly disrupted: displaced passengers spill onto the alternatives.
        level, label = "busier", "Likely busier than usual"
    elif peak and rail:
        level, label = "busy", "Usually busy at this time"
    else:
        level, label = "typical", "Typical for this time"
    return {"level": level, "label": label,
            "basis": "Estimate from time of day and live disruption — not measured train occupancy."}


# ------------------------------------------------------------------- personal baseline
def route_key(signature: str | None) -> str:
    """Loose identity: ordered mode:line without boarding stop ids (stop ids vary by platform)."""
    if not signature:
        return ""
    return ">".join(p.split("@")[0] for p in signature.split(">"))


def personal_baseline(s: Session, commute: Commute, now: datetime) -> dict:
    since = naive_utc(now - timedelta(days=90))
    trips = s.scalars(select(Trip).where(Trip.commute_id == commute.id, Trip.duration_min.is_not(None),
                                         Trip.started_at >= since)).all()
    weekend = local(now).weekday() >= 5
    ws, we = parse_hhmm(commute.window_start) - 90, parse_hhmm(commute.window_end) + 90
    durations = [t.duration_min for t in trips
                 if (local(aware(t.started_at)).weekday() >= 5) == weekend
                 and ws <= minutes_of_day(aware(t.started_at)) <= we
                 and (not commute.usual_signature or route_key(t.signature) == route_key(commute.usual_signature))]
    if len(durations) >= 3:
        qs = statistics.quantiles(durations, n=10) if len(durations) >= 4 else [min(durations)] * 9
        return {"p50": round(statistics.median(durations), 1), "p80": round(qs[7], 1), "n": len(durations),
                "basis": "personal", "label": f"Your last {len(durations)} trips"}
    if commute.usual_nominal_min:
        return {"p50": round(commute.usual_nominal_min, 1), "p80": round(commute.usual_nominal_min + 4, 1), "n": 0,
                "basis": "network", "label": "Typical journey time (learning your routine)"}
    return {"p50": None, "p80": None, "n": 0, "basis": "none", "label": "No baseline yet"}


def historical_reliability(s: Session, commute: Commute, signature: str, baseline_p50: float | None) -> dict | None:
    trips = s.scalars(select(Trip).where(Trip.commute_id == commute.id, Trip.duration_min.is_not(None))).all()
    durs = [t.duration_min for t in trips if route_key(t.signature) == route_key(signature)]
    if len(durs) < 5:
        return None
    ref = statistics.median(durs) if baseline_p50 is None else baseline_p50
    return {"pct": round(sum(d <= ref + 5 for d in durs) / len(durs), 2), "n": len(durs),
            "label": f"On time on {sum(d <= ref + 5 for d in durs)} of your {len(durs)} trips"}


# ------------------------------------------------------------------------- ranking
def score(f: JourneyForecast, preference: str) -> float:
    if not f.feasible:
        return math.inf
    spread = f.p90 - f.p50
    ch, walk = f.journey.changes, f.journey.walking_min
    return {
        "fastest": f.p50 + 0.1 * spread,
        "reliable": f.p50 + 1.2 * spread + 2 * ch,
        "least_walking": f.p50 + 0.3 * spread + 1.0 * walk,
        "fewest_changes": f.p50 + 0.3 * spread + 8 * ch,
    }.get(preference, f.p50 + 0.5 * spread + 1.5 * ch + 0.2 * walk)


def rank(forecasts: list[JourneyForecast], preference: str) -> list[JourneyForecast]:
    for f in forecasts:
        f.score = score(f, preference)
    return sorted(forecasts, key=lambda f: (f.score, f.p50))


# --------------------------------------------------------------------- evaluation
def default_depart_at(commute: Commute, now: datetime) -> datetime:
    m = minutes_of_day(now)
    start = parse_hhmm(commute.window_start)
    if m < start - 1:
        loc = local(now)
        return (loc.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)).astimezone(now.tzinfo)
    return now


def is_active_window(commute: Commute, now: datetime, lead_min: int = 45) -> bool:
    if local(now).weekday() not in (commute.days or []):
        return False
    m = minutes_of_day(now)
    return parse_hhmm(commute.window_start) - lead_min <= m <= parse_hhmm(commute.window_end)


@dataclass
class CommuteEvaluation:
    commute: Commute
    depart_at: datetime
    baseline: dict
    usual: JourneyForecast | None
    options: list[JourneyForecast]
    recommended: JourneyForecast | None
    status: str  # normal | watch | slower | disrupted | unknown
    delta_min: float | None
    gain_min: float | None
    headline: str
    detail: str
    preference: str


def _fmt_min(x: float) -> str:
    n = int(round(x))
    return f"{n} minute{'s' if n != 1 else ''}"


def _disruption_sentence(f: JourneyForecast | None, statuses: dict[str, LineStatus], usual_sig: str | None) -> str:
    items = f.disruptions if f else []
    if not items and usual_sig:
        for part in route_key(usual_sig).split(">"):
            lid = part.split(":")[-1]
            st = statuses.get(lid)
            if st and st.category != GOOD:
                items.append({"line_name": st.line_name, "description": st.description, "reason": st.reason})
    if not items:
        return ""
    d = items[0]
    return d["reason"] or f"{d['line_name']}: {d['description'].lower()}."


def evaluate_commute(s: Session, provider: Provider, commute: Commute, now: datetime,
                     depart_at: datetime | None = None, preference: str | None = None,
                     feed_fresh: bool = True) -> CommuteEvaluation:
    preference = preference or commute.preference or "balanced"
    depart_at = depart_at or default_depart_at(commute, now)
    statuses = current_statuses(provider, now)
    ctx = NetworkContext(provider, now, statuses, active_model(s), feed_fresh)
    o, d = commute.origin, commute.dest
    try:
        journeys = provider.journeys((o.lat, o.lon), (d.lat, d.lon), depart_at)
    except Exception:
        journeys = []
    forecasts = [forecast_journey(j, ctx, depart_at) for j in journeys]
    watch_stops(s, {l.from_stop_id: l.from_name for j in journeys for l in j.transit_legs if l.from_stop_id}, now)

    # Learn the usual route if we don't know it yet: most-travelled, else nominally fastest feasible option.
    if not commute.usual_signature and forecasts:
        sigs = Counter(t.signature for t in s.scalars(select(Trip).where(Trip.commute_id == commute.id)) if t.signature)
        if sigs and sigs.most_common(1)[0][1] >= 2:
            sig = sigs.most_common(1)[0][0]
            match = next((f for f in forecasts if route_key(f.signature) == route_key(sig)), None)
        else:
            feas = [f for f in forecasts if f.feasible and f.journey.transit_legs] or forecasts
            match = min(feas, key=lambda f: f.journey.duration_min)
        if match:
            set_usual(commute, match.journey)
    usual = next((f for f in forecasts if route_key(f.signature) == route_key(commute.usual_signature)), None)
    baseline = personal_baseline(s, commute, now)
    for f in forecasts:
        f.reliability = historical_reliability(s, commute, f.signature, baseline["p50"])

    ranked = rank(forecasts, preference)
    feasible = [f for f in ranked if f.feasible]
    base = baseline["p50"]
    delta = round(usual.p50 - base, 1) if usual and usual.feasible and base else None

    user: User = commute.user
    threshold, min_gain = user.alert_threshold_min, user.min_gain_min
    best = feasible[0] if feasible else None
    recommended, gain = usual if usual and usual.feasible else best, None
    if best and usual and usual.feasible and best is not usual:
        g = usual.p50 - best.p50
        reliability_win = preference == "reliable" and usual.p90 - best.p90 >= min_gain
        if g >= min_gain or reliability_win:
            recommended, gain = best, round(g, 1)
    elif best and (not usual or not usual.feasible):
        recommended = best
        gain = round(usual.p50 - best.p50, 1) if usual else None

    reason = _disruption_sentence(usual, statuses, commute.usual_signature)
    arrive = lambda f: local(f.arrive_p50).strftime("%H:%M")  # noqa: E731
    if not forecasts:
        status, headline, detail = "unknown", "Live journey data is unavailable", "We'll keep trying. Check back shortly."
    elif usual is None or not usual.feasible:
        status = "disrupted"
        headline = "Your usual route isn't running"
        alt = (f" Taking the {recommended.journey.summary} gets you there around {arrive(recommended)}."
               if recommended else "")
        detail = (reason + alt).strip() or "Your usual route isn't in today's options."
    elif delta is not None and delta >= threshold:
        status = "slower"
        headline = f"Your usual commute is {_fmt_min(delta)} slower today"
        if recommended is not usual and gain:
            detail = (f"{reason} Taking the {recommended.journey.summary} is forecast to get you there "
                      f"{_fmt_min(gain)} sooner.").strip()
        else:
            detail = (f"{reason} No faster alternative right now — leave about {_fmt_min(delta)} earlier.").strip()
    elif usual.disruptions:
        status = "watch"
        headline = "Your usual route has some disruption"
        detail = f"{reason} Forecast impact is small — arrive around {arrive(usual)}."
    else:
        status = "normal"
        headline = "Your usual route looks normal"
        detail = f"Leave {'now' if depart_at <= now + timedelta(minutes=1) else 'at ' + local(depart_at).strftime('%H:%M')} to arrive around {arrive(usual)}."
        if recommended is not usual and gain:
            status = "normal"
            detail += f" The {recommended.journey.summary} is {_fmt_min(gain)} quicker today."
    return CommuteEvaluation(commute, depart_at, baseline, usual, ranked, recommended, status, delta, gain,
                             headline, detail, preference)


def set_usual(commute: Commute, j: Journey) -> None:
    commute.usual_signature = j.signature
    commute.usual_summary = j.summary
    commute.usual_nominal_min = j.duration_min


# ------------------------------------------------------------------------- alerts
def maybe_alert(s: Session, ev: CommuteEvaluation, now: datetime, force: bool = False) -> Alert | None:
    """force=True skips the time-window, quiet-hours and cooldown checks (used by the demo 'check now' action)."""
    c, u = ev.commute, ev.commute.user
    if not force:
        if not c.alerts_enabled or u.monitoring_paused or not is_active_window(c, now):
            return None
        if in_window(minutes_of_day(now), parse_hhmm(u.quiet_start), parse_hhmm(u.quiet_end)):
            return None
    rec = ev.recommended
    kind = None
    if ev.status == "disrupted" and rec:
        kind = "usual_unavailable"
    elif ev.status == "slower" and rec is not None and rec is not ev.usual and (ev.gain_min or 0) >= u.min_gain_min:
        if rec.confidence != "low":  # don't spend user trust on shaky recommendations
            kind = "better_route"
    elif ev.status == "slower" and (ev.delta_min or 0) >= u.alert_threshold_min * 1.5:
        kind = "leave_earlier"
    if not kind:
        return None

    day_start = naive_utc(local(now).replace(hour=0, minute=0, second=0, microsecond=0))
    prior = s.scalars(select(Alert).where(Alert.commute_id == c.id, Alert.created_at >= day_start)
                      .order_by(Alert.created_at.desc())).first()
    rec_sig = rec.signature if rec else None
    if not force and prior and prior.kind == kind and prior.recommended_signature == rec_sig and \
            abs((prior.delta_min or 0) - (ev.delta_min or 0)) < 10:
        return None  # nothing materially new since the last alert

    title = ev.headline.upper() if kind != "usual_unavailable" else "YOUR USUAL ROUTE ISN'T RUNNING"
    alert = Alert(user_id=u.id, commute_id=c.id, kind=kind, title=ev.headline, body=ev.detail,
                  confidence=rec.confidence if rec else "low", delta_min=ev.delta_min, gain_min=ev.gain_min,
                  recommended_signature=rec_sig,
                  data={"commute_name": c.name, "recommended_summary": rec.journey.summary if rec else None,
                        "arrive_p50": rec.arrive_p50.isoformat() if rec else None, "push_title": title})
    s.add(alert)
    s.flush()
    return alert
