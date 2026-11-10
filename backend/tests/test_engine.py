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


def test_alerts_dont_flip_flop_or_pile_up(session):
    c = make_commute(session)
    ev(session, c, "normal")
    t = MORNING - timedelta(minutes=10)  # 08:10
    assert maybe_alert(session, ev(session, c, "victoria-severe", now=t), t)
    # the usual route stops running 5 minutes later: that's worth saying straight away
    t2 = t + timedelta(minutes=5)
    stopped = maybe_alert(session, ev(session, c, "victoria-suspended", now=t2), t2)
    assert stopped and stopped.kind == "usual_unavailable"
    # later it flips back to what an earlier alert already said: not sent again
    t3 = t2 + timedelta(minutes=25)
    again = ev(session, c, "victoria-severe", now=t3)
    session.query(Alert).filter(Alert.kind != "usual_unavailable").update(
        {Alert.kind: "better_route" if again.recommended is not again.usual else "leave_earlier",
         Alert.recommended_signature: again.recommended.signature, Alert.delta_min: again.delta_min})
    assert maybe_alert(session, again, t3) is None


def test_alerts_keep_a_gap_and_a_daily_limit(session):
    from paxen import engine

    c = make_commute(session)
    ev(session, c, "normal")
    t = MORNING - timedelta(minutes=10)
    assert maybe_alert(session, ev(session, c, "victoria-severe", now=t), t)
    session.query(Alert).update({Alert.recommended_signature: "something else"})  # make the next one look new
    soon = t + timedelta(minutes=5)
    assert maybe_alert(session, ev(session, c, "victoria-severe", now=soon), soon) is None  # within 20 minutes
    later = t + timedelta(minutes=21)
    assert maybe_alert(session, ev(session, c, "victoria-severe", now=later), later)
    for _ in range(engine.MAX_ALERTS_PER_DAY):
        session.add(Alert(user_id=c.user_id, commute_id=c.id, kind="leave_earlier", title="x", body="x",
                          confidence="high", created_at=(MORNING - timedelta(hours=1)).replace(tzinfo=None)))
    session.query(Alert).update({Alert.recommended_signature: "another"})
    much_later = t + timedelta(minutes=45)
    assert maybe_alert(session, ev(session, c, "victoria-severe", now=much_later), much_later) is None  # cap


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


def test_model_gets_the_same_disruption_definition_it_was_trained_with(session):
    """Training labels predictions with the line-wide status; serving must too (not the section-aware one)."""
    from paxen.domain import LineStatus, StatusSection
    from paxen.engine import NetworkContext, forecast_journey

    seen = []

    class Spy:
        version = None

        def predict(self, line, stop, lead_s, band, disrupted, **ctx):
            seen.append((disrupted, ctx.get("category")))
            return {"bias_s": 0.0, "q10_s": -30.0, "q90_s": 60.0, "support": 0}

    p = SimProvider("normal")
    j = next(j for j in p.journeys(HOME, WORK, MORNING) if j.summary == "Victoria")
    # Severe delays on the Victoria line, but only at stations this journey never uses
    statuses = {s.line_id: s for s in p.line_statuses(MORNING).items}
    statuses["victoria"] = LineStatus("victoria", "Victoria", "tube", "severe", "Severe delays", None,
                                      sections=[StatusSection("severe", frozenset({"brixton"}))])
    ctx = NetworkContext(p, MORNING, statuses, Spy())
    f = forecast_journey(j, ctx, MORNING)
    assert f.legs[1].category == "good"  # the journey itself is unaffected...
    assert seen and all(d is True and c == "severe" for d, c in seen)  # ...but the model sees what it trained on
