#!/usr/bin/env python3
"""vq11_browser.py — VQ 1.1 deterministic capture driver (Playwright, iPhone-13 emulation).
Serves public/ on localhost and drives the vq11 harness:
  - still captures in the three independent modes (pano / splat / both)
  - resource-timing + fps stats via window.__vq.stats()
  - throttled-network load profiles (to model the owner's 6095 ms HUD number)
  - motion video recording (walk out & back, deterministic waypoints)
Used by vq11_*.py experiment scripts. Chromium-headless caveat: frame-rate
numbers are SwiftShader-relative, NOT A15-GPU absolute; real-device numbers
come from the in-page ?autotest=1 battery run by the owner on iPhone Safari.
"""
import argparse, json, os, sys, threading, time, functools
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright

REPO = "/home/z/my-project/3d-idea"
PORT = 8141
IPHONE = dict(viewport={"width": 390, "height": 844}, device_scale_factor=3,
              is_mobile=True, has_touch=True,
              user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
                          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
                          "Mobile/15E148 Safari/604.1"))

_server = None
def serve():
    global _server
    if _server: return PORT
    os.chdir(f"{REPO}/public")
    handler = functools.partial(SimpleHTTPRequestHandler)
    _server = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    return PORT

def wait_ready(page, want_blend=None, timeout=45000):
    page.wait_for_function("window.__vq && window.__vq.stats().splats > 0", timeout=timeout)
    if want_blend is not None:
        page.wait_for_function(f"window.__vq.stats().blend >= {want_blend} - 0.01", timeout=15000)
    page.wait_for_timeout(700)                     # settle frames + fade

def stats(page):
    return page.evaluate("window.__vq.stats()")

def capture(url, out, want_blend=None, settle_ms=700, throttle=None, cold=False, console_errors=True):
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader",
                                    "--enable-unsafe-swiftshader"])
        ctx = b.new_context(**IPHONE, service_workers="block" if cold else "allow")
        if throttle:                                # CDP network conditioning
            ctx.set_default_timeout(60000)
        page = ctx.new_page()
        cdp = ctx.new_cdp_session(page)
        if throttle:
            cdp.send("Network.emulateNetworkConditions", {
                "offline": False, "latency": throttle["latency"],
                "downloadThroughput": throttle["down"], "uploadThroughput": throttle["up"],
                "connectionType": throttle.get("type", "cellular3g")})
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        t0 = time.time()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        wait_ready(page, want_blend)
        if settle_ms: page.wait_for_timeout(settle_ms)
        page.evaluate("window.__vq.freeze(true)")
        s = stats(page)
        page.screenshot(path=out, timeout=60000)
        page.evaluate("window.__vq.freeze(false)")
        s["nav_ms"] = round((time.time() - t0) * 1000)
        s["page_errors"] = errs
        b.close()
    return s

def record(url, out_webm, waypoints, mps=0.9, hide_ui=True, duration_extra_ms=1500):
    """Record a deterministic walk video. waypoints = [[x,z],...] in metres."""
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader",
                                    "--enable-unsafe-swiftshader"])
        ctx = b.new_context(**IPHONE, record_video_dir="/tmp/vq11vid",
                            record_video_size={"width": 390, "height": 844})
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        wait_ready(page)
        page.wait_for_timeout(900)
        if hide_ui: page.evaluate("window.__vq.hideUI()")
        js = f"window.__vq.runWalkPath({json.dumps(waypoints)}, {mps})"
        page.evaluate(js)
        page.wait_for_timeout(duration_extra_ms)
        page.wait_for_function("window.__vq.stats().blend < 0.01 || true")
        page.wait_for_timeout(1200)                 # fade back to pano at rest
        v = page.video.path()
        ctx.close(); b.close()
        os.replace(v, out_webm)
    return {"video": out_webm, "errors": errs}

def throttled_load(url, throttle, out_json=None):
    """Load page under network throttling; capture resource timing (fetch vs parse)."""
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader",
                                    "--enable-unsafe-swiftshader"])
        ctx = b.new_context(**IPHONE, service_workers="block")
        page = ctx.new_page()
        cdp = ctx.new_cdp_session(page)
        cdp.send("Network.emulateNetworkConditions", {
            "offline": False, "latency": throttle["latency"],
            "downloadThroughput": throttle["down"], "uploadThroughput": throttle["up"],
            "connectionType": throttle.get("type", "cellular3g")})
        t0 = time.time()
        page.goto(url, wait_until="domcontentloaded", timeout=120000)
        wait_ready(page, timeout=120000)
        s = stats(page)
        s["wall_ms"] = round((time.time() - t0) * 1000)
        if out_json: json.dump(s, open(out_json, "w"), indent=1)
        b.close()
        return s

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["capture", "record", "load"])
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--blend", type=float, default=None)
    ap.add_argument("--throttle", default=None, help="profile:fast3g|slow3g|mbps15|mbps14")
    ap.add_argument("--waypoints", default=None, help="JSON [[x,z],...]")
    a = ap.parse_args()
    serve()
    TH = {"fast3g": dict(latency=150, down=1.6*125_000, up=750*125, type="cellular3g"),
          "slow3g": dict(latency=400, down=0.5*125_000, up=250*125, type="cellular3g"),
          "mbps15": dict(latency=150, down=1.5*125_000, up=750*125, type="cellular3g"),
          "mbps14": dict(latency=100, down=1.4*125_000, up=700*125, type="cellular4g")}
    if a.cmd == "capture":
        s = capture(a.url, a.out, a.blend, throttle=TH.get(a.throttle))
        print(json.dumps(s, indent=1))
    elif a.cmd == "record":
        wps = json.loads(a.waypoints) if a.waypoints else [[0,0]]
        s = record(a.url, a.out, wps)
        print(json.dumps(s, indent=1))
    else:
        s = throttled_load(a.url, TH[a.throttle], a.out)
        print(json.dumps({k: s[k] for k in ["wall_ms", "timings" if "timings" in s else "spzReadyMs", "resources"]}, indent=1))
