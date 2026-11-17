# Journey model: pre-registered evaluation

**Registered 17 November 2026, before any replayed journey time or any result from this evaluation had been seen.**
Changes after results are seen go in a dated amendment at the end, and the evaluation is then re-run from scratch.

## What it is for

Paxen's job is to say, 30 to 60 minutes before you leave, whether your usual journey will take longer or shorter
than usual today, and so whether to leave earlier, later or another way. The countdown model
(docs/model-evaluation.md) only sharpens live train countdowns in the last minutes before a train; it doesn't
answer that. This model does: it predicts **door-to-door journey minutes** for a departure, made **ahead of time**.

## Ground truth: replayed journeys (`backend/paxen/replay.py`)

Trackernet records when each Tube train reaches each platform. For any journey and departure time, the real
journey is replayed:

- you reach the first platform at the departure time;
- you board the first train that afterwards reaches your stop on the same line (one that reached the platform up
  to 20 s before you is still there);
- trains that turn short, turn round or go another way are let go;
- a walk at a change takes the planner's walking time; then the next leg starts.

The answer is the minutes from the first platform to the last. A departure is **unusable** if any train it let go
was later seen beyond your stop in the same direction without being seen at it (a tracking gap, not a train that
didn't stop), or if no train came within 60 minutes. Unidentified trains (placeholder set numbers, about a third
of Metropolitan line trains) can't be followed and are never boarded; if one reached your platform before the
train you boarded, we can't tell whether it would have taken you, so that departure is unusable too.

**The panel** (`backend/paxen/data/journey_panel.json`) is fixed: 40 home stations across every measured line ×
10 central work stations, planned once by TfL's journey planner (Tube only, quickest route at 08:30 on a
weekday). Every journey is replayed for every departure every 5 minutes from 06:00 to 22:00, every day. The
panel is not changed to suit results; a new panel is a new amendment.

## The task

For panel journey *j*, departure *T* and **horizon** *h* ∈ {60, 30, 10} minutes, predict the replayed minutes
*y(j, T)* using only what was known at the **issue time** *T − h*:

- replayed journeys that had **finished** by *T − h* (their arrival time ≤ *T − h*);
- line statuses as they stood at *T − h* (`context_events`, kept permanently);
- weather for hours that had **ended** by *T − h* (`weather_hours`). Forecasts aren't stored as they were issued
  yet, so no forecast is used; that will be a later amendment once they are;
- the calendar: weekday or weekend, bank holidays.

Any use of later information is a bug. A test checks that changing anything after *T − h* doesn't change a
prediction.

## Candidates

1. **rules**: what the app does today: the panel's planned minutes adjusted the way `engine.forecast_journey`
   does with the line statuses at *T − h* (ride multipliers by status, chance a disruption is still on, waits from
   NUMBAT's timetabled frequencies). No live countdowns.
2. **usual**: the median replayed minutes for this journey in the same 15-minute slot on earlier days of the same
   kind (weekday / weekend); planned minutes when there is no history yet.
3. **persistence**: *usual(T)* plus the latest finished departure's deviation from its own usual
   (*y(j, T′) − usual(j, T′)*, the latest *T′* whose journey ended by *T − h*).
4. **journey_gbm**: gradient-boosted quantile regression (p10/p50/p90) of *y − usual*. Inputs: usual, planned
   minutes, changes, the deviations of the last 3 finished departures of this journey and how long ago each
   finished, the median deviation of all panel journeys sharing a line with it over the last 30 minutes,
   horizon, time of day, weekday/weekend, bank holiday, for each line on the journey its status category at
   *T − h* and how long that status has lasted, and the last finished hour's rain, temperature, gusts and
   snowfall. The first line of the journey as a category.

## Protocol

- Rolling days, like the countdown model: every day *D* with at least 7 earlier days of replayed journeys is a
  test day. Candidates that learn are fitted on days before *D* only and predict all of *D*.
- Scored on usable departures only, every horizon separately.
- **MAE** of the p50 in minutes, overall and in the peaks (07:00–10:00 and 16:30–19:30).
- **The decision**: a departure is *slow* if *y − usual ≥ 5* minutes. Precision and recall of "predicted slow"
  (p50 deviation ≥ 5), and their F1.
- **Coverage** of p10–p90 for journey_gbm (honest if 70–90%).

**journey_gbm replaces the rules in the app only if**, over at least 7 test days:

1. its mean MAE beats the best of rules / usual / persistence by **at least 5%** at h = 30 and at h = 60;
2. it beats that baseline on **at least two-thirds** of test days at both horizons;
3. its F1 for slow departures is **not lower** than the best baseline's at h = 30;
4. its p10–p90 coverage is within **70–90%**.

If it fails, the best baseline that beats rules on conditions 1–3 may replace the rules instead.

## Limits

- Tube only: Trackernet measures nothing else. Other modes keep the rules.
- Platform to platform: walking to and from stations is the planner's time and not modelled.
- Users' own commutes aren't the panel; their legs on panel lines inherit the model, and their own trips
  (automatic trips) check it.
