"""
caller.py  -- places ONE real outbound phone call to the clinic's test agent.
=============================================================================

Run this AFTER the server (server.py) is running and ngrok is pointing at it.

What happens when you run it:
  1. We ask Twilio to call the clinic's assessment number FROM your Twilio number.
  2. We tell Twilio: "when they answer, fetch your instructions from my /twiml URL"
     (which connects the call's audio to our bridge -- see server.py).
  3. We turn on dual-channel recording so we get an audio file of the call
     (both sides on separate channels) to download later in Milestone 2.

Usage:
    python caller.py                      # uses the default scenario
    python caller.py --scenario schedule_basic
"""

import os
import argparse

from twilio.rest import Client
from dotenv import load_dotenv

from scenarios import SCENARIOS
from ngrok_util import get_public_host

load_dotenv()

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")
TO_NUMBER = os.getenv("TEST_AGENT_NUMBER", "+18054398008")


def main():
    parser = argparse.ArgumentParser(description="Place one test call as a simulated patient.")
    parser.add_argument(
        "--scenario",
        default="schedule_basic",
        choices=list(SCENARIOS.keys()),
        help="Which patient scenario to run.",
    )
    args = parser.parse_args()

    # Fail early with a friendly message if something isn't configured.
    missing = [k for k, v in {
        "TWILIO_ACCOUNT_SID": ACCOUNT_SID,
        "TWILIO_AUTH_TOKEN": AUTH_TOKEN,
        "TWILIO_FROM_NUMBER": FROM_NUMBER,
    }.items() if not v]
    if missing:
        raise SystemExit(f"Missing .env values: {', '.join(missing)}. Copy .env.example to .env and fill them in.")

    public_host = get_public_host()   # auto-detected from ngrok (or PUBLIC_HOSTNAME if set)
    client = Client(ACCOUNT_SID, AUTH_TOKEN)
    twiml_url = f"https://{public_host}/twiml?scenario={args.scenario}"

    print(f"Calling {TO_NUMBER} from {FROM_NUMBER}")
    print(f"Scenario : {args.scenario}")
    print(f"TwiML    : {twiml_url}")

    call = client.calls.create(
        to=TO_NUMBER,
        from_=FROM_NUMBER,
        url=twiml_url,
        method="GET",
        record=True,                 # record the call...
        recording_channels="dual",   # ...with each side on its own channel
    )

    print(f"\nCall started. Call SID: {call.sid}")
    print("Watch the server window to see the live conversation transcript.")


if __name__ == "__main__":
    main()
