"""Measured Overground/Elizabeth line arrivals from National Rail's Darwin feed (paxen/darwin.py)."""
import json
from datetime import datetime, timedelta, timezone

from paxen import darwin
from paxen.db import ObservedArrival, Prediction
from paxen.forecast import load_samples


def message(rid, locations, ts="2026-11-06T10:38:55.1669382+00:00", ssd="2026-11-06"):
    """The real envelope: Kafka JSON whose `bytes` holds the Push Port JSON (shape copied from the live feed)."""
    body = {"ts": ts, "version": "18.0", "uR": {"updateOrigin": "TD", "TS": {
        "rid": rid, "uid": "C11177", "ssd": ssd, "Location": locations}}}
    return json.dumps({"destination": {"name": "Consumer.rdmportal.VirtualTopic.PushPort-v18"},
                       "messageType": "bytes", "bytes": json.dumps(body)}).encode()


def test_actual_arrivals_are_read_and_estimates_ignored():
    raw = message("202611066711177", [
        {"tpl": "DALSKLD", "wta": "10:38:30", "pta": "10:39", "arr": {"at": "10:39", "src": "TD"},
         "dep": {"et": "10:40", "src": "Darwin"}},
        {"tpl": "HACKNYC", "pta": "10:42", "arr": {"et": "10:43", "src": "Darwin"}},  # only an estimate
        {"tpl": "BRDFDOA", "dep": {"at": "10:38", "src": "TRUST"}},  # a departure, not an arrival
    ])
    [a] = darwin.parse(raw)
    assert a.rid == "202611066711177" and a.tiploc == "DALSKLD" and a.source == "TD"
    assert a.arrived_at == datetime(2026, 11, 6, 10, 39, tzinfo=timezone.utc)  # GMT in November
    assert darwin.parse(raw, keep={"WLTWCEN"}) == []  # not a station Paxen records
    assert darwin.parse(b"not json") == []


def test_times_after_midnight_land_on_the_next_day():
    raw = message("202611057000001", {"tpl": "WLTWCEN", "arr": {"at": "00:12"}}, ts="2026-11-06T00:13:00+00:00",
                  ssd="2026-11-05")  # the train started on the 5th
    [a] = darwin.parse(raw)
    assert a.arrived_at == datetime(2026, 11, 6, 0, 12, tzinfo=timezone.utc)
    summer = message("202607017000001", {"tpl": "WLTWCEN", "arr": {"at": "08:30"}}, ts="2026-07-01T07:31:00+00:00",
                     ssd="2026-07-01")
    assert darwin.parse(summer)[0].arrived_at == datetime(2026, 7, 1, 7, 30, tzinfo=timezone.utc)  # BST


def test_london_stations_come_from_tfl_stop_ids():
    keep = darwin.london_tiplocs()
    assert {"DALSKLD", "WLTWCEN", "LIVST"} <= keep or {"DALSKLD", "WLTWCEN"} <= keep
    assert all(t and not t.startswith("910G") for t in keep)


def _prediction(session, rid, stop, line, direction, polled, tts):
    session.add(Prediction(source="tfl", polled_at=polled.replace(tzinfo=None), stop_id=stop, line_id=line,
                           mode="overground", direction=direction, vehicle_id=rid,
                           expected_arrival=(polled + timedelta(seconds=tts)).replace(tzinfo=None), tts_s=tts,
                           line_category="good", platform="Platform 2", queue_rank=1, gap_s=None,
                           feed_ts=polled.replace(tzinfo=None)))


def test_actuals_attach_to_the_tfl_train_and_are_preferred_as_truth(session):
    polled = datetime(2026, 11, 6, 10, 30, tzinfo=timezone.utc)
    _prediction(session, "202611066711177", "910GDALSKLD", "mildmay", "Stratford", polled, 480)  # says 10:38
    session.add(ObservedArrival(source="tfl", stop_id="910GDALSKLD", line_id="mildmay", vehicle_id="202611066711177",
                                direction="Stratford", arrived_at=datetime(2026, 11, 6, 10, 40, 10),
                                earliest=datetime(2026, 11, 6, 10, 39), latest=datetime(2026, 11, 6, 10, 41),
                                method="countdown_inferred", quality=0.8))
    session.commit()
    a = darwin.Actual("202611066711177", "DALSKLD", datetime(2026, 11, 6, 10, 39, tzinfo=timezone.utc), "TD")
    other = darwin.Actual("202611069999999", "DALSKLD", datetime(2026, 11, 6, 10, 39, tzinfo=timezone.utc), "TD")
    assert darwin.store(session, [a, a, other]) == 1  # duplicates and other operators' trains are dropped
    session.commit()
    assert darwin.store(session, [a]) == 0  # Darwin repeats earlier actual times: stored once
    obs = session.query(ObservedArrival).filter_by(method="darwin").one()
    assert obs.line_id == "mildmay" and obs.direction == "Stratford"
    [x] = load_samples(session, "tfl")
    assert x.method == "darwin" and x.error_s == 60  # measured beats the countdown inference


def test_actuals_match_from_the_recorders_train_index_without_the_database(session):
    from types import SimpleNamespace

    t0 = datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc)
    index = darwin.TrainIndex()
    poll = [SimpleNamespace(vehicle_id="202611066711177", stop_id="910GDALSKLD", line_id="mildmay", direction="Stratford"),
            SimpleNamespace(vehicle_id="17", stop_id="940GZZLUOXC", line_id="victoria", direction="Brixton")]  # Tube
    index.note(poll, t0)
    index._first = t0 - darwin.WARM_UP  # warmed up: no database fallback for unknown trains
    assert index.get(["17"]) == {}  # only rail stops are kept
    a = darwin.Actual("202611066711177", "DALSKLD", datetime(2026, 11, 6, 10, 39, tzinfo=timezone.utc), "TD")
    other = darwin.Actual("202611069999999", "DALSKLD", datetime(2026, 11, 6, 10, 39, tzinfo=timezone.utc), "TD")
    assert darwin.store(session, [a, other], index=index) == 1  # no Prediction rows exist at all
    session.commit()
    obs = session.query(ObservedArrival).filter_by(method="darwin").one()
    assert (obs.line_id, obs.direction, obs.stop_id) == ("mildmay", "Stratford", "910GDALSKLD")
