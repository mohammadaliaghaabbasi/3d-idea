#!/usr/bin/env python3
"""vq11_ab.py — VQ 1.1 agent-browser driver (instant full-DPR stills + 30fps videos).
Playwright's page.screenshot hangs on splat-only frames in SwiftShader headless
(stability wait); agent-browser's raw captureScreenshot is instant at DPR3.
API (persistent session, one page load per scene/gen — in-page reconfiguration):
  open(gen, scene, url_extra)   load harness, wait for splats
  still(state, path)            __vq.state(...) + freeze + screenshot
  video(waypoints, path, ...)   record start + runWalkPath + record stop
  stats()                       __vq.stats() as dict
"""
import json, os, subprocess, time

BASE = "http://localhost:8137/labs/engine-v1/vq11.html"

def ab(*args, timeout=180):
    r = subprocess.run(["agent-browser", *args], capture_output=True, text=True, timeout=timeout)
    out = (r.stdout + r.stderr).strip()
    return out

def ab_eval(js, timeout=180):
    out = ab("eval", js, timeout=timeout)
    # agent-browser prints the raw result (or JSON for objects)
    if out.startswith("{") or out.startswith("["):
        try: return json.loads(out)
        except Exception: return out
    return out

def close_all():
    ab("close", "--all")

def open_lab(gen="v1", scene="cabin", extra="", wait_splats=True, dpr=3):
    close_all()
    ab("set", "viewport", "390", "844", str(dpr))
    url = f"{BASE}?scene={scene}&gen={gen}&mode=both&ui=0&offset=0&dir=%2Bx&look=back&blend=auto{extra}"
    ab("open", url)
    for _ in range(120):
        try:
            n = int(ab_eval("window.__vq ? window.__vq.stats().splats : 0"))
            if n and n > 0: return n
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("splat never loaded")

def still(state, path, settle_ms=250):
    """state: dict(mode, dir, offset, look, blend, bg, pitch)."""
    ab_eval(f"window.__vq.state({json.dumps(state)})")
    time.sleep(settle_ms / 1000)
    ab_eval("window.__vq.freeze(true)")
    out = ab("screenshot", path)
    ab_eval("window.__vq.freeze(false)")
    if "saved" not in out.lower():
        raise RuntimeError("screenshot failed: " + out)
    return path

def stats():
    return ab_eval("window.__vq.stats()")

def video(waypoints, path, mps=0.9, pre_ms=800, post_ms=2500, look=None):
    """Record one deterministic walk. look: optional [yaw, pitch] applied at start."""
    if look:
        ab_eval(f"window.__vq.setLook({look[0]}, {look[1]})")
    ab_eval("window.__vq.freeze(false)")
    time.sleep(pre_ms / 1000)
    ab("record", "start", path)
    ab_eval(f"window.__vq.runWalkPath({json.dumps(waypoints)}, {mps})")
    time.sleep(sum(0 if i == 0 else __import__('math').hypot(waypoints[i][0]-waypoints[i-1][0], waypoints[i][1]-waypoints[i-1][1]) for i in range(1, len(waypoints))) / mps + post_ms / 1000)
    ab("record", "stop")
    return path

if __name__ == "__main__":
    import sys
    n = open_lab(sys.argv[1] if len(sys.argv) > 1 else "v1")
    print("splats:", n, "| stats fps:", stats()["fps"])
