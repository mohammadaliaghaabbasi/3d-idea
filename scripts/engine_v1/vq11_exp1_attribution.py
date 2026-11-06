#!/usr/bin/env python3
"""vq11_exp1_attribution.py — VQ 1.1 experiment 1: which LAYER causes dots/blur/ghost?
Three INDEPENDENT modes (pano / splat / both) captured at origin and 0.75 m
(+x, back-look, blend locked 1) via agent-browser (instant full-DPR stills).
Metrics (vq11_metrics.py): holes, pano bleed-through, dot-grid spectral peak,
sharpness retention, double-edge excess. Crops + bleed heatmaps saved for VLM.
Usage: vq11_exp1_attribution.py <gen:v1|v11>
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import vq11_ab as AB
import vq11_metrics as M
import numpy as np, cv2

GEN = sys.argv[1] if len(sys.argv) > 1 else "v1"
OUT = "/tmp/vq11/exp1"; os.makedirs(OUT, exist_ok=True)
ART = "/home/z/my-project/3d-idea/docs/rd-artifacts/engine-v1"

AB.open_lab(gen=GEN)
res = {"gen": GEN, "states": {}}
STATES = [("origin", 0.0), ("off075", 0.75)]
for tag, off in STATES:
    files = {}
    for mode in ("pano", "splat", "both"):
        st = dict(mode=mode, dir="+x", offset=off, look="back",
                  bg="magenta" if mode == "splat" else "black",
                  blend=1 if mode == "both" else None)
        st = {k: v for k, v in st.items() if v is not None}
        f = f"{OUT}/{GEN}_{tag}_{mode}.png"
        AB.still(st, f)
        files[mode] = f
        print(tag, mode, "->", f, flush=True)
    r = M.main(files["pano"], files["splat"], files["both"],
               f"{OUT}/metrics_{GEN}_{tag}.json", tag=f"{GEN}/{tag}")
    res["states"][tag] = r
    # edge-rich magnified crop (pano | splat | both) + bleed heatmap
    P = cv2.imread(files["pano"]); S = cv2.imread(files["splat"]); C = cv2.imread(files["both"])
    H, W = S.shape[:2]
    cy, cx = int(H*0.52), int(W*0.30); ch, cw = int(H*0.16), int(W*0.22)
    crop = np.hstack([P[cy:cy+ch, cx:cx+cw], S[cy:cy+ch, cx:cx+cw], C[cy:cy+ch, cx:cx+cw]])
    crop = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(f"{OUT}/{GEN}_{tag}_crop_PSC.png", crop)
    bleed = np.abs(C.astype(float) - S.astype(float)).mean(axis=2).astype(np.uint8)
    cv2.imwrite(f"{OUT}/{GEN}_{tag}_bleedmap.png", cv2.applyColorMap(bleed, cv2.COLORMAP_INFERNO))

json.dump(res, open(f"{ART}/vq11_exp1_attribution_{GEN}.json", "w"), indent=1)
print("saved ->", f"{ART}/vq11_exp1_attribution_{GEN}.json")
print(json.dumps(res, indent=1))
