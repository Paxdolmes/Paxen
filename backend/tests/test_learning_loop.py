"""The core thesis: record predictions, observe outcomes, learn the errors, beat the provider."""
from datetime import timedelta

from sqlalchemy import select

from conftest import MORNING
from paxen.db import ModelVersion, ObservedArrival
from paxen.forecast import active_model, evaluate, load_samples
from paxen.providers.sim import SimProvider
from paxen.seed import backfill_recorder
from paxen.forecast import train_and_maybe_promote

STOPS = ["walthamstow-central", "oxford-circus", "bakers-arms"]


def test_inferred_arrivals_are_close_to_truth(session):
    p = SimProvider("normal")
    backfill_recorder(session, p, MORNING, hours=0.5, stops=STOPS)
    obs = session.scalars(select(ObservedArrival)).all()
    assert len(obs) > 20
    assert all(o.method == "countdown_inferred" and o.earliest <= o.arrived_at <= o.latest for o in obs)
    errs = []
    for o in obs:
        truth = p.true_arrival_time(o.line_id, o.stop_id, o.vehicle_id, MORNING)
        errs.append(abs((truth.replace(tzinfo=None) - o.arrived_at).total_seconds()))
    assert sorted(errs)[len(errs) // 2] < 30  # median inference error under 30 s


def test_correction_model_beats_provider_and_is_promoted(session):
    p = SimProvider("normal")
    backfill_recorder(session, p, MORNING, hours=3, stops=STOPS)
    res = train_and_maybe_promote(session, "sim")
    assert res["status"] == "promoted", res
    assert res["corrected_mae_s"] < res["provider_mae_s"] * 0.8
    mv = session.scalars(select(ModelVersion).where(ModelVersion.active.is_(True))).one()
    assert mv.metrics["by_lead"]["10-20m"]["corrected"]["mae_s"] < mv.metrics["by_lead"]["10-20m"]["provider"]["mae_s"]
    assert 0.6 <= mv.metrics["interval_coverage_p10_p90"] <= 0.95  # roughly calibrated 80% interval

    # Out-of-sample on a *later*, unseen hour.
    backfill_recorder(session, p, MORNING + timedelta(hours=2), hours=1, stops=STOPS)
    later = [x for x in load_samples(session, "sim") if x.polled_at > MORNING + timedelta(hours=1, minutes=5)]
    m = evaluate(active_model(session), later)
    assert m["corrected"]["mae_s"] < m["provider"]["mae_s"]


def test_not_promoted_without_enough_data(session):
    backfill_recorder(session, SimProvider("normal"), MORNING, hours=0.1, stops=STOPS)
    assert train_and_maybe_promote(session, "sim")["status"] == "insufficient_data"


def test_inference_uses_platform_time_and_skips_terminus_layovers(session):
    """Real TfL behaviour: trains sit at 'due' at a terminus for many minutes before departing."""
    from paxen.db import Prediction
    from paxen.recorder import infer_arrivals

    t0 = MORNING.replace(tzinfo=None)
    def poll(i, vehicle, tts):
        p = t0 + timedelta(seconds=30 * i)
        session.add(Prediction(source="tfl", polled_at=p, stop_id="S", line_id="L", mode="tube", vehicle_id=vehicle,
                               expected_arrival=p + timedelta(seconds=tts), tts_s=tts))
    for i, tts in enumerate([200, 90, 20, 0]):       # arrives during poll 2..3, then sits briefly
        poll(i, "A", tts)
    for i in range(14):                              # B is shown as 'due' for 7 minutes: a layover
        poll(i, "B", 0)
    poll(14, "C", 600)                               # a later poll at the stop: A and B have left the board
    session.commit()
    infer_arrivals(session, "tfl", MORNING + timedelta(minutes=8))
    obs = {o.vehicle_id: o for o in session.scalars(select(ObservedArrival))}
    assert set(obs) == {"A"}
    assert obs["A"].arrived_at == t0 + timedelta(seconds=60 + 20)  # first at-platform poll + its countdown
