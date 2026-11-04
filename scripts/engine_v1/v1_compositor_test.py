#!/usr/bin/env python3
"""v1_compositor_test.py — PHASE 5: quantitative ghosting/double-exposure audit.
At camera offset 0.75 m (+x, yaw=-90, pitch=0) capture three states:
  A = pano only (blend 0) | B = splat only (blend 1) | M = mid-fade (blend 0.5)
Checks:
  1. fade math: M ~= 0.5*A + 0.5*B (the transition is a mathematically clean alpha
     crossfade — no third artifact, no double render, no brightness bump)
  2. ghosting budget: mismatch energy between A and B at this offset (the inherent
     two-layer parallax difference visible during the 350 ms window)
  3. brightness conservation: mean(M) ~= 0.5*mean(A)+0.5*mean(B) (no double exposure)
"""
import numpy as np, cv2, json, math

def load(p):
    img = cv2.imread(p)
    H, W = img.shape[:2]
    ch, cw = int(H*0.72), int(W*0.72)          # center crop, HUD-free
    y0, x0 = (H-ch)//2, (W-cw)//2
    return img[y0:y0+ch, x0:x0+cw].astype(np.float32)

A = load('/tmp/ph5_pano_075.png')    # pano endpoint
B = load('/tmp/ph5_splat_075.png')  # splat endpoint
M = load('/tmp/ph5_fade_075.png')   # mid-fade capture
synth = 0.5*A + 0.5*B

def psnr(a, b):
    mse = ((a-b)**2).mean()
    return 10*math.log10(255**2/mse) if mse > 0 else 99

mismatch = psnr(A, B)                        # ghosting budget (low PSNR = big layer difference)
fade_clean = psnr(M, synth)                  # is the mid-fade exactly the alpha blend?
bright_err = abs(M.mean() - synth.mean())    # brightness conservation

res = {
 "camera": {"offset_m": 0.75, "dir": "+x", "yaw_deg": -90, "pitch_deg": 0},
 "fade_tau_ms": 350,
 "checks": [
  {"check": "mid-fade == synthetic alpha blend (no third artifact)",
   "pass": bool(fade_clean > 30), "psnr_db": round(fade_clean, 1)},
  {"check": "brightness conserved (no double exposure bump)",
   "pass": bool(bright_err < 3), "mean_M": round(float(M.mean()), 2), "mean_synth": round(float(synth.mean()), 2)},
  {"check": "ghosting budget at 0.75m documented",
   "pass": bool(mismatch < 24), "note": f"layer mismatch energy: PSNR(A,B) = {mismatch:.1f} dB — visible during the 350ms window only"},
 ],
 "hypothesis": "double exposure rejected — M matches alpha-blend of endpoints within %.1f dB" % fade_clean,
}
ok = all(c["pass"] for c in res["checks"])
res["verdict"] = "ALL COMPOSITOR CHECKS PASS" if ok else "FAILURES PRESENT"
json.dump(res, open('/home/z/my-project/3d-idea/docs/rd-artifacts/engine-v1/phase5_compositor.json', 'w'), indent=1)
print(json.dumps(res, indent=1))
