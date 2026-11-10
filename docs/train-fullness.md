# Train fullness

"The 08:04 is likely packed (7-minute gap ahead of it). The 08:06 should have space, and you'd arrive about 2
minutes later."

Paxen estimates how full each of the next trains is likely to be as it leaves your boarding station, and says when
it's worth letting one go. The code is in `backend/paxen/fullness.py` and the tests are in `backend/tests/test_fullness.py`.

## Why an estimate

Nothing publishes how many people are on a London train in real time. Tap-ins are recorded at gates, not on trains,
and TfL doesn't release them live. Train weight sensors exist on newer stock, but their data isn't public. So Paxen
combines three things it does know.

| Input | Source | What it says |
|---|---|---|
| Typical load | TfL NUMBAT 2025 (`numbat.stop_context(...)["depart_load_per_train"]`) | Passengers on board as trains pull out of this station, by direction, day type and quarter hour (averaged over the surrounding hour) |
| Gap ahead | Live arrivals: the gap behind whichever train is ahead on the same platform, even one to another branch, since it still takes the passengers for the shared stretch. For the first train in the countdown, the gap comes from when the train ahead was last seen at the platform (Trackernet for the Tube, Darwin for the Overground and Elizabeth line, via `observed_arrivals`) | Passengers build up between trains, so a train after a long gap carries more and the one right behind it fewer |
| Live busyness | TfL's Wi-Fi based station crowding, live vs usual, at this station and the two before it (`numbat.upstream`) | Whether today is busier than a typical day |

`share = typical load × gap factor × live factor ÷ capacity`

- **Gap factor:** `1 + 0.85 × (gap ÷ scheduled headway − 1)`, kept between 0.5 and 2.0. Some people time their arrival
  to a train, so load grows a little slower than the gap does.
- **Live factor:** `1 + 0.5 × (live ÷ usual − 1)`, kept between 0.75 and 1.4. A busy station is a hint, not a headcount.
- **Capacity:** seats plus standing at about 4 people per m², per line. The figures are approximate (`CAPACITY`);
  for example, S7 stock is 865 and the 1995 stock on the Northern line is 662.

| Share | Level | Label |
|---|---|---|
| 0.9 or more | `packed` | Likely packed (1.05 or more: "Likely packed, may not fit") |
| 0.6 to 0.9 | `standing` | Standing room |
| below 0.6 | `space` | Space likely |

Advice is given only when the train you'd catch is packed and one within 6 minutes behind it is a level lower and
at least 0.15 emptier.

When the trip is more than about 20 minutes away, or there's no countdown, the app shows the usual level for that
time and direction instead, for example "Usually standing room".

Example: Fulham Broadway, District line eastbound, on a Tuesday at 08:15.

- The typical train leaves with about 580 people on board, which is 0.67 of capacity: standing room.
- A train after an 8-minute gap, when the scheduled headway is 4 minutes, rates as likely packed.
- The train 2 minutes behind it rates as space likely.

## Where it shows

| Screen | What appears |
|---|---|
| Today hero | The card for the recommended route |
| Routes | A chip and the advice on each option; the next trains when expanded |
| Live trip | The next trains while you walk to the stop or wait on the platform |

The API returns:

- `RouteOption.fullness` (`BoardingFullness`)
- `LiveTrip.next_departure.trains`, `catch_index` and `fullness`

## Checking it

Once you're on board, the live trip asks "Did you get on the first train?" The answer goes to `POST /v1/boarding`
and is stored in `boarding_reports` with what the estimate said: level, share, typical share and gap.

`/v1/health` → `data.boarding_reports` shows, for each level, how many people answered and how many got on.

- If most "Likely packed" trains were boarded, `PACKED_AT` is too low.
- If people often missed "Standing room" trains, it is too high.

Revisit the thresholds and the gap weight once each level has about 50 answers.

## What it doesn't touch

Fullness is advice only. It doesn't change journey times, rankings, the prediction model or its training data, and
the model evaluation is unaffected.

The only new database data is the boarding answers. They are deleted with the user's history or account.
