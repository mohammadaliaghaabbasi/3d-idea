#!/usr/bin/env python3
"""moradi_metrics.py — MORADI REAL-CONTENT TEST, Phase D.
VQ 1.1 metrics (identical definitions to vq11_metrics2.py) over the moradi
still battery:
  holes_pct / soft_holes_pct (splat-mode magenta), bleed_pct (both vs splat),
  dot-grid spectral peak, sharpness retention (splat vs pano ref),
  mismatch PSNR (both vs pano ref = stretch/reconstruction budget),
  double-edge excess (composite edge energy beyond max single layer).
Per scene: 0.75 m x 4 dirs. Ladders: bed1a (mx,px) + main3 (pz,px) 0.2-1.3 m.
Output: docs/rd-artifacts/engine-v1/moradi_metrics.json + .csv
"""
import glob, json, os
import numpy as np
import cv2

STILLS = "/home/z/my-project/download/panodrome-moradi/stills"
ART = "/home/z/my-project/3d-idea/docs/rd-artifacts/engine-v1"
SCENES = ["moradi_main1", "moradi_main2", "moradi_main3", "moradi_main4",
          "moradi_kit1", "moradi_kit2", "moradi_bed1a", "moradi_bed1b",
          "moradi_bed2a", "moradi_bed3a"]
DIRS = {"px": "+x", "mx": "-x", "pz": "+z", "mz": "-z"}
# state dir=D look=back -> viewed region = -D
VIEWED = {"px": "-x", "mx": "+x", "pz": "-z", "mz": "+z"}
LADDER = {"moradi_bed1a": ["mx", "px"], "moradi_main3": ["pz", "px"]}
LADDER_DISTS = ["02", "04", "06", "075", "10", "13"]

def load(p):
    img = cv2.imread(p); assert img is not None, p
    return img

def band(img):
    H, W = img.shape[:2]
    m_y, m_x = int(H*0.05), int(W*0.05)
    return img[m_y:H-m_y, m_x:W-m_x]

def metrics(pano_p, splat_p, both_p):
    P, S, C = band(load(pano_p)), band(load(splat_p)), band(load(both_p))
    Bm, Gm, Rm = S[...,0].astype(int), S[...,1].astype(int), S[...,2].astype(int)
    magenta = (Rm > 200) & (Bm > 200) & (Gm < 120)
    nonhole = ~magenta
    half = (Rm > 150) & (Bm > 150) & (Gm < 160) & ~magenta
    holes_pct = float(magenta.mean()*100)
    soft_holes_pct = float(half.mean()*100)
    bleed = np.abs(C.astype(np.float64) - S.astype(np.float64)).mean(axis=2)
    bleed_nonhole = bleed[nonhole]
    bleed_pct = float((bleed_nonhole > 12).mean()*100)
    bl = bleed - bleed.mean()
    F = np.abs(np.fft.rfft2(bl)); F[0,0] = 0
    dot_peak = float(F.max() / max(np.median(F), 1e-9))
    def lapv(img, mask=None):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float64)
        l = cv2.Laplacian(g, cv2.CV_64F)
        return float(l.var()) if mask is None else float(l[mask].var())
    sp, ss = lapv(P), lapv(S, nonhole)
    sharp_ret_pct = float(ss / max(sp, 1e-9) * 100)
    mse = ((C[nonhole].astype(np.float64) - P[nonhole].astype(np.float64))**2).mean()
    psnr = float(99.0 if mse <= 1e-9 else 10*np.log10(255.0*255.0/mse))
    def emag(img):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float64)
        return np.hypot(cv2.Sobel(g, cv2.CV_64F, 1, 0, 3), cv2.Sobel(g, cv2.CV_64F, 0, 1, 3))
    EP, ES, EC = emag(P), emag(S), emag(C)
    strong = np.maximum(EP, ES) > 60
    de = float((((EC[strong] - np.maximum(EP, ES)[strong]) / np.maximum(EP, ES)[strong]).mean()*100)
               ) if strong.sum() else 0.0
    return {"holes_pct": round(holes_pct, 3), "soft_holes_pct": round(soft_holes_pct, 2),
            "bleed_pct": round(bleed_pct, 2), "dot_peak": round(dot_peak, 1),
            "sharp_ret_pct": round(sharp_ret_pct, 1), "psnr_db": round(psnr, 2),
            "double_edge_excess_pct": round(de, 1),
            "nonhole_px": int(nonhole.sum())}

def state_metrics(scene, code, dtag):
    pano_p = f"{STILLS}/{scene}_pano_{code}.jpg"
    splat_p = f"{STILLS}/{scene}_{code}_{dtag}_splat.jpg"
    both_p = f"{STILLS}/{scene}_{code}_{dtag}_both.jpg"
    if not all(os.path.exists(p) for p in (pano_p, splat_p, both_p)):
        return None
    m = metrics(pano_p, splat_p, both_p)
    m["travel_dir"] = DIRS[code]; m["viewed_dir"] = VIEWED[code]
    m["offset_m"] = (float(dtag)/10) if len(dtag) <= 2 else (float(dtag)/100)  # 02->0.2, 075->0.75, 13->1.3
    return m

def main():
    out = {"battery_075": {}, "ladders": {}}
    rows = []
    for scene in SCENES:
        per_dir = {}
        for code in DIRS:
            m = state_metrics(scene, code, "075")
            if m: per_dir[code] = m; rows.append((scene, "0.75", code, m))
        if per_dir:
            ps = [m["psnr_db"] for m in per_dir.values()]
            out["battery_075"][scene] = {
                "n_dirs": len(per_dir), "per_dir": per_dir,
                "psnr_mean": round(float(np.mean(ps)), 2),
                "psnr_worst": round(float(np.min(ps)), 2),
                "psnr_best": round(float(np.max(ps)), 2),
                "holes_max": round(max(m["holes_pct"] for m in per_dir.values()), 3),
                "bleed_max": round(max(m["bleed_pct"] for m in per_dir.values()), 2),
                "sharp_ret_mean": round(float(np.mean([m["sharp_ret_pct"] for m in per_dir.values()])), 1),
                "de_excess_max": round(max(m["double_edge_excess_pct"] for m in per_dir.values()), 1),
            }
            print(f"[075] {scene}: psnr mean {out['battery_075'][scene]['psnr_mean']} "
                  f"worst {out['battery_075'][scene]['psnr_worst']} "
                  f"holes max {out['battery_075'][scene]['holes_max']}%")
    for scene, codes in LADDER.items():
        lad = {}
        for code in codes:
            for dtag in LADDER_DISTS:
                m = state_metrics(scene, code, dtag)
                if m: lad[f"{code}_{dtag}"] = m; rows.append((scene, dtag, code, m))
        out["ladders"][scene] = lad
        if lad:
            print(f"[ladder] {scene}: " + ", ".join(
                f"{k}:{v['psnr_db']}dB h{v['holes_pct']}%" for k, v in lad.items()))
    # CSV
    with open(f"{ART}/moradi_metrics.csv", "w") as f:
        f.write("scene,offset_m,travel_dir,viewed_dir,holes_pct,soft_holes_pct,bleed_pct,"
                "dot_peak,sharp_ret_pct,psnr_db,double_edge_excess_pct\n")
        for scene, off, code, m in rows:
            f.write(f"{scene},{off},{m['travel_dir']},{m['viewed_dir']},{m['holes_pct']},"
                    f"{m['soft_holes_pct']},{m['bleed_pct']},{m['dot_peak']},"
                    f"{m['sharp_ret_pct']},{m['psnr_db']},{m['double_edge_excess_pct']}\n")
    json.dump(out, open(f"{ART}/moradi_metrics.json", "w"), indent=1)
    print("saved ->", f"{ART}/moradi_metrics.json / .csv")

if __name__ == "__main__":
    main()
