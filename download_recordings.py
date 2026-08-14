"""
download_recordings.py  -- pull the call audio from Twilio into recordings/.
============================================================================

Twilio records each call (we turned that on in caller.py). This script downloads
those recordings as MP3 files so we can submit them (the challenge requires audio
in MP3 or OGG). Each file is named by its Call SID, which matches the Call SID in
the transcript files -- so a reviewer can line up "the audio" with "the words."

Usage:
    python download_recordings.py            # download all recordings from your account
    python download_recordings.py --limit 20 # only the most recent 20
"""

import os
import argparse
import pathlib
import requests
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
RECORDINGS_DIR = pathlib.Path(__file__).parent / "recordings"


def main():
    parser = argparse.ArgumentParser(description="Download Twilio call recordings as MP3.")
    parser.add_argument("--limit", type=int, default=50, help="Max recordings to fetch.")
    args = parser.parse_args()

    if not (ACCOUNT_SID and AUTH_TOKEN):
        raise SystemExit("Missing TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN in .env")

    RECORDINGS_DIR.mkdir(exist_ok=True)
    client = Client(ACCOUNT_SID, AUTH_TOKEN)

    recordings = client.recordings.list(limit=args.limit)
    if not recordings:
        print("No recordings found yet. Make some calls first.")
        return

    print(f"Found {len(recordings)} recording(s). Downloading to {RECORDINGS_DIR}/ ...")
    for rec in recordings:
        # Twilio serves the audio as MP3 if you request the .mp3 media URL.
        media_url = f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/Recordings/{rec.sid}.mp3"
        out_path = RECORDINGS_DIR / f"{rec.call_sid}-{rec.sid}.mp3"

        resp = requests.get(media_url, auth=(ACCOUNT_SID, AUTH_TOKEN))
        if resp.status_code == 200:
            out_path.write_bytes(resp.content)
            print(f"  saved {out_path.name}  ({len(resp.content)//1024} KB)")
        else:
            print(f"  FAILED {rec.sid} (HTTP {resp.status_code})")

    print("Done.")


if __name__ == "__main__":
    main()
