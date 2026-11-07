#!/usr/bin/env python3
"""moradi_battery.py — MORADI REAL-CONTENT TEST, Phase C still battery.
Settle-aware in-page toDataURL captures (VQ 1.1 exp2 methodology, DPR1):
  per scene: origin pano refs (4 dirs) + warm sort + 0.75 m x 4 dirs x (splat
  magenta / both full-blend) + window.__vq.stats() perf marks.
  ladder mode: full 0.2-1.3 m distance ladder x 4 dirs for one scene.
Usage: moradi_battery.py <scene_id> [--ladder]
Outputs -> /home/z/my-project/download/panodrome-moradi/stills/
Index    -> docs/rd-artifacts/engine-v1/moradi_stills_index.json (merged)
"""
import base64, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright
import vq11_browser as B

OUT = "/home/z/my-project/download/panodrome-moradi/stills"; os.makedirs(OUT, exist_ok=True)
ART = "/home/z/my-project/3d-idea/docs/rd-artifacts/engine-v1"
IDX = f"{ART}/moradi_stills_index.json"
BASE = "http://127.0.0.1:8141/labs/engine-v1/vq11.html"
DISTS_LADDER = [0.2, 0.4, 0.6, 0.75, 1.0, 1.3]
DIRS = ["+x", "-x", "+z", "-z"]
CODES = {"+x": "px", "-x": "mx", "+z": "pz", "-z": "mz"}

def load_index():
    return json.load(open(IDX)) if os.path.exists(IDX) else {"scenes": {}, "errors": []}

def snap(page, name, results):
    path = f"{OUT}/{name}.jpg"
    data = page.evaluate("window.__vq.snap('jpeg')")
    open(path, "wb").write(base64.b64decode(data.split(",", 1)[1]))
    results["states"][name] = path
    print(f"  still {name}", flush=True)

def settle(page, state, label, results, min_ms=12000, timeout_ms=40000):
    r = page.evaluate(f"window.__vq.settleState({json.dumps(state)}, {min_ms}, {timeout_ms})")
    results["settle"][label] = r
    ok = isinstance(r, dict) and r.get("settled")
    print(f"  settle {label}: settled={ok}" + ("" if ok else f" raw={r}"), flush=True)
    return ok

def run(scene, ladder=False, dirs=None):
    global DIRS
    if dirs:
        DIRS = dirs
    results = load_index()
    results.setdefault("states", {}); results.setdefault("settle", {})
    sr = {"t_start": time.time()}
    B.serve()
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader",
                                    "--enable-unsafe-swiftshader"])
        ctx = b.new_context(viewport={"width": 390, "height": 844},
                            device_scale_factor=1, is_mobile=True, has_touch=True,
                            user_agent=B.IPHONE["user_agent"])
        page = ctx.new_page()
        page.on("pageerror", lambda e: results["errors"].append(f"{scene}: {e}"))
        page.goto(f"{BASE}?scene={scene}&gen=v11&mode=pano&ui=0&offset=0&dir=%2Bx&look=back",
                  wait_until="domcontentloaded", timeout=60000)
        B.wait_ready(page)
        page.wait_for_timeout(1200)
        sr["stats_load"] = B.stats(page)
        # origin pano refs (4 look dirs; pano-only renders are instant)
        for d in DIRS:
            ok = page.evaluate(f"window.__vq.settleState({json.dumps(dict(mode='pano', dir=d, offset=0.0, look='back', bg='black'))}, 800, 8000)")
            snap(page, f"{scene}_pano_{CODES[d]}", results)
        # warm the first sort (origin, splat over magenta)
        t0 = time.time()
        ok = settle(page, dict(mode="splat", dir="+x", offset=0.0, look="back", bg="magenta"),
                    f"{scene}-warm", results, min_ms=12000, timeout_ms=150000)
        if not ok:  # one retry — cold SwiftShader sorts can exceed 150 s
            ok = settle(page, dict(mode="splat", dir="+x", offset=0.0, look="back", bg="magenta"),
                        f"{scene}-warm-retry", results, min_ms=20000, timeout_ms=180000)
        sr["warm_s"] = round(time.time()-t0, 1)
        dists = DISTS_LADDER if ladder else [0.75]
        for d in DIRS:
            code = CODES[d]
            for off in dists:
                dtag = str(off).replace(".", "")           # 0.2->02, 0.75->075, 1.3->13
                names = dict(splat=f"{scene}_{code}_{dtag}_splat", both=f"{scene}_{code}_{dtag}_both")
                if all(os.path.exists(f"{OUT}/{n}.jpg") for n in names.values()):
                    print(f"  skip fresh {code} {off}m", flush=True); continue
                settle(page, dict(mode="splat", dir=d, offset=off, look="back", bg="magenta"),
                       f"{scene}-{code}-{off}", results)
                snap(page, names["splat"], results)
                ok = page.evaluate(f"window.__vq.settleState({json.dumps(dict(mode='both', dir=d, offset=off, look='back', bg='black', blend=1))}, 1000, 12000)")
                results["settle"][f"verify:{names['both']}"] = ok
                snap(page, names["both"], results)
        sr["stats_end"] = B.stats(page)
        page.close(); ctx.close(); b.close()
    sr["t_total_s"] = round(time.time()-sr["t_start"], 1)
    results["scenes"][scene] = sr
    json.dump(results, open(IDX, "w"), indent=1)
    print(f"[battery] {scene} DONE in {sr['t_total_s']}s (warm {sr['warm_s']}s) | errors: {results['errors'][-3:]}")

if __name__ == "__main__":
    scene = sys.argv[1]
    ladder = "--ladder" in sys.argv
    dirs = None
    for a in sys.argv[2:]:
        if a.startswith("--dirs="):
            dirs = a.split("=", 1)[1].split(",")
    run(scene, ladder, dirs)
