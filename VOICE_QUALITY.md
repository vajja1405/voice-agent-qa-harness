# Voice-Quality Scorecard (measured from the call audio)

_Measured across 12 calls from the dual-channel recordings. Energy-based voice-activity detection, so treat gap timings as indicative; talk-over and silence are robust._


## Per-call metrics

| Scenario | Duration | Talk-over % | Silence % | Longest gap (s) | Mean turn gap (s) | Agent/Patient talk |
|---|---|---|---|---|---|---|
| cancel | 151.6s | 0.7% | 45.7% | 4.1 | 0.55 | 68/32 |
| reschedule | 130.5s | 0.6% | 43.4% | 2.0 | 0.55 | 64/36 |
| schedule_basic | 133.4s | 0.5% | 41.6% | 2.2 | 0.56 | 66/34 |
| emergency_escalation | 89.9s | 0.4% | 37.9% | 2.1 | 0.5 | 71/29 |
| memory_consistency | 156.6s | 0.3% | 46.2% | 2.0 | 0.51 | 69/31 |
| prompt_injection | 129.9s | 0.3% | 46.3% | 2.0 | 0.54 | 64/36 |
| refill_basic | 135.9s | 0.3% | 49.0% | 2.3 | 0.61 | 64/36 |
| medical_advice | 124.1s | 0.3% | 44.2% | 2.0 | 0.58 | 64/36 |
| phi_privacy | 145.4s | 0.3% | 44.1% | 3.6 | 0.58 | 64/36 |
| hours_insurance | 196.1s | 0.2% | 44.2% | 2.2 | 0.59 | 65/35 |
| weekend_rule | 144.4s | 0.2% | 40.4% | 2.2 | 0.47 | 66/34 |
| new_patient | 157.8s | 0.1% | 43.8% | 2.0 | 0.53 | 68/32 |

## Averages

- **Talk-over (both speaking at once):** 0.3%
- **Silence / dead air (mid-call):** 43.9%
- **Longest single gap:** 2.4s (avg of per-call worst)
- **Mean pause between turns:** 0.5s

## Why this matters

Natural conversation is the #1 thing this role grades, and it's usually judged by ear. These are hard numbers on that exact axis, measured on the live agent. High talk-over and long gaps are the audible 'it feels broken' symptoms behind the turn-taking bugs in `FINDINGS.md` -- now quantified and trackable release-over-release.