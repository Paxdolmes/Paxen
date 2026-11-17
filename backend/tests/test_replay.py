"""Replaying real journey times from measured trains (paxen/replay.py)."""
from datetime import datetime, timedelta

import pytest

from paxen import replay

T0 = datetime(2026, 11, 18, 8, 0)  # naive UTC = London in November
A, B, C, X = "940GZZLUAAA", "940GZZLUBBB", "940GZZLUCCC", "940GZZLUXXX"


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def train(line, veh, calls, direction="eastbound"):
    return [(line, stop, veh, direction, at(m)) for stop, m in calls]


def network(lo=-150, hi=1000):
    """Elsewhere on the network a train reaches some platform every minute: the tracking is running."""
    return [("elsewhere", "940GZZLUZZZ", f"e{m}", "westbound", at(m)) for m in range(lo, hi)]


def Index(arr):
    return replay.Index(arr + network())


def test_the_first_train_that_goes_there(monkeypatch):
    monkeypatch.setattr(replay, "_serves", lambda *a: False)
    arr = (train("district", "101", [(A, 1), (X, 4)])  # turns off before B: let go
           + train("district", "102", [(A, 3), (B, 10)])
           + train("district", "103", [(A, 6), (B, 13)]))
    idx = Index(arr)
    r = replay.journey_time(idx, [{"line_id": "district", "from": A, "to": B, "minutes": 7}], at(0))
    assert r == {"minutes": 10.0, "wait": 3.0, "ride": 7.0, "walk": 0.0, "let_go": 1, "gap": False, "outage": False}
    # a train already at the platform (reached it 15 s ago) can still be caught
    r = replay.journey_time(idx, [{"line_id": "district", "from": A, "to": B, "minutes": 7}], at(3.25))
    assert r["minutes"] == 6.75 and r["wait"] == 0.0


def test_a_change_adds_the_walk_and_the_next_wait(monkeypatch):
    monkeypatch.setattr(replay, "_serves", lambda *a: False)
    arr = train("district", "102", [(A, 3), (B, 10)]) + train("central", "201", [(B, 14), (C, 20)]) \
        + train("central", "202", [(B, 11), (C, 17)])  # leaves before you've walked across: missed
    legs = [{"line_id": "district", "from": A, "to": B, "minutes": 7}, {"walk": 2},
            {"line_id": "central", "from": B, "to": C, "minutes": 6}]
    r = replay.journey_time(Index(arr), legs, at(0))
    assert r["minutes"] == 20.0 and r["walk"] == 2 and r["wait"] == 5.0  # 3 at A, 2 at B


def test_a_train_seen_beyond_your_stop_but_not_at_it_is_a_tracking_gap(monkeypatch):
    monkeypatch.setattr(replay, "_serves", lambda line, a, b, last, bound: last == X)
    arr = train("district", "101", [(A, 1), (X, 9)]) + train("district", "102", [(A, 5), (B, 11)])
    r = replay.journey_time(Index(arr), [{"line_id": "district", "from": A, "to": B, "minutes": 6}], at(0))
    assert r["gap"] is True and r["minutes"] == 11.0


def test_unidentified_trains_reversals_and_suspensions(monkeypatch):
    monkeypatch.setattr(replay, "_serves", lambda *a: False)
    arr = (train("district", "000", [(A, 1), (B, 7)])  # can't be followed
           + train("district", "104", [(A, 2), (X, 5), (A, 8), (B, 14)])  # goes away, comes back through A
           + train("district", "105", [(A, 9), (B, 15)]))
    idx = Index(arr)
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
    rows = replay.replay_day(Index(arr), panel, "2026-11-18")
    assert {r["journey"] for r in rows} == {f"{A}>{B}"}  # C is never reported on: left out
    s = replay.summarise(rows, panel)
    assert s["journeys_measured"] == 1 and s["usable"] > 0 and s["minutes_over_planned"]["p50"] == 0.0


def test_exported_days_are_replayed_once_and_reported(monkeypatch, session, tmp_path):
    import json

    from paxen import history
    from paxen.archive import LocalArchive
    from paxen.db import AppSecret, ExportedDay, ObservedArrival

    monkeypatch.setattr(replay, "_serves", lambda *a: False)
    calls = [(A, "district", str(500 + k), 5 * k) for k in range(150)] + \
        [(B, "district", str(500 + k), 5 * k + 6) for k in range(150)] + \
        [("940GZZLUZZZ", "elsewhere", f"e{m}", m) for m in range(-30, 1000)]  # the rest of the network
    for stop, line, veh, m in calls:
        t = datetime(2026, 11, 9, 6, 0) + timedelta(minutes=m)
        session.add(ObservedArrival(source="tfl", stop_id=stop, line_id=line, vehicle_id=veh,
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

    assert rep["version"] == replay.VERSION and rep["tracked"]["from"] == "05:30"
    assert rep["by_first_line"]["district"]["usable"] == rep["usable"]
    # the replay rules change: every day is replayed again, and its cached file replaced
    row = session.get(AppSecret, replay.REPORT)
    row.value = json.dumps({**json.loads(row.value), "version": replay.VERSION - 1})
    session.commit()
    assert replay.replay_pending(session, "tfl", archive)["days"] == ["2026-11-09"]
    assert session.query(ExportedDay).filter(ExportedDay.table == "journey_times").count() == 1


def test_missing_directions_and_set_numbers_never_break_the_index():
    t = at(0)
    arr = [("district", A, "101", None, t), ("district", A, "101", "eastbound", t), ("district", B, None, None, t)]
    idx = Index(arr)
    assert len(idx.at_stop[("district", A)]) == 2 and idx.unknown[("district", B)] == [t]


def test_departures_while_the_tracking_was_down_are_not_used(monkeypatch):
    monkeypatch.setattr(replay, "_serves", lambda *a: False)
    leg = [{"line_id": "district", "from": A, "to": B, "minutes": 6}]
    arr = [x for k in range(40) for x in train("district", str(300 + k), [(A, 60 + 3 * k), (B, 66 + 3 * k)])]
    # the recorder only started at 60: leaving at 0, the first train seen is at 60, but that is not a 60-minute wait
    started = replay.Index(arr + network(lo=60, hi=200))
    r = replay.journey_time(started, leg, at(0))
    assert r["outage"] is True and r["gap"] is True
    assert replay.journey_time(started, leg, at(70))["outage"] is False
    # ten minutes with nothing measured anywhere (the feed was down): journeys over it are not used
    down = replay.Index([a for a in arr + network(lo=0, hi=200) if not at(100) <= a[4] < at(110)])
    assert replay.journey_time(down, leg, at(97))["outage"] is True
    assert replay.journey_time(down, leg, at(112))["outage"] is False
    # but one line stopping while the rest of the network runs is a real delay, and is kept
    suspended = replay.Index([a for a in arr if not at(100) <= a[4] < at(130)] + network(lo=0, hi=200))
    r = replay.journey_time(suspended, leg, at(98))
    assert r["outage"] is False and r["gap"] is False and r["wait"] > 30


def test_the_summary_says_when_tracking_ran(monkeypatch):
    monkeypatch.setattr(replay, "_serves", lambda *a: False)
    day = "2026-11-18"  # T0 is 08:00 that day
    arr = [x for k in range(115) for x in train("district", str(300 + k), [(A, 5 * k), (B, 5 * k + 6)])]
    idx = replay.Index(arr + network(lo=0, hi=600))  # tracked 08:00 to 18:00
    panel = [{"id": f"{A}>{B}", "legs": [{"line_id": "district", "from": A, "to": B, "minutes": 6}]}]
    s = replay.summarise(replay.replay_day(idx, panel, day), panel, idx, day)
    assert s["tracked"]["from"] == "08:00" and s["tracked"]["to"] == "17:59"
    assert s["tracked"]["silent_min_06_22"] == pytest.approx(120 + 241, abs=1)  # 06:00-08:00 and 17:59-22:00
    assert s["outages"] > 0 and s["usable"] > 0 and s["minutes_over_planned"]["p50"] == 0.0
