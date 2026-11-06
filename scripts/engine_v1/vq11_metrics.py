#!/usr/bin/env python3
"""vq11_metrics.py — VQ 1.1 layer-attribution metrics.
Inputs: three captures of the SAME view — pano.png (mode=pano),
splat.png (mode=splat, magenta bg), both.png (mode=both, blend locked 1).
Metrics:
  holes_pct      — splat-layer true coverage holes (magenta fraction, splat mode)
  bleed_pct      — pano visible THROUGH the splat at full blend (both vs splat)
  dot_grid       — periodic modulation energy of the bleed map (FFT peak ratio)
  sharp_pano / sharp_splat / sharp_both — Laplacian variance (same view, same res)
  sharp_retention— sharp(both)/sharp(pano) %
  double_edge    — edge energy of composite not explained by either layer alone
                   (ghost/double edges at parallax-shifted object borders)
  mean_lum ratios
"""
import sys, json
import numpy as np
import cv2

def load(p):
    img = cv2.imread(p)
    assert img is not None, p
    return img  # BGR

def lap_var(img, mask=None):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float64)
    lap = cv2.Laplacian(g, cv2.CV_64F)
    if mask is None: return lap.var()
    m = mask.astype(bool)
    return lap[m].var() if m.sum() > 100 else -1

def edge_mag(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float64)
    gx = cv2.Sobel(g, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_64F, 0, 1, ksize=3)
    return np.hypot(gx, gy)

def main(pano_p, splat_p, both_p, out_json, tag=""):
    P, S, C = load(pano_p), load(splat_p), load(both_p)
    H, W = S.shape[:2]
    # central analysis band (avoid dpad corners / HUD leftovers): crop 6% margins
    m_y, m_x = int(H*0.06), int(W*0.06)
    P, S, C = P[m_y:H-m_y, m_x:W-m_x], S[m_y:H-m_y, m_x:W-m_x], C[m_y:H-m_y, m_x:W-m_x]

    # holes: magenta background visible in splat mode (R,B high, G low)
    Bm, Gm, Rm = S[...,0].astype(int), S[...,1].astype(int), S[...,2].astype(int)
    magenta = (Rm > 200) & (Bm > 200) & (Gm < 120)
    holes_pct = float(magenta.mean() * 100)

    # bleed: pano showing through the composite at full splat blend.
    # bleed map = |C - S| restricted to NON-hole pixels (where splat claims coverage)
    nonhole = ~magenta
    bleed = np.abs(C.astype(np.float64) - S.astype(np.float64)).mean(axis=2)
    bleed_nonhole = bleed[nonhole]
    bleed_pct = float((bleed_nonhole > 12).mean() * 100)      # px where pano visibly shifts result
    bleed_mean = float(bleed_nonhole.mean())

    # dot grid: FFT of bleed map — periodic lattice shows a spectral peak
    bl = bleed - bleed.mean()
    F = np.abs(np.fft.rfft2(bl))
    F[0, 0] = 0
    spec_max = float(F.max())
    # baseline = median of the 2D spectrum (broadband noise)
    base = float(np.median(F))
    dot_grid_peak_ratio = spec_max / max(base, 1e-9)

    # sharpness
    sp, ss, sc = lap_var(P), lap_var(S, nonhole), lap_var(C)
    retention = sc / max(sp, 1e-9) * 100

    # double edges: composite edge energy vs max(single-layer edge energy)
    EP, ES, EC = edge_mag(P), edge_mag(S), edge_mag(C)
    strong = (np.maximum(EP, ES) > 60)                         # object borders
    ghost = (EC[strong] - np.maximum(EP, ES)[strong]).mean()
    explain = (np.maximum(EP, ES)[strong] / EC[strong].clip(1))
    double_edge_excess_pct = float(ghost / np.maximum(EP, ES)[strong].mean() * 100)

    res = {
        "tag": tag, "size": [W, H],
        "holes_pct": round(holes_pct, 2),
        "bleed_pct_px_gt12": round(bleed_pct, 2),
        "bleed_mean_rgb": round(bleed_mean, 2),
        "dot_grid_spectral_peak": round(dot_grid_peak_ratio, 1),
        "sharpness": {"pano": round(sp, 1), "splat": round(ss, 1), "both": round(sc, 1),
                      "retention_pct": round(retention, 1)},
        "double_edge": {"excess_edge_energy_pct": round(double_edge_excess_pct, 2),
                         "n_border_px": int(strong.sum())},
        "mean_lum": {"pano": round(float(P.mean()), 1), "splat": round(float(S[nonhole].mean()), 1),
                      "both": round(float(C.mean()), 1)},
    }
    json.dump(res, open(out_json, "w"), indent=1)
    print(json.dumps(res, indent=1))
    return res

if __name__ == "__main__":
    main(*sys.argv[1:5], tag=sys.argv[5] if len(sys.argv) > 5 else "")
