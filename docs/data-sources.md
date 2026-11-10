# Data sources & open questions

| Source | Used for | Status in code | To validate |
|---|---|---|---|
| TfL Unified API: `/StopPoint/{id}/Arrivals` | live countdowns (tube, Overground, Elizabeth line, DLR, bus) | implemented (`providers/tfl.py`) | rate limits with an app key; how long vehicle ids stay stable across feed resets |
| TfL Unified API: `/Line/Mode/{modes}/Status` | disruption categories + reasons | implemented | mapping of all `statusSeverity` codes (see `_SEVERITY`) |
| TfL Journey Planner: `/Journey/JourneyResults` | candidate routes incl. National Rail | implemented | alternative-route coverage; leg `directions` vs arrivals `destinationName` matching |
| TfL `/StopPoint/Search` | place search | implemented | add a proper address geocoder (postcodes, addresses) |
| National Rail Darwin Push Port v18 (Rail Data Marketplace, Kafka) | **measured** arrival times for the Overground and Elizabeth line (ground truth, `method="darwin"`) | implemented (`darwin.py`, runs in the worker when `DARWIN_*` are set) | live check 6 Nov: 92% of London actuals matched a TfL train by id; actual times are to the minute (stored as a 59 s window) |
| Bus Open Data Service (SIRI-VM) | bus vehicle positions → better ground truth | not yet | coverage in the pilot corridor; matching to TfL vehicle ids |
| TfL NUMBAT 2025 (crowding.data.tfl.gov.uk) | scheduled trains per hour for waits without a countdown; typical demand features for the `gbm_numbat` candidate; typical load per train leaving each station for train fullness (`fullness.py`) | implemented (`numbat.py`, data file committed) | rebuild yearly when TfL publishes a new edition; see [historical-data.md](historical-data.md) |
| TfL Journey Planner timetabled departures | waits on services 8+ min apart; walk time when changing trains | implemented (`engine.timetable_wait`, `transfer_min`) | change walks are a heuristic from the planner's connection time |
| TfL trains service status messages (Apr 2022 - Oct 2026) | how likely a current disruption is to still be on when you travel | implemented (`disruptions.py`, derived curves committed) | confirm licence; rebuild when a newer export is available |
| TfL station crowding (`/crowding`) | station busyness | implemented; **live busyness of every Tube station recorded every 15 min** (`station_crowding`) | only ever shown as an estimate |
| Live context recorded for future models (`context.py`) | permanent line-status history (one row per change, all modes); hourly London weather (Open-Meteo); station disruptions; lift outages; planned works for the week ahead (daily); road disruptions (raw, archive only) | recording only: no model uses these yet | only build in signals that are also available live (they all are) |

**Ground truth.** Tube arrivals are measured by Trackernet; Overground and Elizabeth line arrivals by Darwin's actual
times (TfL's vehicle id is Darwin's `rid`, and TfL's `910G…` stop ids are Darwin TIPLOCs, so the match is exact).
Everything else is inferred from countdowns: a vehicle that was ≤2 min away and then disappeared from the board.
That is bounded and quality-scored, but it is not measurement. Bus AVL positions could replace it for buses
(`ObservedArrival.method` records which).

**Licensing.** TfL open data is free to use under its transport data terms, but attribution, caching and
model-training rights still need to be confirmed for commercial use. Raw payloads are kept 14 days
(`recorder.KEEP_RAW_PAYLOAD_DAYS`); the normalised rows are kept.
