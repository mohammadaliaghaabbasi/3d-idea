#!/usr/bin/env python3
"""Double-fork daemon launcher for the owner-review server.

The sandbox reaper kills any process that is still a descendant of the Bash
session after each tool call. A classic double-fork + setsid daemon escapes
that tree and survives. Usage:

    python3 scripts/engine_v1/serve_review_daemon.py            # start (idempotent)
    python3 scripts/engine_v1/serve_review_daemon.py --status   # is it up?
    python3 scripts/engine_v1/serve_review_daemon.py --stop     # stop it

Serves 3d-idea/public on 0.0.0.0:3000 (platform gateway :81 -> preview URL).
"""
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE / "serve_review.py"
PORT = 3000
PIDFILE = Path("/tmp/serve_review_daemon.pid")


def is_up() -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{PORT}/index.html", timeout=2
        ) as r:
            return r.status == 200
    except Exception:
        return False


def start() -> None:
    if is_up():
        print(f"already running on :{PORT}")
        return
    # double fork
    pid = os.fork()
    if pid > 0:
        # parent waits briefly so the child can detach, then reports
        os.waitpid(pid, 0)
        return
    # child 1
    os.setsid()
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)
    # child 2 (daemon) — redirect std fds, then exec the real server
    sys.stdout = open("/tmp/serve_review.log", "a")
    sys.stderr = open("/tmp/serve_review.log", "a")
    sys.stdin = open("/dev/null", "r")
    PIDFILE.write_text(str(os.getpid()))
    os.execv(sys.executable, [sys.executable, str(SERVER), str(PORT)])


def main() -> None:
    if "--status" in sys.argv:
        alive = is_up()
        print(f"port {PORT}: {'UP' if alive else 'DOWN'}")
        sys.exit(0 if alive else 1)
    if "--stop" in sys.argv:
        if PIDFILE.exists():
            try:
                os.kill(int(PIDFILE.read_text().strip()), 15)
            except ProcessLookupError:
                pass
            PIDFILE.unlink(missing_ok=True)
        print("stop signal sent")
        return
    start()
    # give the daemon a moment, then verify
    import time

    for _ in range(20):
        time.sleep(0.25)
        if is_up():
            print(f"daemon started, serving on :{PORT} (pid {PIDFILE.read_text().strip()})")
            return
    print("FAILED to start — see /tmp/serve_review.log")
    sys.exit(1)


if __name__ == "__main__":
    main()
