#!/usr/bin/env python3
"""run_daemon.py — run a python script as a double-fork daemon (reaper-proof).

The sandbox reaper kills process groups of finished tool calls; a classic
double-fork + setsid grandchild survives it (proven pattern: marble_lab_render.py,
serve_review_daemon.py). Usage:

  python3 run_daemon.py <logfile> <script.py> [args...]

The grandchild redirects std fds to <logfile> and execs the script.
"""
import os, sys

def double_fork_daemon(logfile):
    pid = os.fork()
    if pid > 0:
        os.waitpid(pid, 0)
        print(f"daemon grandchild launched (parent reaped child {pid})")
        os._exit(0)
    os.setsid()
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)
    log = open(logfile, "a", buffering=1)
    os.dup2(log.fileno(), 1)
    os.dup2(log.fileno(), 2)
    sys.stdout = log
    sys.stderr = log

if __name__ == "__main__":
    logfile, script = sys.argv[1], sys.argv[2]
    double_fork_daemon(logfile)
    os.execvp(sys.executable, [sys.executable, script] + sys.argv[3:])
