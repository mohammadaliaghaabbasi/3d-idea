#!/usr/bin/env python3
"""vq11_exp2_stills.py — VQ 1.1 still capture battery v3 (settle-aware).
METHODOLOGY (validated in this session):
  * Pages load with mode=pano so the pano mesh EXISTS (pano/both states valid).
  * Spark's async depth sort: after a camera MOVE the splat pass renders only
    the background for ~10 s in software GL (ms on real GPUs). Every new
    camera position is settled via __vq.settleState (fresh + stable + content).
  * Mode-only changes (splat -> both, bg switch) reuse the settled sort and
    render instantly — captured with a short verify-wait.
  * Snaps are in-page toDataURL at TRUE framebuffer resolution (agent-browser
    screenshots upscale from CSS — unusable for dot/edge metrics).
Sessions: exp1 (DPR2, 12 stills: attribution) | exp2 (DPR1, 52: distance matrix)
Usage: vq11_exp2_stills.py exp1|exp2|exp2a|exp2b   (a/b = +x,-x / +z,-z halves)
"""
import base64, json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from playwright.sync_api import sync_playwright
import vq11_browser as B

DISTS = [0.2, 0.4, 0.6, 0.75, 1.0, 1.3]
DIRS = ["+x", "-x", "+z", "-z"]
OUT = "/home/z/my-project/download/panodrome-vq11/stills"; os.makedirs(OUT, exist_ok=True)
# v3-methodology cutoff: first settle-aware capture of this session (v1 exp1 origin pano)
_CUT = os.path.getmtime(f"{OUT}/v1_exp1_origin_pano.jpg") - 60 if os.path.exists(f"{OUT}/v1_exp1_origin_pano.jpg") else time.time() - 7200
ART = "/home/z/my-project/3d-idea/docs/rd-artifacts/engine-v1"
BASE = "http://127.0.0.1:8141/labs/engine-v1/vq11.html"
ONLY = sys.argv[1] if len(sys.argv) > 1 else "all"

results = {"dpr": {"exp1": 2, "exp2": 1}, "states": {}, "settle": {}, "errors": []}

def snap(page, name, fmt="jpeg"):
    path0 = f"{OUT}/{name}.{'png' if fmt=='png' else 'jpg'}"
    if os.path.exists(path0) and os.path.getmtime(path0) > _CUT:
        results["states"][name] = path0
        print(f"skip (fresh) {name}", flush=True)
        return path0
    data = page.evaluate(f"window.__vq.snap('{fmt}')")
    path = f"{OUT}/{name}.{'png' if fmt=='png' else 'jpg'}"
    open(path, "wb").write(base64.b64decode(data.split(",", 1)[1]))
    results["states"][name] = path
    print(f"still {name}", flush=True)
    return path

def settle(page, state, label):
    r = page.evaluate(f"window.__vq.settleState({json.dumps(state)})")
    results["settle"][label] = r
    ok = isinstance(r, dict) and r.get("settled")
    print(f"settle {label}: {r}", flush=True)
    return ok

def quick_mode_capture(page, state, name, fmt="jpeg"):
    """Mode/bg change at an already-settled camera: render is instant, but
    verify content to guard against an unexpected re-sort."""
    ok = page.evaluate(f"window.__vq.settleState({json.dumps(state)}, 1000, 8000)")
    results["settle"][f"verify:{name}"] = ok
    if not ok:
        print(f"  ! quick mode not instant for {name}; settled={ok}", flush=True)
    snap(page, name, fmt)

def load_page(ctx, gen, dpr_note):
    page = ctx.new_page()
    page.on("pageerror", lambda e: results["errors"].append(str(e)))
    page.goto(f"{BASE}?scene=cabin&gen={gen}&mode=pano&ui=0&offset=0&dir=%2Bx&look=back",
              wait_until="domcontentloaded", timeout=60000)
    B.wait_ready(page)
    page.wait_for_timeout(1000)
    # warm the FIRST sort (origin, splat mode over magenta) — ~90 s cold in SwiftShader
    t0 = time.time()
    ok = settle(page, dict(mode="splat", dir="+x", offset=0.0, look="back", bg="magenta"),
                f"warm-{gen}-{dpr_note}")
    print(f"[{gen}] warm sort {'OK' if ok else 'TIMEOUT'} after {time.time()-t0:.0f}s", flush=True)
    return page

def main():
    B.serve()
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader",
                                    "--enable-unsafe-swiftshader"])
        if ONLY in ("all", "exp1", "exp1v1", "exp1v11"):
            # ---- exp1 attribution @ DPR2 ----
            ctx = b.new_context(viewport={"width": 390, "height": 844},
                                device_scale_factor=2, is_mobile=True, has_touch=True,
                                user_agent=B.IPHONE["user_agent"])
            for gen in ({"exp1v1": ("v1",), "exp1v11": ("v11",)}.get(ONLY, ("v1", "v11"))):
                page = load_page(ctx, gen, "exp1-dpr2")
                for tag, off in (("origin", 0.0), ("off075", 0.75)):
                    # pano state (no splat involved — instant)
                    quick_mode_capture(page, dict(mode="pano", dir="+x", offset=off, look="back", bg="black"),
                                       f"{gen}_exp1_{tag}_pano")
                    # splat state (settles the sort for this camera)
                    settle(page, dict(mode="splat", dir="+x", offset=off, look="back", bg="magenta"),
                           f"{gen}-{tag}-splat")
                    snap(page, f"{gen}_exp1_{tag}_splat")
                    # both state (same camera, settled sort — instant)
                    quick_mode_capture(page, dict(mode="both", dir="+x", offset=off, look="back",
                                                 bg="black", blend=1),
                                       f"{gen}_exp1_{tag}_both")
                page.close()
            ctx.close()
        if ONLY in ("all", "exp2", "exp2a", "exp2b"):
            # ---- exp2 distance matrix @ DPR1 ----
            ctx = b.new_context(viewport={"width": 390, "height": 844},
                                device_scale_factor=1, is_mobile=True, has_touch=True,
                                user_agent=B.IPHONE["user_agent"])
            page = load_page(ctx, "v11", "exp2-dpr1")
            dirs = {"exp2a": ["+x", "-x"], "exp2b": ["+z", "-z"]}.get(ONLY, DIRS)
            # pano refs (one per look; camera stays at origin)
            for d in dirs:
                code = d.replace("+", "p").replace("-", "m")
                quick_mode_capture(page, dict(mode="pano", dir=d, offset=0.0, look="back", bg="black"),
                                   f"v11_exp2_pano_{code}")
            for dname in dirs:
                code = dname.replace("+", "p").replace("-", "m")
                for d in DISTS:
                    dtag = str(d).replace('.','')
                    f_s = f"{OUT}/v11_exp2_{code}_{dtag}_splat.jpg"
                    f_b = f"{OUT}/v11_exp2_{code}_{dtag}_both.jpg"
                    fresh = all(os.path.exists(f) and os.path.getmtime(f) > _CUT
                                for f in (f_s, f_b))
                    if fresh:
                        print(f"skip position {code} {d}m (fresh)", flush=True)
                        continue
                    # settle once for this camera position (splat mode, magenta holes bg)
                    settle(page, dict(mode="splat", dir=dname, offset=d, look="back", bg="magenta"),
                           f"v11-{code}-{d}")
                    snap(page, f"v11_exp2_{code}_{dtag}_splat")
                    quick_mode_capture(page, dict(mode="both", dir=dname, offset=d, look="back",
                                                 bg="black", blend=1),
                                       f"v11_exp2_{code}_{dtag}_both")
                print(f"[v11] {dname} done", flush=True)
            page.close()
            ctx.close()
        b.close()
    json.dump(results, open(f"{ART}/vq11_stills_index.json", "w"), indent=1)
    print("saved ->", f"{ART}/vq11_stills_index.json", "| errors:", results["errors"])

if __name__ == "__main__":
    main()
