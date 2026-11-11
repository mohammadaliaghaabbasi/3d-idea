#!/usr/bin/env python3
"""v12_smoke.py — one-capture smoke test of the v12 harness wiring.
Loads moradi_main1 gen=v12 (default now), waits for the splat, checks
splatCount ~520k, lod on, no page errors, snaps splat+both at origin and
0.75m. Prints stats JSON. Nothing is written into the repo."""
import json, sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright
import vq11_browser as B

BASE = "http://127.0.0.1:8141/labs/engine-v1/vq11.html"
B.serve()
out = {}
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader",
                                "--enable-unsafe-swiftshader"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1,
                        is_mobile=True, has_touch=True, user_agent=B.IPHONE["user_agent"])
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    t0 = time.time()
    page.goto(f"{BASE}?scene=moradi_main1&gen=v12&mode=both", wait_until="domcontentloaded", timeout=120000)
    B.wait_ready(page, timeout=240000)
    s = B.stats(page)
    out["load"] = {k: s[k] for k in ("gen", "genActual", "splats", "lod", "spzReadyMs", "errors", "mode")}
    out["load"]["wall_s"] = round(time.time()-t0, 1)
    print("[load]", json.dumps(out["load"]), "pageerrors:", errs, flush=True)
    for tag, state in [
        ("origin_splat", dict(mode="splat", dir="+x", offset=0.0, look="back", bg="magenta")),
        ("origin_both",  dict(mode="both",  dir="+x", offset=0.0, look="back", bg="black", blend=1)),
        ("px075_both",   dict(mode="both",  dir="+x", offset=0.75, look="back", bg="black", blend=1)),
        ("px075_splat",  dict(mode="splat", dir="+x", offset=0.75, look="back", bg="magenta")),
    ]:
        r = page.evaluate(f"window.__vq.settleState({json.dumps(state)}, 15000, 60000)")
        # in-page snap (base64) — page.screenshot stalls on SwiftShader first sort
        import base64
        data = page.evaluate("window.__vq.snap('jpeg')")
        open(f"/tmp/v12_smoke_{tag}.jpg", "wb").write(base64.b64decode(data.split(",", 1)[1]))
        out[tag] = r
        print(f"[{tag}]", json.dumps(r), flush=True)
    b.close()
out["page_errors"] = errs
json.dump(out, open("/tmp/v12_smoke.json", "w"), indent=1)
print("SMOKE", "PASS" if (out["load"]["splats"] > 500000 and out["load"]["lod"] and not errs) else "CHECK",
      json.dumps({k: out[k] for k in ("load",)}, default=str))
