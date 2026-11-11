#!/usr/bin/env python3
"""moradi_v12_e2e.py — E2E verification of the VQ 1.2 exemplar wiring (2026-11-11).

Owner order: complete flawless Moradi exemplar with the new engine, on GitHub +
live link. Checks (branch engine-upgrade-v1, public/ served locally, SwiftShader
+ DPR1 — same profile as every mission battery):
  1.  default generation is now v12: splats ~520,823, genActual v12, lod OFF
      (measured: in-app LoD build does not complete on this profile — opt-in only)
  2.  default safeR stays the measured envelope 0.75
  3.  walk demo: never leaves the envelope; splat layer blends in while moving
  4.  walk label honest (safeR=0.3 -> "0.3m")
  5.  explicit gen=v11 archive loads byte-identical behavior (132,349 splats)
  6.  gen=v1 on a v1-less scene falls back to v11 and SAYS so (genActual)
  7.  cabin v12 loads (529,396) — the CC0 A/B anchor of the WM comparison
  8.  moradi.html exemplar page: v12 section + per-card v12 buttons + v11 archive
      links, no JS errors
  9.  ?lod=1 is accepted as a param (page boots, no error) — full LoD settle is
      NOT asserted (measured non-completing on SwiftShader; device verification
      pending — documented in the mission doc)
"""
import json, os, sys, time
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
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1,
                        is_mobile=True, has_touch=True, user_agent=B.IPHONE["user_agent"])
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))

    # -- 1+2: default = v12, envelope unchanged --------------------------------
    print("TEST 1-2: default gen v12 + safeR 0.75 (moradi_main1)", flush=True)
    page.goto(f"{BASE}?scene=moradi_main1&mode=both", wait_until="domcontentloaded", timeout=300000)
    B.wait_ready(page, timeout=240000)
    s = B.stats(page)
    check("default gen == v12", s["gen"] == "v12" and s["genActual"] == "v12", f"gen={s['gen']}/{s['genActual']}")
    check("v12 splat count ~520823", 515000 <= s["splats"] <= 535000, f"splats={s['splats']}")
    check("lod default OFF (measured opt-in)", s["lod"] is False, f"lod={s['lod']}")
    check("default safeR == 0.75", s["safeR"] == 0.75, f"safeR={s['safeR']}")
    check("no page errors", not errs, "; ".join(errs[:2]))

    # -- 3: walk stays in envelope, splat blends --------------------------------
    print("TEST 3: walk demo stays in envelope + blends (v12)", flush=True)
    page.click("#walkbtn")
    max_dist, saw_blend = 0.0, False
    t0 = time.time()
    while time.time() - t0 < 40:
        st = B.stats(page)
        max_dist = max(max_dist, st["dist"])
        if st["dist"] > 0.1 and st["blend"] > 0.3:
            saw_blend = True
        page.wait_for_timeout(400)
    check("walk never leaves the 0.75 m envelope", max_dist <= 0.75 + 0.02, f"max_dist={max_dist:.3f}")
    check("moving: splat layer blended in", saw_blend, f"max_dist={max_dist:.3f}")
    # v12: the 529k-splat depth sort drains ~3 min on SwiftShader after motion;
    # drain before navigating (else goto stalls behind the busy renderer)
    print("  draining sort queue…", flush=True)
    page.wait_for_timeout(150000)

    # -- 4: honest walk label ---------------------------------------------------
    print("TEST 4: honest walk label (safeR=0.3, v12)", flush=True)
    page.goto(f"{BASE}?scene=moradi_main1&mode=both&safeR=0.3", wait_until="domcontentloaded", timeout=300000)
    B.wait_ready(page, timeout=240000)
    page.click("#walkbtn")
    done, max_dist = False, 0.0
    t0 = time.time()
    while time.time() - t0 < 150:
        st = B.stats(page)
        max_dist = max(max_dist, st["dist"])
        if st["dist"] < 0.02 and st["blend"] < 0.05 and time.time() - t0 > 4:
            done = True; break
        page.wait_for_timeout(500)
    label = (page.text_content("#walkbtn") or "").strip()
    check("short walk completes + rests on pano", done, f"max_dist={max_dist:.3f}")
    check("label shows radius actually walked (0.3)", "0.3" in label, f"label='{label}'")

    # -- 5: v11 archive intact ---------------------------------------------------
    print("TEST 5: explicit gen=v11 archive (moradi_main1)", flush=True)
    page.goto(f"{BASE}?scene=moradi_main1&gen=v11&mode=both", wait_until="domcontentloaded", timeout=300000)
    B.wait_ready(page, timeout=240000)
    s = B.stats(page)
    check("v11 loads 132,349 splats", s["splats"] == 132349 and s["genActual"] == "v11",
          f"splats={s['splats']} gen={s['genActual']}")

    # -- 6: fallback says the truth ----------------------------------------------
    print("TEST 6: gen=v1 fallback to v11 (moradi_main1 has no v1 asset)", flush=True)
    page.goto(f"{BASE}?scene=moradi_main1&gen=v1&mode=both", wait_until="domcontentloaded", timeout=300000)
    B.wait_ready(page, timeout=240000)
    s = B.stats(page)
    check("v1 -> v11 fallback surfaced (genActual v11, 132,349)",
          s["genActual"] == "v11" and s["splats"] == 132349, f"genActual={s['genActual']} splats={s['splats']}")

    # -- 7: cabin v12 (CC0 anchor) ------------------------------------------------
    print("TEST 7: cabin v12 loads (529,396)", flush=True)
    page.goto(f"{BASE}?scene=cabin&mode=both", wait_until="domcontentloaded", timeout=300000)
    B.wait_ready(page, timeout=240000)
    s = B.stats(page)
    check("cabin v12 loads 529,396", 520000 <= s["splats"] <= 540000 and s["genActual"] == "v12",
          f"splats={s['splats']}")

    # -- 8: moradi.html exemplar page ---------------------------------------------
    print("TEST 8: moradi.html exemplar page (v12 sections + buttons)", flush=True)
    errs.clear()
    page2 = ctx.new_page()
    page2.on("pageerror", lambda e: errs.append(str(e)))
    page2.goto("http://127.0.0.1:8141/labs/engine-v1/moradi.html", wait_until="domcontentloaded", timeout=300000)
    page2.wait_for_selector("#v12", timeout=15000)
    cards = page2.locator("#scenes article.card").count()
    v12_btns = page2.locator("#scenes article.card a[href*='gen=v12']").count()
    v11_links = page2.locator("#scenes article.card a[href*='gen=v11']").count()
    check("v12 exemplar section present", page2.locator("#v12").count() == 1)
    check("10 cards", cards == 10, f"cards={cards}")
    check("per-card v12 buttons (>= 10)", v12_btns >= 10, f"v12 buttons={v12_btns}")
    check("v11 archive links kept (>= 10)", v11_links >= 10, f"v11 links={v11_links}")
    check("no JS errors on review page", not errs, "; ".join(errs[:2]))
    page2.locator("#v12").scroll_into_view_if_needed()
    page2.wait_for_timeout(400)
    page2.screenshot(path="/tmp/render/e2e_v12_section.jpg", timeout=60000)
    page2.locator("#scenes article.card").first.scroll_into_view_if_needed()
    page2.wait_for_timeout(400)
    page2.screenshot(path="/tmp/render/e2e_v12_card.jpg", timeout=60000)

    # -- 9: lod param accepted (no crash; settle NOT asserted — measured) ---------
    print("TEST 9: ?lod=1 param accepted (boot check only)", flush=True)
    page3 = ctx.new_page()
    errs3 = []
    page3.on("pageerror", lambda e: errs3.append(str(e)))
    page3.goto(f"{BASE}?scene=cabin&mode=pano&lod=1", wait_until="domcontentloaded", timeout=300000)
    page3.wait_for_timeout(2500)
    check("lod=1 boots without page error (pano mode)", not errs3, "; ".join(errs3[:1]))

    b.close()

fails = [r for r in RESULTS if not r[1]]
print(f"\nE2E SUMMARY: {len(RESULTS)-len(fails)}/{len(RESULTS)} PASS" + (f" — FAILURES: {[f[0] for f in fails]}" if fails else ""))
sys.exit(1 if fails else 0)
