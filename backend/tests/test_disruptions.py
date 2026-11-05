"""How long disruptions last (TfL status history) and how the forecast uses it."""
from datetime import datetime, timedelta, timezone

import pytest

from paxen import disruptions
from paxen.db import LineStatusSnapshot
from paxen.domain import GOOD, Journey, Leg, LineStatus
from paxen.engine import NetworkContext, disruption_starts, forecast_journey
from paxen.forecast import CorrectionModel

needs_data = pytest.mark.skipif(disruptions.get() is None, reason="clearance data not built")
NOW = datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc)


def test_causes_read_from_message_text():
    assert disruptions.cause_of("Severe delays due to a signal failure at Baker Street.") == "signal"
    assert disruptions.cause_of("Minor delays due to an earlier signal failure.") == "earlier"
    assert disruptions.cause_of("No service while we respond to a customer incident.") == "customer"
    assert disruptions.cause_of("Minor delays due to train cancellations.") == "staff_cancellations"
    assert disruptions.cause_of(None) == "other"


def test_observations_split_incidents_and_skip_planned_closures():
    t = datetime(2026, 1, 5, 8, 0)
    rows = [{"line": "Central", "start": t, "end": t + timedelta(minutes=20), "status": "Severe Delays",
             "text": "signal failure"},
            {"line": "Central", "start": t + timedelta(minutes=20), "end": t + timedelta(minutes=50),
             "status": "Minor Delays", "text": "earlier signal failure"},
            {"line": "Central", "start": t + timedelta(hours=3), "end": t + timedelta(hours=9),
             "status": "Part Closure", "text": "planned engineering work"}]
    obs = disruptions.observations(rows)
    assert len(obs) == 2  # the planned closure isn't an incident
    assert obs[0]["remaining"] == 50 and obs[1]["elapsed"] == 20 and obs[1]["remaining"] == 30


@needs_data
def test_chance_still_on_falls_with_time_and_planned_work_is_certain():
    ps = [disruptions.p_ongoing("severe", "Severe Delays", "signal failure", 5, h) for h in (15, 60, 240, 1080)]
    assert ps == sorted(ps, reverse=True) and ps[0] > 0.8 and ps[-1] < 0.15
    assert disruptions.p_ongoing("part_suspended", "Part Closure", "engineering works", 5, 600) == 1.0
    assert disruptions.p_ongoing("minor", "Minor Delays", "x", None, 0) == 1.0


class Tfl:
    name = "tfl"

    def arrivals(self, stop_id, now):
        raise RuntimeError("no live data")


def journey(depart):
    leg = Leg("tube", 20.0, "A", "B", depart + timedelta(minutes=2), depart + timedelta(minutes=22),
              line_id="central", line_name="Central", from_stop_id="x", stop_ids=[])
    return Journey([leg], 22.0, depart, depart + timedelta(minutes=22), "tfl")


@needs_data
def test_a_disruption_now_fades_out_of_tomorrows_forecast():
    st = {"central": LineStatus("central", "Central", "tube", "suspended", "Suspended",
                                "Suspended due to a signal failure.")}
    ctx = NetworkContext(Tfl(), NOW, st, CorrectionModel(), disrupted_since={"central": NOW - timedelta(minutes=5)})
    soon = forecast_journey(journey(NOW), ctx, NOW)
    tomorrow = forecast_journey(journey(NOW + timedelta(hours=18)), ctx, NOW + timedelta(hours=18))
    assert not soon.feasible  # suspended now: no way through
    assert tomorrow.feasible and tomorrow.p50 < 30  # almost certainly back by tomorrow morning
    assert tomorrow.disruptions[0]["chance_still_on"] < 0.2


def test_simulated_disruptions_stay_certain():
    class Sim(Tfl):
        name = "sim"

    st = {"central": LineStatus("central", "Central", "tube", "severe", "Severe Delays", "signal failure")}
    ctx = NetworkContext(Sim(), NOW, st, CorrectionModel())
    assert ctx.chance_still_on("central", "severe", NOW + timedelta(hours=18)) == 1.0
    assert ctx.chance_still_on("central", GOOD, NOW) == 0.0


def test_disruption_start_comes_from_status_snapshots(session):
    for minutes_ago, cat in ((40, "good"), (30, "severe"), (20, "minor"), (10, "severe")):
        session.add(LineStatusSnapshot(source="tfl", polled_at=(NOW - timedelta(minutes=minutes_ago)).replace(tzinfo=None),
                                       line_id="central", line_name="Central", mode="tube", category=cat,
                                       description="", reason=None))
    session.commit()
    st = {"central": LineStatus("central", "Central", "tube", "severe", "Severe Delays")}
    assert disruption_starts(session, "tfl", st, NOW)["central"] == NOW - timedelta(minutes=30)


@needs_data
def test_new_disruption_risk_differs_by_line_and_hour():
    from datetime import timezone as tz

    peak = (datetime(2026, 11, 6, 8, 0, tzinfo=tz.utc), datetime(2026, 11, 6, 8, 40, tzinfo=tz.utc))
    late = (datetime(2026, 11, 5, 22, 0, tzinfo=tz.utc), datetime(2026, 11, 5, 22, 40, tzinfo=tz.utc))
    assert disruptions.onset_risk("victoria", *peak) < disruptions.onset_risk("district", *peak)
    assert disruptions.onset_risk("district", *late) < disruptions.onset_risk("district", *peak)
    assert disruptions.onset_risk("elizabeth", *peak) is None  # not in the Underground history


@needs_data
def test_reliable_preference_counts_disruption_risk():
    from paxen.engine import rank

    ctx = NetworkContext(Tfl(), NOW, {}, CorrectionModel())
    a, b = forecast_journey(journey(NOW), ctx, NOW), forecast_journey(journey(NOW), ctx, NOW)
    a.disruption_risk, b.disruption_risk = 0.15, 0.03
    assert rank([a, b], "reliable")[0] is b
    assert forecast_journey(journey(NOW), ctx, NOW).disruption_risk > 0  # central line, afternoon
