# Remediation Roadmap (fix-first, by impact ÷ effort)

Findings turned into a decision: *what to fix first for the most value.* Based on the
hand-reviewed `FINDINGS.md` (test-setup artifacts excluded), not the raw auto-report.

| # | Issue | Impact | Est. effort | Suggested fix |
|---|-------|--------|-------------|---------------|
| 1 | **PHI-authorization flow** — verifies the *subject* (patient looked up), not the *caller* | 🟠 Med — HIPAA/policy risk (no leak observed, but a real gap if the record exists) | Low–Med (flow) | Before disclosing a third party's info, verify the **caller's** identity and authorization — not just the subject's name+DOB. Confirm the intended disclosure policy. |
| 2 | **Turn-taking** — agent sometimes responds before processing what the caller just said (e.g., asks "Am I speaking with Priya?" after the caller gave a different name) | 🟠 Med — hurts the #1 "natural conversation" bar | Med | Tighten input handling / endpointing so the agent consumes the caller's last utterance before its next prompt. |
| 3 | **Dead air / slow responses** (~44% silence, gaps up to ~4s — measured in `VOICE_QUALITY.md`) | 🟠 Med — audible latency; compute/telephony cost at scale | Med | Tune turn-detection + response latency; add brief acknowledgements ("one moment") instead of silence. |
| 4 | **Name-capture ASR errors** ("Aleida" for Elena, "Tom Muin" for Tom Nguyen) | 🟠 Med — failed/duplicate chart match | Med | Add spell-back confirmation + a phonetic re-check before committing to a record. |
| 5 | **Service-type / rules not reconciled** (primary-care request at an ortho clinic; weekend hours never surfaced) | 🟡 Low — rule conformance (your 95-5 thesis) | Low | Check requested service/day against practice config early and state the rule. |

**Where I'd start:** #1 and #2 — highest risk-per-hour (a policy/PHI gap and the most audible
voice-quality issue), both are flow/prompt changes rather than model retraining, and both become
catchable forever after via the regression gate (`compare_runs.py`).

_Deliberately NOT on this list (test-setup artifacts, not agent bugs): "record not found" for my
synthetic patients, transfers hitting the assessment test line, and the inflated frequency of the
caller-ID guess (all my calls came from one number)._
