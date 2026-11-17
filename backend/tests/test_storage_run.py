"""The 2-hourly storage and history run (workers.thin_tick): replays new days first, and saves its progress."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

import paxen.archive as arch
from paxen import replay, workers
from paxen.db import AppSecret, Base, ExportedDay, ObservedArrival, make_engine
from paxen.timeutil import LONDON

A, B = "940GZZLUAAA", "940GZZLUBBB"


@pytest.fixture
def worker_db(monkeypatch, tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path}/worker.db")
    Base.metadata.create_all(eng)
    local = sessionmaker(bind=eng, expire_on_commit=False)
    monkeypatch.setattr(workers, "SessionLocal", local)
    monkeypatch.setenv("PAXEN_ARCHIVE_URL", f"file://{tmp_path}/store")
    monkeypatch.setenv("PAXEN_HISTORY_CACHE", str(tmp_path / "cache"))
    arch.get_archive.cache_clear()
    monkeypatch.setattr(replay, "_serves", lambda *a: False)
    monkeypatch.setattr(replay, "load_panel", lambda: [
        {"id": f"{A}>{B}", "legs": [{"line_id": "district", "from": A, "to": B, "minutes": 6}]}])
    yield local
    arch.get_archive.cache_clear()
    eng.dispose()


def a_measured_day(local) -> str:
    day = (datetime.now(timezone.utc).astimezone(LONDON) - timedelta(days=2)).date()
    start = datetime(day.year, day.month, day.day, 6, 0, tzinfo=LONDON).astimezone(timezone.utc).replace(tzinfo=None)
    with local() as s:
        for k in range(150):  # a train every 5 minutes from A to B, 6 minutes apart
            for stop, m in ((A, 5 * k), (B, 5 * k + 6)):
                t = start + timedelta(minutes=m)
                s.add(ObservedArrival(source="sim", stop_id=stop, line_id="district", vehicle_id=str(500 + k),
                                      direction="eastbound", arrived_at=t, earliest=t, latest=t,
                                      method="trackernet", quality=1.0))
        s.commit()
    return str(day)


def progress(local) -> dict:
    with local() as s:
        return json.loads(s.get(AppSecret, workers.THIN_STATUS).value)


def test_new_days_are_replayed_and_every_step_is_timed(worker_db):
    day = a_measured_day(worker_db)
    out = workers.thin_tick()
    assert day in out["history"]["days"] and out["replay"]["days"] == [day]  # (the empty days after it: not replayed)
    run = progress(worker_db)["run"]
    assert run["finished_at"] and run["step"] is None and run["errors"] == {}
    assert {"export", f"export {day} observed_arrivals", f"replay {day}", "thin", "rebuild"} <= set(run["steps"])
    assert run["result"]["replay"]["days"] == [day]
    workers.thin_tick()  # the next run keeps the one before it, so a run that was cut short stays visible
    p = progress(worker_db)
    assert p["previous"]["started_at"] == run["started_at"] and p["run"]["result"]["replay"]["days"] == []


def test_a_failed_export_is_recorded_without_addresses(worker_db, monkeypatch):
    from paxen import history

    a_measured_day(worker_db)

    def broken(*a, **kw):
        raise ValueError("Could not connect to the endpoint URL: https://abc123.r2.cloudflarestorage.com/paxen")

    monkeypatch.setattr(history, "export_pending", broken)
    assert workers.thin_tick() == {"history": "failed"}
    run = progress(worker_db)["run"]
    assert run["finished_at"] and run["errors"]["export"].startswith("ValueError: Could not connect")
    assert "cloudflarestorage" not in json.dumps(run) and "<url>" in run["errors"]["export"]
    with worker_db() as s:  # nothing was replayed or thinned
        assert s.query(ExportedDay).count() == 0


def test_a_failing_step_does_not_stop_the_ones_after_it(worker_db, monkeypatch):
    import paxen.evaluate as ev

    day = a_measured_day(worker_db)
    monkeypatch.setattr(ev, "thin_history", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("disk full")))
    out = workers.thin_tick()
    assert out["thin"] == "failed" and out["replay"]["days"] == [day] and isinstance(out["rebuilt"], dict)
    assert progress(worker_db)["run"]["errors"] == {"thin": "RuntimeError: disk full"}


def test_the_report_shows_the_store_and_the_run():
    from fastapi.testclient import TestClient

    import paxen.main as main
    from paxen.db import SessionLocal

    days = ["2001-01-01", "2001-01-02"]
    with TestClient(main.app) as c:  # (starting the app creates the tables)
        with SessionLocal() as s:
            for day, partial in zip(days, (True, False)):
                s.add(ExportedDay(source="sim", table="observed_arrivals", day=day, key=f"k{day}", rows=10,
                                  bytes=2_000_000, partial=partial))
            s.merge(AppSecret(name=workers.THIN_STATUS, value=json.dumps(
                {"run": {"step": "rebuild 2001-01-01"}, "previous": None})))
            s.commit()
        try:
            c.headers["Authorization"] = "Bearer " + c.post("/v1/users").json()["token"]
            rep = c.get("/v1/journeys/report").json()
            c.delete("/v1/me")
        finally:
            with SessionLocal() as s:
                s.query(ExportedDay).filter(ExportedDay.day.in_(days)).delete()
                s.query(AppSecret).filter(AppSecret.name == workers.THIN_STATUS).delete()
                s.commit()
    oa = rep["store"]["observed_arrivals"]
    assert oa["days"] >= 2 and oa["partial"] >= 1 and oa["rows"] >= 20 and oa["mb"] >= 4.0
    assert rep["pipeline"]["run"]["step"] == "rebuild 2001-01-01"
