#!/usr/bin/env python3
"""marble_lab_render.py — THE decisive cross-content experiment (read-only for the repo).

Owner question 2026-11-10: reverse-engineer Marble (worldlabs.ai) as a SYSTEM and
answer "what is usable in our system?". This script renders Marble's own public
example SPZ (warm_traditional_kitchen_interior_500k.spz, from
docs.worldlabs.ai/marble/export/specs) inside OUR OWN VQ 1.1 harness — same
three 0.180.0 + Spark 2.4.0, same camera, same capture path — next to our own
moradi_main1 content as the control. If Marble content renders sharp and
movement-stable in OUR harness, the engine is exonerated and the diagnosis is
CONTENT (density / fog-splats / opaque-alpha / occlusion filling).

Nothing in the repo is modified:
  - the harness copy lives in /tmp/marble_lab (patched only with the documented
    OpenCV->OpenGL 180-deg X rotation that Marble's own viewer applies to
    generated SPZ, per docs.worldlabs.ai/api/rendering-spz);
  - outputs go to /home/z/my-project/download/marble-lab-preview/ (full PNG)
    and docs/rd-artifacts/engine-v1/marble_lab_*.jpg (downscaled, for the doc).
SwiftShader caveat: fps numbers are software-GL-relative, NOT device absolute
(same caveat as every VQ 1.1 experiment).
"""
import functools
import json
import os
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

from playwright.sync_api import sync_playwright

REPO = "/home/z/my-project/3d-idea"
sys.path.insert(0, os.path.join(REPO, "scripts/engine_v1"))
import vq11_browser as B  # proven deterministic-capture driver (iPhone profile)

LAB_DIR = "/tmp/marble_lab"
LAB_PORT = 8142
OUT_PNG = "/home/z/my-project/download/marble-lab-preview"
ART = os.path.join(REPO, "docs/rd-artifacts/engine-v1")
VLM_JSON = os.path.join(ART, "marble_lab_vlm.json")

TARGETS = [
    dict(key="marble", name="Marble SPAR-1 sample rendered in OUR VQ1.1 harness",
         base=f"http://127.0.0.1:{LAB_PORT}", scene="marble_kitchen", gen="v11"),
    dict(key="moradi", name="OURS moradi_main1 in the same harness (control)",
         base=f"http://127.0.0.1:{B.PORT}", scene="moradi_main1", gen="v11"),
]

# capture plan: (shot-id, state-object, settle_ms)
SHOTS = [
    ("origin_both",  {"mode": "both"}, 12000),
    ("origin_splat", {"mode": "splat"}, 6000),
    ("move_px075_splat", {"dir": "+x", "offset": 0.75, "mode": "splat", "look": "back"}, 12000),
]

_lab_server = None
_pub_server = None

def _serve(dirpath, port):
    handler = functools.partial(SimpleHTTPRequestHandler, directory=dirpath)
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

def serve_lab():
    global _lab_server
    if not _lab_server:
        _lab_server = _serve(LAB_DIR, LAB_PORT)
    return LAB_PORT

def serve_pub():
    """Serve repo public/ with a FIXED directory (vq11_browser.serve() chdir's
    the process, which races with the lab server's cwd — handlers here pin
    their directory instead)."""
    global _pub_server
    if not _pub_server:
        _pub_server = _serve(os.path.join(REPO, "public"), B.PORT)
    return B.PORT


def shrink_to_art(src_png, dst_jpg, width=780):
    from PIL import Image
    im = Image.open(src_png).convert("RGB")
    h = round(im.height * width / im.width)
    im.resize((width, h), Image.LANCZOS).save(dst_jpg, quality=82)
    return dst_jpg


def double_fork_daemon():
    """Escape the sandbox per-call process reaper (same pattern as
    serve_review_daemon.py — a classic double-fork + setsid daemon survives)."""
    pid = os.fork()
    if pid > 0:
        os.waitpid(pid, 0)
        print(f"daemon grandchild launched (parent reaped child {pid})")
        os._exit(0)
    os.setsid()
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)
    # grandchild: redirect std fds to the log
    sys.stdout = sys.stderr = open("/tmp/marble_lab.log", "a", buffering=1)


def main():
    os.makedirs(OUT_PNG, exist_ok=True)
    os.makedirs(ART, exist_ok=True)
    serve_pub()      # repo public/ on :8141 (control) — fixed-directory server
    serve_lab()      # /tmp/marble_lab on :8142 (Marble content)

    report = dict(test="marble_lab_render", when="2026-11-10",
                 harness="vq11.html/js copy in /tmp/marble_lab (repo untouched)",
                 runtime="three 0.180.0 + Spark 2.4.0 (same vendored modules as production lab)",
                 shots={})
    all_pngs = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader",
                                          "--enable-unsafe-swiftshader"])
        ctx = browser.new_context(viewport={"width": 390, "height": 844},
                                  device_scale_factor=2, is_mobile=True, has_touch=True,
                                  user_agent=B.IPHONE["user_agent"])
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))

        for t in TARGETS:
            url = f"{t['base']}/labs/engine-v1/vq11.html?scene={t['scene']}&gen={t['gen']}&mode=both&ui=0"
            print(f"\n== {t['name']} ==\n   {url}", flush=True)
            page.goto(url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_function("window.__vq && window.__vq.stats().splats > 0", timeout=120000)
            page.wait_for_timeout(1500)
            for shot_id, state, settle_ms in SHOTS:
                png = os.path.join(OUT_PNG, f"{t['key']}_{shot_id}.png")
                jpg = os.path.join(ART, f"marble_lab_{t['key']}_{shot_id}.jpg")
                settled = page.evaluate(
                    f"window.__vq.settleState({json.dumps(state)}, {settle_ms}, 40000)")
                stats = page.evaluate("window.__vq.stats()")
                stats["settled"] = settled
                entry = dict(stats=stats, page_errors=list(errs), png=os.path.basename(png))
                if os.path.exists(png):        # deterministic: keep prior screenshot,
                    entry["cached_png"] = True  # but stats are re-collected fresh
                    print(f"   [{shot_id}] png cached, stats fresh", flush=True)
                else:
                    page.screenshot(path=png, timeout=120000)
                    shrink_to_art(png, jpg)
                    print(f"   [{shot_id}] captured", flush=True)
                report["shots"][f"{t['key']}_{shot_id}"] = entry
                print(f"   [{shot_id}] splats={stats['splats']} fps={stats['fps']:.1f} "
                      f"frameP95={stats['frameP95Ms']:.0f}ms blend={stats['blend']} "
                      f"spzReady={stats['spzReadyMs']}ms errors={stats['errors']}", flush=True)
                all_pngs[f"{t['key']}_{shot_id}"] = png
            errs.clear()
        browser.close()

    # VLM verdict on the decisive pair: splat-only at origin (same mode, same bg,
    # same camera) — Marble content vs ours.
    vlm_prompt = (
        "You are inspecting two screenshots from the SAME WebGL gaussian-splat viewer "
        "(identical engine, camera and background). Image 1 renders a 3D kitchen scene "
        "generated by World Labs Marble; Image 2 renders our own reconstructed room "
        "(moradi_main1). Answer precisely, in numbered points: "
        "(1) Which image looks SHARPER overall at surfaces and edges? "
        "(2) In which image do surfaces look blurry/veiled or dotted? "
        "(3) Which image shows black holes / missing content behind or around objects? "
        "(4) Any rendering artifacts (floaters, smearing, banding) in each? "
        "(5) One-line verdict: is the difference mainly in CONTENT quality/density "
        "or in the renderer?")
    if not os.path.exists(VLM_JSON):
        subprocess.run(["z-ai", "vision", "-p", vlm_prompt,
                        "-i", all_pngs["marble_origin_splat"],
                        "-i", all_pngs["moradi_origin_splat"],
                        "-o", VLM_JSON],
                       capture_output=True, text=True, timeout=240)
    verdict = ""
    try:
        d = json.load(open(VLM_JSON))
        verdict = d["choices"][0]["message"]["content"]
    except Exception as e:
        verdict = f"(vlm output unreadable: {e})"
    report["vlm_pair_verdict"] = verdict
    print("\n===== VLM verdict (marble vs moradi, splat-mode origin) =====\n" + verdict, flush=True)

    out_path = os.path.join(ART, "marble_lab_render.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    if "--daemon" in sys.argv or os.environ.get("MARBLE_LAB_DAEMON") == "1":
        double_fork_daemon()
    main()
