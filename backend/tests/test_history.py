"""The history store (paxen/history.py): each day exported to the archive, checked, and only then thinned or
dropped from the database."""
from datetime import datetime, timedelta, timezone

from paxen import history
from paxen.archive import LocalArchive
from paxen.db import DaySample, ExportedDay, ObservedArrival, Prediction, StationCrowding

DAY1 = datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc)  # Monday (GMT: London = UTC)
DAY2 = DAY1 + timedelta(days=1)
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)


def fill(session, at, n):
    for i in range(n):
        t = (at + timedelta(seconds=30 * i)).replace(tzinfo=None)
        session.add(Prediction(source="tfl", polled_at=t, stop_id="940GZZLUFBY", line_id="district", mode="tube",
                               vehicle_id=str(i), expected_arrival=t + timedelta(minutes=3), tts_s=180,
                               platform="Eastbound - Platform 1"))
        session.add(ObservedArrival(source="tfl", stop_id="940GZZLUFBY", line_id="district", vehicle_id=str(i),
                                    direction="eastbound", arrived_at=t + timedelta(minutes=3),
                                    earliest=t + timedelta(minutes=3), latest=t + timedelta(minutes=3), method="trackernet",
                                    quality=1.0))
    session.add(StationCrowding(stop_id="940GZZLUFBY", polled_at=at.replace(tzinfo=None), pct_of_baseline=0.4))
    session.commit()


def test_each_finished_day_is_exported_checked_and_readable(session, tmp_path):
    fill(session, DAY1, 120)
    fill(session, DAY2, 80)
    archive = LocalArchive(str(tmp_path / "store"))
    out = history.export_pending(session, "tfl", NOW, archive)
    assert out["days"][:2] == ["2026-11-09", "2026-11-10"] and out["rows"] == 120 * 2 + 80 * 2 + 2
    t = history.read_day(archive, "tfl", "predictions", "2026-11-09", cache_dir=str(tmp_path / "cache"))
    assert t.num_rows == 120 and t.column("line_id")[0].as_py() == "district"
    assert t.column("polled_at")[0].as_py() == DAY1.replace(tzinfo=None)
    arr = history.read_day(archive, "tfl", "observed_arrivals", "2026-11-10", cache_dir=str(tmp_path / "cache"))
    assert arr.num_rows == 80 and set(arr.column("method").to_pylist()) == {"trackernet"}
    assert {"2026-11-09", "2026-11-10"} <= history.exported_days(session, "tfl")
    again = history.export_pending(session, "tfl", NOW, archive)
    assert "2026-11-09" not in again["days"]  # never exported twice
    # today isn't over: not exported
    assert "2026-11-12" not in history.exported_days(session, "tfl")


def test_a_day_is_thinned_only_once_it_is_in_the_store(session, tmp_path):
    from paxen.evaluate import thin_history

    fill(session, DAY1, 60)
    fill(session, DAY2, 60)
    thin_history(session, "tfl", NOW, pause_s=0, exported=set())  # nothing exported yet
    assert session.query(DaySample).filter(DaySample.thinned.is_(True)).count() == 0
    archive = LocalArchive(str(tmp_path / "store"))
    history.export_pending(session, "tfl", NOW, archive)
    thin_history(session, "tfl", NOW, pause_s=0, exported=history.exported_days(session, "tfl"))
    assert session.query(DaySample).filter(DaySample.thinned.is_(True)).count() == 2


def test_dropping_needs_a_setting_and_an_export(session, tmp_path):
    fill(session, DAY1, 50)
    fill(session, DAY2, 50)
    archive = LocalArchive(str(tmp_path / "store"))
    assert history.drop_exported(session, "tfl", NOW, keep_days=1, pause_s=0)["days"] == []  # nothing exported
    history.export_pending(session, "tfl", NOW, archive)
    assert history.drop_exported(session, "tfl", NOW, keep_days=0, pause_s=0)["days"] == []  # 0: keep every day
    out = history.drop_exported(session, "tfl", NOW, keep_days=2, pause_s=0)  # keep 10 and 11 Nov
    assert out["days"] == ["2026-11-09"]
    assert session.query(Prediction).count() == 50 and session.query(ObservedArrival).count() == 50
    assert all(r.dropped for r in session.query(ExportedDay).filter(ExportedDay.day == "2026-11-09"))
    # the dropped day is still there in the store
    assert history.read_day(archive, "tfl", "predictions", "2026-11-09", cache_dir=str(tmp_path / "c")).num_rows == 50


def test_a_bad_upload_stops_everything(session, tmp_path):
    import pytest

    fill(session, DAY1, 10)

    class Broken(LocalArchive):
        def get_bytes(self, key):
            import io

            import pyarrow as pa
            import pyarrow.parquet as pq

            buf = io.BytesIO()
            pq.write_table(pa.table({"x": [1]}), buf)
            return buf.getvalue()  # reads back the wrong file

    with pytest.raises(RuntimeError, match="history check failed"):
        history.export_pending(session, "tfl", NOW, Broken(str(tmp_path / "store")))
    assert session.query(ExportedDay).count() == 0


def test_complete_days_go_before_already_thinned_ones(session, tmp_path):
    fill(session, DAY1, 10)
    fill(session, DAY2, 10)
    session.add(DaySample(source="tfl", day="2026-11-09", stride=17, thinned=True))
    session.commit()
    out = history.export_pending(session, "tfl", NOW, LocalArchive(str(tmp_path / "s")), max_days=1)
    assert out["days"] == ["2026-11-10"]
    out = history.export_pending(session, "tfl", NOW, LocalArchive(str(tmp_path / "s")), max_days=3)
    assert "2026-11-09" in out["days"]
    assert session.query(ExportedDay).filter(ExportedDay.day == "2026-11-09").first().partial is True
