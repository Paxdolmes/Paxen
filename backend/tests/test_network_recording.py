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
