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
