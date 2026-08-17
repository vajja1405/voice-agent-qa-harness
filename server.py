"""
server.py  -- the "bridge" that lets our patient bot talk on a phone call.
============================================================================

BIG PICTURE (say this in your Loom):

    Clinic agent (Maggie)  <== phone call ==>  Twilio  <== WebSocket ==>  THIS SERVER  <== WebSocket ==>  OpenAI Realtime API
         (their AI)                          (the phone line)              (our bridge)                    (our patient's brain + voice)

    1. Twilio places a real phone call to the clinic's test number.
    2. When Maggie answers, Twilio streams her voice (as audio chunks) to this server.
    3. This server forwards her voice to OpenAI's Realtime API.
    4. OpenAI -- acting as our "patient" (see scenarios.py) -- talks back with a
       human-sounding voice. We stream that audio back to Twilio, so Maggie hears it.
    5. We log what BOTH sides said (transcripts) as we go.

WHY THIS DESIGN (tradeoffs for the architecture doc):
    - OpenAI Realtime is *speech-to-speech*: one model listens and speaks, with
      built-in turn-taking + interruption handling. That gives natural conversation
      with low latency -- the #1 thing the challenge grades. A "cascaded" pipeline
      (speech-to-text -> LLM -> text-to-speech) would give more control but adds
      lag and clunkier turn-taking.
    - Twilio phone audio and OpenAI both speak "g711_ulaw" (8kHz phone audio), so
      the audio bytes pass straight through -- no format conversion needed.

NOTE (honest, and useful for your AI-debugging Loom): the Realtime model id and the
"OpenAI-Beta" header below are the parts most likely to change over time. If OpenAI
rejects the connection, updating OPENAI_REALTIME_MODEL in .env is the first fix to try.
"""

import os
import json
import asyncio
import pathlib
from datetime import datetime

from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import PlainTextResponse
from fastapi.websockets import WebSocketDisconnect
from dotenv import load_dotenv

# The `websockets` library renamed the header keyword between versions:
#   - newer "asyncio" client uses  additional_headers=...
#   - older/legacy client uses     extra_headers=...
# We detect which one is available so this works on any installed version.
try:
    from websockets.asyncio.client import connect as ws_connect
    _WS_HEADER_KW = "additional_headers"
except Exception:  # fall back to the legacy client
    from websockets import connect as ws_connect
    _WS_HEADER_KW = "extra_headers"

from scenarios import get_scenario
from ngrok_util import get_public_host

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REALTIME_MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime")
PATIENT_VOICE = os.getenv("PATIENT_VOICE", "alloy")

app = FastAPI()


@app.get("/health")
async def health():
    """A tiny endpoint so you can confirm the server is up in a browser."""
    try:
        host = get_public_host()
    except SystemExit:
        host = "(not detected yet)"
    return {"status": "ok", "model": REALTIME_MODEL, "public_host": host}


@app.api_route("/twiml", methods=["GET", "POST"])
async def twiml(request: Request):
    """
    Twilio calls this the moment the clinic agent answers the phone.
    We reply with TwiML (Twilio's XML) that says: "open a two-way audio stream
    to my /media WebSocket." We pass the scenario name along in the URL so the
    bridge knows which patient to play.
    """
    scenario = request.query_params.get("scenario", "schedule_basic")
    host = get_public_host()
    stream_url = f"wss://{host}/media"
    # Pass the scenario as a <Parameter> (reliable) rather than a URL query string,
    # which Twilio does not preserve on <Stream>. It arrives in the 'start' event.
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "  <Connect>\n"
        f'    <Stream url="{stream_url}">\n'
        f'      <Parameter name="scenario" value="{scenario}" />\n'
        "    </Stream>\n"
        "  </Connect>\n"
        "</Response>"
    )
    return PlainTextResponse(content=xml, media_type="application/xml")


TRANSCRIPTS_DIR = pathlib.Path(__file__).parent / "transcripts"


def save_transcript(scenario, transcript, call_sid, started_at):
    """
    Write the conversation to two files in transcripts/:
      - a human-readable .txt (what a reviewer reads)
      - a .json (what our analyzer/grader reads in Milestone 4)
    The call_sid links this transcript to its audio recording (same id).
    """
    if not transcript:
        return None
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    stamp = started_at.strftime("%Y%m%d-%H%M%S")
    base = f"{scenario.name}-{stamp}"

    # Human-readable transcript
    txt_path = TRANSCRIPTS_DIR / f"{base}.txt"
    with open(txt_path, "w") as f:
        f.write(f"Scenario   : {scenario.name} ({scenario.category})\n")
        f.write(f"Call SID   : {call_sid}\n")
        f.write(f"Started    : {started_at.isoformat()}\n")
        f.write(f"Testing    : {scenario.what_to_check}\n")
        f.write("-" * 60 + "\n")
        for speaker, text in transcript:
            label = "AGENT (Maggie)" if speaker == "agent" else "PATIENT (bot)"
            f.write(f"{label}: {text}\n")

    # Machine-readable transcript (for the grader)
    json_path = TRANSCRIPTS_DIR / f"{base}.json"
    with open(json_path, "w") as f:
        json.dump({
            "scenario": scenario.name,
            "category": scenario.category,
            "call_sid": call_sid,
            "started_at": started_at.isoformat(),
            "what_to_check": scenario.what_to_check,
            "turns": [{"speaker": s, "text": t} for s, t in transcript],
        }, f, indent=2)

    print(f"[bridge] saved transcript -> {txt_path.name}")
    return txt_path


def build_session_update(scenario) -> str:
    """
    The one-time config we send OpenAI: who to be, and the audio settings.
    Uses the GA ("general availability") Realtime shape: audio settings are nested
    under session.audio.input / session.audio.output. "audio/pcmu" == G.711 μ-law,
    the 8 kHz phone audio Twilio streams (so no conversion needed).
    """
    return json.dumps({
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": REALTIME_MODEL,
            "output_modalities": ["audio"],
            "instructions": scenario.instructions(),   # <- our patient persona
            "audio": {
                "input": {
                    "format": {"type": "audio/pcmu"},        # matches Twilio phone audio
                    # server_vad = OpenAI decides when the other person stopped talking,
                    # then our patient answers automatically -> natural turn-taking.
                    "turn_detection": {"type": "server_vad"},
                    # transcribe the INCOMING audio (the clinic agent) so we capture her words.
                    "transcription": {"model": "whisper-1"},
                },
                "output": {
                    "format": {"type": "audio/pcmu"},        # matches Twilio phone audio
                    "voice": PATIENT_VOICE,
                },
            },
        },
    })


@app.websocket("/media")
async def media(twilio_ws: WebSocket):
    """
    The live bridge for one phone call. Runs two jobs at the same time:
      (A) Twilio -> OpenAI : forward the clinic agent's voice to our patient's brain
      (B) OpenAI -> Twilio : send our patient's spoken reply back onto the call
    """
    await twilio_ws.accept()

    # Shared state between the two jobs
    stream_sid = None                 # Twilio's id for this call's audio stream
    call_sid = None                   # Twilio's id for the call (links to the recording)
    started_at = datetime.now()
    transcript = []                   # [(speaker, text), ...]
    scenario_name = twilio_ws.query_params.get("scenario", "schedule_basic")  # fallback only

    # ---- Interruption (barge-in) state -----------------------------------------
    # A correct barge-in isn't just "stop the audio." We also have to tell the
    # model HOW MUCH of its reply the caller actually heard before cutting in,
    # or the model's memory desyncs from reality. These three track that.
    latest_media_timestamp = 0        # ms, advanced by Twilio's media events (the call clock)
    last_assistant_item = None        # id of the patient's in-flight audio response
    response_start_timestamp = None   # call-clock ms when that reply began playing

    # ---- Wait for Twilio's 'start' event to learn WHICH scenario this call is. ----
    # The scenario arrives as a <Parameter> (see /twiml) in start.customParameters.
    try:
        async for message in twilio_ws.iter_text():
            data = json.loads(message)
            if data.get("event") == "start":
                stream_sid = data["start"]["streamSid"]
                call_sid = data["start"].get("callSid")
                params = data["start"].get("customParameters") or {}
                scenario_name = params.get("scenario", scenario_name)
                break
    except WebSocketDisconnect:
        return

    scenario = get_scenario(scenario_name)
    print(f"\n[bridge] call connected  |  scenario = {scenario_name}  (stream {stream_sid})")

    oai_url = f"wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}"
    # GA Realtime API: only the Authorization header is needed (no more OpenAI-Beta).
    oai_headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }

    try:
        async with ws_connect(oai_url, max_size=None, **{_WS_HEADER_KW: oai_headers}) as openai_ws:
            # Configure our patient before any audio flows.
            await openai_ws.send(build_session_update(scenario))
            print("[bridge] OpenAI session configured; waiting for the agent to speak...")

            # ---- Job A: clinic agent's audio (from Twilio) -> OpenAI --------------
            async def twilio_to_openai():
                nonlocal latest_media_timestamp
                try:
                    async for message in twilio_ws.iter_text():
                        data = json.loads(message)
                        event = data.get("event")

                        if event == "media":
                            # Advance the call clock so we can measure interruptions precisely.
                            latest_media_timestamp = int(data["media"].get("timestamp") or latest_media_timestamp)
                            # Maggie's voice, base64 g711_ulaw -> hand it to OpenAI's ears
                            await openai_ws.send(json.dumps({
                                "type": "input_audio_buffer.append",
                                "audio": data["media"]["payload"],
                            }))

                        elif event == "stop":
                            print("[twilio] call ended")
                            break
                except WebSocketDisconnect:
                    print("[twilio] websocket disconnected")

            # ---- Job B: our patient's audio (from OpenAI) -> Twilio ---------------
            async def openai_to_twilio():
                nonlocal stream_sid, last_assistant_item, response_start_timestamp
                async for raw in openai_ws:
                    evt = json.loads(raw)
                    etype = evt.get("type")

                    # GA renamed this to response.output_audio.delta; accept both.
                    if etype in ("response.output_audio.delta", "response.audio.delta") and stream_sid:
                        delta = evt.get("delta")
                        if delta:
                            # First chunk of a reply: stamp when it started (call-clock ms)
                            # and remember which item it is. Both are needed to truncate
                            # correctly if the caller interrupts mid-sentence.
                            if response_start_timestamp is None:
                                response_start_timestamp = latest_media_timestamp
                            if evt.get("item_id"):
                                last_assistant_item = evt["item_id"]
                            # Our patient's spoken audio chunk -> play it onto the call
                            await twilio_ws.send_text(json.dumps({
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": delta},
                            }))

                    elif etype == "conversation.item.input_audio_transcription.completed":
                        text = (evt.get("transcript") or "").strip()
                        if text:
                            print(f"  AGENT   : {text}")
                            transcript.append(("agent", text))

                    # GA renamed this to response.output_audio_transcript.done; accept both.
                    elif etype in ("response.output_audio_transcript.done", "response.audio_transcript.done"):
                        text = (evt.get("transcript") or "").strip()
                        if text:
                            print(f"  PATIENT : {text}")
                            transcript.append(("patient", text))

                    elif etype == "response.done":
                        # Reply finished cleanly -> re-arm the timers so the NEXT reply
                        # measures interruptions from its own start, not this one's.
                        # (The reference sample skips this and mis-times later replies.)
                        response_start_timestamp = None
                        last_assistant_item = None

                    elif etype == "input_audio_buffer.speech_started":
                        # The caller barged in. TWO things must happen, in this order:
                        #
                        #   1) Tell OpenAI HOW MUCH of the in-flight reply the caller
                        #      actually heard, so the model trims its own memory to match.
                        #      Skip this and the model believes it spoke the whole reply,
                        #      then later turns reference words the caller never got.
                        #   2) Tell Twilio to DROP the patient audio it has buffered but
                        #      not yet played, so the caller stops hearing us immediately.
                        #
                        # We must compute the truncate point BEFORE re-arming the timers
                        # below, because it's derived from them.
                        if last_assistant_item is not None and response_start_timestamp is not None:
                            # ms of THIS reply that reached the caller = now - when it began.
                            # (latest_media_timestamp is Twilio's real-time call clock, so
                            # this is exactly what was played -- never more than was generated.)
                            audio_end_ms = latest_media_timestamp - response_start_timestamp
                            if audio_end_ms < 0:
                                audio_end_ms = 0
                            await openai_ws.send(json.dumps({
                                "type": "conversation.item.truncate",
                                "item_id": last_assistant_item,
                                "content_index": 0,       # the audio content part
                                "audio_end_ms": audio_end_ms,
                            }))

                        if stream_sid:
                            await twilio_ws.send_text(json.dumps({
                                "event": "clear",
                                "streamSid": stream_sid,
                            }))

                        # This reply is done. Re-arm the timers so the next reply measures
                        # from its own first chunk, and clear the item so a second
                        # speech_started can't truncate it twice.
                        response_start_timestamp = None
                        last_assistant_item = None

                    elif etype == "error":
                        print("[openai][error]", json.dumps(evt))

            # Run both jobs; when either finishes (call ends), stop the other.
            task_a = asyncio.create_task(twilio_to_openai())
            task_b = asyncio.create_task(openai_to_twilio())
            done, pending = await asyncio.wait(
                {task_a, task_b}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()

    except Exception as e:
        print("[bridge] error:", repr(e))
    finally:
        # Save the conversation to transcripts/ (both .txt and .json).
        save_transcript(scenario, transcript, call_sid, started_at)
        print("[bridge] call finished.\n")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "5050"))
    print(f"Starting bridge server on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
