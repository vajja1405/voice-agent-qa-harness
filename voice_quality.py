"""
voice_quality.py  -- measure the agent's VOICE quality with hard numbers.
=========================================================================

Voice quality is the thing Pretty Good AI grades FIRST and sells on ("natural
conversation") -- yet it's almost always judged by ear. This measures it.

Twilio recorded every call in DUAL CHANNEL (the two call legs on separate audio
channels). We fetch the WAV, split the channels, run a simple energy-based
voice-activity detector, and compute, per call:

  - talk-over %      : how often BOTH sides speak at once (bad turn-taking)
  - silence %        : dead air inside the conversation
  - longest silence  : the worst single gap
  - mean turn gap    : average pause between turns (a responsiveness proxy)
  - talk split       : how much the agent talks vs the patient

HONESTY: this is an energy-based approximation (not a trained VAD). The talk-over
and silence numbers are robust; treat the gap timing as indicative, not exact.

Usage:
    python voice_quality.py          # analyze every recording -> VOICE_QUALITY.md
"""

import os
import io
import glob
import json
import base64
import wave
import pathlib
import urllib.request

import numpy as np

HERE = pathlib.Path(__file__).parent
REC_DIR = HERE / "recordings"
FRAME_MS = 20  # analysis frame size


def load_env():
    env = {}
    for line in (HERE / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def scenario_map():
    """call_sid -> scenario name, from the saved transcripts."""
    m = {}
    for p in glob.glob(str(HERE / "transcripts" / "*.json")):
        d = json.load(open(p))
        m[d["call_sid"]] = d["scenario"]
    return m


def fetch_wav(sid, tok, rec_sid):
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Recordings/{rec_sid}.wav"
    auth = base64.b64encode(f"{sid}:{tok}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    return urllib.request.urlopen(req, timeout=60).read()


def _runs(mask):
    """Return (start, end) index pairs for each run of True."""
    m = mask.astype(np.int8)
    d = np.diff(np.concatenate(([0], m, [0])))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    return list(zip(starts, ends))


def analyze(wav_bytes):
    w = wave.open(io.BytesIO(wav_bytes))
    fr = w.getframerate()
    ch = w.getnchannels()
    raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    if ch == 2:
        raw = raw.reshape(-1, 2)
        a, b = raw[:, 0], raw[:, 1]
    else:
        a, b = raw, np.zeros_like(raw)

    fs = int(fr * FRAME_MS / 1000)  # samples per frame

    def frame_rms(x):
        n = len(x) // fs
        x = x[:n * fs].reshape(n, fs)
        return np.sqrt(np.mean(x * x, axis=1) + 1e-9)

    ra, rb = frame_rms(a), frame_rms(b)
    n = min(len(ra), len(rb))
    ra, rb = ra[:n], rb[:n]

    def vad(r):
        floor = np.percentile(r, 20)
        return r > max(floor * 3.0, 150.0)

    sa, sb = vad(ra), vad(rb)
    combined = sa | sb
    if not combined.any():
        return None

    # Restrict to the active window (first speech -> last speech) so leading/
    # trailing silence doesn't skew the numbers.
    first = int(np.argmax(combined))
    last = int(len(combined) - np.argmax(combined[::-1]))
    sa, sb = sa[first:last], sb[first:last]
    combined = sa | sb
    frame_s = FRAME_MS / 1000
    dur = len(sa) * frame_s

    overlap = sa & sb
    silence = ~combined
    talkover_s = overlap.sum() * frame_s
    silence_s = silence.sum() * frame_s
    longest_sil = max(((e - s) * frame_s for s, e in _runs(silence)), default=0.0)

    # Inter-turn gaps: silence stretches between two speech stretches.
    speech = _runs(combined)
    gaps = [(speech[i + 1][0] - speech[i][1]) * frame_s for i in range(len(speech) - 1)]
    gaps = [g for g in gaps if g > 0.1]

    # Who spoke first == the agent (clinics greet first).
    onset_a = int(np.argmax(sa)) if sa.any() else 1 << 30
    onset_b = int(np.argmax(sb)) if sb.any() else 1 << 30
    agent, patient = (sa, sb) if onset_a <= onset_b else (sb, sa)
    tot = (agent.sum() + patient.sum()) or 1

    return {
        "duration_s": round(dur, 1),
        "talkover_pct": round(100 * talkover_s / dur, 1) if dur else 0.0,
        "silence_pct": round(100 * silence_s / dur, 1) if dur else 0.0,
        "longest_silence_s": round(longest_sil, 1),
        "mean_gap_s": round(float(np.mean(gaps)), 2) if gaps else 0.0,
        "agent_talk_pct": int(round(100 * agent.sum() / tot)),
        "patient_talk_pct": int(round(100 * patient.sum() / tot)),
    }


def main():
    env = load_env()
    sid, tok = env["TWILIO_ACCOUNT_SID"], env["TWILIO_AUTH_TOKEN"]
    scen = scenario_map()

    rows = []
    for mp3 in sorted(glob.glob(str(REC_DIR / "*.mp3"))):
        name = os.path.basename(mp3)
        call = name.split("-RE")[0]
        rec = "RE" + name.split("-RE")[1].split(".")[0]
        try:
            met = analyze(fetch_wav(sid, tok, rec))
        except Exception as e:
            print(f"  skip {name}: {e}")
            continue
        if not met:
            continue
        met["scenario"] = scen.get(call, call[:10])
        rows.append(met)
        print(f"  {met['scenario']:22} talkover={met['talkover_pct']}%  "
              f"silence={met['silence_pct']}%  longest_gap={met['longest_silence_s']}s")

    if not rows:
        print("No recordings analyzed.")
        return

    def avg(k):
        return round(sum(r[k] for r in rows) / len(rows), 1)

    lines = ["# Voice-Quality Scorecard (measured from the call audio)\n",
             f"_Measured across {len(rows)} calls from the dual-channel recordings. "
             "Energy-based voice-activity detection, so treat gap timings as indicative; "
             "talk-over and silence are robust._\n",
             "\n## Per-call metrics\n",
             "| Scenario | Duration | Talk-over % | Silence % | Longest gap (s) | Mean turn gap (s) | Agent/Patient talk |",
             "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: -x["talkover_pct"]):
        lines.append(
            f"| {r['scenario']} | {r['duration_s']}s | {r['talkover_pct']}% | {r['silence_pct']}% "
            f"| {r['longest_silence_s']} | {r['mean_gap_s']} | {r['agent_talk_pct']}/{r['patient_talk_pct']} |"
        )
    lines += [
        "\n## Averages\n",
        f"- **Talk-over (both speaking at once):** {avg('talkover_pct')}%",
        f"- **Silence / dead air (mid-call):** {avg('silence_pct')}%",
        f"- **Longest single gap:** {avg('longest_silence_s')}s (avg of per-call worst)",
        f"- **Mean pause between turns:** {avg('mean_gap_s')}s",
        "\n## Why this matters\n",
        "Natural conversation is the #1 thing this role grades, and it's usually judged by ear. "
        "These are hard numbers on that exact axis, measured on the live agent. High talk-over and "
        "long gaps are the audible 'it feels broken' symptoms behind the turn-taking bugs in "
        "`FINDINGS.md` -- now quantified and trackable release-over-release.",
    ]
    (HERE / "VOICE_QUALITY.md").write_text("\n".join(lines))
    # also machine-readable for the regression baseline
    (HERE / "voice_quality.json").write_text(json.dumps(rows, indent=2))
    print("\n[voice_quality] wrote VOICE_QUALITY.md + voice_quality.json")


if __name__ == "__main__":
    main()
