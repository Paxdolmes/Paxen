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
