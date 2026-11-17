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


GPK, OXC, WRR, EUS = "940GZZLUGPK", "940GZZLUOXC", "940GZZLUWRR", "940GZZLUEUS"


def test_stations_a_train_was_missed_at_are_filled_in_from_the_line_map():
    # Trackernet never reports Oxford Circus on the Victoria line; trains are seen at Green Park, then Warren St
    arr = train("victoria", "201", [(GPK, 0), (WRR, 4), (EUS, 6)], "northbound")
    filled = replay.fill_missed(arr)
    assert ("victoria", OXC, "201", "northbound", at(2)) in filled and len(filled) == 4
    idx = Index(arr)
    r = replay.journey_time(idx, [{"line_id": "victoria", "from": OXC, "to": EUS, "minutes": 4}], at(1))
    assert r["minutes"] == 5.0 and r["gap"] is False  # boarded at Oxford Circus at 2, at Euston at 6
    # not across a reversal or a long stop: Green Park to Warren Street in 20 minutes isn't a train passing through
    slow = train("victoria", "202", [(GPK, 0), (WRR, 20)], "northbound")
    assert len(replay.fill_missed(slow)) == 2


def test_a_train_is_followed_only_until_it_turns_round(monkeypatch):
    monkeypatch.setattr(replay, "_serves", lambda *a: False)
    # 301 passes B without being seen there, turns round at the end of the line and comes back through B:
    # that is not your train (its later arrival at B is on the way back)
    arr = (train("district", "301", [(A, 1), (X, 9), (C, 15), (X, 21), (B, 25)])
           + train("district", "302", [(A, 6), (B, 12)]))
    r = replay.journey_time(Index(arr), [{"line_id": "district", "from": A, "to": B, "minutes": 6}], at(0))
    assert r["minutes"] == 12.0 and r["let_go"] == 1


def test_a_train_standing_at_the_end_of_the_line_can_be_boarded(monkeypatch):
    monkeypatch.setattr(replay, "_serves", lambda *a: False)
    arr = []
    for k in range(5):  # trains coming in from B take 3 minutes to reach A, the end of the line
        arr += train("bakerloo", f"9{k}", [(C, 10 * k - 6), (B, 10 * k - 3), (A, 10 * k)], "southbound")
    # 401 came in at 30, stands until about 37 and goes back out; you get there at 33: you can still board it
    arr += train("bakerloo", "401", [(C, 24), (B, 27), (A, 30), (B, 40), (C, 43)], "northbound")
    arr += train("bakerloo", "402", [(A, 36), (B, 49)], "northbound")
    r = replay.journey_time(Index(arr), [{"line_id": "bakerloo", "from": A, "to": B, "minutes": 3}], at(33))
    assert r["minutes"] == 7.0 and r["wait"] == 0.0 and r["ride"] == 7.0  # sat on it until it left


def test_you_take_whichever_train_gets_you_there_first(monkeypatch):
    monkeypatch.setattr(replay, "_serves", lambda *a: False)
    arr = []
    for k in range(4):  # earlier trains: the usual running time from A to B is 3 minutes
        arr += train("hammersmith-city", f"8{k}", [(C, 10 * k - 5), (A, 10 * k - 3), (B, 10 * k)])
    # at the end of the line: 501 came in first but stands for 20 minutes; 502 came in later and leaves at once
    arr += train("hammersmith-city", "501", [(A, 30), (B, 53)])
    arr += train("hammersmith-city", "502", [(A, 38), (B, 41)])
    r = replay.journey_time(Index(arr), [{"line_id": "hammersmith-city", "from": A, "to": B, "minutes": 3}], at(31))
    assert r["minutes"] == 10.0  # on 502, at B at 41 (501 would have been 53)


def test_a_train_taken_out_of_service_is_not_boardable_for_hours(monkeypatch):
    monkeypatch.setattr(replay, "_serves", lambda *a: False)
    arr = []
    for k in range(6):
        arr += train("central", f"7{k}", [(C, 10 * k - 2), (A, 10 * k), (B, 10 * k + 3)])
    arr += train("central", "601", [(A, 5), (B, 200)])  # into the sidings at A, out again hours later
    r = replay.journey_time(Index(arr), [{"line_id": "central", "from": A, "to": B, "minutes": 3}], at(44))
    assert r["minutes"] == 9.0  # the 50 train, not 601 "standing" at A
