# Paxen: from concept brief to MVP

The brief's thesis: *don't just tell people how to get somewhere. Learn how they travel, predict when the usual
journey is going wrong, and recommend a better decision before they lose time.* This MVP covers brief phases
1–3 (data recorder, forecast lift, commute MVP), so a closed beta (phase 4) can start on top of it.

## How the brief maps to the code

| Brief | Where |
|---|---|
| Collect & standardise data (§4A) | `providers/` → common model in `domain.py`; `recorder.py` keeps raw payloads **and** normalised rows, with source, timestamp, latency and errors |
| Historical ground truth (§4B) | `recorder.infer_arrivals`: a vehicle that was ≤2 min away and then vanished from the countdown is recorded as an *inferred* arrival, with earliest/latest bounds and a quality score. It is never labelled as measured. |
| Provider baseline / feed quality | provider countdowns and planner legs; stale feeds downgrade confidence (`engine.forecast_journey`) |
| Arrival correction | `forecast.CorrectionModel`: an interpretable hierarchy (network → line → stop → time band) of error distributions with shrinkage. It returns an *adjustment plus an interval* and never overwrites the feed. |
| Evaluation & promotion | `forecast.train_and_maybe_promote`: time-ordered holdout, metrics by lead time and line, promoted only if it beats the provider by ≥3% MAE |
| Disruption impact | line status widens headways, stretches ride times and widens the uncertainty interval; suspended lines make a route infeasible |
| Personal commute model | `engine.personal_baseline`: the user's own trips on the usual route, same day-type and time window. Cold start falls back to typical network time. |
| Route decision | `engine.rank`: preference-weighted score (balanced / fastest / reliable / least walking / fewest changes) that penalises uncertainty, not just nominal speed |
| Outcome learning | trips store the forecast made at departure, so insights report forecast error and interval hit-rate |
| Smart alerts (§2, §7) | `engine.maybe_alert`: only inside the commute window, outside quiet hours, when the usual route is ≥N min slower **and** an alternative is ≥M min better with non-low confidence (or the usual route isn't running). Includes a cooldown so the same situation isn't re-sent. |
| Crowding (§6) | `engine.crowding_estimate`: phase-1 evidence only (time of day + disruption spill-over), always labelled as an estimate |
| Train fullness | `fullness.py`: how full each of the next trains is likely to be as it leaves your station ("Likely packed" / "Standing room" / "Space likely"), with advice to wait for a clearly emptier train a few minutes behind. NUMBAT typical load × the live gap ahead of the train × damped live busyness at this station and the two before it, against approximate train capacity. Always an estimate; answers to "Did you get on the first train?" (`boarding_reports`, totals on `/v1/health`) check it |
| Privacy (§7) | places rounded to ~11 m; no background location (schedule-based); pause monitoring; edit/delete places; clear history; delete account; inferred places need confirmation |
| Success metrics (§10) | `GET /v1/insights`: provider vs corrected MAE, % within 2/5 min, interval coverage, minutes saved, alerts rated useful, alerts followed |

## What I added
- **A simulated London corridor** (`providers/sim.py`): deterministic, with stable vehicle ids, a realistic
  provider bias that grows with lead time, and switchable disruption scenarios. It means the whole
  predict → observe → learn loop runs and is tested offline, and you can demo it on demand.
- **Ranges, not just times**: every option carries a p10–p90 arrival window and an "on-time chance".
- **"Make this my usual route"** and **trip logging** ("Start this route" / "I've arrived"): the explicit
  feedback loop that builds the personal baseline without background location.
- **Simulator controls** in the app for demos and user interviews.

## What I cut (for now)
- **Live vehicle map.** The brief itself says to prototype alerts and comparison before a big general map.
  The Network tab is a status list instead.
- **Inferred Home/Work from location history and background location.** These are the biggest adoption and
  privacy risk, and the brief offers manual schedules as a first-class path. The data model already
  supports `source="inferred"` with explicit confirmation.
- **Native app.** The UI is a mobile-first PWA built with v0 (Next.js), and the design tokens are kept
  platform-neutral so a React Native/Expo port can reuse them. Push delivery already speaks the Expo push API.
- **Gradient-boosted models.** The interpretable model gets most of the lift (in the sim, about 42% lower MAE)
  and is explainable. Swap it in later behind the same `predict()` interface once real data justifies it.

## Before production
See [data-sources.md](data-sources.md). In short: confirm TfL/National Rail commercial terms, attribution and
retention; replace anonymous tokens with proper accounts; move workers out of the API process; and use
PostgreSQL (+ partitioning or TimescaleDB for `predictions`).
