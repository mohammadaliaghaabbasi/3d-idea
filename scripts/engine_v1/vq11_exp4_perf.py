#!/usr/bin/env python3
"""vq11_exp4_perf.py — VQ 1.1 mobile load/perf battery (Playwright + CDP throttle).
Question 3 of the mission: real SPZ load time, first frame, fps/p95 at rest and
walking, memory, and the 6095 ms HUD number vs the earlier 338-934 ms lab result.
Profiles: localhost (no network) — isolates parse; fast3g 1.6 Mbps; mbps15
1.5 Mbps (matches the owner's implied bandwidth); slow3g 0.5 Mbps.
Fresh cold context per run (no cache, service workers blocked).
Honesty note: headless Chromium+SwiftShader fps numbers are RELATIVE (software
rasterizer), NOT iPhone-13-absolute; the ?autotest=1 in-page battery is what
the owner runs on the real device for absolute numbers.
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from playwright.sync_api import sync_playwright
import vq11_browser as B

BASE = "http://127.0.0.1:8141/labs/engine-v1/vq11.html"
OUT = "/home/z/my-project/3d-idea/docs/rd-artifacts/engine-v1"
PROFILES = {
    "localhost": None,
    "fast3g_1.6mbps_150ms": dict(latency=150, down=int(1.6*125_000), up=750*125, type="cellular3g"),
    "mbps15_1.5mbps_150ms":  dict(latency=150, down=int(1.5*125_000), up=750*125, type="cellular3g"),
    "slow3g_0.5mbps_400ms": dict(latency=400, down=int(0.5*125_000), up=250*125, type="cellular3g"),
}
URLS = {
    "gen_v11_pano1": f"{BASE}?scene=cabin&gen=v11&mode=both&ui=0&blend=auto",
    "gen_v11_pano0": f"{BASE}?scene=cabin&gen=v11&mode=splat&ui=0&bg=black",
}

def run(p, throttle, url, tag, load_only=False):
    b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader",
                                "--enable-unsafe-swiftshader"])
    ctx = b.new_context(**B.IPHONE, service_workers="block")
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    if throttle:
        cdp.send("Network.emulateNetworkConditions", {
            "offline": False, "latency": throttle["latency"],
            "downloadThroughput": throttle["down"], "uploadThroughput": throttle["up"],
            "connectionType": throttle.get("type", "cellular3g")})
    t0 = time.time()
    page.goto(url, wait_until="domcontentloaded", timeout=180000)
    B.wait_ready(page, timeout=180000)          # splats loaded (fetch+parse done)
    s = page.evaluate("window.__vq.stats()")
    s["wall_ms"] = round((time.time()-t0)*1000)
    idle = walk = None
    if not load_only:
        # idle fps window
        page.wait_for_timeout(6000)
        idle = page.evaluate("window.__vq.stats()")
        # walking fps window (SwiftShader-relative)
        page.evaluate("window.__vq.runWalkPath([[0,0],[0.75,0],[0,0],[0,0.75],[0,0]], 0.9)")
        page.wait_for_timeout(7000)
        walk = page.evaluate("window.__vq.stats()")
    b.close()
    rec = {"tag": tag,
           "spz_ready_ms": s["spzReadyMs"], "first_frame_ms": s["firstFrameMs"],
           "marks": s["marks"], "resources": s["resources"], "wall_ms": s["wall_ms"],
           "idle_fps_swiftshader": idle["fps"] if idle else None,
           "idle_p95_ms": idle["frameP95Ms"] if idle else None,
           "walk_fps_swiftshader": walk["fps"] if walk else None,
           "walk_p95_ms": walk["frameP95Ms"] if walk else None,
           "heapMB_chromium": (walk or s)["heapMB"], "errors": s["errors"]}
    return rec

def main():
    B.serve()
    results = {"note": "fps values are SwiftShader-relative (headless software GL); "
                       "real-device absolute numbers come from ?autotest=1 on iPhone Safari",
               "runs": []}
    JOBS = ([("localhost", None, "gen_v11_pano1", False),
             ("localhost", None, "gen_v11_pano0", False)] +
            [(pn, th, "gen_v11_pano1", True) for pn, th in PROFILES.items() if th] +
            [(pn, th, "gen_v11_pano0", True) for pn, th in PROFILES.items() if th])
    with sync_playwright() as p:
        for pname, th, uname, lo in JOBS:
            tag = f"{pname}/{uname}"
            try:
                r = run(p, th, URLS[uname], tag, load_only=lo)
                r["profile"] = pname
                results["runs"].append(r)
                print(tag, "->", r["spz_ready_ms"], "ms spz |", r["first_frame_ms"], "ms ff", flush=True)
            except Exception as e:
                print(tag, "FAILED:", str(e)[:200], flush=True)
                results["runs"].append({"tag": tag, "error": str(e)[:300]})
            json.dump(results, open(f"{OUT}/vq11_perf.json", "w"), indent=1)   # incremental
    print("saved ->", f"{OUT}/vq11_perf.json")

if __name__ == "__main__":
    main()
