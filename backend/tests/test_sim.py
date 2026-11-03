from datetime import timedelta

from conftest import HOME, MORNING, WORK
from paxen.providers.sim import SimProvider


def test_normal_day_offers_multimodal_options():
    js = SimProvider("normal").journeys(HOME, WORK, MORNING)
    summaries = [j.summary for j in js]
    assert summaries[0] == "Victoria"
    assert any("Central" in s for s in summaries)
    assert any(j.transit_legs and all(l.mode == "bus" for l in j.transit_legs) for j in js)


def test_suspended_line_is_not_offered():
    js = SimProvider("victoria-suspended").journeys(HOME, WORK, MORNING)
    assert all("victoria" not in j.signature for j in js)


def test_vehicle_ids_are_stable_across_polls():
    p = SimProvider("normal")
    a1 = {a.vehicle_id for a in p.arrivals("walthamstow-central", MORNING).items}
    a2 = {a.vehicle_id for a in p.arrivals("walthamstow-central", MORNING + timedelta(seconds=30)).items}
    assert len(a1 & a2) >= len(a1) - 2


def test_provider_underestimates_long_waits():
    """The sim's countdown is biased: there is something for the correction model to learn."""
    p = SimProvider("normal")
    errs = []
    for a in p.arrivals("walthamstow-central", MORNING).items:
        if a.line_id == "victoria" and a.time_to_station_s > 600:
            truth = p.true_arrival_time("victoria", "walthamstow-central", a.vehicle_id, MORNING)
            errs.append((truth - a.expected_arrival).total_seconds())
    assert errs and sum(errs) / len(errs) > 30
