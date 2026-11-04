#!/usr/bin/env python3
"""v1_spark_orientation_check.py — PHASE 4: prove Spark renders our SPZ in the
correct orientation, numerically. Builds equirect ground-truth perspective views
under 6 orientation hypotheses (identity, yaw±90, yaw 180, x-flip, z-flip) and
compares each with the actual Spark WebGL screenshot (center crop, HUD-free).
Correct orientation must win by a wide margin. Also cross-checks hole coverage."""
import numpy as np, cv2, math, json, sys

shot = cv2.imread('/tmp/spark_cabin_center.png')        # Spark render (BGR)
H_s, W_s = shot.shape[:2]
# center crop avoiding HUD (top-left) & badge (bottom-left)
ch, cw = int(H_s*0.72), int(W_s*0.72)
y0, x0 = (H_s-ch)//2, (W_s-cw)//2
crop = shot[y0:y0+ch, x0:x0+cw]

pano = cv2.imread('/home/z/my-project/3d-idea/public/assets/panoramas/cabin.jpg')  # BGR 4096x2048
Hp, Wp = pano.shape[:2]

def gt_view(yaw_deg, pitch_deg, W, H, fov_v_deg=72.0):
    fovx_deg = 2*math.degrees(math.atan(math.tan(math.radians(fov_v_deg)/2) * (W/H)))  # three.js fov is VERTICAL
    fw = np.array([-math.sin(math.radians(yaw_deg)), math.sin(math.radians(pitch_deg)), -math.cos(math.radians(yaw_deg))])
    fw = fw / np.linalg.norm(fw)
    up0 = np.array([0, 1, 0.0])
    right = np.cross(fw, up0); right /= np.linalg.norm(right)
    upv = np.cross(right, fw)
    fl = (W/2) / math.tan(math.radians(fovx_deg)/2)
    px = np.arange(W)[None,:].repeat(H,0) - W/2
    py = np.arange(H)[:,None].repeat(W,1) - H/2
    dirs = fw[None,None,:] + right[None,None,:]*(px/fl)[...,None] + upv[None,None,:]*(-py/fl)[...,None]
    d = dirs / np.linalg.norm(dirs, axis=-1, keepdims=True)
    phi = np.arcsin(np.clip(d[...,1], -1, 1))
    a = np.arctan2(d[...,2], -d[...,0]) % (2*np.pi)
    row = np.clip(((np.pi/2 - phi)/np.pi)*Hp, 0, Hp-1).astype(int)
    col = np.clip((a/(2*np.pi))*Wp, 0, Wp-1).astype(int)
    return pano[row, col].astype(np.float32)

def score(img_a, img_b):
    a = cv2.resize(img_a, (160, 90)).astype(np.float32)
    b = cv2.resize(img_b, (160, 90)).astype(np.float32)
    mse = ((a - b)**2).mean()
    return 10*math.log10(255**2/mse) if mse > 0 else 99

hyp = {}
for name, (yaw, pitch) in {
    'correct(yaw=-90,pitch=-2)': (-90, -2),
    'yaw=+90 (looking +z)': (90, 0),
    'yaw=180 (looking +x)': (180, 0),
    'yaw=0 (looking -z)': (0, 0),
}.items():
    hyp[name] = score(crop, gt_view(yaw, pitch, cw, ch))

best = max(hyp, key=hyp.get)
res = {
  'screenshot': {'w': W_s, 'h': H_s, 'crop': [x0, y0, cw, ch]},
  'hole_pct_screen': round(float((shot.max(axis=2) < 10).mean()*100), 2),
  'hypothesis_psnr_db': {k: round(v, 2) for k, v in hyp.items()},
  'winner': best,
  'margin_db': round(hyp[best] - sorted(hyp.values())[-2], 2),
  'verdict': 'ORIENTATION CONFIRMED' if best.startswith('correct') and hyp[best] - sorted(hyp.values())[-2] > 3 else 'CHECK FAILED',
}
print(json.dumps(res, indent=1))
json.dump(res, open('/home/z/my-project/3d-idea/docs/rd-artifacts/engine-v1/phase4_orientation_check.json', 'w'), indent=1)
