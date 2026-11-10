"""Whole-network recording: sampled storage must not cost arrival-inference accuracy."""
import gzip
from datetime import timedelta

from sqlalchemy import func, select

from conftest import MORNING
from paxen.archive import LocalArchive, S3Archive, archive_raw
from paxen.db import ObservedArrival, Prediction, RawSnapshot
from paxen.providers.sim import SimProvider
from paxen.recorder import DENSE_WINDOW_S, LeadSampler, record_once


def test_sampler_keeps_near_arrival_and_one_per_early_group():
    s = LeadSampler()
    k = ("S", "L", "V", "D")
    kept = [s.keep(k, tts, MORNING) for tts in (1500, 1470, 900, 880, 450, 420, 290, 260, 110, 80, 30)]
    assert kept == [True, False, True, False, True, False, True, False, True, True, True]


def test_network_recording_is_lean_and_inference_stays_accurate(session, tmp_path):
    p = SimProvider("normal")
    t, end = MORNING - timedelta(minutes=40), MORNING
    import paxen.recorder as rec
    rec.SAMPLER = LeadSampler()
    archive = LocalArchive(str(tmp_path))
    seen = kept = 0
    while t <= end:
        r = rec.record_network(session, p, "tube", t, {}, sampler=rec.SAMPLER, archive=archive)
        seen, kept = seen + r["seen"], kept + r["kept"]
        rec.infer_arrivals(session, "sim", t)
        session.commit()
        t += timedelta(seconds=30)
    assert kept < seen * 0.6  # the database keeps well under the raw volume
    assert len(list(tmp_path.rglob("*.json.gz"))) == 81  # every raw response archived
    obs = session.scalars(select(ObservedArrival)).all()
    assert len(obs) > 100
    errs = sorted(abs((p.true_arrival_time(o.line_id, o.stop_id, o.vehicle_id, end).replace(tzinfo=None)
                       - o.arrived_at).total_seconds()) for o in obs)
    assert errs[len(errs) // 2] < 30  # same inference accuracy as full-resolution recording
    # every stored far-out snapshot is the first of its group: at most 4 per vehicle/stop beyond the dense window
    far = session.execute(select(Prediction.stop_id, Prediction.vehicle_id, func.count())
                          .where(Prediction.tts_s > DENSE_WINDOW_S)
                          .group_by(Prediction.stop_id, Prediction.vehicle_id, Prediction.direction)).all()
    assert max(c for *_, c in far) <= 4
    assert session.scalar(select(func.count(RawSnapshot.id)).where(RawSnapshot.archive_key.is_not(None))) == 81


def test_record_once_skips_individual_polls_for_network_covered_stops(session):
    p = SimProvider("normal")
    r = record_once(session, p, MORNING, extra_stops=["walthamstow-central", "hoe-street"], modes=["tube"])
    assert r["network"][0]["mode"] == "tube" and r["network"][0]["kept"] > 0
    assert r["stops"] == 1  # walthamstow-central came from the tube poll; the bus stop needs its own


def test_s3_archive_writes_gzip_with_key_layout():
    calls = []

    class FakeS3:
        def put_object(self, **kw):
            calls.append(kw)

    url = archive_raw("tfl", "mode-tube", MORNING, '{"a":1}', archive=S3Archive("paxen-raw", "/prod/", FakeS3()))
    assert url == "s3://paxen-raw/prod/raw/tfl/2026-11-03/08/mode-tube-082000.json.gz"
    assert gzip.decompress(calls[0]["Body"]) == b'{"a":1}'


def test_archive_failure_never_breaks_recording():
    class Broken:
        def put(self, *_):
            raise OSError("bucket unreachable")

    assert archive_raw("tfl", "mode-tube", MORNING, "{}", archive=Broken()) is None


def test_prediction_retention(session):
    from paxen.recorder import prune
    old, new = MORNING - timedelta(days=61), MORNING
    for t in (old, new):
        session.add(Prediction(source="sim", polled_at=t.replace(tzinfo=None), stop_id="S", line_id="L", mode="tube",
                               vehicle_id="V", expected_arrival=t.replace(tzinfo=None), tts_s=60))
    session.commit()
    prune(session, MORNING, prediction_days=60)
    assert session.scalar(select(func.count(Prediction.id))) == 1


def test_archive_only_poll_is_invisible_to_arrival_inference(session, tmp_path):
    from paxen.recorder import archive_network, infer_arrivals

    class BusFeed(SimProvider):
        def mode_arrivals_raw(self, mode):
            return b'[{"naptanId":"490000254W"}]', 200, 1500

    r = archive_network(session, BusFeed("normal"), "bus", MORNING, archive=LocalArchive(str(tmp_path)))
    assert r["archived"] and list(tmp_path.rglob("*.json.gz"))
    snap = session.scalars(select(RawSnapshot)).one()
    assert snap.endpoint == "/Mode/bus/Arrivals?archive-only" and snap.archive_key.startswith("file://")
    assert infer_arrivals(session, "sim", MORNING + timedelta(minutes=1)) == 0


def test_misconfigured_archive_never_breaks_recording(session, monkeypatch):
    import paxen.archive as arch
    import paxen.recorder as rec

    def broken():
        raise ValueError("Invalid endpoint: https://….r2.cloudflarestorage.com")

    monkeypatch.setattr(arch, "get_archive", broken)
    r = rec.record_network(session, SimProvider("normal"), "tube", MORNING, {}, sampler=LeadSampler())
    assert r["kept"] > 0 and r["archived"] is False


def test_retention_covers_every_recording_table(session):
    from paxen.db import LineStatusSnapshot
    from paxen.recorder import prune
    old, new = (MORNING - timedelta(days=20)).replace(tzinfo=None), MORNING.replace(tzinfo=None)
    for t in (old, new):
        session.add(ObservedArrival(source="sim", stop_id="S", line_id="L", vehicle_id="V", arrived_at=t,
                                    earliest=t, latest=t, method="trackernet", quality=1.0))
        session.add(LineStatusSnapshot(source="sim", polled_at=t, line_id="L", line_name="L", mode="tube",
                                       category="good", description="Good service"))
        session.add(RawSnapshot(source="sim", endpoint="x", polled_at=t, status=200, payload="{}"))
    session.commit()
    prune(session, MORNING, prediction_days=14)
    for model in (ObservedArrival, LineStatusSnapshot, RawSnapshot):
        assert session.scalar(select(func.count()).select_from(model)) == 1
    assert session.scalars(select(RawSnapshot)).one().payload == "{}"  # recent payload kept (< 2 days)


def test_per_stop_raw_responses_go_to_the_archive_in_one_object(session, tmp_path):
    import paxen.archive as arch
    arch.get_archive.cache_clear()
    import os
    os.environ["PAXEN_ARCHIVE_URL"] = f"file://{tmp_path}"
    try:
        record_once(session, SimProvider("normal"), MORNING, extra_stops=["walthamstow-central", "oxford-circus"])
    finally:
        del os.environ["PAXEN_ARCHIVE_URL"]
        arch.get_archive.cache_clear()
    snaps = session.scalars(select(RawSnapshot).where(RawSnapshot.endpoint.like("%StopPoint%"))).all()
    assert len(snaps) == 2 and all(s.payload is None and s.archive_key for s in snaps)
    assert len(list(tmp_path.rglob("stops-*.json.gz"))) == 1


def test_replay_matches_live_inference(session):
    """python -m paxen.reinfer replays history after it is all recorded; each step only reads data up to its own
    time (for memory), and must still give what the live recorder gave."""
    import paxen.recorder as rec
    from paxen.reinfer import reinfer

    p = SimProvider("normal")
    rec.SAMPLER = LeadSampler()
    t, end = MORNING - timedelta(minutes=30), MORNING
    while t <= end:
        rec.record_network(session, p, "tube", t, {}, sampler=rec.SAMPLER)
        rec.infer_arrivals(session, "sim", t)
        session.commit()
        t += timedelta(seconds=30)
    live = sorted(session.execute(select(ObservedArrival.stop_id, ObservedArrival.vehicle_id,
                                         ObservedArrival.arrived_at)).all())
    assert live
    reinfer(session, "sim")
    replay = sorted(session.execute(select(ObservedArrival.stop_id, ObservedArrival.vehicle_id,
                                           ObservedArrival.arrived_at)).all())
    assert {r for r in replay if r[2] <= end.replace(tzinfo=None) - timedelta(minutes=2)} == \
        {r for r in live if r[2] <= end.replace(tzinfo=None) - timedelta(minutes=2)}


def test_operational_records_go_after_a_week_training_data_stays(session):
    from datetime import timedelta

    from paxen.db import LineStatusSnapshot, Prediction, RawSnapshot
    from paxen.recorder import prune

    for days in (6, 8):
        t = (MORNING - timedelta(days=days)).replace(tzinfo=None)
        session.add(RawSnapshot(source="tfl", endpoint="line_status", polled_at=t, status=200))
        session.add(LineStatusSnapshot(source="tfl", polled_at=t, line_id="victoria", line_name="Victoria", mode="tube",
                                       category="good", description="Good Service"))
        session.add(Prediction(source="tfl", polled_at=t, stop_id="S", line_id="victoria", mode="tube",
                               vehicle_id="1", expected_arrival=t, tts_s=60))
    session.commit()
    prune(session, MORNING, prediction_days=60)
    assert session.query(RawSnapshot).count() == 1 and session.query(LineStatusSnapshot).count() == 1
    assert session.query(Prediction).count() == 2  # training data follows its own 60-day retention
