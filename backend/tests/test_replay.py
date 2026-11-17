"""Replaying real journey times from measured trains (paxen/replay.py)."""
from datetime import datetime, timedelta

from paxen import replay

T0 = datetime(2026, 11, 18, 8, 0)  # naive UTC = London in November
A, B, C, X = "940GZZLUAAA", "940GZZLUBBB", "940GZZLUCCC", "940GZZLUXXX"


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def train(line, veh, calls, direction="eastbound"):
    return [(line, stop, veh, direction, at(m)) for stop, m in calls]


def test_the_first_train_that_goes_there(monkeypatch):
    monkeypatch.setattr(replay, "_serves", lambda *a: False)
    arr = (train("district", "101", [(A, 1), (X, 4)])  # turns off before B: let go
           + train("district", "102", [(A, 3), (B, 10)])
           + train("district", "103", [(A, 6), (B, 13)]))
    idx = replay.Index(arr)
    r = replay.journey_time(idx, [{"line_id": "district", "from": A, "to": B, "minutes": 7}], at(0))
    assert r == {"minutes": 10.0, "wait": 3.0, "ride": 7.0, "walk": 0.0, "let_go": 1, "gap": False}
    # a train already at the platform (reached it 15 s ago) can still be caught
    r = replay.journey_time(idx, [{"line_id": "district", "from": A, "to": B, "minutes": 7}], at(3.25))
    assert r["minutes"] == 6.75 and r["wait"] == 0.0


def test_a_change_adds_the_walk_and_the_next_wait(monkeypatch):
    monkeypatch.setattr(replay, "_serves", lambda *a: False)
    arr = train("district", "102", [(A, 3), (B, 10)]) + train("central", "201", [(B, 14), (C, 20)]) \
        + train("central", "202", [(B, 11), (C, 17)])  # leaves before you've walked across: missed
    legs = [{"line_id": "district", "from": A, "to": B, "minutes": 7}, {"walk": 2},
            {"line_id": "central", "from": B, "to": C, "minutes": 6}]
    r = replay.journey_time(replay.Index(arr), legs, at(0))
    assert r["minutes"] == 20.0 and r["walk"] == 2 and r["wait"] == 5.0  # 3 at A, 2 at B


def test_a_train_seen_beyond_your_stop_but_not_at_it_is_a_tracking_gap(monkeypatch):
    monkeypatch.setattr(replay, "_serves", lambda line, a, b, last, bound: last == X)
    arr = train("district", "101", [(A, 1), (X, 9)]) + train("district", "102", [(A, 5), (B, 11)])
    r = replay.journey_time(replay.Index(arr), [{"line_id": "district", "from": A, "to": B, "minutes": 6}], at(0))
    assert r["gap"] is True and r["minutes"] == 11.0


def test_unidentified_trains_reversals_and_suspensions(monkeypatch):
    monkeypatch.setattr(replay, "_serves", lambda *a: False)
    arr = (train("district", "000", [(A, 1), (B, 7)])  # can't be followed
           + train("district", "104", [(A, 2), (X, 5), (A, 8), (B, 14)])  # goes away, comes back through A
           + train("district", "105", [(A, 9), (B, 15)]))
    idx = replay.Index(arr)
    leg = [{"line_id": "district", "from": A, "to": B, "minutes": 6}]
    r = replay.journey_time(idx, leg, at(0))
    assert r["minutes"] == 14.0  # 104 is let go at 2 (it turns round), boarded on its way back at 8
    assert r["gap"] is True  # an unidentified train came at 1: it might have been the one to take
    assert replay.journey_time(idx, leg, at(20)) is None  # nothing more: no answer
    assert replay.journey_time(idx, leg, at(3))["gap"] is False  # after the unidentified train: fine


def test_a_day_of_departures_and_its_summary(monkeypatch):
    monkeypatch.setattr(replay, "_serves", lambda *a: False)
    arr = []
    for k in range(200):  # a train every 5 minutes, 6 minutes from A to B
        arr += train("district", str(300 + k), [(A, -120 + 5 * k), (B, -114 + 5 * k)])
    panel = [{"id": f"{A}>{B}", "legs": [{"line_id": "district", "from": A, "to": B, "minutes": 6}]},
             {"id": f"{A}>{C}", "legs": [{"line_id": "district", "from": A, "to": C, "minutes": 9}]}]
    deps = replay.departures("2026-11-18")
    assert deps[0] == datetime(2026, 11, 18, 6, 0) and deps[-1] == datetime(2026, 11, 18, 22, 0) and len(deps) == 193
    rows = replay.replay_day(replay.Index(arr), panel, "2026-11-18")
    assert {r["journey"] for r in rows} == {f"{A}>{B}"}  # C is never reported on: left out
    s = replay.summarise(rows, panel)
    assert s["journeys_measured"] == 1 and s["usable"] > 0 and s["minutes_over_planned"]["p50"] == 0.0


def test_exported_days_are_replayed_once_and_reported(monkeypatch, session, tmp_path):
    import json

    from paxen import history
    from paxen.archive import LocalArchive
    from paxen.db import AppSecret, ExportedDay, ObservedArrival

    monkeypatch.setattr(replay, "_serves", lambda *a: False)
    for k in range(150):
        for stop, m in ((A, 5 * k), (B, 5 * k + 6)):
            t = datetime(2026, 11, 9, 6, 0) + timedelta(minutes=m)
            session.add(ObservedArrival(source="tfl", stop_id=stop, line_id="district", vehicle_id=str(500 + k),
                                        direction="eastbound", arrived_at=t, earliest=t, latest=t,
                                        method="trackernet", quality=1.0))
    session.commit()
    archive = LocalArchive(str(tmp_path / "store"))
    monkeypatch.setenv("PAXEN_HISTORY_CACHE", str(tmp_path / "cache"))
    history.export_pending(session, "tfl", datetime(2026, 11, 11, 9, 0), archive)
    panel = [{"id": f"{A}>{B}", "legs": [{"line_id": "district", "from": A, "to": B, "minutes": 6}]}]
    monkeypatch.setattr(replay, "load_panel", lambda: panel)
    out = replay.replay_pending(session, "tfl", archive)
    assert out["days"] == ["2026-11-09"]
    assert replay.replay_pending(session, "tfl", archive)["days"] == []  # once
    rep = json.loads(session.get(AppSecret, replay.REPORT).value)["days"]["2026-11-09"]
    assert rep["journeys_measured"] == 1 and rep["usable"] > 100
    stored = history.read_day(archive, "tfl", "journey_times", "2026-11-09", cache_dir=str(tmp_path / "cache"))
    assert stored.num_rows == 193 and session.query(ExportedDay).filter(ExportedDay.table == "journey_times").count() == 1
