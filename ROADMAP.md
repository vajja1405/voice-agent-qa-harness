# Remediation Roadmap (fix-first, by impact ÷ effort)

Turning the findings into a decision: *what to fix first for the most value.* Ordered so
the biggest risk-per-hour-of-work is at the top. (Details/evidence in `FINDINGS.md`;
voice numbers in `VOICE_QUALITY.md`.)

| # | Issue | Impact | Est. effort | Suggested fix |
|---|-------|--------|-------------|---------------|
| 1 | **Caller-ID identity bleed** — every caller from one number becomes the first caller ("Priya") | 🔴 High — wrong chart + PHI to the wrong person; families share phones | Low–Med (flow/prompt) | Stop auto-trusting ANI as identity. Always confirm "Am I speaking with **X**?" and re-verify name+DOB per call; never pre-load a profile from phone number alone. |
| 2 | **PHI authorization gap** on third-party requests | 🔴 High — HIPAA liability | Med | Before disclosing anyone else's info, verify the **caller's** identity and their authorization to access it — not just the subject's name+DOB. |
| 3 | **Dead air / slow responses** (~44% silence, gaps up to ~4s) | 🟠 Med — hurts the #1 "natural conversation" bar; also compute/telephony cost at scale | Med | Tune turn-detection + response latency; add brief acknowledgements ("one moment") to fill think-time instead of silence. |
| 4 | **Name-capture ASR errors** ("Aleida" for Elena, "Tom Muin" for Tom Nguyen) | 🟠 Med — failed/duplicate chart match | Med | Add spell-back confirmation for names and a phonetic re-check before committing to a record. |
| 5 | **Service-type / rules not reconciled** (took a primary-care request at an ortho clinic; never surfaced weekend hours) | 🟡 Low–Med — rule conformance (your 95-5 thesis) | Low | Check requested service/day against practice config early and state the rule ("we're closed weekends; next opening is…"). |
| 6 | **Turn-taking overlap** | 🟢 Low — measured talk-over is only ~0.3%, so this is already good | — | Monitor via `VOICE_QUALITY.md`; no action needed now. |

**Where I'd start:** #1 and #2. They're the highest-risk (wrong chart + PHI/HIPAA), they're
relatively cheap (flow/prompt changes, not model retraining), and both are catchable forever
after by re-running this harness as a regression gate (`compare_runs.py`).
