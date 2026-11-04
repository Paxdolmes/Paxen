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
