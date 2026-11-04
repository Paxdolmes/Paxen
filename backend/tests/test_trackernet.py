"""Measured Tube arrivals from Trackernet, and their use as ground truth."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from conftest import MORNING
from paxen.db import ObservedArrival, Prediction
from paxen.forecast import load_samples
from paxen.recorder import record_trackernet
from paxen.trackernet import bound_of, norm_name, parse_summary

SUMMARY = b"""<ROOT><Time TimeStamp="2026/11/03 08:20:30" />
<S Code="WAL" N="Walthamstow Central.">
 <P N="Southbound - Platform 1" Code="1" Next="0">
  <T S="220" T="14" D="88" C="-" L="At Platform" DE="Brixton" AT="" DT="08:20:05" />
  <T S="213" T="16" D="88" C="0:30" L="Between Blackhorse Road and Walthamstow Central" DE="Walthamstow Central" DT="08:20:28" />
 </P>
</S>
<S Code="XYZ" N="Nowhere Junction."><P N="Northbound - Platform 2"><T S="999" C="-" L="At Platform" DE="X" DT="08:19:00" /></P></S>
</ROOT>"""


def test_parse_summary_keeps_trains_at_platform_with_measured_time():
    ts, trains = parse_summary(SUMMARY, "V")
    assert ts == datetime(2026, 11, 3, 8, 20, 30, tzinfo=timezone.utc)  # GMT in November
    [a, _] = trains
    assert (a.station_code, a.set_no, a.destination) == ("WAL", "220", "Brixton")
    assert a.seen_since == datetime(2026, 11, 3, 8, 20, 5, tzinfo=timezone.utc)
    assert bound_of(a.platform) == "southbound"


def test_midnight_rollover():
    xml = SUMMARY.replace(b"2026/11/03 08:20:30", b"2026/11/04 00:00:20").replace(b'DT="08:20:05"', b'DT="23:59:50"')
    _, trains = parse_summary(xml, "V")
    assert trains[0].seen_since == datetime(2026, 11, 3, 23, 59, 50, tzinfo=timezone.utc)


def test_station_names_normalise():
    assert norm_name("King's Cross St. Pancras.") == norm_name("King's Cross St. Pancras Underground Station")
    assert norm_name("Highbury & Islington.") == norm_name("Highbury & Islington Underground Station")


class FakeTN:
    def summary(self, code):
        if code != "V":
            return None, [], b"<ROOT/>"
        ts, trains = parse_summary(SUMMARY, "V")
        return ts, trains, SUMMARY

    def station_map(self, code, names):
        return {"WAL": "940GZZLUWWL"}


def test_record_trackernet_measures_once_and_skips_unmapped(session):
    now = datetime(2026, 11, 3, 8, 20, 31, tzinfo=timezone.utc)
    r = record_trackernet(session, FakeTN(), now, source="tfl", archive=False)
    assert r["measured_arrivals"] == 1 and r["unmapped"] == 1
    again = record_trackernet(session, FakeTN(), now + timedelta(seconds=30), source="tfl", archive=False)
    assert again["measured_arrivals"] == 0  # the same arrival isn't recorded twice
    [o] = session.scalars(select(ObservedArrival)).all()
    assert (o.method, o.stop_id, o.vehicle_id, o.direction, o.quality) == (
        "trackernet", "940GZZLUWWL", "220", "southbound", 1.0)


def test_measured_arrival_preferred_and_direction_respected(session):
    t0 = MORNING.replace(tzinfo=None)
    arr = t0 + timedelta(minutes=5)

    def pred(platform, direction="Brixton"):
        p = Prediction(source="tfl", polled_at=t0, stop_id="S", line_id="victoria", mode="tube", vehicle_id="220",
                       direction=direction, expected_arrival=t0 + timedelta(minutes=4), tts_s=240, platform=platform)
        session.add(p)
        return p
    pred("Southbound - Platform 1")
    pred("Northbound - Platform 2", "Walthamstow Central")  # same train id, other direction: must not match
    for method, when, direction, q in [("countdown_inferred", arr + timedelta(seconds=40), "Brixton", 0.6),
                                       ("trackernet", arr, "southbound", 1.0)]:
        session.add(ObservedArrival(source="tfl", stop_id="S", line_id="victoria", vehicle_id="220",
                                    direction=direction, arrived_at=when, earliest=when, latest=when,
                                    method=method, quality=q))
    session.commit()
    samples = load_samples(session, "tfl")
    assert len(samples) == 1 and samples[0].error_s == 60  # measured (5:00) beats inferred (5:40)
    assert len(load_samples(session, "tfl", methods=("countdown_inferred",))) == 1
