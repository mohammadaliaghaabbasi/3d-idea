#!/usr/bin/env python3
"""v1_movement_benchmark.py — PHASE 6: per-scene movement safety profile (CPU track).
For each movement direction D in {+x,-x,+z,-z} and distance d in {0.20,0.50,0.75,1.00,1.30}:
  - render the PURE splat layer from the offset camera under two looks:
      back = toward -D (near content slides), perp = perpendicular to D
  - metrics: disocclusion hole %, layer mismatch vs pano GT (parallax+reconstruction budget),
    sharpness retention, visible floor-y spread (floor stability proxy), mean visible depth
Scene-level truth from the PLY itself — deterministic, independent of browser timing.
Usage: v1_movement_benchmark.py <scene> <ply_path> <pano_path> <out_json>
"""
import sys, os, json, math
import numpy as np
import cv2

scene, PLY, PANO, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
GW_W, GW_H = 640, 360
FOVX = 70 * math.pi / 180
SPRITE_K = 1.42
SH_C0 = 0.28209479177387814

# ---- load PLY (INRIA schema, binary LE) ----
with open(PLY, "rb") as f:
    head = []
    while True:
        line = f.readline().decode()
        head.append(line.strip())
        if line.strip() == "end_header":
            break
    off = f.tell()
nv = int([l for l in head if l.startswith("element vertex")][0].split()[-1])
nprops = len([l for l in head if l.startswith("property")])
A = np.fromfile(PLY, dtype="<f4", count=nv * nprops, offset=off).reshape(nv, nprops)
pos = A[:, 0:3].copy()
scl = np.exp(A[:, 55:58]).mean(axis=1)          # isotropic
col = np.clip(SH_C0 * A[:, 6:9] + 0.5, 0, 1)     # f_dc -> rgb
print(f"[{scene}] {nv:,} splats loaded")

# ---- pano GT ----
pano = cv2.imread(PANO); Hp, Wp = pano.shape[:2]
def gt_view(forward, W=GW_W, H=GW_H):
    f = np.array(forward, np.float64); f /= np.linalg.norm(f)
    up0 = np.array([0, 1, 0.0])
    right = np.cross(f, up0); right /= np.linalg.norm(right)
    upv = np.cross(right, f)
    fl = (W/2) / math.tan(FOVX/2)
    px = np.arange(W)[None, :].repeat(H, 0) - W/2
    py = np.arange(H)[:, None].repeat(W, 1) - H/2
    dirs = f[None,None,:] + right[None,None,:]*(px/fl)[...,None] + upv[None,None,:]*(-py/fl)[...,None]
    d = dirs / np.linalg.norm(dirs, axis=-1, keepdims=True)
    phi = np.arcsin(np.clip(d[...,1], -1, 1)); a = np.arctan2(d[...,2], -d[...,0]) % (2*np.pi)
    row = np.clip(((np.pi/2-phi)/np.pi)*Hp, 0, Hp-1).astype(int)
    colm = np.clip((a/(2*np.pi))*Wp, 0, Wp-1).astype(int)
    return pano[row, colm].astype(np.float32)

def render(cam_pos, forward):
    f = np.array(forward, np.float64); f /= np.linalg.norm(f)
    up0 = np.array([0, 1, 0.0])
    right = np.cross(f, up0); right /= np.linalg.norm(right)
    upv = np.cross(right, f)
    fl = (GW_W/2) / math.tan(FOVX/2)
    v = pos - np.array(cam_pos, np.float64)
    zc = v @ f
    ok = zc > 0.2
    vv, zz, ss, cc = v[ok], zc[ok], scl[ok], col[ok]
    # floor stability sample: splats in frustum near floor plane
    inb = ((np.abs((vv @ right)/zz*fl) < GW_W/2) & (np.abs((vv @ upv)/zz*fl) < GW_H/2))
    fl_y = vv[inb, 1][vv[inb, 1] < -0.8]
    floor_spread = float(np.percentile(fl_y, 90) - np.percentile(fl_y, 10)) if fl_y.size > 100 else -1
    xc = vv @ right; yc = vv @ upv
    px = GW_W/2 + (xc/zz)*fl; py = GW_H/2 - (yc/zz)*fl
    r_px = np.clip(ss/zz*fl*SPRITE_K, 0.5, 40)
    order = np.argsort(-zz)
    img = np.zeros((GW_H, GW_W, 3), np.float32)
    for i in order:
        x0, y0 = int(px[i]), int(py[i])
        if x0 < -50 or x0 > GW_W+50 or y0 < -50 or y0 > GW_H+50: continue
        c = np.clip(cc[i]*255, 0, 255)
        cv2.circle(img, (x0, y0), int(np.ceil(r_px[i])), (float(c[0]),float(c[1]),float(c[2])), -1)
    return img, zz[inb], floor_spread

def lap_var(img, mask=None):
    g = cv2.cvtColor(img.astype(np.uint8), cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(g, cv2.CV_64F)
    if mask is None:
        return lap.var()
    m = cv2.erode(mask.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    return lap[m].var() if m.sum() > 100 else -1

DIRECTIONS = {"+x": (1,0,0), "-x": (-1,0,0), "+z": (0,0,1), "-z": (0,0,-1)}
DISTANCES = [0.20, 0.50, 0.75, 1.00, 1.30]

# baseline at origin (back view of +x direction)
base_render, base_depth, _ = render([0,0,0], (-1,0,0))
base_hole_mask = base_render.max(axis=-1) < 2
cov0 = ~base_hole_mask
base_hole = float(base_hole_mask.mean())
base_lap = lap_var(base_render, cov0)
gt0 = gt_view((-1,0,0)); base_lap_gt = lap_var(gt0, cov0)

results = {"scene": scene, "splat_count": nv, "origin_baseline": {
    "hole_pct": round(base_hole*100, 2), "laplacian": round(base_lap, 1),
    "gt_laplacian": round(base_lap_gt, 1),
    "sharpness_retention_pct": round(base_lap/base_lap_gt*100, 1)}, "states": []}

os.makedirs("/tmp/ph6", exist_ok=True)
for dname, D in DIRECTIONS.items():
    back = tuple(-np.array(D, float))
    # perpendicular: rotate D 90 deg about Y (left of travel)
    perp = (-D[2], 0, D[0]) if dname in ("+x", "-z") else (D[2], 0, -D[0])
    for look_name, fw in (("back", back), ("perp", perp)):
        gt = gt_view(fw)
        for d in DISTANCES:
            cam = (D[0]*d, 0, D[2]*d)
            img, vis_depth, floor_spread = render(cam, fw)
            hole = (img.max(axis=-1) < 2)
            cov = ~hole
            nh = cov
            mse = (((img[nh] - gt[nh])/255.0)**2).mean() if nh.sum() else 9
            rec = {
                "dir": dname, "dist_m": d, "look": look_name,
                "hole_pct": round(float(hole.mean()*100), 2),
                "mismatch_psnr_db": round(10*math.log10(1.0/mse), 1) if mse > 0 else 99,
                "sharpness_retention_pct": round(lap_var(img, cov)/max(base_lap_gt, 1e-6)*100, 1),
                "floor_y_p10_p90_spread_m": round(floor_spread, 2) if floor_spread > 0 else None,
                "mean_visible_depth_m": round(float(vis_depth.mean()), 2),
            }
            results["states"].append(rec)
            print(f"[{scene}] {dname} {d:.2f}m {look_name}: hole {rec['hole_pct']}% | mismatch {rec['mismatch_psnr_db']} dB | sharp {rec['sharpness_retention_pct']}% | floorSpread {rec['floor_y_p10_p90_spread_m']}")

# save sample renders for visual reference (back views at 0.20 / 0.75 / 1.30 on +x)
for d, tag in [(0.20, "020"), (0.75, "075"), (1.30, "130")]:
    img, _, _ = render((d, 0, 0), (-1, 0, 0))
    cv2.imwrite(f"/tmp/ph6/{scene}_back_{tag}.jpg", img.astype(np.uint8))

json.dump(results, open(OUT, "w"), indent=1)
print("saved ->", OUT)
