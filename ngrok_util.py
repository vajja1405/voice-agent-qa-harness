"""
ngrok_util.py  -- find the current public URL automatically.
============================================================

ngrok's free URL changes every time you restart it, which was annoying (you had to
copy it into .env each time). This removes that step: if PUBLIC_HOSTNAME isn't set in
.env, we ask ngrok's own local API (http://127.0.0.1:4040) for the current URL.

So the workflow becomes: start ngrok, run the calls. No copy-paste, no restarts.
"""

import os
import json
import urllib.request

_PLACEHOLDER = "your-subdomain.ngrok-free.app"


def get_public_host() -> str:
    """Return the public hostname (no scheme, no trailing slash)."""
    # 1) If you explicitly set PUBLIC_HOSTNAME in .env, use that.
    env = os.getenv("PUBLIC_HOSTNAME", "").replace("https://", "").replace("http://", "").rstrip("/")
    if env and env != _PLACEHOLDER:
        return env

    # 2) Otherwise, auto-detect from ngrok's local dashboard API.
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=3) as r:
            data = json.load(r)
    except Exception:
        raise SystemExit(
            "Couldn't find the public URL.\n"
            "  - Make sure `ngrok http 5050` is running in another terminal, OR\n"
            "  - set PUBLIC_HOSTNAME in your .env manually."
        )

    for tunnel in data.get("tunnels", []):
        url = tunnel.get("public_url", "")
        if url.startswith("https://"):
            return url.replace("https://", "").rstrip("/")

    raise SystemExit("ngrok is running but no https tunnel was found. Try restarting `ngrok http 5050`.")
