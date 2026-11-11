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


def test_gbm_copes_with_signals_missing_from_older_recordings():
    """Rows recorded before queue/gap/feed-age existed have no values: the model must still fit and predict."""
    xs = synth(2, bias=True, seed=11)
    for x in xs:
        x.queue_rank = x.gap_s = x.feed_age_s = None
    m = GBMModel.from_params(GBMModel.fit(xs).to_params())
    p = m.predict(xs[0].line_id, xs[0].stop_id, xs[0].lead_s, xs[0].band, False, queue_rank=2, gap_s=120)
    assert p["q10_s"] <= p["bias_s"] <= p["q90_s"]


# --------------------------------------------------------------------------- storage thinning (thin_history)

def _record_days(session, days: int, per_day: int, start: datetime):
    """per_day predictions a day (London days, GMT in November), each matched by a measured (darwin) arrival."""
    from paxen.db import ObservedArrival, Prediction

    for d in range(days):
        for i in range(per_day):
            polled = start + timedelta(days=d, minutes=10 + i * (1380 // per_day))
            exp = polled + timedelta(seconds=300)
            veh = f"v{d}-{i}"
            session.add(Prediction(source="tfl", polled_at=polled.replace(tzinfo=None), stop_id="910GX", line_id="weaver",
                                   mode="overground", direction="outbound", vehicle_id=veh,
                                   expected_arrival=exp.replace(tzinfo=None), tts_s=300))
            arr = (exp + timedelta(seconds=(i % 7) * 20 - 40)).replace(tzinfo=None)
            session.add(ObservedArrival(source="tfl", stop_id="910GX", line_id="weaver", vehicle_id=veh,
                                        direction="outbound", arrived_at=arr, earliest=arr, latest=arr,
                                        method="darwin", quality=1.0))
    session.commit()


def _key(samples):
    return [(x.polled_at, x.event, x.error_s) for x in samples]


def test_thinning_keeps_exactly_what_the_evaluation_reads(session, monkeypatch):
    from sqlalchemy import func, select

    from paxen import evaluate as ev
    from paxen.db import Prediction

    monkeypatch.setattr(ev, "MAX_PER_DAY", 5)
    monkeypatch.setattr(ev, "PRESAMPLE", 2)  # stride = n // 10: 43 a day -> every 4th prediction is read
    start = datetime(2026, 11, 2, tzinfo=timezone.utc)
    _record_days(session, days=6, per_day=43, start=start)
    before = ev.load_daily(session, "tfl", ("darwin",))
    total = session.scalar(select(func.count()).select_from(Prediction))

    now = start + timedelta(days=5, hours=12)  # 7 Nov: 4-6 Nov (and today) stay complete, 2-3 Nov are thinned
    res = ev.thin_history(session, "tfl", now, keep_full_days=3, max_days=10, pause_s=0)
    assert len(res["days"]) == 2 and res["deleted"] > 0
    assert session.scalar(select(func.count()).select_from(Prediction)) == total - res["deleted"]
    after = ev.load_daily(session, "tfl", ("darwin",))
    assert len(after) == len(before) > 0 and _key(after) == _key(before)

    # the recent days are untouched, and a second run changes nothing
    recent = session.scalar(select(func.count()).select_from(Prediction).where(
        Prediction.polled_at >= (start + timedelta(days=2)).replace(tzinfo=None)))
    assert recent == 4 * 43
    assert ev.thin_history(session, "tfl", now, keep_full_days=3, max_days=10, pause_s=0)["deleted"] == 0


def test_thinning_goes_a_few_days_per_run(session, monkeypatch):
    from paxen import evaluate as ev

    monkeypatch.setattr(ev, "MAX_PER_DAY", 5)
    monkeypatch.setattr(ev, "PRESAMPLE", 2)
    start = datetime(2026, 11, 2, tzinfo=timezone.utc)
    _record_days(session, days=6, per_day=43, start=start)
    now = start + timedelta(days=5, hours=12)
    assert len(ev.thin_history(session, "tfl", now, keep_full_days=3, max_days=1, pause_s=0)["days"]) == 1
    assert len(ev.thin_history(session, "tfl", now, keep_full_days=3, max_days=1, pause_s=0)["days"]) == 1  # the next old day
    assert ev.thin_history(session, "tfl", now, keep_full_days=3, max_days=1, pause_s=0)["days"] == []


def _record_busy_day(session, day_start: datetime, first_hour: int, rest: int):
    """A day with `first_hour` predictions in its first hour and `rest` spread over the remainder, all matched."""
    from paxen.db import ObservedArrival, Prediction

    times = [day_start + timedelta(seconds=3 + i * 3600 // first_hour) for i in range(first_hour)]
    times += [day_start + timedelta(hours=1, seconds=i * 82800 // rest) for i in range(rest)]
    for i, polled in enumerate(times):
        exp = polled + timedelta(seconds=300)
        veh = f"b{day_start:%d}-{i}"
        session.add(Prediction(source="tfl", polled_at=polled.replace(tzinfo=None), stop_id="910GX", line_id="weaver",
                               mode="overground", direction="outbound", vehicle_id=veh,
                               expected_arrival=exp.replace(tzinfo=None), tts_s=300))
        arr = (exp + timedelta(seconds=(i % 9) * 15 - 60)).replace(tzinfo=None)
        session.add(ObservedArrival(source="tfl", stop_id="910GX", line_id="weaver", vehicle_id=veh,
                                    direction="outbound", arrived_at=arr, earliest=arr, latest=arr, method="darwin",
                                    quality=1.0))
    session.commit()


def test_an_interrupted_thinning_run_resumes_with_the_same_sample(session, monkeypatch):
    import time as _time

    from paxen import evaluate as ev

    monkeypatch.setattr(ev, "MAX_PER_DAY", 5)
    monkeypatch.setattr(ev, "PRESAMPLE", 2)
    start = datetime(2026, 11, 2, tzinfo=timezone.utc)
    _record_days(session, days=4, per_day=43, start=start)
    before = ev.load_daily(session, "tfl", ("darwin",))
    now = start + timedelta(days=3, hours=12)

    class Stop(Exception):
        pass

    def stop(_s):
        raise Stop

    monkeypatch.setattr(_time, "sleep", stop)  # the run dies after its first 10-minute slice
    try:
        ev.thin_history(session, "tfl", now, keep_full_days=1, pause_s=1)
    except Stop:
        pass
    monkeypatch.undo()
    monkeypatch.setattr(ev, "MAX_PER_DAY", 5)
    monkeypatch.setattr(ev, "PRESAMPLE", 2)
    assert _key(ev.load_daily(session, "tfl", ("darwin",))) == _key(before)  # mid-way: still the same sample
    ev.thin_history(session, "tfl", now, keep_full_days=1, pause_s=0)
    assert _key(ev.load_daily(session, "tfl", ("darwin",))) == _key(before)


def test_a_day_thinned_before_strides_were_recorded_is_recovered(session, monkeypatch):
    from sqlalchemy import func, select

    from paxen import evaluate as ev
    from paxen.db import Prediction

    monkeypatch.setattr(ev, "MAX_PER_DAY", 100)
    monkeypatch.setattr(ev, "PRESAMPLE", 2)  # stride = n // 200
    day = datetime(2026, 11, 2, tzinfo=timezone.utc)
    _record_busy_day(session, day, first_hour=1000, rest=400)
    _record_busy_day(session, day + timedelta(days=1), first_hour=1000, rest=400)
    before = ev.load_daily(session, "tfl", ("darwin",))
    k = 1400 // 200
    # the previous version thinned the first hour of 2 Nov, then stopped (no stride recorded)
    first_hour_end = (day + timedelta(hours=1)).replace(tzinfo=None)
    session.query(Prediction).filter(Prediction.polled_at < first_hour_end, Prediction.id % k != 0).delete(
        synchronize_session=False)
    session.commit()
    assert _key(ev.load_daily(session, "tfl", ("darwin",))) == _key(before)
    ev.thin_history(session, "tfl", day + timedelta(days=2, hours=12), keep_full_days=0, pause_s=0)
    assert _key(ev.load_daily(session, "tfl", ("darwin",))) == _key(before)
    left = session.scalar(select(func.count()).select_from(Prediction).where(
        Prediction.polled_at < (day + timedelta(days=1)).replace(tzinfo=None)))
    assert left <= 1400 // k + 1


# --------------------------------------------------------------------------- arrivals trim (trim_arrivals)

def _record_network_day(session, start: datetime, days: int, per_day: int):
    """Several predictions per train visit (as the recorder stores them), each visit seen by Trackernet *and* inferred
    from countdowns, plus visits nobody predicted (a stop the recorder doesn't store) and one train that arrives
    just after midnight, predicted the evening before."""
    from paxen.db import ObservedArrival, Prediction

    def arrival(veh, arr, method, direction):
        session.add(ObservedArrival(source="tfl", stop_id="940GZZLUFBY", line_id="district", vehicle_id=veh,
                                    direction=direction, arrived_at=arr, earliest=arr, latest=arr, method=method,
                                    quality=1.0 if method == "trackernet" else 0.8))

    for d in range(days):
        for i in range(per_day):
            arr = (start + timedelta(days=d, minutes=20 + i * (1380 // per_day))).replace(tzinfo=None)
            veh = f"t{d}-{i}"
            for lead in (840, 600, 360, 120, 90, 60, 30):  # one per lead group, then the last two minutes
                polled = arr - timedelta(seconds=lead + 20)
                session.add(Prediction(source="tfl", polled_at=polled, stop_id="940GZZLUFBY", line_id="district",
                                       mode="tube", direction="inbound", platform="Eastbound - Platform 1",
                                       vehicle_id=veh, expected_arrival=arr + timedelta(seconds=(i % 5) * 10 - 20),
                                       tts_s=lead))
            arrival(veh, arr, "trackernet", "eastbound")
            arrival(veh, arr + timedelta(seconds=15), "countdown_inferred", "inbound")
            arrival(f"x{d}-{i}", arr, "trackernet", "westbound")  # a train nobody predicted
    # 23:55 the evening before day 2, arriving 00:10 on day 2
    late = (start + timedelta(days=2) - timedelta(minutes=5)).replace(tzinfo=None)
    session.add(Prediction(source="tfl", polled_at=late, stop_id="940GZZLUFBY", line_id="district", mode="tube",
                           direction="inbound", platform="Eastbound - Platform 1", vehicle_id="night",
                           expected_arrival=late + timedelta(minutes=15), tts_s=900))
    arrival("night", late + timedelta(minutes=15), "trackernet", "eastbound")
    session.commit()


def test_trimming_arrivals_changes_nothing_training_or_evaluation_reads(session, monkeypatch):
    from sqlalchemy import func, select

    from paxen import evaluate as ev
    from paxen.db import DaySample, ObservedArrival
    from paxen.forecast import load_samples

    monkeypatch.setattr(ev, "MAX_PER_DAY", 5)
    monkeypatch.setattr(ev, "PRESAMPLE", 2)  # 7 x 40 = 280 predictions a day -> every 28th is kept
    start = datetime(2026, 11, 2, tzinfo=timezone.utc)
    _record_network_day(session, start, days=5, per_day=40)
    now = start + timedelta(days=4, hours=12)
    ev.thin_history(session, "tfl", now, keep_full_days=1, max_days=10, pause_s=0)  # 2-4 Nov thinned
    ev.thin_history(session, "tfl", now, keep_full_days=1, max_days=10, pause_s=0)
    reads = lambda: (_key(ev.load_daily(session, "tfl", ("trackernet",))), _key(ev.load_daily(session, "tfl", None)),  # noqa: E731
                     _key(load_samples(session, "tfl")))
    before = reads()
    n = session.scalar(select(func.count()).select_from(ObservedArrival))

    res = ev.trim_arrivals(session, "tfl", max_days=10, pause_s=0)
    assert res["deleted"] > 0.6 * 3 * 40 * 3  # most of the thinned days' arrivals had nothing left to pair with
    assert session.scalar(select(func.count()).select_from(ObservedArrival)) == n - res["deleted"]
    assert reads() == before and before[0]  # identical pairs for training and both evaluations
    # the train predicted before midnight keeps its arrival exactly when that prediction survived thinning
    from paxen.db import Prediction

    night_pred = session.scalar(select(Prediction.id).where(Prediction.vehicle_id == "night"))
    night_arr = session.scalar(select(ObservedArrival.id).where(ObservedArrival.vehicle_id == "night"))
    assert (night_arr is not None) == (night_pred is not None)
    # recent (unthinned) days are untouched
    recent = (start + timedelta(days=3)).replace(tzinfo=None)
    assert session.scalar(select(func.count()).select_from(ObservedArrival).where(
        ObservedArrival.arrived_at >= recent)) == 2 * 40 * 3
    assert all(r.arrivals_trimmed == r.thinned for r in session.scalars(select(DaySample)))
    assert ev.trim_arrivals(session, "tfl", max_days=10, pause_s=0)["deleted"] == 0  # once per day


def test_a_day_waits_until_the_day_before_is_thinned(session, monkeypatch):
    from paxen import evaluate as ev
    from paxen.db import DaySample

    start = datetime(2026, 11, 2, tzinfo=timezone.utc)
    _record_network_day(session, start, days=3, per_day=10)
    session.add_all([DaySample(source="tfl", day="2026-11-01", stride=1, thinned=False),
                     DaySample(source="tfl", day="2026-11-02", stride=1, thinned=False),
                     DaySample(source="tfl", day="2026-11-03", stride=1, thinned=True)])
    session.commit()
    assert ev.trim_arrivals(session, "tfl", max_days=10, pause_s=0)["days"] == []  # 2 Nov's predictions aren't final


def test_arrivals_predicted_the_evening_before_are_kept(session):
    from sqlalchemy import select

    from paxen import evaluate as ev
    from paxen.db import DaySample, ObservedArrival, Prediction

    late = datetime(2026, 11, 2, 23, 50)  # GMT = London in November
    session.add(Prediction(source="tfl", polled_at=late, stop_id="S", line_id="district", mode="tube",
                           direction="inbound", vehicle_id="night", expected_arrival=late + timedelta(minutes=20),
                           tts_s=1200))
    for veh, at in (("night", late + timedelta(minutes=21)), ("other", late + timedelta(minutes=30))):
        session.add(ObservedArrival(source="tfl", stop_id="S", line_id="district", vehicle_id=veh,
                                    direction="eastbound", arrived_at=at, earliest=at, latest=at,
                                    method="trackernet", quality=1.0))
    session.add_all([DaySample(source="tfl", day="2026-11-02", stride=1, thinned=True),
                     DaySample(source="tfl", day="2026-11-03", stride=1, thinned=True)])
    session.commit()
    assert ev.trim_arrivals(session, "tfl", max_days=10, pause_s=0)["deleted"] == 1
    assert [v for v, in session.execute(select(ObservedArrival.vehicle_id))] == ["night"]
