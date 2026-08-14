# Patient Simulator & Voice-Agent Conformance Tester

A Python bot that **calls a clinic's AI phone agent, acts like a real patient, records and
transcribes the conversation, and checks whether the agent behaves correctly** — including
the rules, memory, and safety behavior that actually matter in healthcare.

Built for the Pretty Good AI — AI Engineering Challenge.

---

## What it does (in one picture)

```
  Clinic AI agent          Twilio            THIS BRIDGE            OpenAI Realtime API
   ("Maggie")   <== call ==>  phone  <== ws ==>  server.py  <== ws ==>  our "patient" (voice + brain)
```

1. **Twilio** places a real phone call to the clinic's test line.
2. When the agent answers, Twilio streams her voice to our **bridge** (`server.py`).
3. The bridge forwards her voice to the **OpenAI Realtime API**, which plays a realistic
   **patient** (defined in `scenarios.py`) and talks back.
4. We stream the patient's voice back onto the call, and **log both sides** of the conversation.

> **Why this stack?** OpenAI Realtime is *speech-to-speech* — one model that listens and
> speaks with natural turn-taking and low latency, which is exactly what a good phone call
> needs. Twilio and OpenAI both use `g711_ulaw` (8 kHz phone audio), so audio passes straight
> through with no conversion. (Full tradeoffs in `docs/ARCHITECTURE.md`.)

---

## The files

| File | What it does |
|------|--------------|
| `scenarios.py` | The **test matrix**: 15 patient personas/goals across 5 categories (the system prompts). |
| `server.py`    | The **bridge**: serves Twilio's instructions, relays audio both ways, saves transcripts. |
| `caller.py`    | Places **one outbound call** for a chosen scenario. |
| `run_all.py`   | Places the **whole batch** of calls automatically, one after another. |
| `ngrok_util.py`| Auto-detects the current ngrok URL (so you never edit `.env` for it). |
| `download_recordings.py` | Downloads the call audio from Twilio as MP3 into `recordings/`. |
| `analyzer.py`  | The **grader**: an LLM judge scores each transcript → `bug_report.md`, `BUSINESS_IMPACT.md`, `scorecard.json`. |
| `money_model.py` | The **transparent dollar model** the analyzer uses (edit the assumptions here). |
| `voice_quality.py` | Measures **voice quality from the audio** (talk-over, silence, gaps) → `VOICE_QUALITY.md`. |
| `compare_runs.py` | **Regression gate**: diffs a run vs `baseline.json`; non-zero exit if quality/safety/containment regressed. |
| **`FINDINGS.md`** | **The curated headline report** — real bugs vs test artifacts, what the agent did well. |
| `ROADMAP.md`   | Prioritized fix-first remediation plan (impact ÷ effort). |
| `bug_report.md` / `BUSINESS_IMPACT.md` / `VOICE_QUALITY.md` | Auto-generated detail, dollar impact, and voice metrics. |
| `docs/ARCHITECTURE.md` | The design + tradeoffs writeup (why Realtime, why Twilio, etc.). |
| `.env.example` | Template for your API keys (copy to `.env`; never commit `.env`). |
| `transcripts/` / `recordings/` | Saved conversations (`.txt`+`.json`) and call audio (MP3). |

---

## Prerequisites (accounts you need)

1. **OpenAI API key** with billing enabled (Realtime API access).
2. **Twilio account**, upgraded (add ~$20 credit so it can call any number), plus **one phone
   number** you buy (~$1). That number is the single number you report on the submission form.
3. **ngrok** (free) — lets Twilio reach the server running on your laptop.

Typical total cost for a full run is **under $20** (reimbursed by PGA — keep your receipts).

---

## Setup

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure your secrets
cp .env.example .env
#   ...then open .env and fill in your OpenAI + Twilio values.
```

## Run the calls (3 terminals, then one command)

The ngrok URL is now **auto-detected** — you never edit `.env` for it.

```bash
# Terminal 1 — start the bridge server
source .venv/bin/activate && python server.py

# Terminal 2 — expose it to the internet (leave running)
ngrok http 5050

# Terminal 3 — run the WHOLE test batch automatically
source .venv/bin/activate && python run_all.py
```

`run_all.py` places every scenario call one after another (waiting for each to finish),
so you just watch. Each call's transcript is saved to `transcripts/`.

Prefer to run them individually? You still can:
```bash
python caller.py --scenario emergency_escalation
python run_all.py --only safety      # or run just one category
python run_all.py --list             # see what it will run
```

## Grade the calls + get the reports (Milestones 2 & 4)

```bash
# 1. Pull the call audio from Twilio into recordings/ (MP3)
python download_recordings.py

# 2. Grade every transcript -> bug_report.md, BUSINESS_IMPACT.md, scorecard.json
python analyzer.py           # (--dry-run to preview format with no API spend)

# 3. Measure voice quality from the audio -> VOICE_QUALITY.md
python voice_quality.py

# 4. Regression gate: did this run break anything vs the frozen baseline?
python compare_runs.py       # exit 0 = clean, 1 = regressions
```

The curated, human-facing results live in **`FINDINGS.md`** (headline bugs) and
**`ROADMAP.md`** (what to fix first).

---

## Build status

- [x] **M1** — Core: make a real call and hold a natural conversation. *(code done; verify with your first live call)*
- [x] **M2** — Save each call's recording (MP3) + transcript to files.
- [x] **M3** — Full scenario matrix (15 scenarios, 5 categories incl. safety/memory/rule probes).
- [x] **M4** — Analyzer/grader → `bug_report.md` + `BUSINESS_IMPACT.md`.
- [ ] **M5** — Run 10+ calls and iterate. *(needs your accounts)*
- [x] **M6** — Architecture writeup (`docs/ARCHITECTURE.md`) + this README.
- [ ] **M7** — Loom videos + submit.
