#!/usr/bin/env python3
"""Owner-review static server: serves 3d-idea/public on port 81 (platform preview port).

Purpose: let the owner review lab pages (e.g. /labs/engine-v1/moradi.html) through the
preview URL of the sandbox — without deploying anything and without touching main.
Read-only: serves existing files only, never writes.

Usage: python3 scripts/engine_v1/serve_review.py [port]   (default 81)
"""
import functools
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "public"


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 81
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    srv = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"serving {ROOT} on 0.0.0.0:{port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
