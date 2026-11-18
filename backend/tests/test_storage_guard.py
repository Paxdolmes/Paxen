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


def test_pauses_are_logged_and_paused_days_are_rebuilt_from_the_archive(monkeypatch, session, tmp_path):
    """A day recording was paused in is incomplete in the database: it's exported as partial, so the worker
    rebuilds its measured arrivals from the raw archive, as for days thinned before the history store."""
    from paxen import history
    from paxen.archive import LocalArchive
    from paxen.db import ExportedDay, ObservedArrival

    monkeypatch.setattr(recorder, "PAUSED", None)
    monkeypatch.setattr(recorder, "_pause_log_checked", False)
    monkeypatch.setenv("PAXEN_DB_PAUSE_MB", "4200")
    sizes = iter([4100, 4250, 4250, 4050])
    monkeypatch.setattr(recorder, "db_size_mb", lambda s, now: next(sizes))
    t = MORNING  # Tuesday 3 Nov, 08:20
    assert recorder.recording_allowed(session, t)
    assert not recorder.recording_allowed(session, t + timedelta(hours=1))  # paused 09:20
    monkeypatch.setattr(recorder, "PAUSED", None)  # the worker restarts while paused: one pause, not two
    assert not recorder.recording_allowed(session, t + timedelta(hours=2))
    assert recorder.recording_allowed(session, t + timedelta(hours=26))  # resumes Wednesday 10:20
    pauses = recorder.pause_intervals(session, t)
    assert pauses == [((t + timedelta(hours=1)).replace(tzinfo=None), (t + timedelta(hours=26)).replace(tzinfo=None))]
    for day_offset in range(3):  # an arrival on each of Tue, Wed, Thu
        a = (t + timedelta(days=day_offset)).replace(tzinfo=None)
        session.add(ObservedArrival(source="tfl", stop_id="S", line_id="victoria", vehicle_id="1", arrived_at=a,
                                    earliest=a, latest=a, method="trackernet", quality=1.0))
    session.commit()
    history.export_pending(session, "tfl", t + timedelta(days=4), LocalArchive(str(tmp_path)))
    partial = {r.day: r.partial for r in session.query(ExportedDay).filter(ExportedDay.table == "observed_arrivals")}
    assert partial == {"2026-11-03": True, "2026-11-04": True, "2026-11-05": False}


def test_a_restart_after_a_pause_closes_it(monkeypatch, session):
    import json

    from paxen.db import AppSecret

    session.add(AppSecret(name=recorder.PAUSES, value=json.dumps([["2026-11-03T08:00:00+00:00", None]])))
    session.commit()
    monkeypatch.setattr(recorder, "PAUSED", None)
    monkeypatch.setattr(recorder, "_pause_log_checked", False)
    monkeypatch.setenv("PAXEN_DB_PAUSE_MB", "8000")  # the limit was raised, then the worker restarted
    monkeypatch.setattr(recorder, "db_size_mb", lambda s, now: 4300)
    assert recorder.recording_allowed(session, MORNING)
    assert recorder.pause_intervals(session, MORNING + timedelta(days=1))[0][1] == MORNING.replace(tzinfo=None)
