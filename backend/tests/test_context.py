"""Recording the live context (paxen/context.py)."""
from datetime import datetime, timedelta, timezone

from paxen.context import record_context, record_status_changes, store_weather, touch
from paxen.db import ContextEvent, StationCrowding, WeatherHour
from paxen.domain import LineStatus

NOW = datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc)


def test_events_are_runs_not_rows_per_poll(session):
    gap = timedelta(minutes=2)
    for i in range(5):
        touch(session, "x", "k", NOW + timedelta(seconds=30 * i), gap)
    touch(session, "x", "k", NOW + timedelta(minutes=30), gap)  # seen again after a gap: a new run
    session.commit()
    runs = session.query(ContextEvent).order_by(ContextEvent.first_seen).all()
    assert len(runs) == 2 and runs[0].last_seen - runs[0].first_seen == timedelta(minutes=2)


def test_line_status_history_is_one_row_per_change(session):
    good = [LineStatus("central", "Central", "tube", "good", "Good Service")]
    bad = [LineStatus("central", "Central", "tube", "severe", "Severe Delays", "Signal failure at Bank.")]
    for i, sts in enumerate([good, good, bad, bad, bad, good]):
        record_status_changes(session, sts, NOW + timedelta(seconds=30 * i))
    session.commit()
    rows = session.query(ContextEvent).filter_by(kind="line_status").order_by(ContextEvent.first_seen).all()
    assert [r.category for r in rows] == ["good", "severe", "good"]
    assert rows[1].summary == "Signal failure at Bank."


def test_weather_keeps_hours_up_to_now_and_refines_them(session):
    data = {"hourly": {"time": ["2026-11-05T13:00", "2026-11-05T14:00", "2026-11-05T15:00"],
                       "temperature_2m": [9.0, 10.0, 11.0], "precipitation": [0, 0.4, 0], "snowfall": [0, 0, 0],
                       "wind_gusts_10m": [30, 35, 40], "relative_humidity_2m": [80, 82, 85], "weather_code": [3, 61, 3]}}
    assert store_weather(session, data, NOW) == 2  # 15:00 is still a forecast
    data["hourly"]["temperature_2m"][1] = 10.5
    store_weather(session, data, NOW)
    session.commit()
    assert session.get(WeatherHour, "2026-11-05T14").temp_c == 10.5


class FakeTfl:
    name = "tfl"

    def _get(self, path, params=None):
        if "StopPoint/Mode" in path:
            return [{"atcoCode": "940GZZLUBCT", "type": "Part Closure", "description": "Westbound trains will not call"}], "", 200, 1
        if "Lifts" in path:
            raise RuntimeError("down")  # one source failing mustn't stop the others
        if "crowding" in path:
            return {"dataAvailable": True, "percentageOfBaseline": 0.42}, "", 200, 1
        if "/Status/" in path:
            return [], "[]", 200, 1
        return [], "[]", 200, 1


def test_context_cycle_survives_a_failing_source(session, monkeypatch):
    import paxen.context as ctx

    monkeypatch.setattr(ctx, "record_weather", lambda s, now: 0)
    monkeypatch.setattr(ctx, "tube_stations", lambda: ["940GZZLUOXC", "940GZZLUBST"])
    ctx._last.clear()
    out = record_context(session, FakeTfl(), NOW)
    assert out["station_disruptions"] == 1 and out["lifts"].startswith("failed") and out["crowding"] == 2
    assert session.query(StationCrowding).count() == 2
    assert session.query(ContextEvent).filter_by(kind="station_disruption").one().stop_id == "940GZZLUBCT"
