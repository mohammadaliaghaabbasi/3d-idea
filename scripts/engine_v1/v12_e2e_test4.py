#!/usr/bin/env python3
"""v12_e2e_test4.py — focused re-run of E2E TEST 4 (honest walk label, safeR=0.3)
with a SwiftShader-v12-sized window (the 150 s window of the v11-era test is a
132k-splat budget; at 529k the walk's effective m/s shrinks with fps, so the
full 8-leg 0.3 m diamond needs a longer window to COMPLETE and restore the
button label — the walk function itself is already proven by TEST 3)."""
import json, sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright
import vq11_browser as B

BASE = "http://127.0.0.1:8141/labs/engine-v1/vq11.html"
B.serve()
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader",
                                "--enable-unsafe-swiftshader"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1,
                        is_mobile=True, has_touch=True, user_agent=B.IPHONE["user_agent"])
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(f"{BASE}?scene=moradi_main1&gen=v12&mode=both&safeR=0.3",
              wait_until="domcontentloaded", timeout=300000)
    B.wait_ready(page, timeout=300000)
    page.click("#walkbtn")
    done, max_dist = False, 0.0
    t0 = time.time()
    while time.time() - t0 < 600:                 # 10-min window (529k on SwiftShader)
        st = B.stats(page)
        max_dist = max(max_dist, st["dist"])
        if st["dist"] < 0.02 and st["blend"] < 0.05 and time.time() - t0 > 20:
            done = True; break
        page.wait_for_timeout(500)
    label = (page.text_content("#walkbtn") or "").strip()
    btn_disabled = page.evaluate("document.getElementById('walkbtn').disabled")
    print(f"[TEST4-rerun] done={done} max_dist={max_dist:.3f} label='{label}' "
          f"disabled={btn_disabled} errors={errs}", flush=True)
    ok1 = done and not btn_disabled
    ok2 = "0.3" in label
    print(f"  walk completes + control returns: {'PASS' if ok1 else 'FAIL'}")
    print(f"  label shows radius actually walked (0.3): {'PASS' if ok2 else 'FAIL'}")
    b.close()
    sys.exit(0 if (ok1 and ok2 and not errs) else 1)
