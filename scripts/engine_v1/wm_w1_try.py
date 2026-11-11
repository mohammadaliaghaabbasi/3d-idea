#!/usr/bin/env python3
"""wm_w1_try.py — WorldMirror W1 boundary experiment (time-boxed, honest).

Owner order 2026-11-11: build the complete Moradi exemplar with all gathered
experience (Marble §7 program locally + the newly found HunyuanWorld-Mirror).
This script is the WM half of W1 from worldmirror_reverse_engineering.md §8:

  CC0 asset ONLY (cabin, Poly Haven CC0 — R&D-only license rule is NOT violated:
  we never upload Moradi/Kuula content to any external service) ->
  8 perspective cube-face crops (yaw k*45 deg, pitch 0, FOV 70) from the
  equirect pano -> official free tencent/HunyuanWorld-Mirror HF Space via
  gradio_client -> gaussians.ply -> our SPZ converter -> A/B vs VQ 1.2 cabin.

Honest failure paths (all recorded, never faked):
  - space asleep/queue/ZeroGPU quota -> record status, exit cleanly
  - gradio schema mismatch -> record view_api dump, exit cleanly
Artifacts -> docs/rd-artifacts/engine-v1/wm_w1_*.json (+ .spz if it succeeds)
"""
import json, math, os, sys, time
import numpy as np
import cv2

REPO = "/home/z/my-project/3d-idea"
PANO = f"{REPO}/public/assets/panoramas/cabin.jpg"
ART = f"{REPO}/docs/rd-artifacts/engine-v1"
LAB = f"{REPO}/public/labs/engine-v1/assets"
OUT = "/tmp/wm_w1"; os.makedirs(OUT, exist_ok=True)
SPACE = "tencent/HunyuanWorld-Mirror"
N_FACE, FOV = 8, 70.0
SIZE = 1024                              # per-face crop resolution

report = {"tool": "wm_w1_try.py", "asset": "cabin (Poly Haven, CC0)",
          "space": SPACE, "when": time.strftime("%Y-%m-%dT%H:%M:%S%z")}

# ---------- 1. equirect -> 8 perspective crops ----------
pano = cv2.imread(PANO); assert pano is not None, PANO
Hp, Wp = pano.shape[:2]
fl = 0.5 * SIZE / math.tan(math.radians(FOV) / 2)
xs, ys = np.meshgrid(np.arange(SIZE) - SIZE/2 + 0.5, np.arange(SIZE) - SIZE/2 + 0.5)
d = np.stack([xs, -ys, np.full_like(xs, fl)], axis=-1)          # camera: fwd=+z
d /= np.linalg.norm(d, axis=-1, keepdims=True)
crops = []
for k in range(N_FACE):
    yaw = math.radians(k * 360.0 / N_FACE)
    cy, sy = math.cos(yaw), math.sin(yaw)
    Rz = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])       # rotate about y
    v = d @ Rz.T
    lon = np.arctan2(v[..., 0], v[..., 2])                        # -pi..pi
    lat = np.arcsin(np.clip(v[..., 1], -1, 1))
    colm = ((lon + math.pi) / (2*math.pi)) * Wp
    row = ((math.pi/2 - lat) / math.pi) * Hp
    face = cv2.remap(pano, colm.astype(np.float32), row.astype(np.float32), cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_WRAP)
    p = f"{OUT}/cabin_face{k}.jpg"
    cv2.imwrite(p, face, [cv2.IMWRITE_JPEG_QUALITY, 95])
    crops.append(p)
report["crops"] = {"n": N_FACE, "size": SIZE, "fov_deg": FOV, "files": crops}
print(f"[1] {N_FACE} crops x {SIZE}px (FOV {FOV}) -> {OUT}", flush=True)

# ---------- 2. gradio_client attempt (time-boxed) ----------
try:
    from gradio_client import Client, handle_file
    t0 = time.time()
    client = Client(SPACE, verbose=False)
    report["client_connect_s"] = round(time.time()-t0, 1)
    api = client.view_api(return_format="dict")
    report["api_endpoints"] = sorted(api.get("named_endpoints", {}).keys())
    print("[2] connected; endpoints:", report["api_endpoints"], flush=True)

    # main fn signature probe (gradio_demo): inputs [OutputPath, ShowPointsFrame,
    # ShowCamera, FilterSky, ShowMesh, FilterLowConf] per worldmirror_space_api.json
    fn = "/gradio_demo" if "/gradio_demo" in report["api_endpoints"] else \
         next((e for e in report["api_endpoints"] if "gradio_demo" in e), None)
    if fn is None:
        raise RuntimeError(f"no gradio_demo endpoint; have {report['api_endpoints']}")
    sig = api["named_endpoints"][fn]
    print(f"[2] {fn} parameters:", json.dumps(sig.get("parameters", []))[:800], flush=True)
    report["gradio_demo_params"] = sig.get("parameters", [])

    # upload path: the gallery upload handler update_gallery_on_file_upload [files, interval]
    up = next((e for e in report["api_endpoints"] if "update_gallery_on_file_upload" in e), None)
    report["upload_endpoint"] = up
    if up is None:
        raise RuntimeError("no upload handler endpoint found")
    files = [handle_file(p) for p in crops]
    t0 = time.time()
    res_up = client.predict(files, 1.0, api_name=up)   # up = '/update_gallery_on_file_upload'
    report["upload_s"] = round(time.time()-t0, 1)
    print(f"[3] upload done in {report['upload_s']}s raw={str(res_up)[:300]}", flush=True)
    report["upload_raw"] = str(res_up)[:1000]

    # run the reconstruction with default filters ON (confidence + sky = native culls)
    t0 = time.time()
    res = client.predict("", "All", True, True, False, True, api_name=fn)
    report["run_s"] = round(time.time()-t0, 1)
    print(f"[4] run done in {report['run_s']}s", flush=True)
    report["run_raw"] = str(res)[:3000]

    # find downloadable outputs (model3d gsplat / ply / camera params) in the result
    outs = []
    def walk(o):
        if isinstance(o, (list, tuple)):
            for x in o: walk(x)
        elif isinstance(o, dict):
            for x in o.values(): walk(x)
        elif isinstance(o, str) and (o.startswith("/") or "tmp" in o or o.startswith("http")):
            outs.append(o)
        elif hasattr(o, "path"):
            outs.append(o.path)
    walk(res)
    report["run_files"] = outs
    print("[4] run files:", outs, flush=True)
    report["status"] = "RUN_OK"
except Exception as e:
    report["status"] = "FAIL"
    report["fail"] = f"{type(e).__name__}: {str(e)[:600]}"
    print(f"[!] WM attempt failed honestly: {report['fail']}", flush=True)

json.dump(report, open(f"{ART}/wm_w1_attempt.json", "w"), indent=1, ensure_ascii=False)
print(f"saved -> {ART}/wm_w1_attempt.json  status={report['status']}", flush=True)
