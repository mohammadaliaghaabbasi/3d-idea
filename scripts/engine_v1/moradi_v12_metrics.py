#!/usr/bin/env python3
"""moradi_v12_metrics.py — VQ 1.2 fidelity metrics on the v12 still battery.
Identical metric definitions to moradi_metrics.py (holes/soft-holes/bleed/
dot-grid/sharpness-retention/PSNR/double-edge) — reads stills_v12/ (pano refs
are regenerated there by moradi_battery_gen.py), compares against the recorded
v11 numbers (moradi_metrics.json) and writes:
  docs/rd-artifacts/engine-v1/moradi_v12_metrics.json
Also builds the A/B pair sheets (v11 vs v12 same-state) for the VLM verdict.
Usage: moradi_v12_metrics.py [scene ...]   (default: all scenes in the index)
"""
import glob, json, os, sys
import numpy as np
import cv2

STILLS = "/home/z/my-project/download/panodrome-moradi/stills_v12"
V11_STILLS = "/home/z/my-project/download/panodrome-moradi/stills"
ART = "/home/z/my-project/3d-idea/docs/rd-artifacts/engine-v1"
IDX = f"{ART}/moradi_v12_battery_index.json"
V11_MET = f"{ART}/moradi_metrics.json"
OUT = f"{ART}/moradi_v12_metrics.json"
PAIRS_DIR = f"{ART}/v12_ab_pairs"; os.makedirs(PAIRS_DIR, exist_ok=True)
DIRS = {"px": "+x", "mx": "-x", "pz": "+z", "mz": "-z"}
VIEWED = {"px": "-x", "mx": "+x", "pz": "-z", "mz": "+z"}

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

def state_metrics(scene, code, dtag="075"):
    pano_p = f"{STILLS}/{scene}_pano_{code}.jpg"
    splat_p = f"{STILLS}/{scene}_{code}_{dtag}_splat.jpg"
    both_p = f"{STILLS}/{scene}_{code}_{dtag}_both.jpg"
    if not all(os.path.exists(p) for p in (pano_p, splat_p, both_p)):
        return None
    m = metrics(pano_p, splat_p, both_p)
    m["travel_dir"] = DIRS[code]; m["viewed_dir"] = VIEWED[code]
    m["offset_m"] = 0.75
    return m

def ab_pair(scene, code, dtag="075"):
    """Side-by-side v11|v12 splat sheet for the VLM verdict."""
    a = load(f"{V11_STILLS}/{scene}_{code}_{dtag}_splat.jpg")
    b = load(f"{STILLS}/{scene}_{code}_{dtag}_splat.jpg")
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    lab = lambda t: cv2.putText(np.full((34, a.shape[1], 3), 24, np.uint8), t,
                                (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (160, 255, 210), 1, cv2.LINE_AA)
    sheet = np.vstack([lab("LEFT: VQ 1.1 (v11, 132k isotropic)"), a,
                       lab("RIGHT: VQ 1.2 (v12, ~521k anisotropic surface-adhering)"), b])
    out = f"{PAIRS_DIR}/{scene}_{code}_{dtag}_v11_vs_v12.jpg"
    cv2.imwrite(out, sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return out

if __name__ == "__main__":
    idx = json.load(open(IDX))
    v11 = json.load(open(V11_MET))
    scenes = sys.argv[1:] or sorted(idx.get("scenes", {}))
    out = {"tool": "moradi_v12_metrics.py", "metric_definitions": "identical to moradi_metrics.py (VQ 1.1 exp2)",
           "battery": "docs/rd-artifacts/engine-v1/moradi_v12_battery_index.json",
           "scenes": {}, "ab_pairs": {}}
    for scene in scenes:
        per_dir = {}
        for code in ("px", "mx", "pz", "mz"):
            m = state_metrics(scene, code)
            if m: per_dir[code] = m
        if not per_dir:
            print(f"[skip] {scene}: no complete states"); continue
        ps = [per_dir[c]["psnr_db"] for c in per_dir]
        rec = {
            "n_states": len(per_dir),
            "psnr_mean": round(float(np.mean(ps)), 2),
            "psnr_best": round(float(np.max(ps)), 2),
            "psnr_worst": round(float(np.min(ps)), 2),
            "holes_max": max(per_dir[c]["holes_pct"] for c in per_dir),
            "soft_holes_max": max(per_dir[c]["soft_holes_pct"] for c in per_dir),
            "bleed_max": max(per_dir[c]["bleed_pct"] for c in per_dir),
            "dot_peak_max": max(per_dir[c]["dot_peak"] for c in per_dir),
            "sharp_ret_min": min(per_dir[c]["sharp_ret_pct"] for c in per_dir),
            "double_edge_max": max(per_dir[c]["double_edge_excess_pct"] for c in per_dir),
            "per_dir": per_dir,
        }
        v11s = v11.get("battery_075", {}).get(scene)
        if v11s:
            rec["v11_psnr_mean"] = v11s["psnr_mean"]
            rec["v11_holes_max"] = v11s["holes_max"]
            rec["v11_dot_peak_max"] = v11s.get("dot_peak_max")
            rec["delta_psnr_mean_db"] = round(rec["psnr_mean"] - v11s["psnr_mean"], 2)
        out["scenes"][scene] = rec
        for code in per_dir:
            out["ab_pairs"][f"{scene}_{code}"] = ab_pair(scene, code)
        print(f"[{scene}] psnr mean/worst {rec['psnr_mean']}/{rec['psnr_worst']} dB "
              f"(v11 {rec.get('v11_psnr_mean')}, delta {rec.get('delta_psnr_mean_db')}) "
              f"holes_max {rec['holes_max']} dot_max {rec['dot_peak_max']} sharp_min {rec['sharp_ret_min']}")
    json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False)
    print(f"saved -> {OUT}")
