"""The pre-registered rolling-day protocol (docs/model-evaluation.md)."""
import random
from datetime import datetime, timedelta, timezone

from paxen.evaluate import evaluate
from paxen.forecast import Sample
from paxen.models import GBMModel, HierCtxModel, HierModel, ProviderModel


def synth(days: int, bias: bool, seed: int = 1, per_day: int = 400) -> list[Sample]:
    """Each day: predictions at random leads. With bias, TfL under-states waits by 10% of lead (+ noise)."""
    r = random.Random(seed)
    out = []
    for d in range(days):
        day = datetime(2026, 11, 2, tzinfo=timezone.utc) + timedelta(days=d)
        for _ in range(per_day):
            lead = r.uniform(30, 1500)
            err = (0.10 * lead if bias else 0.0) + r.gauss(0, 25)
            line = r.choice(["victoria", "central", "district"])
            t = day + timedelta(hours=r.uniform(6, 22))
            out.append(Sample(t, line, f"{line}-s{r.randint(1, 5)}", lead, "interpeak", False, err, 1.0,
                              queue_rank=r.randint(1, 4), gap_s=r.randint(60, 400), feed_age_s=r.uniform(1, 30)))
    return out


FAST = {"provider": ProviderModel, "hier": HierModel, "hier_ctx": HierCtxModel}


def test_refuses_to_decide_without_enough_days():
    rep = evaluate(synth(9, bias=True), FAST)
    assert rep["status"] == "not_enough_data" and rep["winner"] is None


def test_real_consistent_bias_produces_a_winner():
    rep = evaluate(synth(11, bias=True), FAST)
    assert rep["status"] == "winner"
    s = rep["summary"]
    assert s[rep["winner"]]["mean_mae_s"] < s["provider"]["mean_mae_s"] * 0.97
    assert s[rep["winner"]]["win_days"] == s[rep["winner"]]["test_days"] == 4
    assert rep["winner"] == "hier"  # hier_ctx adds nothing here, so the simpler model wins the tie


def test_noise_only_promotes_nothing():
    rep = evaluate(synth(11, bias=False), FAST)
    assert rep["status"] == "no_eligible_candidate" and rep["winner"] is None


def test_gbm_learns_the_bias_and_round_trips():
    train, test = synth(3, bias=True, seed=2), synth(1, bias=True, seed=3)
    m = GBMModel.fit(train)
    preds = m.predict_many(test)
    mae_before = sum(abs(x.error_s) for x in test) / len(test)
    mae_after = sum(abs(x.error_s - p["bias_s"]) for x, p in zip(test, preds)) / len(test)
    assert mae_after < mae_before * 0.6
    again = GBMModel.from_params(m.to_params())
    x = test[0]
    assert abs(again.predict(x.line_id, x.stop_id, x.lead_s, x.band, x.disrupted, queue_rank=x.queue_rank,
                             gap_s=x.gap_s, feed_age_s=x.feed_age_s)["bias_s"] - preds[0]["bias_s"]) < 1e-6


def test_app_summary_reads_protocol_reports(session):
    from paxen.db import ModelVersion
    from paxen.evaluate import _slim
    from paxen.insights import model_summary

    rep = evaluate(synth(9, bias=True), FAST)
    session.add(ModelVersion(kind="arrival_correction:tfl", params={"model": "provider"}, metrics=_slim(rep),
                             active=False, note=rep["message"]))
    session.commit()
    m = model_summary(session, "tfl")
    assert m["status"] == "no_model" and "9 of 10 days" in m["message"]

    rep = evaluate(synth(11, bias=True), FAST)
    session.add(ModelVersion(kind="arrival_correction:tfl", params={"model": "provider"}, metrics=_slim(rep),
                             active=False, note=rep["message"]))
    session.commit()
    m = model_summary(session, "tfl")
    assert m["provider"]["mae_s"] > m["corrected"]["mae_s"] and m["by_lead"] and m["candidate"] == "hier"


# ---- Amendment 1 -----------------------------------------------------------------------------------------
from paxen.evaluate import decision_mae  # noqa: E402
from paxen.models import Conformal, from_params  # noqa: E402


def test_purge_drops_training_outcomes_inside_the_test_day():
    """A1.1: a prediction made before midnight whose arrival happens after it must not be trained on."""
    seen = []

    class Spy(ProviderModel):
        @classmethod
        def fit(cls, samples):
            seen.append(max(x.arrived_at for x in samples if x.arrived_at))
            return super().fit(samples)

    samples = synth(11, bias=True)
    for x in samples:
        x.arrived_at = x.polled_at + timedelta(seconds=x.lead_s + x.error_s)
    late = samples[0].polled_at.replace(hour=23, minute=55) + timedelta(days=7)  # day 8, just before midnight
    samples.append(Sample(late, "victoria", "victoria-s1", 900, "off_peak", False, 0.0, 1.0,
                          arrived_at=late + timedelta(minutes=15)))
    evaluate(samples, {"provider": Spy})
    from paxen.evaluate import _day_start_utc
    for train_max, d in zip(seen, sorted({x.day for x in samples})[-4:]):
        assert train_max < _day_start_utc(d)


def test_decision_rule_rejects_a_win_that_is_only_in_the_last_two_minutes():
    """A1.2: a correction that only helps 0-2 min predictions (the densest, least useful) isn't promoted."""
    r = random.Random(5)
    out = []
    for d in range(11):
        day = datetime(2026, 11, 2, tzinfo=timezone.utc) + timedelta(days=d)
        for i in range(600):
            lead = r.uniform(10, 110) if i < 450 else r.uniform(150, 1100)  # dense near arrival, like the recorder
            err = (60 if lead < 120 else 0) + r.gauss(0, 20)
            t = day + timedelta(hours=r.uniform(6, 22))
            out.append(Sample(t, "victoria", "victoria-s1", lead, "interpeak", False, err, event=f"{d}-{i}"))
    rep = evaluate(out, FAST)
    s = rep["summary"]["hier"]
    assert s["checks"]["mae_gain"] and s["checks"]["wins"]  # wins on the headline number...
    assert not s["checks"]["decision_gain"] and rep["winner"] is None  # ...but not where decisions are made


def test_each_arrival_counts_once_per_bucket():
    """A1.2: one train seen 100 times can't outweigh four trains seen once each."""
    t = datetime(2026, 11, 3, 8, tzinfo=timezone.utc)
    xs = [Sample(t, "v", "s", 400, "am_peak", False, 100.0, event="busy-train") for _ in range(100)]
    xs += [Sample(t, "v", "s", 400, "am_peak", False, 0.0, event=f"train-{i}") for i in range(4)]
    assert decision_mae(xs, [{"bias_s": 0.0}] * len(xs)) == 20.0  # (100 + 0 + 0 + 0 + 0) / 5, not ~96


class Overconfident(ProviderModel):
    """A base model whose intervals are far too narrow (zero width)."""
    kind = "overconfident"

    def predict(self, line, stop, lead_s, band, disrupted, **ctx):
        return {"bias_s": 0.0, "q10_s": 0.0, "q90_s": 0.0, "support": 0}

    def to_params(self):
        return {"model": "provider", "q10": 0.0, "q90": 0.0}


def test_conformal_fixes_coverage_without_moving_point_predictions():
    """A1.3: an overconfident model gets ~80% coverage on new days; its point predictions don't change."""
    train, test = synth(4, bias=False, seed=7), synth(2, bias=False, seed=8)
    for i, x in enumerate(train + test):
        x.polled_at = x.polled_at  # days already distinct by construction
    cal = Conformal.fit_with(Overconfident, train)
    preds = cal.predict_many(test)
    cover = sum(p["q10_s"] <= x.error_s <= p["q90_s"] for x, p in zip(test, preds)) / len(test)
    assert 0.75 <= cover <= 0.85
    assert all(p["bias_s"] == 0.0 for p in preds)
    raw = sum(0.0 <= x.error_s <= 0.0 for x in test) / len(test)
    assert raw < 0.05


def test_conformal_round_trips_and_noise_gives_no_winner():
    m = Conformal.fit_with(HierModel, synth(3, bias=True))
    again = from_params(m.to_params())
    x = synth(1, bias=True, seed=9)[0]
    a = m.predict(x.line_id, x.stop_id, x.lead_s, x.band, x.disrupted)
    b = again.predict(x.line_id, x.stop_id, x.lead_s, x.band, x.disrupted)
    assert a == b
    assert evaluate(synth(11, bias=False, seed=4), FAST)["winner"] is None  # still nothing invented from noise
