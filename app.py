#!/usr/bin/env python3
"""Start the Job MCP web UI + local API.

    .venv\\Scripts\\python app.py               # http://127.0.0.1:8765, opens the browser
    .venv\\Scripts\\python app.py --no-browser

Serves web/dist at / (build it with: cd web && npm install && npm run build) and
the API under /api. Binds to localhost only.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

for _stream in (sys.stdout, sys.stderr):  # Windows consoles + "₹" in job data
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Job MCP web UI")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser")
    args = ap.parse_args()

    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    import uvicorn
    from api.app import create_app

    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"Job MCP web UI: {url}  (Ctrl+C to stop)", file=sys.stderr, flush=True)
    # loop="asyncio" without reload/workers gives a ProactorEventLoop on Windows.
    # Browser (Playwright) work runs on its own Proactor loop thread anyway
    # (api/browser_thread.py), so it works however the server loop is set up.
    uvicorn.run(create_app(), host=args.host, port=args.port, loop="asyncio", log_level="info")


if __name__ == "__main__":
    main()
