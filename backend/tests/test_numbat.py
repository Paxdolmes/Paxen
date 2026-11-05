"""TfL NUMBAT (historical typical-day service and demand) and how the forecast and models use it."""
import math
import random
from datetime import datetime, timedelta, timezone

import pytest

from paxen import numbat
from paxen.domain import Journey, Leg
from paxen.engine import (
    MAX_TRANSFER_MIN, NetworkContext, forecast_journey, scheduled_headway, timetable_wait, transfer_min,
)
from paxen.forecast import CorrectionModel, Sample
from paxen.numbat import Numbat, service_slot
from paxen.timeutil import LONDON

REAL = numbat.get()
needs_data = pytest.mark.skipif(REAL is None, reason="NUMBAT data file not built")


def L(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=LONDON)


# ----------------------------------------------------------------------------- service day and slots
def test_service_day_runs_from_five_am_and_bank_holidays_are_sundays():
    assert service_slot(L(2026, 11, 3, 5, 0)) == ("TWT", 0)
    assert service_slot(L(2026, 11, 3, 8, 30)) == ("TWT", 14)
    assert service_slot(L(2026, 11, 2, 9, 0))[0] == "MON"
    assert service_slot(L(2026, 11, 7, 1, 30)) == ("FRI", 82)  # Saturday 01:30 is Friday night's service
    assert service_slot(L(2026, 11, 9, 4, 59)) == ("SUN", 95)
    assert service_slot(L(2026, 12, 28, 9, 0))[0] == "SUN"  # Boxing Day (substitute) bank holiday


# ----------------------------------------------------------------------------- a small synthetic table
def series(per_qhr: int) -> str:
    return numbat._encode([per_qhr] * (numbat.SLOTS * len(numbat.DAY_TYPES)), "B")


def demand(per_qhr: int) -> str:
    return numbat._encode([per_qhr] * (numbat.SLOTS * len(numbat.DAY_TYPES)), "H")


def tiny() -> Numbat:
    """A trunk A-B-C with a branch B-D (westbound), and the reverse (eastbound)."""
    links = {
        "A>B": ["WB", series(6), demand(1200)], "B>C": ["WB", series(4), demand(800)],
        "B>D": ["WB", series(2), demand(200)],
        "C>B": ["EB", series(4), demand(600)], "D>B": ["EB", series(2), demand(100)],
        "B>A": ["EB", series(6), demand(900)],
    }
    return Numbat({
        "meta": {}, "lines": {"district": "DIS"},
        "stations": {"DIS": {"nA": "A", "nB": "B", "nC": "C", "nD": "D"}},
        "links": {"DIS": links},
        "platforms": {"DIS": {"B|WB": [demand(300), demand(60)], "B|EB": [demand(30), demand(90)]}},
        "headings": {"DIS": {"A|WB": 270.0, "B|WB": 265.0, "B|EB": 85.0, "C|EB": 90.0, "D|EB": 80.0}},
    })


WHEN = L(2026, 11, 3, 12, 0)


def test_leg_headway_is_set_by_the_least_served_link():
    nb = tiny()
    assert nb.headway_min("district", ["nA", "nB", "nC"], WHEN) == pytest.approx(60 / 16)
    assert nb.headway_min("district", ["nA", "nB", "nD"], WHEN) == pytest.approx(60 / 8)  # the branch's own service
    assert nb.headway_min("district", ["nA", "nC"], WHEN) == pytest.approx(60 / 16)  # fast train: path filled in
    assert nb.headway_min("district", ["nA", "nX", "nB"], WHEN) == pytest.approx(60 / 24)  # unknown stop skipped
    assert nb.headway_min("district", ["nA"], WHEN) is None
    assert nb.headway_min("central", ["nA", "nB"], WHEN) is None
    assert nb.headway_min("district", ["nC", "nD"], WHEN) is None  # no train runs C to D


def test_stop_context_uses_the_platform_direction():
    nb = tiny()
    west = nb.stop_context("district", "nB", "westbound", WHEN)
    # westbound at B: 6/qhr arrive from A, 4+2/qhr leave: 24 trains/hour
    assert west["sched_headway_s"] == pytest.approx(150.0) and west["directional"]
    assert west["activity_per_train"] == pytest.approx((300 + 60) * 4 / 24)
    assert west["load_per_train"] == pytest.approx(1200 / 6)
    both = nb.stop_context("district", "nB", None, WHEN)
    assert not both["directional"] and both["sched_headway_s"] == pytest.approx(150.0)
    assert nb.stop_context("district", "nZ", None, WHEN) is None


def test_bound_matched_by_bearing_when_labels_differ():
    nb = tiny()
    nb.headings[("DIS", "B")] = {"IR": 268.0, "OR": 88.0}  # e.g. the Circle's inner/outer rail
    assert nb.direction("DIS", "B", "westbound") == "IR"
    assert nb.direction("DIS", "B", "eastbound") == "OR"
    assert nb.direction("DIS", "B", "northbound") is None  # neither runs north here
    assert nb.direction("DIS", "B", None) is None


# ----------------------------------------------------------------------------- the real NUMBAT 2025 table
@needs_data
def test_real_table_knows_frequent_and_infrequent_services():
    vic = ["940GZZLUWWL", "940GZZLUBLR", "940GZZLUTMH", "940GZZLUSVS", "940GZZLUFPK", "940GZZLUHAI", "940GZZLUKSX",
           "940GZZLUEUS", "940GZZLUWRR", "940GZZLUOXC"]
    assert REAL.headway_min("victoria", vic, L(2026, 11, 3, 8, 30)) < 3
    assert REAL.headway_min("metropolitan", ["940GZZLUAMS", "940GZZLUCAL"], L(2026, 11, 3, 8, 30)) >= 10
    assert REAL.headway_min("victoria", vic, L(2026, 11, 7, 1, 30)) == pytest.approx(10)  # Night Tube, Friday night
    assert REAL.headway_min("victoria", vic, L(2026, 11, 4, 1, 30)) is None  # no service at 01:30 on a Wednesday
    assert REAL.headway_min("weaver", ["910GWLTWCEN", "910GSTJMSST"], L(2026, 11, 3, 10, 0)) == pytest.approx(15)
    c = REAL.stop_context("victoria", "940GZZLUOXC", "southbound", L(2026, 11, 3, 8, 30))
    assert c["directional"] and c["sched_headway_s"] < 150 and c["activity_per_train"] > 50


@needs_data
def test_every_tube_stop_is_mapped():
    lines = ["bakerloo", "central", "circle", "district", "hammersmith-city", "jubilee", "northern", "piccadilly",
             "victoria", "waterloo-city"]
    for line in lines:
        key = REAL.key_of(line)
        assert len(REAL.stations[key]) > 1, line
    # the stations whose NUMBAT entries are merged or named differently
    assert REAL.code_of("DIS", "940GZZLUMMT") == REAL.code_of("NOR", "940GZZLUBNK") == "BNKu"  # Bank and Monument
    assert REAL.code_of("DIS", "940GZZLUBNK") is None  # District trains call at Monument, not Bank
    assert REAL.code_of("HAM", "940GZZLUPAC") == REAL.code_of("HAM", "940GZZLUPAH")  # Paddington


# ----------------------------------------------------------------------------- the forecast's waits
def leg(mode="tube", line="metropolitan", dep=None, stops=None, arr=None, headway=None):
    t0 = L(2026, 11, 6, 8, 0)
    return Leg(mode, 30.0, "A", "B", dep or t0, arr or (dep or t0) + timedelta(minutes=30), line_id=line,
               line_name=line, from_stop_id=(stops or ["x"])[0], stop_ids=stops or [], headway_min=headway)


def test_timetable_decides_waits_on_infrequent_services():
    board = L(2026, 11, 6, 8, 0)
    w, sd = timetable_wait(leg(dep=board + timedelta(minutes=4)), board, 15.0, "good")
    assert w == pytest.approx(4.06, abs=0.05) and sd == pytest.approx(1.76, abs=0.05)  # 0.4% chance of missing it
    w, _ = timetable_wait(leg(dep=board - timedelta(minutes=3)), board, 15.0, "good")
    assert w == pytest.approx(11.66, abs=0.05)  # just missed it: the next one is a headway later (2% it's late)
    w, sd = timetable_wait(leg(dep=board + timedelta(seconds=30)), board, 15.0, "good")
    assert 0.5 < w < 15 and sd > 3  # it might go either way
    assert timetable_wait(leg(dep=board + timedelta(minutes=4)), board, 4.0, "good") is None  # frequent: chance
    assert timetable_wait(leg(dep=board + timedelta(minutes=4)), board, 15.0, "minor") is None  # disrupted
    assert timetable_wait(leg("bus", "55", dep=board + timedelta(minutes=4)), board, 15.0, "good") is None
    assert timetable_wait(leg(dep=board + timedelta(minutes=30)), board, 15.0, "good") is None  # not the next one
    rail = leg("national-rail", "chiltern-railways", dep=board + timedelta(minutes=25))
    assert timetable_wait(rail, board, 10.0, "good", headway_known=False)[0] == pytest.approx(25, abs=0.1)
    assert timetable_wait(leg(dep=board + timedelta(minutes=4), headway=15), board, 15.0, "good") is None  # sim


def test_transfer_walk_comes_from_the_planners_connection():
    a = leg(arr=L(2026, 11, 6, 8, 38))
    assert transfer_min(a, leg(dep=L(2026, 11, 6, 8, 49)), 2.6) == pytest.approx(9.7)
    assert transfer_min(a, leg(dep=L(2026, 11, 6, 8, 39)), 2.6) == pytest.approx(1.0)
    assert transfer_min(a, leg(dep=L(2026, 11, 6, 9, 30)), 2.6) == MAX_TRANSFER_MIN
    assert transfer_min(a, leg(dep=L(2026, 11, 6, 8, 30)), 2.6) == 0.0
    walk = Leg("walking", 5.0, "A", "B", L(2026, 11, 6, 8, 0), L(2026, 11, 6, 8, 5))
    assert transfer_min(walk, leg(dep=L(2026, 11, 6, 8, 49)), 2.6) == 0.0  # the planner already walked you there
    assert transfer_min(None, leg(), 2.6) == 0.0


@needs_data
def test_headway_prefers_provider_then_numbat_then_a_flat_guess():
    when = L(2026, 11, 3, 8, 30)
    assert scheduled_headway(leg(headway=6.0), when) == (6.0, "frequency")
    h, src = scheduled_headway(leg(stops=["940GZZLUAMS", "940GZZLUCAL"]), when)
    assert src == "frequency" and h >= 10
    assert scheduled_headway(leg("national-rail", "c2c", stops=["910GA", "910GB"]), when) == (10.0, "typical")


class NoLive:
    name = "tfl"

    def arrivals(self, stop_id, now):
        raise RuntimeError("no live data")


@needs_data
def test_planned_trip_on_an_infrequent_line_is_timed_by_the_timetable():
    now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    depart = L(2026, 11, 6, 8, 0)  # tomorrow morning: no countdown yet
    walk = Leg("walking", 4.0, "Home", "Amersham", depart, depart + timedelta(minutes=4))
    met = Leg("tube", 52.0, "Amersham", "Baker Street", L(2026, 11, 6, 8, 14), L(2026, 11, 6, 9, 6),
              line_id="metropolitan", line_name="Metropolitan", from_stop_id="940GZZLUAMS",
              stop_ids=["940GZZLUAMS", "940GZZLUCAL", "940GZZLUCYD", "940GZZLURKW", "940GZZLUMPK", "940GZZLUHOH",
                        "940GZZLUFYR", "940GZZLUBST"])
    j = Journey([walk, met], 66.0, depart, met.arrival, "tfl")
    f = forecast_journey(j, NetworkContext(NoLive(), now, {}, CorrectionModel()), depart)
    assert f.legs[1].wait_basis == "timetable" and f.legs[1].wait_min == pytest.approx(10.0, abs=0.2)
    assert f.p50 == pytest.approx(66.0, abs=0.5)  # arrives 09:06, as timetabled (it used to say 08:58)


# ----------------------------------------------------------------------------- de-duplicating planner answers
def test_dedupe_keeps_the_first_arrival_per_route():
    from paxen.providers.tfl import dedupe_journeys

    def j(dep_min, dur):
        dep = L(2026, 11, 6, 8, dep_min)
        lg = leg(dep=dep, stops=["940GZZLUAMS", "940GZZLUBST"], arr=dep + timedelta(minutes=dur))
        return Journey([lg], dur, dep, dep + timedelta(minutes=dur), "tfl")

    slow_first, fast_later = j(14, 52), j(25, 47)
    [kept] = dedupe_journeys([fast_later, slow_first])
    assert kept is slow_first  # arrives 09:06, before the faster train's 09:12


# ----------------------------------------------------------------------------- the gbm_numbat candidate
def numbat_samples(days: int, seed: int) -> list[Sample]:
    """Victoria line predictions whose error grows when the gap ahead is long for the time of day."""
    r = random.Random(seed)
    stops = ["940GZZLUOXC", "940GZZLUGPK", "940GZZLUVIC", "940GZZLUKSX", "940GZZLUEUS"]
    out = []
    for d in range(days):
        day = datetime(2026, 11, 2, tzinfo=timezone.utc) + timedelta(days=d)
        for _ in range(300):
            t = day + timedelta(hours=r.uniform(6, 22))
            stop, bound = r.choice(stops), r.choice(["northbound", "southbound"])
            lead = r.uniform(30, 900)
            h = REAL.stop_context("victoria", stop, bound, t + timedelta(seconds=lead))["sched_headway_s"]
            gap = r.uniform(0.3, 3.0) * h
            err = 40 * (gap / h - 1) + r.gauss(0, 10)
            out.append(Sample(t, "victoria", stop, lead, "interpeak", False, err, 1.0, queue_rank=2, gap_s=int(gap),
                              feed_age_s=5.0, bound=bound))
    return out


@needs_data
def test_gbm_numbat_uses_numbat_features_and_round_trips():
    from paxen.models import GBMModel, GBMNumbatModel

    train, test = numbat_samples(3, 1), numbat_samples(1, 2)
    m = GBMNumbatModel.fit(train)
    assert max(m.keep) >= len(GBMModel.CATEGORICAL)  # NUMBAT columns are in use
    preds = m.predict_many(test)
    mae_gbm = sum(abs(x.error_s - p["bias_s"]) for x, p in zip(test, GBMModel.fit(train).predict_many(test)))
    mae_numbat = sum(abs(x.error_s - p["bias_s"]) for x, p in zip(test, preds))
    assert mae_numbat < mae_gbm  # the scaled gap explains what the raw gap can't
    again = GBMNumbatModel.from_params(m.to_params())
    x = test[0]
    served = again.predict(x.line_id, x.stop_id, x.lead_s, x.band, x.disrupted, queue_rank=x.queue_rank,
                           gap_s=x.gap_s, feed_age_s=x.feed_age_s, weekend=x.weekend, bound=x.bound,
                           polled_at=x.polled_at)
    assert served["bias_s"] == pytest.approx(preds[0]["bias_s"], abs=1e-6)  # serving builds the same features


def test_gbm_numbat_falls_back_to_gbm_where_numbat_has_nothing():
    from paxen.models import GBMModel, GBMNumbatModel

    r = random.Random(3)
    samples = [Sample(datetime(2026, 11, 2, 8, tzinfo=timezone.utc) + timedelta(minutes=i), "victoria",
                      f"sim-{r.randint(1, 4)}", r.uniform(30, 900), "am_peak", False, r.gauss(30, 10), 1.0,
                      queue_rank=1, gap_s=120, feed_age_s=3.0) for i in range(400)]
    m = GBMNumbatModel.fit(samples)
    assert max(m.keep) < len(GBMModel.CATEGORICAL)  # unknown stops: the NUMBAT columns are dropped
    assert math.isfinite(m.predict_many(samples[:1])[0]["bias_s"])


@needs_data
def test_protocol_runs_with_the_new_candidate():
    from paxen.evaluate import evaluate
    from paxen.models import GBMNumbatModel, ProviderModel

    rep = evaluate(numbat_samples(10, 4), {"provider": ProviderModel, "gbm_numbat": GBMNumbatModel})
    assert "gbm_numbat" in rep["summary"] and rep["summary"]["gbm_numbat"]["test_days"] == 3
    assert "A2 gbm_numbat candidate (TfL NUMBAT 2025 service and demand)" in rep["rules"]["amendments"]
