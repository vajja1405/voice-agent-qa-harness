"""
run_all.py  -- place ALL the test calls automatically, one after another.
=========================================================================

Instead of running `python caller.py --scenario X` eleven times by hand, this runs
the whole test matrix for you: it places a call, waits for it to finish, then places
the next one. You just start the server + ngrok, run this once, and watch.

Usage:
    python run_all.py                 # run the default set (12 scenarios)
    python run_all.py --only safety   # run just one category
    python run_all.py --list          # show the scenarios it will run

Prerequisites (in two other terminals):
    1) python server.py
    2) ngrok http 5050
"""

import os
import time
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

# A sensible order: safety/rule/memory probes first (highest-value bugs), then the rest.
DEFAULT_ORDER = [
    "schedule_basic",
    "emergency_escalation", "medical_advice", "phi_privacy",
    "weekend_rule", "memory_consistency",
    "prompt_injection",
    "reschedule", "cancel", "refill_basic", "new_patient", "hours_insurance",
]

FINISHED = {"completed", "failed", "busy", "no-answer", "canceled"}


def place_and_wait(client, scenario, host, max_wait=360):
    """Place one call and block until Twilio says it finished (or we time out)."""
    url = f"https://{host}/twiml?scenario={scenario}"
    call = client.calls.create(
        to=TO_NUMBER, from_=FROM_NUMBER, url=url, method="GET",
        record=True, recording_channels="dual",
    )
    print(f"    call SID: {call.sid}  (dialing...)")
    start = time.time()
    last = None
    while time.time() - start < max_wait:
        time.sleep(6)
        status = client.calls(call.sid).fetch().status
        if status != last:
            print(f"    status: {status}")
            last = status
        if status in FINISHED:
            return status
    return "timeout"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Run only scenarios in this category "
                        "(normal|rule_discovery|memory|safety|compliance).")
    parser.add_argument("--gap", type=int, default=8, help="Seconds to wait between calls.")
    parser.add_argument("--list", action="store_true", help="List the scenarios and exit.")
    args = parser.parse_args()

    # Build the run list
    if args.only:
        order = [n for n in SCENARIOS if SCENARIOS[n].category == args.only]
        if not order:
            raise SystemExit(f"No scenarios in category '{args.only}'.")
    else:
        order = [n for n in DEFAULT_ORDER if n in SCENARIOS]

    if args.list:
        print("Will run these scenarios:")
        for n in order:
            print(f"  - {n} ({SCENARIOS[n].category})")
        return

    for req in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"):
        if not os.getenv(req):
            raise SystemExit(f"Missing {req} in .env")

    host = get_public_host()
    client = Client(ACCOUNT_SID, AUTH_TOKEN)

    print(f"Public host : {host}")
    print(f"Calling     : {TO_NUMBER}")
    print(f"Scenarios   : {len(order)}\n")

    results = []
    for i, scenario in enumerate(order, 1):
        print(f"[{i}/{len(order)}] {scenario}")
        try:
            status = place_and_wait(client, scenario, host)
        except Exception as e:
            status = f"error: {e}"
        results.append((scenario, status))
        print(f"    -> {status}\n")
        time.sleep(args.gap)

    print("=" * 50)
    print("Batch complete. Summary:")
    for scenario, status in results:
        print(f"  {scenario:22} {status}")
    print("\nNext:")
    print("  python download_recordings.py   # save the audio (MP3)")
    print("  python analyzer.py              # grade -> bug_report.md + BUSINESS_IMPACT.md")


if __name__ == "__main__":
    main()
