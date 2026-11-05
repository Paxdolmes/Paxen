# Historical data: what's useful, what Paxen now uses, and what it changed (5 Nov 2026)

Daniel found two lists of historical TfL datasets (*TfL Tube Journey Time Datasets* and *London Underground
Historical Data Guide*). This is the assessment of each, against what Paxen actually predicts.

## What Paxen predicts, and what data could help

| Part of Paxen | What it needs | Before today |
|---|---|---|
| **Arrival correction** (adjusts TfL's live countdown) | many *actual* arrivals paired with the countdowns that predicted them | Paxen's own recordings: Trackernet measured arrivals, about 11,000 an hour, since 4 Nov |
| **Journey forecast, without a live countdown** (planned trips, later legs, feed outages) | how often trains run, timetables, how long changes take | one flat headway per mode (every Tube line "every 4 minutes", all day); changes between trains took no time |
| Crowding | how busy things usually are | TfL's live station-busyness API |

The key point: **none of the public datasets records actual train arrivals at scale**, which is what the correction model
learns from. The only one that does (NetMIS) is a single Sunday on one line. Paxen's own Trackernet recording is
already a bigger, current version of exactly that. What the historical data *can* do is replace guesses in the journey
forecast with TfL's real service patterns, and give the correction model context it can't see in the countdown.

## Verdict on each dataset

| Dataset | Verdict | Why |
|---|---|---|
| **NUMBAT** (typical-day frequencies, loads, boarders, 15-min) | ✅ **Used (2025 edition)** | Real scheduled trains per hour for every link and day type replace the flat guess. Typical demand becomes features for a new model candidate. Downloadable here (TfL's open-data bucket). |
| **Timetables / route topology** | ✅ **Used** | Via the TfL Journey Planner, which already returns timetabled departures, plus NUMBAT's link network for branches. No separate TransXChange download was needed (tfl.gov.uk is blocked here anyway). |
| **Tube interchange times** (Hugging Face) | ⚠️ Idea used, dataset not | Hugging Face is blocked by this environment's network settings. Changes were costing 0 minutes, so Paxen now uses the connection time TfL's own planner allows. The dataset could refine that later. |
| **TrackerNet** | ✅ Already used | It's Paxen's measured ground truth since 4 Nov. |
| **NetMIS District line, 23 Mar 2025** (FOI-4221-2425) | ❌ Not now | foi.tfl.gov.uk is blocked here. Even downloaded, it's one Sunday on one line; Trackernet records all lines every day. **Best use: as a template for an FOI request** (below). |
| **Oyster / ODX journey durations** | ❌ Not available | ODX isn't public (FOI only). The 2009 5% sample is 17 years old (no Elizabeth line, old Overground) and its download wasn't verified. Worth an FOI for anonymised station-pair durations. |
| **RODS** | ❌ Superseded | NUMBAT is built from RODS plus ticketing data, and RODS stops in 2017. |
| **Daily station footfall** (2019 on) | ❌ Not now | Daily totals, published weekly after the fact, so it can't describe *today* when a prediction is made. NUMBAT's 15-minute typical demand is what dwell times depend on. |
| **LU Performance Almanac** | ❌ Not used | Blocked here (London Datastore), and its four-weekly line averages say nothing about a particular train or hour. Paxen's recordings will measure reliability directly. |
| **DUNNART** | ❌ Not available | Not in TfL's open data. |
| **Line status FOI archives** | ⏳ Later | Blocked here. Useful for a future "how long will this disruption last?" feature, not the current models. |
| **Met line T402 FOI** | ❌ Not usable | Only counts within/over 2 and 5 minutes; no dated rows (as your guide says). |

Also in TfL's bucket and not used for now: BUSTO (bus demand by route; relevant only if bus prediction becomes a focus),
annual station counts and LU train loading (covered by NUMBAT).

## What was added

### 1. NUMBAT 2025 in Paxen's data (`backend/paxen/numbat.py`, `backend/paxen/data/numbat_2025.json.gz`)
- TfL's NUMBAT 2025 outputs (typical autumn 2025, published July 2026) for Monday, Tuesday-Thursday, Friday, Saturday
  and Sunday: scheduled trains, passenger loads, and boarders/alighters per quarter hour. Covers 1,189 links and 1,203
  platform-directions on the Underground, Overground, Elizabeth line, DLR and trams. 1.7 MB compressed, 16 MB in memory.
- Every TfL stop ID on those lines (676) is matched to its NUMBAT station, except Willesden Green on the
  Metropolitan, where Met trains don't stop. Hand-checked cases: Bank and Monument (NUMBAT treats them as one
  station), both Paddingtons, and Edgware Road.
- Rebuild: `python -m paxen.numbat build` (needs TfL's bucket and API).

### 2. Waits when there's no live countdown (`engine.forecast_journey`)
- **Frequency:** the leg's scheduled trains per hour for that day and time, taken from its least-served link, so a
  branch's own service counts, not the busier trunk.
  Example: District to Richmond every ~9 min, Met from Amersham every 15, Victoria every 1.8, Night Tube every 10.
- **Timetable:** on services 8+ minutes apart (Overground, Elizabeth line branches, outer Tube branches, National
  Rail), the wait is timed to the planner's scheduled departure, allowing for the chance of just missing it.
  Buses and trams keep the frequency estimate (they're run to even gaps, not to the timetable).
- **Changing trains:** when the planner lists one train straight after another, Paxen now adds the walk between them
  (TfL's planned connection, minus half a headway; at most 12 min). It was 0 before. For example, Weaver to
  Elizabeth line at Liverpool Street is ~10 minutes, and Paxen had that journey arriving 10 minutes early.
- When the planner offers several departures of the same route, Paxen keeps the first to arrive, not the shortest ride.
- Each leg now says where its wait came from (`wait_basis`: live, timetable, frequency or typical).

### 3. A new correction-model candidate, `gbm_numbat` (pre-registered)
Same as `gbm`, plus four NUMBAT features: scheduled headway, gap behind the train ahead relative to it (an early sign
of bunching), boarders plus alighters per train (what stretches dwell times) and passengers on board. Written into
the rules **before** any multi-day results ([Amendment 2](model-evaluation.md)). The fair test decides on unseen days,
and its simpler rivals win any tie. **First verdict: around 14-15 November**, once there are 10 days of measured
arrivals.

## Did it help? Live check, Thursday 5 November, 10:49-11:07 (`python -m paxen.waitcheck`)
219 random single-line trips across 15 lines (Central, District and the Suffragette line were disrupted, so they were
left out). Each trip started 10-12 minutes ahead. The "truth" is the first train TfL's live countdown then showed
calling at the trip's destination.

| Wait estimate (no live countdown) | Mean error | Bias |
|---|---|---|
| Before: flat headway per mode | 3.7 min | 2.9 min too optimistic |
| NUMBAT frequency only | 3.0 min | 0.5 min too optimistic |
| **Now: timetable (8+ min apart) or NUMBAT frequency** | **1.6 min** | 0.5 min too optimistic |

| | Before | Now |
|---|---|---|
| Services 8+ min apart (122 trips) | 5.0 min | **1.4 min** |
| Services under 8 min apart (97 trips) | 1.9 min | 1.9 min (no change, as expected) |
| Overground (90) | 5.0 min | **1.2 min** |
| Elizabeth line (18) | 7.1 min | 4.3 min |
| Tube (104) | 2.1 min | 1.5 min |
| DLR (7) | 1.6 min | 1.7 min |

The new estimate was closer on 154 trips and worse on 62. Planned trips now mostly land on TfL's timetabled arrival.
Example: leaving for Amersham station at 08:00, Paxen now says 09:06, as timetabled (next train 08:14). It used to
assume a 2-minute wait on any Tube line and said 08:58.

**Caveats, honestly:**
- It's one morning off-peak on one weekday. Re-run it at peaks and weekends with `python -m paxen.waitcheck`.
- The truth is TfL's own countdown 10-25 minutes ahead (accurate to about a minute). For the Overground that far ahead,
  it's probably still the timetable, so the timetable method's Overground score is partly circular.
- Trips where no qualifying train was yet on the board were skipped. That drops long waits, which flatters the old
  flat guess, so the improvement is if anything understated.
- The Elizabeth line is still too optimistic by about 3 minutes (irregular gaps on the outer branches).
- The change-walk allowance is a heuristic from TfL's planner. It's not yet checked against measured journeys.

## Update (5 Nov, later): line-status history and the other files Daniel sent

| File | Verdict | Why |
|---|---|---|
| **Trains service status messages** (every Tube line status, Apr 2022 - Oct 2026, ~120k messages) | ✅ **Used** | It's the "historical line status" FOI request, already answered. Paxen learns how long disruptions last. |
| Service operated (% of timetable) / km operated | ℹ️ Evidence, not used directly | Weekdays typically run 85-93% of timetabled trains, which helps explain why frequency-based waits are about 1 min optimistic. The fix is to measure real gaps from Paxen's own Trackernet data (next task), not to bolt on monthly percentages that include strike days. |
| Lost customer hours | ❌ | Stops in 2020; line totals per 4 weeks. |
| Daily journeys, station footfall, journeys by mode | ❌ | Totals published after the fact; nothing about the moment of a prediction. NUMBAT already covers typical demand. |

### How long disruptions last (`backend/paxen/disruptions.py`, `data/disruption_clearance.json`)
Consecutive status messages make one disruption (94,690 observations). For a line disrupted now, Paxen estimates
the chance it's **still disrupted when you reach that line**, from the status (minor, severe, part-suspended or
suspended), the cause in the message text (signal failure, faulty train, customer incident, staff shortage, strike,
"earlier ...", and so on) and how long it has lasted so far. Paxen's recorder already logs status every 30 s, so it
knows that last one. Planned closures and the nightly closure stay certain, as before.

**Held-out check:** fit on Apr 2022 - Oct 2025, scored on Nov 2025 - Oct 2026 (26,901 observations). The table gives
Brier scores for P(still disrupted later); lower is better.

| Ahead | Before (assumed still on) | Status only | + time so far | **+ cause (used)** |
|---|---|---|---|---|
| 15 min | 0.054 | 0.051 | 0.049 | **0.049** |
| 1 hour | 0.216 | 0.165 | 0.155 | **0.149** |
| 2 hours | 0.378 | 0.227 | 0.212 | **0.200** |

**In the forecast:** a disruption's extra wait and ride time is weighted by that chance, and so is the extra
uncertainty. A suspension only makes a route impossible if it's more likely than not to still be on. Each disruption
in the API now carries `chance_still_on`. Example: severe delays from a signal failure 5 minutes ago are 76% likely to
still be on in an hour, and 6% by tomorrow morning. Before, they were applied in full to tomorrow's commute.
Limits: "still disrupted" includes being downgraded (say from severe to minor), but the current status's impact is
what gets weighted, so it errs a little on the cautious side. Only Underground lines are in the history; the
Overground and Elizabeth line use the Tube curves for the same status.

Rebuild or re-check: `python -m paxen.disruptions build|check <status-messages.csv>`. The 25 MB source file isn't
in the repo; only the derived curves are (28 KB). Confirm the file's licence for commercial use, as with other TfL data.

## Licensing
NUMBAT is TfL open data (Open Government Licence based terms). Attribution: *Powered by TfL Open Data*. As with the
rest of TfL's data, confirm commercial-use terms before launch (see [data-sources.md](data-sources.md)).

## Suggested FOI requests (the datasets that would really move the model)
1. **NetMIS train movements:** one month, all lines (arrivals, departures, matched timetable, train-run ids), with
   explicit permission for model training. It adds departure and dwell times, which Trackernet doesn't give directly.
2. **Gate-to-gate journey times:** anonymised station-pair distributions by 15-minute entry time (counts, percentiles,
   small cells suppressed). These would let Paxen check whole-journey forecasts, including walks and changes.
3. ~~Historical line status~~: no longer needed (Daniel found TfL's status-message history; see above).
