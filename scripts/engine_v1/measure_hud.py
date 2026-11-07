#!/usr/bin/env python3
"""measure_hud.py — precise overlap check for vq11 HUD vs mode buttons (mobile).

Loads the harness at rest and during the demo, prints bounding boxes of
#hud, #modes, #walkbtn and their intersection. Read-only instrumentation.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright
import vq11_browser as B

BASE = "http://127.0.0.1:8141"

JS = """
() => {
  const ids = ['hud','modes','walkbtn','err','dpad'];
  const out = {};
  for (const id of ids) {
    const el = document.getElementById(id);
    if (!el) { out[id] = null; continue; }
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    out[id] = {x:r.x, y:r.y, w:r.width, h:r.height,
               right:r.x+r.width, bottom:r.y+r.height,
               display:cs.display, z:cs.zIndex};
  }
  return out;
}
"""

def inter(a, b):
    if not a or not b: return None
    x = max(a["x"], b["x"]); y = max(a["y"], b["y"])
    r = min(a["right"], b["right"]); bt = min(a["bottom"], b["bottom"])
    if r <= x or bt <= y: return None
    return {"x": x, "y": y, "w": round(r-x,1), "h": round(bt-y,1)}

B.serve()
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader",
                                "--enable-unsafe-swiftshader"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1,
                        is_mobile=True, has_touch=True, user_agent=B.IPHONE["user_agent"])
    page = ctx.new_page()
    for label, url in [
        ("REST", f"{BASE}/labs/engine-v1/vq11.html?scene=moradi_main1&gen=v11"),
        ("DEMO", f"{BASE}/labs/engine-v1/vq11.html?scene=moradi_main1&gen=v11&demo=1"),
    ]:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # wait for splats to be ready so hud text is fully populated
        for _ in range(120):
            time.sleep(0.5)
            if page.evaluate("window.__state && window.__state.splatCount"):
                break
        page.wait_for_timeout(1000)
        boxes = page.evaluate(JS)
        print(f"--- {label} ---")
        for k, v in boxes.items():
            if v: print(f"{k:8s} x={v['x']:.0f} y={v['y']:.0f} w={v['w']:.0f} h={v['h']:.0f} right={v['right']:.0f} z={v['z']}")
            else: print(f"{k:8s} (missing)")
        ov = inter(boxes.get("hud"), boxes.get("modes"))
        ov2 = inter(boxes.get("hud"), boxes.get("walkbtn"))
        print(f"hud ∩ modes  : {ov}")
        print(f"hud ∩ walkbtn: {ov2}")
    ctx.close(); b.close()
