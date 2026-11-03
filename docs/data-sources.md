# Data sources & open questions

| Source | Used for | Status in code | To validate |
|---|---|---|---|
| TfL Unified API: `/StopPoint/{id}/Arrivals` | live countdowns (tube, Overground, Elizabeth line, DLR, bus) | implemented (`providers/tfl.py`) | rate limits with an app key; how long vehicle ids stay stable across feed resets |
| TfL Unified API: `/Line/Mode/{modes}/Status` | disruption categories + reasons | implemented | mapping of all `statusSeverity` codes (see `_SEVERITY`) |
| TfL Journey Planner: `/Journey/JourneyResults` | candidate routes incl. National Rail | implemented | alternative-route coverage; leg `directions` vs arrivals `destinationName` matching |
| TfL `/StopPoint/Search` | place search | implemented | add a proper address geocoder (postcodes, addresses) |
| National Rail Darwin (LDB / Push Port) | rail live departures & actual times | not yet | registration, licence, and whether "actual" times give better ground truth than countdown inference |
| Bus Open Data Service (SIRI-VM) | bus vehicle positions → better ground truth | not yet | coverage in the pilot corridor; matching to TfL vehicle ids |
| TfL station crowding / NUMBAT | crowding priors | not yet | licence; only ever shown as an estimate |

**Ground truth.** Today it is inferred from countdowns: a vehicle that was ≤2 min away and then disappeared
from the board. That is bounded and quality-scored, but it is not measurement. Darwin actual times and bus
AVL positions should replace it where available (`ObservedArrival.method` records which).

**Licensing.** TfL open data is free to use under its transport data terms, but attribution, caching and
model-training rights still need to be confirmed for commercial use. Raw payloads are kept 14 days
(`recorder.KEEP_RAW_PAYLOAD_DAYS`); the normalised rows are kept.
