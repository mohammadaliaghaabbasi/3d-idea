#!/usr/bin/env python3
"""owner_shots.py — fresh mobile screenshots of the new-rules Moradi state.

For the owner, before deploy: what the pages look like RIGHT NOW on the
engine-upgrade-v1 branch (iPhone viewport, same SwiftShader profile as the
mission battery). Output -> /home/z/my-project/download/moradi-newrules-preview/
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright
import vq11_browser as B

OUT = "/home/z/my-project/download/moradi-newrules-preview"
os.makedirs(OUT, exist_ok=True)
BASE = "http://127.0.0.1:8141"

B.serve()
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader",
                                "--enable-unsafe-swiftshader"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                        is_mobile=True, has_touch=True, user_agent=B.IPHONE["user_agent"])
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))

    # -- 1: moradi.html — top (title + attribution banner) -------------------
    if not os.path.exists(f"{OUT}/1_moradi_top.png"):
        print("1: moradi.html top", flush=True)
        page.goto(f"{BASE}/labs/engine-v1/moradi.html", wait_until="networkidle", timeout=60000)
        page.screenshot(path=f"{OUT}/1_moradi_top.png")

    # -- 2: moradi.html — new EQL / data-confidence section ------------------
    if not os.path.exists(f"{OUT}/2_moradi_eql_section.png"):
        print("2: EQL section", flush=True)
        el = page.locator("text=قوانین جدید").first
        el.scroll_into_view_if_needed()
        page.wait_for_timeout(600)
        page.screenshot(path=f"{OUT}/2_moradi_eql_section.png")

    # -- 3: moradi.html — first card with EQL row -----------------------------
    if not os.path.exists(f"{OUT}/3_moradi_card.png"):
        print("3: first card", flush=True)
        card = page.locator(".card").first
        card.scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        page.screenshot(path=f"{OUT}/3_moradi_card.png")

    # -- 4: vq11 demo walk — mid-walk state ----------------------------------
    print("4: vq11 demo walk", flush=True)
    page.goto(f"{BASE}/labs/engine-v1/vq11.html?scene=moradi_main1&gen=v11&demo=1",
              wait_until="domcontentloaded", timeout=60000)
    # wait for splat layer to appear (blend > 0 means splat visible)
    for _ in range(120):
        time.sleep(0.5)
        st = page.evaluate("window.__state && window.__state.blend")
        if st and st > 0.5:
            break
    page.wait_for_timeout(1200)
    page.screenshot(path=f"{OUT}/4_vq11_walk_demo.png", timeout=90000)

    # -- 5: homepage badge (after entering the gallery) --------------------
    print("5: homepage badge (enter gallery first)", flush=True)
    page.goto(f"{BASE}/index.html", wait_until="networkidle", timeout=60000)
    try:
        page.locator("#btn-enter").click(timeout=15000)
        print("   clicked enter", flush=True)
    except Exception as e:
        print("   enter click:", e, flush=True)
    page.wait_for_timeout(4000)
    badge = page.locator("#qa-labs")
    if badge.count():
        vis = page.evaluate("() => { const b=document.getElementById('qa-labs'); const r=b.getBoundingClientRect(); const cs=getComputedStyle(b); return {w:r.width,h:r.height,display:cs.display,opacity:cs.opacity,txt:b.textContent.slice(0,30)}; }")
        print("   badge state:", vis, flush=True)
    page.screenshot(path=f"{OUT}/5_homepage_badge.png", timeout=90000)

    print("JS errors:", errs if errs else "none", flush=True)
    ctx.close(); b.close()
print("done ->", OUT, flush=True)
