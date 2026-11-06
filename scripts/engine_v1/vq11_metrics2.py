#!/usr/bin/env python3
"""vq11_metrics2.py — VQ 1.1 metrics over the native-snap stills battery.
For every distance/direction state (v11): holes (splat-mode magenta),
pano bleed-through at full blend (both vs splat), dot-grid spectral peak,
sharpness retention vs pano reference, double-edge excess, mismatch PSNR
(splat vs pano ref = stretch/reconstruction budget at that offset).
Also re-runs the EXP1 attribution states for both gens.
Output: docs/rd-artifacts/engine-v1/vq11_metrics.json (+ CSV)
"""
import glob, json, math, os, sys
import numpy as np
import cv2

STILLS = "/home/z/my-project/download/panodrome-vq11/stills"
ART = "/home/z/my-project/3d-idea/docs/rd-artifacts/engine-v1"
DISTS = [0.2, 0.4, 0.6, 0.75, 1.0, 1.3]
DIRS = {"px": "+x", "mx": "-x", "pz": "+z", "mz": "-z"}

def load(p):
    img = cv2.imread(p); assert img is not None, p
    return img

def band(img):
    H, W = img.shape[:2]
    m_y, m_x = int(H*0.05), int(W*0.05)
    return img[m_y:H-m_y, m_x:W-m_x]

def metrics(pano_p, splat_p, both_p, tag):
    P, S, C = band(load(pano_p)), band(load(splat_p)), band(load(both_p))
    Bm, Gm, Rm = S[...,0].astype(int), S[...,1].astype(int), S[...,2].astype(int)
    magenta = (Rm > 200) & (Bm > 200) & (Gm < 120)
    nonhole = ~magenta
    # holes from magenta; near-holes = alpha<~0.5 (half-magenta mix)
    half = (Rm > 150) & (Bm > 150) & (Gm < 160) & ~magenta
    holes_pct = float(magenta.mean()*100)
    soft_holes_pct = float(half.mean()*100)
    # bleed-through at full blend (pano visible through splat)
    bleed = np.abs(C.astype(np.float64) - S.astype(np.float64)).mean(axis=2)
    bleed_nonhole = bleed[nonhole]
    bleed_pct = float((bleed_nonhole > 12).mean()*100)
    # dot grid: periodic modulation of bleed map
    bl = bleed - bleed.mean()
    F = np.abs(np.fft.rfft2(bl)); F[0,0] = 0
    dot_peak = float(F.max() / max(np.median(F), 1e-9))
    # sharpness
    def lapv(img, mask=None):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float64)
        l = cv2.Laplacian(g, cv2.CV_64F)
        return float(l.var()) if mask is None else float(l[mask].var())
    sp, ss, sc = lapv(P), lapv(S, nonhole), lapv(C)
    # mismatch PSNR (stretch/reconstruction budget) splat vs pano on covered px
    mse = ((C[nonhole].astype(np.float64) - P[nonhole].astype(np.float64))**2).mean()
    mm = ((S[nonhole].astype(np.float64) - P[nonhole].astype(np.float64))**2).mean()
    # double-edge excess: composite edge energy beyond max(single layer)
    def emag(img):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float64)
        return np.hypot(cv2.Sobel(g, cv2.CV_64F, 1, 0, 3), cv2.Sobel(g, cv2.CV_64F, 0, 1, 3))
    EP, ES, EC = emag(P), emag(S), emag(C)
    strong = np.maximum(EP, ES) > 60
    de = float(((EC[strong] - np.maximum(EP, ES)[strong]) / np.maximum(EP, ES)[strong]).mean()*100) if strong.sum() else 0.0
    return {
        "tag": tag, "holes_pct": round(holes_pct, 2), "soft_holes_pct": round(soft_holes_pct, 2),
        "bleed_pct_gt12": round(bleed_pct, 2), "bleed_mean": round(float(bleed_nonhole.mean()), 2),
        "dot_grid_peak": round(dot_peak, 1),
        "sharp": {"pano": round(sp,1), "splat": round(ss,1), "both": round(sc,1),
                  "retention_pct": round(sc/max(sp,1e-9)*100,1)},
        "double_edge_excess_pct": round(de, 1),
        "mismatch_psnr_splat_vs_pano_db": round(10*math.log10(255**2/mm),1) if mm>0 else 99,
        "compos_psnr_vs_pano_db": round(10*math.log10(255**2/mse),1) if mse>0 else 99,
    }

out = {"exp1": {}, "exp2": []}
# ---- exp1 attribution (both gens) ----
for gen in ("v1", "v11"):
    for tag in ("origin", "off075"):
        try:
            out["exp1"][f"{gen}/{tag}"] = metrics(
                f"{STILLS}/{gen}_exp1_{tag}_pano.jpg",
                f"{STILLS}/{gen}_exp1_{tag}_splat.jpg",
                f"{STILLS}/{gen}_exp1_{tag}_both.jpg", f"{gen}/{tag}")
        except FileNotFoundError as e:
            print("skip", gen, tag, e)
# ---- exp2 distance matrix (v11) ----
for code, dname in DIRS.items():
    pano_p = f"{STILLS}/v11_exp2_pano_{code}.jpg"
    for d in DISTS:
        tag = f"{dname}/{d}m"
        try:
            m = metrics(pano_p,
                        f"{STILLS}/v11_exp2_{code}_{str(d).replace('.','')}_splat.jpg",
                        f"{STILLS}/v11_exp2_{code}_{str(d).replace('.','')}_both.jpg", tag)
            m["dir"] = dname; m["dist_m"] = d
            out["exp2"].append(m)
        except FileNotFoundError as e:
            print("skip", tag, e)

# ---- summary aggregates ----
import statistics as st
def agg(items, key):
    vals = [i[key] for i in items]
    return {"mean": round(st.mean(vals), 2), "max": round(max(vals), 2), "min": round(min(vals), 2)}
per_dist = {}
for d in DISTS:
    items = [m for m in out["exp2"] if m["dist_m"] == d]
    if items:
        per_dist[str(d)] = {
            "holes_pct": agg(items, "holes_pct"), "soft_holes_pct": agg(items, "soft_holes_pct"),
            "bleed_pct_gt12": agg(items, "bleed_pct_gt12"), "dot_grid_peak": agg(items, "dot_grid_peak"),
            "sharp_retention_pct": agg(items, "retention_pct") if "retention_pct" in items[0] else None,
            "double_edge_excess_pct": agg(items, "double_edge_excess_pct"),
            "mismatch_psnr_db": agg(items, "mismatch_psnr_splat_vs_pano_db"),
        }
out["per_dist_summary"] = per_dist
json.dump(out, open(f"{ART}/vq11_metrics.json", "w"), indent=1)

# CSV
with open(f"{ART}/vq11_metrics.csv", "w") as f:
    f.write("dir,dist_m,holes_pct,soft_holes_pct,bleed_pct,dot_grid_peak,sharp_retention_pct,double_edge_excess_pct,mismatch_psnr_db\n")
    for m in out["exp2"]:
        f.write(f"{m['dir']},{m['dist_m']},{m['holes_pct']},{m['soft_holes_pct']},{m['bleed_pct_gt12']},"
                f"{m['dot_grid_peak']},{m['sharp']['retention_pct']},{m['double_edge_excess_pct']},"
                f"{m['mismatch_psnr_splat_vs_pano_db']}\n")
print(json.dumps(out["exp1"], indent=1))
print("per-dist:", json.dumps(per_dist, indent=1))
print("saved ->", f"{ART}/vq11_metrics.json / .csv")
