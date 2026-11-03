from datetime import timedelta

from conftest import HOME, MORNING, WORK
from paxen.db import Alert, Commute, Place, Trip, User
from paxen.engine import clear_status_cache, evaluate_commute, maybe_alert, personal_baseline
from paxen.providers.sim import SimProvider


def make_commute(s, **kw):
    u = User(token_hash="x" * 64, **kw)
    s.add(u)
    s.flush()
    h = Place(user_id=u.id, label="home", name="Home", lat=HOME[0], lon=HOME[1])
    w = Place(user_id=u.id, label="work", name="Work", lat=WORK[0], lon=WORK[1])
    s.add_all([h, w])
    s.flush()
    c = Commute(user_id=u.id, name="To work", origin_id=h.id, dest_id=w.id, window_start="08:00", window_end="08:45")
    s.add(c)
    s.commit()
    return c


def ev(s, c, scenario, now=MORNING, **kw):
    clear_status_cache()
    return evaluate_commute(s, SimProvider(scenario), c, now, depart_at=now, **kw)


def test_learns_usual_route_and_reports_normal(session):
    c = make_commute(session)
    e = ev(session, c, "normal")
    assert c.usual_summary == "Victoria"
    assert e.status == "normal" and e.recommended is e.usual
    assert e.baseline["basis"] == "network"
    assert e.usual.confidence in ("high", "medium") and e.usual.live_data


def test_severe_delays_trigger_better_route(session):
    c = make_commute(session)
    ev(session, c, "normal")  # learn usual = Victoria
    e = ev(session, c, "victoria-severe")
    assert e.status == "slower" and e.delta_min >= 8
    assert e.recommended is not e.usual and e.gain_min >= 5
    assert "slower today" in e.headline and "sooner" in e.detail
    assert e.usual.disruptions[0]["line_id"] == "victoria"
    assert e.usual.p90 - e.usual.p50 > 3  # disruption widens uncertainty


def test_suspension_means_usual_unavailable(session):
    c = make_commute(session)
    ev(session, c, "normal")
    e = ev(session, c, "victoria-suspended")
    assert e.status == "disrupted" and e.recommended and "victoria" not in e.recommended.signature


def test_personal_baseline_from_trips(session):
    c = make_commute(session)
    ev(session, c, "normal")
    for i, d in enumerate([30, 32, 31, 35, 29]):
        start = (MORNING - timedelta(days=7 * (i + 1))).replace(tzinfo=None)
        session.add(Trip(user_id=c.user_id, commute_id=c.id, signature=c.usual_signature, started_at=start,
                         arrived_at=start + timedelta(minutes=d), duration_min=d))
    session.commit()
    b = personal_baseline(session, c, MORNING)
    assert b["basis"] == "personal" and b["p50"] == 31 and b["n"] == 5


def test_reliable_preference_changes_ranking(session):
    c = make_commute(session)
    ev(session, c, "normal")
    fast = ev(session, c, "mixed", preference="fastest").options
    reliable = ev(session, c, "mixed", preference="reliable").options
    assert [f.signature for f in fast] != [f.signature for f in reliable] or len(fast) < 2


def test_alert_rules(session):
    c = make_commute(session)
    ev(session, c, "normal")
    e = ev(session, c, "victoria-severe")
    a = maybe_alert(session, e, MORNING)
    assert a and a.kind == "better_route" and a.confidence in ("high", "medium")
    # cooldown: same situation -> no second alert
    assert maybe_alert(session, ev(session, c, "victoria-severe"), MORNING + timedelta(minutes=2)) is None
    # outside the window: nothing
    late = MORNING.replace(hour=11)
    assert maybe_alert(session, ev(session, c, "victoria-severe", now=late), late) is None
    # paused monitoring: nothing
    c.user.monitoring_paused = True
    session.query(Alert).delete()
    assert maybe_alert(session, ev(session, c, "victoria-severe"), MORNING) is None


def test_no_alert_on_normal_day_or_in_quiet_hours(session):
    c = make_commute(session, quiet_start="07:00", quiet_end="09:00")
    ev(session, c, "normal")
    assert maybe_alert(session, ev(session, c, "normal"), MORNING) is None
    assert maybe_alert(session, ev(session, c, "victoria-severe"), MORNING) is None  # quiet hours


def test_crowding_uses_station_data_when_available(session):
    from paxen.engine import NetworkContext, crowding_estimate
    from paxen.forecast import CorrectionModel

    class WithCrowding(SimProvider):
        def __init__(self, reading):
            super().__init__("normal")
            self.reading = reading

        def station_crowding(self, stop_id, when, live=False):
            return dict(self.reading)

    def label(reading, scenario="normal"):
        p = WithCrowding(reading)
        p.scenario = scenario
        clear_status_cache()
        j = next(j for j in p.journeys(HOME, WORK, MORNING) if j.summary == "Victoria")
        ctx = NetworkContext(p, MORNING, {s.line_id: s for s in p.line_statuses(MORNING).items}, CorrectionModel())
        return crowding_estimate(j, ctx, MORNING)

    peak = {"pct": 0.49, "peak": 0.49, "ratio": 1.0, "band": "08:30", "day": "Tue"}
    c = label(peak)
    assert c["level"] == "busy" and "Walthamstow Central" in c["label"] and "not a measure of train" in c["basis"]
    assert label({**peak, "ratio": 0.2})["level"] == "quiet"
    assert label({**peak, "ratio": 0.4, "live_vs_typical": 1.5})["label"] == "Busier than usual right now"
    assert label(peak, "victoria-severe")["level"] == "very_busy"  # disruption overrides
