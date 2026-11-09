# How Paxen decides whether a model is better than TfL

*Written on 4 November 2026, before any multi-day results existed, so the rules can't be bent to fit the data.*

## The question
Does a Paxen correction make TfL's live countdowns more accurate, on days the model has never seen? If not, Paxen
shows TfL's own numbers.

## Ground truth
- **Tube:** measured arrivals from Trackernet (the signalling system's "At Platform" time). Preferred whenever
  available.
- **Other modes:** arrivals inferred from countdowns (bounded and quality-scored). Reported separately, because
  they're less certain.
- A prediction counts only if it can be paired with *the same train, same direction* within a plausible time
  window.

## Candidates (all fixed in advance)
| Id | Model | Why it's in the running |
|---|---|---|
| `provider` | TfL's countdown, uncorrected | the baseline to beat |
| `hier` | Hierarchical median correction (network → line → stop → time band), the current model | simple, interpretable |
| `hier_ctx` | `hier`, plus position in the queue (1st/2nd/3rd train) and weekday/weekend | adds context available at prediction time |
| `gbm` | Gradient-boosted quantile model (p10/p50/p90) on all features below | can learn interactions; most flexible |

**Features**, all known at the moment of the prediction: line, stop, lead time, time band, weekday/weekend, line
status category, the train's position in the queue at that stop, the gap to the train ahead, and feed age. No
feature uses anything from after the prediction was made.

## Protocol: rolling days
1. Group samples by **London calendar day**.
2. For each test day D (the most recent `k` days, `k ≤ 7`): train on **all days before D**, test on **D only**.
   Never train on D or later.
3. A run needs **at least 7 training days** before the first test day and **at least 3 test days**. Otherwise the
   report says "not enough data", no model is active, and Paxen shows TfL's own numbers.
4. **Metrics per test day:** mean absolute error (seconds), % within 2 minutes, and p10–p90 interval coverage.
   Also broken down by lead time (0–2, 2–5, 5–10, 10–20, 20+ min), line and peak/off-peak.

## Decision rule (applied automatically)
A candidate is **eligible** if, across the test days:
1. its mean MAE is **at least 3% lower than `provider`**, and
2. it beats `provider` on **at least two-thirds of test days**, and
3. its p10–p90 coverage is **between 70% and 90%** (an honest 80% range).

Among eligible candidates, the **lowest mean MAE** wins. If two are within 1% of each other, the **simpler** one
wins (`hier` < `hier_ctx` < `gbm`). If none is eligible, Paxen keeps showing TfL's numbers. The winner is then
re-fitted on all days and served.

## What is not allowed
- Changing candidates, features or thresholds after seeing results, without writing down the change and why in
  this file, and re-running from scratch.
- Judging on fewer than 3 test days, or on a single line.
- Mixing measured and inferred ground truth in the headline number. The headline uses measured (Tube); inferred is
  reported alongside.

Run it: `python -m paxen.evaluate` (prints the report and, if a candidate is eligible, promotes it).

---

## Amendment 1 (4 November 2026, before any multi-day results; nothing below has been run on recorded data)

Each change is justified by reasoning or synthetic tests, not by scores on recorded data. Every change makes
the protocol **stricter or more honest**; none relaxes the original rules, which all still apply.

**A1.1 Purge at the split boundary.** A training sample whose *outcome* (the measured or inferred arrival
time) falls on or after the start of the test day is dropped from training. Without this, a prediction made at
23:55 for a train arriving at 00:10 teaches the model an outcome from inside the test day, which is standard
label leakage in time-series validation (purged cross-validation; López de Prado, *Advances in Financial Machine
Learning*, 2018, ch. 7). The effect is small (the network is quiet around midnight), but it costs nothing and
removes the leak.

**A1.2 A decision-horizon requirement (added to the eligibility rules).** The headline MAE weights every stored
prediction equally, so it's dominated by whatever the recorder stores most densely. That's the last two minutes
before arrival, the horizon that matters least for "should I leave now?". So, in addition to rules 1–3, a
candidate must also:

> 4. beat `provider` by **at least 3%** on the **decision MAE**: the average, over the lead buckets
>    **2–5, 5–10 and 10–20 minutes** (equal weight per bucket), of each bucket's MAE, where every train arrival
>    counts **once** per bucket (its predictions in that bucket are averaged first).

Counting each arrival once also stops one train, observed many times, from dominating, so correlated samples
don't inflate the result. The 3% margin is the same as rule 1; it isn't tuned.

**A1.3 Calibrated intervals for every challenger (conformalized quantile regression).** Each non-provider
candidate's p10–p90 interval is recalibrated by split CQR (Romano, Patterson & Candès, *Conformalized Quantile
Regression*, NeurIPS 2019), per lead bucket ("Mondrian" conformal):
- Within the training days only, the candidate is fitted on all but the **last** training day; on that last day
  the conformity score is `max(q10 − y, y − q90)`, and per lead bucket the `⌈(n+1)(0.8)⌉/n` empirical quantile
  `Q_b` of the scores is taken (falling back to the pooled quantile when a bucket has fewer than 50 scores).
- The served candidate is then refitted on all training days, and its interval is widened (or narrowed, if
  `Q_b < 0`) by `Q_b`. Point predictions are unchanged.
- Rationale: quantile models' raw intervals are often miscalibrated out of sample. CQR gives coverage that's
  approximately right under exchangeability. Refitting on all days before applying `Q_b` is a common
  approximation; it's recorded here so it isn't mistaken for the exact guarantee. The provider baseline is not
  recalibrated (it isn't a candidate for promotion).

**Not adopted (and why):** sample weights by ground-truth quality (the headline already uses measured truth, all
quality 1.0); upstream-delay and time-since-status-change features (they need a new recorder signal and
validation; listed for later); extending measured truth to the Overground and Elizabeth line (there's no
Trackernet equivalent; National Rail's Darwin feed carries actual times for both and is the planned route).

---

## Amendment 2 (5 November 2026, before any multi-day results; nothing below has been run on recorded data)

Written before the first verdict (about 14 November, once 10 days of measured arrivals exist). Nobody involved has
seen a protocol result on recorded data. Rules 1-4, the ground truth and Amendment 1 are unchanged.

**A2.1 One new candidate, `gbm_numbat`.** It's the `gbm` candidate (same model, hyperparameters and conformal
intervals per A1.3), with four extra features from TfL's **NUMBAT 2025** (`paxen/numbat.py`: a *typical* autumn
2025 day for each of Mon / Tue-Thu / Fri / Sat / Sun, published July 2026, before any recording; it's a fixed table, so
nothing in it comes from the test days). Each feature is looked up for the prediction's station and line, in the
platform's direction when its name gives one ("Westbound - Platform 1"; otherwise averaged over directions), over the
hour around the train's expected arrival (prediction time + lead), all known when the prediction is made:

| Feature | Definition | Why it could matter |
|---|---|---|
| `sched_headway_s` | scheduled seconds between trains (3600 / timetabled trains per hour) | sets how much a late train matters, and how full the platform gets |
| `gap_ratio` | `gap_s` / `sched_headway_s` (the gap behind the train ahead vs the timetabled one) | above 1, more passengers are waiting for this train than usual, so it dwells longer and runs later: the start of bunching |
| `activity_per_train` | typical boarders plus alighters per train at that platform | the main driver of dwell time |
| `load_per_train` | typical passengers on board arriving trains | crowded trains board more slowly |

TfL's countdown doesn't use demand. `hier` and `gbm` only see a stop's average error by five time bands. These
features add 15-minute demand that carries across stations, and a scale for the existing gap feature.

**A2.2 Order of simplicity:** `provider` < `hier` < `hier_ctx` < `gbm` < `gbm_numbat` (it depends on an extra data
source). A tie within 1% still goes to the simpler model, so NUMBAT must earn its place on unseen days.

**A2.3 Honest cost.** A fifth candidate slightly raises the chance that one passes by luck. The thresholds aren't
loosened to compensate: they're the same 3% / two-thirds / 70-90% / decision-horizon rules. If NUMBAT data is missing
at run time, the four columns are empty and dropped (as for any never-observed signal), so the candidate falls back
to being `gbm`.

**Separate from this protocol:** the journey forecast now also uses NUMBAT frequencies and TfL's timetable for waits
when there is no live countdown (docs/historical-data.md). That doesn't correct TfL's countdown, so it isn't a
candidate here. It was checked directly against live arrivals instead.

---

## Amendment 3 (6 November 2026, before any multi-day results; nothing below has been run on recorded data)

Rules 1-4, the ground truth for the headline and Amendments 1-2 are unchanged.

**A3.1 Measured rail truth.** From 6 November the worker records Darwin's actual arrival times for Overground and
Elizabeth line trains (`paxen/darwin.py`, `ObservedArrival.method = "darwin"`). The match to TfL's predictions needs
no inference: TfL's vehicle id is Darwin's train id and TfL's rail stop id is `910G` + Darwin's TIPLOC. Darwin's times
are to the minute, so each arrival is stored as a 59-second window starting at the stated minute.

**A3.2 Reported, never decisive.** The promotion decision stays on Trackernet-measured Tube arrivals only. The same
protocol (same candidates, rules, purge and intervals) is run separately on Darwin-measured pairs and reported as
`rail_measured`. It doesn't promote, demote or veto anything. A rail-specific model would need its own amendment,
written before its results are seen.

**A3.3 Why not merge them.** Rail and Tube errors differ in scale and cause (signalling-based train describers vs
platform countdowns), and Darwin's minute rounding adds up to ±30 s of noise that Trackernet doesn't have. Pooling
them would change the headline metric after the protocol was registered.

---

## Storage note (9 November 2026, before any multi-day results; not a change to the protocol)

The recorder stores about 1.8 million predictions a day, but `load_daily` only ever reads every stride-th one (by
prediction id) of a busy day, where stride = day's predictions // (MAX_PER_DAY x PRESAMPLE). From 9 November,
`thin_history` deletes the other predictions of each London day once the next day has ended (yesterday and today stay
complete for arrival inference, which reads 20 minutes back, and Darwin matching, 6 hours). Afterwards that day's stride is 1 and `load_daily` reads exactly
the same predictions, so every report and promotion decision is unchanged; tests check this on SQLite and Postgres.
Arrivals are not thinned, and the raw archive keeps every original response.

At the same time, `load_samples` now returns pairs in prediction-id order before sorting them by time, so the seeded
per-day sample (rule: "same seed, same sample") no longer depends on the order the database returns rows in.

