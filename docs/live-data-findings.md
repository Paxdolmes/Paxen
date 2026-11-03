# What one hour of live TfL data taught us (3 Nov 2026, ~13:00–14:00)

The recorder ran on the Walthamstow ↔ Regent Street corridor (Victoria, Weaver, Elizabeth, Central and
Bakerloo lines and several bus routes): ~9,000 live predictions and ~160 inferred arrivals.

## TfL feed behaviours the simulator didn't have (all now handled)
| Behaviour | Effect if ignored | Fix |
|---|---|---|
| At a terminus each incoming train is listed once per platform | duplicate trains | keep the earliest per (line, vehicle) |
| A terminating train reappears as a departure in the other direction | false "arrivals" | key observations by direction |
| Trains sit at "due" at a terminus for ~30 min before departing | arrival recorded 30 min late | use the first time the train reaches the platform; skip layovers longer than 5 min |
| The same train id is reused on the return trip | predictions matched to the wrong trip (±25 min errors) | match by direction plus a plausible time window |
| Vehicles flicker on and off the board between polls | repeated arrivals for one train | require two missed polls; one arrival per train/direction per 10 min |
| Journey planner returns near-identical routes | no real alternatives | three planner queries (all modes, without Tube, bus only) and dedupe |
| Disruptions often cover only part of a line | whole line penalised | use `detail=true` affected stops per leg |

Ground truth before the fixes made TfL look ~4 minutes wrong for trains under 2 minutes away. After them,
TfL's countdown error is a realistic ~35–45 s, with ~93–98% within 2 minutes.

## The correction model on real data: not proven yet
| Evaluation window | TfL MAE | Paxen MAE | Promoted? |
|---|---|---|---|
| Train 13:00–13:35, test 13:35–13:50 | 44.2 s | 36.1 s | would be |
| Train 13:00–13:40, test 13:40–13:55 | 33.3 s | 47.9 s | no (shadow) |

Paxen helped most at longer lead times (10–20 min out: 83 s → 59 s in the first window), but TfL's own
accuracy shifted within the hour, and corrections learned at 1 pm didn't hold at 1:45 pm. **One hour isn't
enough.** The promotion rule (beat TfL by ≥3% on a later, held-out period) correctly keeps the model in
shadow, so users see TfL's own numbers.

Next: run the deployed recorder for ~2 weeks across peaks and weekdays, then judge on a full held-out week.
Rebuild arrivals after any inference change with `python -m paxen.reinfer`.
