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

---

# Measured arrivals (Trackernet) vs inferred, 4 Nov 2026, ~14:00, all Tube lines, 12 minutes

Trackernet reports each train's position from the signalling system; the first "At Platform" timestamp is the
arrival time to the second. Recorded side by side with the countdown inference:

| | Result |
|---|---|
| Measured arrivals per 30-second cycle | ~90–200 (≈11,000/hour across 10 lines) |
| Stations mapped to NaPTAN ids | 360/377 automatically, plus 2 aliases; the rest are closed or not served |
| Same arrival seen both ways | 1,054 |
| Countdown inference vs measured | **median +41 s late**; 90% within ±89 s; 27% more than a minute off |

**Why it matters:** the countdown method records an arrival when the train *leaves the board*, a little after it
actually arrives, and it partly reads the answer off TfL's own countdown, so it's circular. Against inferred
truth TfL looked better than it is:

| TfL countdown error | vs inferred truth | vs measured truth |
|---|---|---|
| Mean absolute error | 41 s | **51 s** |
| Average bias | +33 s | **+11 s** |
| Within 2 minutes | 98% | **92%** |

By lead time against measured truth: 0–2 min MAE 50 s (TfL ~29 s optimistic); 2–5 min 46 s; 5–10 min 59 s;
10–20 min 98 s, where trains came ~92 s *earlier* than predicted (only 97 trains so far; treat as a hint).

Consequences: measured arrivals are now the headline ground truth (docs/model-evaluation.md), and they take
priority over inferred ones when both exist. Countdown inference remains for buses, Overground and the Elizabeth
line, reported separately.
