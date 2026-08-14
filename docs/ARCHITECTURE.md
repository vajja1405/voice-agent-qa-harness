# Architecture & Design Decisions

> This is the "why," not just the "what." (The 1–2 paragraph version the challenge
> asks for is the first section; the rest is backup for the founder call.)

## Short version (the required 1–2 paragraphs)

The system is a **simulated patient** that places real phone calls to the clinic's AI
agent, holds a natural voice conversation, records/transcribes it, and then grades the
agent. I chose a **Twilio → local bridge → OpenAI Realtime API** design. Twilio places the
outbound PSTN call and streams the call audio to a small FastAPI **bridge** over a
WebSocket; the bridge relays that audio to the **OpenAI Realtime API**, which plays a
scripted "patient" (persona + goal from `scenarios.py`) and talks back. Twilio and the
Realtime API both use **G.711 μ-law at 8 kHz**, so audio passes through with no
transcoding. I used Realtime (speech-to-speech) rather than a cascaded
speech-to-text → LLM → text-to-speech stack because natural turn-taking and low latency
are the single most important thing on a phone call, and Realtime handles voice-activity
detection and barge-in for me.

The second half is the part I think actually matters for Pretty Good AI. Rather than
stopping at "here are some bugs," the analyzer runs a **separate LLM judge (Claude)** over
each transcript and grades it on the things a *healthcare* deployment lives or dies on:
did the agent **complete and contain** the call (their headline KPI), did it **honor the
practice's rules** (e.g., closed weekends), did it **retain context within the call**, and
did it stay **safe** (escalate emergencies, refuse medical advice, protect PHI)? Each
failure is then priced with a transparent, editable **dollar model**. I use a different
model to judge than to speak so the voice model isn't grading itself.

## Data flow

```
 caller.py ──create call──► Twilio ──"who answered? fetch instructions"──► server.py /twiml
                                                                              │
                                        (TwiML: <Connect><Stream>)            │
 Clinic AI  ◄──── PSTN voice ────► Twilio ◄═══ audio (μ-law) WebSocket ═══►  server.py /media
 ("Maggie")                                                                    │
                                                                     ═══ WebSocket ═══► OpenAI Realtime
                                                                     (our "patient": persona + voice)
        after the call:
 transcripts/*.json ──► analyzer.py ──(Claude judge + money_model)──► bug_report.md + BUSINESS_IMPACT.md
 recordings/*.mp3   ◄── download_recordings.py
```

## Key decisions & tradeoffs

**1. Speech-to-speech (OpenAI Realtime) vs. cascaded STT→LLM→TTS.**
Chose Realtime. Pro: lowest latency, built-in turn detection + barge-in, one system to
reason about → natural conversation, which is the #1 grading criterion. Con: less control
over each stage, and it locks the "brain" to OpenAI. A cascaded pipeline would let me mix
best-in-class STT/TTS and any LLM, but I'd own endpointing, interruption handling, and
~1–2s of added latency — the exact "awkward pauses/glitches" the rubric rejects. For a
6-hour build where voice quality is pass/fail, Realtime is the right call.

**2. Twilio + my own bridge vs. a managed voice platform (Vapi/Retell/Bland).**
Chose Twilio + bridge. Managed platforms would be faster to "it talks," but they hide the
part that demonstrates engineering (the media streaming + the audio loop) and give less
control. Twilio + a thin bridge keeps that visible and debuggable, while still being
little code.

**3. G.711 μ-law end-to-end.** Twilio phone audio and the Realtime API both speak μ-law
8 kHz, so I set both input and output formats to `g711_ulaw` and pass bytes straight
through — no resampling, fewer bugs, lower latency.

**4. ngrok for the public webhook.** Twilio must reach the bridge over the public
internet. ngrok is the right tool for a **test harness**; I would not use it in production
(there I'd deploy the bridge behind a real host / load balancer).

**5. The judge is a different model than the speaker.** The patient's voice is OpenAI
Realtime; the grader is Claude. Separating them avoids a model grading its own output and
makes the evaluation more credible.

**6. Dollar model kept small and transparent (`money_model.py`).** The figures are
illustrative and stated out loud, so the *method* (measure containment, price each
failure) is what's on display — not a fake precise number. Plug in real figures and it
updates.

## What I'd do with more time (honest next steps)

- Save the raw μ-law frames in the bridge as a WAV backup (belt-and-suspenders vs. Twilio recording).
- Add measured voice metrics per call (agent response latency, talk-over count, silence gaps).
- Turn the scenario matrix into a true **regression suite** that diffs conformance across agent versions over time.
- Auto-generate scenarios from a practice's actual rule set (so the tests match each clinic).

## Cost

Roughly: Twilio number (~$1) + outbound minutes (~$0.013/min) + OpenAI Realtime audio +
Claude grading. A full 10–15 call run typically stays **under $20** (reimbursed).
