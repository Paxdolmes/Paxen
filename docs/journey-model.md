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

## Amendment 1 (17 November 2026): tracking outages

**What had been seen.** The first replayed day's summary only (4 November, rebuilt from the raw archive):
358 of 400 journeys measured, 49% of departures answered, real minus planned p50 +4.9 and p90 +35.2. No
evaluation had run, no candidate had been scored, and nothing about any journey's individual times had been
looked at.

**Why.** A p90 of 35 minutes over planned on an ordinary day isn't plausible. The likely reason is that the
replay can't tell "no train came" from "nothing was being recorded". On 4 November, Trackernet responses were
only archived from partway through the day. A departure shortly before that point waits until the first train
recorded afterwards, which looks like a long delay.

**The rule.** A departure is **unusable** (`outage`) if, at any point between leaving and arriving, the whole
network's tracking was silent for more than **3 minutes**, meaning no measured arrival on any line. That
includes before the first and after the last arrival recorded that day. While the Tube runs, some train
reaches some platform every few seconds, so a silence that long means the recorder or the feed was down. A
suspension on one line doesn't silence the network, so real delays stay in the ground truth.

**Also changed.**
- Each day's summary now records:
  - when tracking ran;
  - the silent minutes between 06:00 and 22:00;
  - outages, counted apart from tracking gaps;
  - real minus planned by each journey's first line.
- A sort that crashed on arrivals with no recorded direction (16 November) is fixed.

**Re-run.** The replay rules have a version number (`replay.VERSION`, now 2). Every day replayed under an older
version is replayed again, and the evaluation scores every test day again from scratch.

## Amendment 2 (17 November 2026): following trains properly

**What had been seen.**
- The per-line summaries of four days replayed under Amendment 1 (4, 5, 6 and 16 November). Departures on the
  Central, Piccadilly and Circle lines ran a p90 of 42–49 minutes over planned on every day, including days with
  no tracking outage.
- The measured arrivals of 16 November, downloaded and replayed offline.
- A trace of the slowest departures on 16 November, train by train.

No evaluation had run and no candidate had been scored.

**What was wrong.** Three faults in the replay, not in the trains:

1. **Trains missed at a station.** Trackernet misses a train at about one station in eight. It misses some
   platforms altogether: Oxford Circus on the Victoria line is never reported, so 42 panel journeys couldn't be
   measured. A train that passed your stop without being seen there was followed to the end of the line and
   back. Its arrival at your stop on the way back counted as your journey: Ealing Broadway to Bank came out at
   144 minutes against 33 planned.
2. **Trains standing at the end of the line.** A train standing there for several minutes could only be
   boarded by someone who reached the platform before it arrived. Journeys from the ends of lines (Elephant &
   Castle, Barking, Harrow & Wealdstone) waited for the next train instead.
3. **The first train in isn't the first out.** At the end of a line, the first train to arrive isn't always the
   first to leave.

**The rules now.**
- **Missed stations are filled in.** Where a train was seen at two stations a few stops apart, it passed the
  stations between them on NUMBAT's map of the line. They are filled in at times spaced evenly between the two
  sightings. This applies only along one direction of travel, to at most 3 missed stations, and only if it took
  no more than 4 minutes per link.
- **A train is followed only until it turns round.** It is followed until it reaches a station it already passed
  on this ride. An arrival at your stop after that is on its way back.
- **A standing train can be boarded.** You can board a train while it is still at the platform. When it leaves
  is estimated from where it was seen next, less the usual running time there (the median of trains passing
  through). A train that seems to stand for more than 30 minutes was out of service.
- **The rider is informed.** Of the trains you could board, you take the one that gets you there first.

**Effect on 16 November** (all 400 panel journeys now measured, 95% of departures usable):

| | Before | After |
|---|---|---|
| Real minus planned, p50 | +4.6 min | +2.9 min |
| Real minus planned, p90 | +24.8 min | +11.2 min |
| Victoria line only, p50 / p90 | | +0.4 / +2.4 min |
| Jubilee line only, p50 / p90 | | +1.2 / +4.5 min |

Bakerloo rides remain about 3 minutes over the planner's times. That is consistent across stations, so it looks
like the planner being optimistic, not a replay fault. The models learn "usual" from replayed journeys, not from
planned times.

**Re-run.** `replay.VERSION` is now 3. Every day is replayed again, and the evaluation starts from scratch.

## Amendment 3 (17 November 2026, about 17:30 UTC): two more candidates, scored only on new days

**What had been seen.**
- The registered protocol's results on its first 4 test days (11, 12, 13 and 16 November).
- An offline check of 16 November, described under "Why" below.

| h = 30, mean over the 4 test days | MAE | F1, slow |
|---|---|---|
| rules | 4.54 | 0.21 |
| usual | 3.25 | 0.00 |
| persistence | 4.33 | 0.07 |
| journey_gbm | 3.21 | 0.04 (coverage 0.79) |

**Why.**
- **Most of the error is luck.** On 16 November, an "oracle" that knew how the same journey ran within 15
  minutes either side that same day still had an MAE of 2.62 minutes. Against that, usual scored 2.75 and
  journey_gbm 2.67. The waits at the first platform average 3.4 minutes. On an ordinary day, the error is almost
  all the luck of when trains come, which nothing known 30 minutes ahead can predict.
- **The two signals are split between candidates.** "usual" has the best typical time (27% better than the
  rules). Only the rules react to disruptions, which is what decides "leave 10 minutes earlier" (F1 0.21 against
  0 for usual).
- **"Slow" is mostly noise.** A single departure 5 minutes over usual is mostly luck. The question a commuter has
  is whether the journey is slow around that time.

**Added.** The registered protocol above continues unchanged.

1. **usual_status**: usual, plus the minutes the rules add for the line statuses at the issue time. That is the
   rules' forecast with those statuses, less the same forecast with every line on good service; on good service
   it is just usual.
2. **journey_gbm_status**: journey_gbm with those status minutes as one more input.
3. A metric for all candidates: **slow around this time**. The mean real minutes of the journey's departures
   within 15 minutes either side is at least 5 over usual. Its precision, recall and F1 are reported as `*_sys`.

**Test days.** Only test days from **17 November 2026** count. None of those days had been replayed or scored
when this was written.

**Decision.** usual_status or journey_gbm_status replaces the rules if, over at least 7 such test days, all of
these hold:
- its MAE beats the rules' by at least 5% at h = 30 and at h = 60;
- it beats the rules on at least two-thirds of the days at both horizons;
- its F1 for slow around this time at h = 30 is no lower than the rules';
- for journey_gbm_status, its p10–p90 coverage is within 70–90%.

If both qualify, the one with the lower MAE at h = 30 is chosen. The report shows this as `amendment3`, next to
the registered `decision`.

### Result of Amendment 3 (24 November 2026): no change, the rules stay

Scored on the 7 test days from 17 to 23 November, as registered (evaluation of 24 November, 03:12 UTC; replay
version 3). Recording into the database was paused from 19 November 13:10 UTC (disk safety switch). Those days
were rebuilt from the raw archive. Every test day was tracked from 00:00 to 23:59 with no outages.

| h = 30, mean over 17–23 Nov | MAE | MAE vs rules | days beating rules | F1, slow around this time | coverage |
|---|---|---|---|---|---|
| rules | 4.77 | | | 0.169 | |
| usual | 3.29 | −31% | | 0.000 | |
| usual_status | 4.62 | −3.3% | 6 of 7 | 0.195 | |
| journey_gbm | 3.23 | −32% | | 0.035 | 0.79 |
| journey_gbm_status | 3.23 | −32% | 7 of 7 | 0.053 | 0.79 |

At h = 60: usual_status 4.46 against 4.68 (−4.7%, 6 of 7 days); journey_gbm_status 3.25 (−31%, 7 of 7 days,
coverage 0.79, F1 0.046 against 0.162).

- **usual_status** fails on accuracy. It is only 3.3% (h = 30) and 4.7% (h = 60) better than the rules, short of
  the 5% required. It passes the F1 check and is the best of all at flagging a slow time (0.195).
- **journey_gbm_status** fails on F1. It is far more accurate (about 31% lower MAE, every day, coverage in range),
  but it rarely flags a slow time (F1 0.053 against the rules' 0.169).
- The registered `decision` is also no_change (rules), so the briefing, leave-by and alerts keep using the rules.

Seen, not acted on: the most accurate times (journey_gbm) and the best "slow" flags (usual_status) still come from
different candidates. Any combination of the two would need its own amendment, written before the days it is
scored on.
