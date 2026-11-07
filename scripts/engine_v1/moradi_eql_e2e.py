#!/usr/bin/env python3
"""moradi_eql_e2e.py — E2E verification of the new-rules Moradi fix (2026-11-07).

Checks (branch engine-upgrade-v1, public/ served locally, SwiftShader + DPR1
— same profile as the mission battery moradi_battery.py):
  1. vq11 default safeR is now the MEASURED envelope 0.75 (was 1.3)
     + during the walk demo the camera never leaves the envelope and the
       splat layer blends in while moving
  1b. walk button label shows the radius actually walked (safeR=0.3 -> "0.3m")
  2. explicit ?safeR=1.3 still gives the full R&D ladder
  3. ?autotest=1 battery self-lifts SAFE_R to 1.3 (instrument not degraded)
  5. moradi.html renders with the EQL section, 10 cards x EQL rows, no JS errors
Screenshots -> /tmp/render/ for visual inspection.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright
import vq11_browser as B

os.makedirs("/tmp/render", exist_ok=True)
BASE = "http://127.0.0.1:8141/labs/engine-v1/vq11.html"
RESULTS = []

def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""), flush=True)

B.serve()
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader",
                                "--enable-unsafe-swiftshader"])
    # battery profile: DPR 1 (DPR3 software-GL rasterization is far too slow for E2E)
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1,
                        is_mobile=True, has_touch=True, user_agent=B.IPHONE["user_agent"])
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))

    # -- 1: default envelope + walk stays inside it --------------------------
    print("TEST 1: default envelope + walk clamp (moradi_main1)", flush=True)
    page.goto(f"{BASE}?scene=moradi_main1&gen=v11&mode=both", wait_until="domcontentloaded", timeout=60000)
    B.wait_ready(page)
    s = B.stats(page)
    check("default safeR == 0.75", s["safeR"] == 0.75, f"safeR={s['safeR']}")
    check("splat loaded (v11)", s["splats"] == 132349 and s["genActual"] == "v11",
          f"splats={s['splats']} gen={s['genActual']}")
    page.click("#walkbtn")
    max_dist, saw_blend = 0.0, False
    t0 = time.time()
    while time.time() - t0 < 14:                 # sample the walk; SwiftShader paces slowly
        st = B.stats(page)
        max_dist = max(max_dist, st["dist"])
        if st["dist"] > 0.1 and st["blend"] > 0.3:
            saw_blend = True
        page.wait_for_timeout(400)
    check("walk never leaves the 0.75 m envelope", max_dist <= 0.75 + 0.02,
          f"max_dist={max_dist:.3f}")
    check("moving: splat layer blended in", saw_blend, f"max_dist={max_dist:.3f}")

    # -- 1b: dynamic label with a DIFFERENT radius (safeR=0.3) ----------------
    print("TEST 1b: honest walk label (safeR=0.3)", flush=True)
    page.goto(f"{BASE}?scene=moradi_main1&gen=v11&mode=both&safeR=0.3", wait_until="domcontentloaded", timeout=60000)
    B.wait_ready(page)
    check("override safeR == 0.3", B.stats(page)["safeR"] == 0.3)
    page.click("#walkbtn")
    done, max_dist = False, 0.0
    t0 = time.time()
    while time.time() - t0 < 45:                 # 8 x 0.3 m diamond; SwiftShader margin
        st = B.stats(page)
        max_dist = max(max_dist, st["dist"])
        if st["dist"] < 0.02 and st["blend"] < 0.05 and time.time() - t0 > 4:
            done = True
            break
        page.wait_for_timeout(500)
    label = (page.text_content("#walkbtn") or "").strip()
    check("short walk completes + rests on pano", done, f"max_dist={max_dist:.3f}")
    check("label shows radius actually walked (0.3)", "0.3" in label, f"label='{label}'")
    page.evaluate("window.__vq.freeze(true)")
    page.screenshot(path="/tmp/render/e2e_walk_demo_end.jpg", timeout=90000)
    page.evaluate("window.__vq.freeze(false)")

    # -- 2: explicit R&D ladder still available ------------------------------
    print("TEST 2: explicit ?safeR=1.3 ladder", flush=True)
    page.goto(f"{BASE}?scene=moradi_kit2&gen=v11&mode=both&safeR=1.3", wait_until="domcontentloaded", timeout=60000)
    B.wait_ready(page)
    check("explicit safeR == 1.3", B.stats(page)["safeR"] == 1.3, f"safeR={B.stats(page)['safeR']}")

    # -- 3: autotest self-lift ------------------------------------------------
    print("TEST 3: autotest battery self-lift (10s idle, then lift)", flush=True)
    page.goto(f"{BASE}?scene=moradi_bed1a&gen=v11&mode=both&autotest=1", wait_until="domcontentloaded", timeout=60000)
    B.wait_ready(page)
    check("autotest start: safeR still 0.75 (pre-lift)", B.stats(page)["safeR"] == 0.75,
          f"safeR={B.stats(page)['safeR']}")
    lifted = False
    t0 = time.time()
    while time.time() - t0 < 35:
        if B.stats(page)["safeR"] == 1.3:
            lifted = True
            break
        page.wait_for_timeout(500)
    check("autotest lifts SAFE_R to 1.3 before walk battery", lifted,
          f"safeR={B.stats(page)['safeR']}")

    # -- 5: moradi.html review page ------------------------------------------
    print("TEST 5: moradi.html EQL section + 10 cards", flush=True)
    errs.clear()
    page2 = ctx.new_page()
    page2.on("pageerror", lambda e: errs.append(str(e)))
    page2.goto("http://127.0.0.1:8141/labs/engine-v1/moradi.html", wait_until="domcontentloaded", timeout=60000)
    page2.wait_for_selector("#eql", timeout=15000)
    cards = page2.locator("#scenes article.card").count()
    eql_rows = page2.locator("#scenes article.card .kv span.k", has_text="EQL").count()
    chips = page2.locator("#eql .eqlchip").count()
    rows = page2.locator("#eql table.eql tbody tr").count()
    check("EQL section present", page2.locator("#eql").count() == 1)
    check("10 cards", cards == 10, f"cards={cards}")
    check("10 per-card EQL rows", eql_rows == 10, f"rows={eql_rows}")
    check("4 EQL chips", chips == 4, f"chips={chips}")
    check("5-row confidence table", rows == 5, f"rows={rows}")
    check("manifest path in footer", "moradi_eql_manifest.json" in page2.content())
    check("no JS errors on review page", not errs, "; ".join(errs[:2]))
    page2.locator("#eql").scroll_into_view_if_needed()
    page2.wait_for_timeout(400)
    page2.screenshot(path="/tmp/render/e2e_moradi_eql_section.jpg", timeout=60000)
    page2.locator("#scenes article.card").first.scroll_into_view_if_needed()
    page2.wait_for_timeout(400)
    page2.screenshot(path="/tmp/render/e2e_moradi_card.jpg", timeout=60000)

    b.close()

fails = [r for r in RESULTS if not r[1]]
print(f"\nE2E SUMMARY: {len(RESULTS)-len(fails)}/{len(RESULTS)} PASS" + (f" — FAILURES: {[f[0] for f in fails]}" if fails else ""))
sys.exit(1 if fails else 0)
