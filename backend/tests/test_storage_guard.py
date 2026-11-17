"""The disk safety switch (recorder.recording_allowed) and recording while paused (workers.recorder_tick)."""
from datetime import timedelta

from conftest import MORNING
from paxen import recorder


def test_recording_pauses_over_the_limit_and_resumes_well_under_it(monkeypatch, session):
    sizes = iter([4100, 4250, 4150, 4090])
    monkeypatch.setattr(recorder, "db_size_mb", lambda s, now: next(sizes))
    monkeypatch.setattr(recorder, "PAUSED", None)
    monkeypatch.setenv("PAXEN_DB_PAUSE_MB", "4200")
    assert recorder.recording_allowed(session, MORNING)
    assert not recorder.recording_allowed(session, MORNING)  # 4,250 MB: paused
    assert recorder.PAUSED["db_mb"] == 4250 and recorder.PAUSED["limit_mb"] == 4200
    assert not recorder.recording_allowed(session, MORNING)  # 4,150: under the limit but not by enough
    assert recorder.recording_allowed(session, MORNING) and recorder.PAUSED is None  # 4,090: resumes
    monkeypatch.setenv("PAXEN_DB_PAUSE_MB", "0")
    assert recorder.recording_allowed(session, MORNING)  # 0: no limit


def test_sqlite_is_never_paused(monkeypatch, session):
    monkeypatch.setattr(recorder, "_db_size", None)
    monkeypatch.setenv("PAXEN_DB_PAUSE_MB", "1")
    assert recorder.db_size_mb(session, MORNING) is None or session.get_bind().dialect.name == "postgresql"
    if session.get_bind().dialect.name != "postgresql":
        assert recorder.recording_allowed(session, MORNING)


def test_while_paused_trains_go_to_the_archive_only(monkeypatch, session):
    from types import SimpleNamespace

    from paxen.db import ObservedArrival

    raw = b"<ROOT><S Code='FBY' N='Fulham Broadway.'/></ROOT>"
    train = SimpleNamespace(station_code="FBY", set_no="123", platform="Eastbound - Platform 1",
                            seen_since=MORNING - timedelta(seconds=10))

    class Tn:
        def summary(self, code):
            return None, [train], raw

        def station_map(self, code, names):
            return {"FBY": "940GZZLUFBY"}

    stored = []
    monkeypatch.setattr(recorder, "archive_raw", lambda *a, **k: stored.append(a[1]) or "key")
    out = recorder.record_trackernet(session, Tn(), MORNING, present={}, store=False)
    assert out["measured_arrivals"] == 0 and stored == ["trackernet"]
    assert session.query(ObservedArrival).count() == 0
    out = recorder.record_trackernet(session, Tn(), MORNING, present={})
    assert out["measured_arrivals"] > 0
