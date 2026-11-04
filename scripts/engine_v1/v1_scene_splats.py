#!/usr/bin/env python3
"""v1_scene_splats.py — PHASE 7/8 batch engine: identical settings per scene.
Full CPU pipeline (same math as rd_pano_to_splat.py, parameterized):
  pano_4k -> DAV2-small ONNX @CPU -> floor metric calibration -> equirect unprojection
  -> INRIA 3DGS PLY -> niantic SPZ v4 -> labs asset
Plus per-azimuth measured shell profile (doc-12 method, simplified) ->
data-driven SAFE_R (min tested-region constraint, no invented dimensions).
Usage: v1_scene_splats.py <scene_name>   -> docs/rd-artifacts/engine-v1/phase8_<scene>.json
"""
import sys, os, json, time, hashlib, resource, shutil
import numpy as np
import cv2
import onnxruntime as ort
from PIL import Image
import spz

REPO = "/home/z/my-project/3d-idea"
scene = sys.argv[1]
PANO = f"{REPO}/public/assets/panoramas/{scene}.jpg"
OUT_DIR = f"{REPO}/docs/rd-artifacts/engine-v1"
LAB_ASSETS = f"{REPO}/public/labs/engine-v1/assets"
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(LAB_ASSETS, exist_ok=True)
GW, GH, STRIDE, CAM_H = 1022, 518, 2, 1.5
SH_C0 = 0.28209479177387814
R = {"scene": scene}

t0 = time.time()
md5 = hashlib.md5(open(PANO, "rb").read()).hexdigest()
img = Image.open(PANO).convert("RGB")
W_pano, H_pano = img.size
pano_np = np.array(img)
R["pano"] = {"size": [W_pano, H_pano], "md5": md5}

# 1. DAV2-small ONNX CPU
t1 = time.time()
sess = ort.InferenceSession("/tmp/dav2/dav2_small.onnx", providers=["CPUExecutionProvider"])
rgb = cv2.resize(pano_np, (GW, GH), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
x = (rgb - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
disp = sess.run(None, {sess.get_inputs()[0].name: np.transpose(x, (2, 0, 1))[None]})[0][0]
t_dav2 = time.time() - t1

# 2. metric calibration (floor-plane robust fit — identical to engine)
depth_rel = 1.0 / np.maximum(disp, 1e-6)
V = np.linspace(0.5 / GH, 1 - 0.5 / GH, GH)[:, None] * np.ones((1, GW))
phi = np.pi / 2 - V * np.pi
mask = (V > 0.86) & (V < 0.985) & (-np.sin(phi) > 0.25)
t_floor = CAM_H / (-np.sin(phi))
k = np.median(t_floor[mask] / depth_rel[mask])
depth = np.clip(depth_rel * k, 0.3, 60.0)

# 3. unprojection (room.js convention)
U = (np.arange(GW) + 0.5) / GW
a = U * 2 * np.pi
dx = -np.cos(a)[None, :] * np.cos(phi)
dz = np.sin(a)[None, :] * np.cos(phi)
dy = np.sin(phi)
P = np.stack([dx * depth, dy * depth, dz * depth], axis=-1)
scales = np.clip(depth * (2 * np.pi / GW) * 0.7, 0.02, 2.0)

# 4. PLY export
sel = np.zeros((GH, GW), bool); sel[::STRIDE, ::STRIDE] = True
pos = P[sel].astype(np.float32); scl = scales[sel].astype(np.float32); col = rgb[sel]
n = len(pos)
log_op = np.full(n, np.log(0.95 / 0.05), np.float32)
f_dc = ((col - 0.5) / SH_C0).astype(np.float32)
log_s = np.log(scl)
t2 = time.time()
fields = [("x", pos[:, 0]), ("y", pos[:, 1]), ("z", pos[:, 2]),
          ("nx", np.zeros(n, np.float32)), ("ny", np.zeros(n, np.float32)), ("nz", np.zeros(n, np.float32)),
          ("f_dc_0", f_dc[:, 0]), ("f_dc_1", f_dc[:, 1]), ("f_dc_2", f_dc[:, 2])]
for i in range(45):
    fields.append((f"f_rest_{i}", np.zeros(n, np.float32)))
fields += [("opacity", log_op), ("scale_0", log_s), ("scale_1", log_s), ("scale_2", log_s),
           ("rot_0", np.ones(n, np.float32)), ("rot_1", np.zeros(n, np.float32)),
           ("rot_2", np.zeros(n, np.float32)), ("rot_3", np.zeros(n, np.float32))]
hdr = ["ply", "format binary_little_endian 1.0", f"element vertex {n}"]
for name, _ in fields:
    hdr.append(f"property float {name}")
hdr.append("end_header")
ply_path = f"/tmp/splat/{scene}_splat.ply"
with open(ply_path, "wb") as f:
    f.write(("\n".join(hdr) + "\n").encode())
    f.write(np.stack([v for _, v in fields], axis=1).astype("<f4").tobytes())
t_ply = time.time() - t2
ply_mb = os.path.getsize(ply_path) / 1e6

# 5. SPZ v4
t3 = time.time()
gc = spz.load_splat_from_ply(ply_path)
spz_path = f"/tmp/splat/{scene}_splat.spz"
spz.save_spz(gc, spz.PackOptions(), spz_path)
t_spz = time.time() - t3
spz_kb = os.path.getsize(spz_path) / 1e3
shutil.copy(spz_path, f"{LAB_ASSETS}/{scene}_splat.spz")

# 6. measured shell profile (doc-12 method, simplified) -> data-driven SAFE_R
# eye-height band: |pitch| <= 10deg (approx rows around equator), min depth per 2.5-deg azimuth bin
band = np.abs(phi) < np.radians(10)
NB = 144
bin_px = GW / NB
prof = np.full(NB, np.inf)
dband = np.where(band, depth, np.inf)
for b in range(NB):
    seg = dband[:, int(b * bin_px):int((b + 1) * bin_px)]
    m = seg[seg < np.inf]
    if m.size: prof[b] = float(np.percentile(m, 5))    # 5th pct: nearest surface in that azimuth
finite = prof[np.isfinite(prof)]
p10 = float(np.percentile(finite, 10)); p50 = float(np.percentile(finite, 50))
SAFE_R = max(0.20, min(1.30, p10 - 0.35))               # cap at TESTED max 1.30m; margin 35cm
R["shell_profile"] = {"bins": NB, "min_m": round(float(finite.min()), 2),
                      "p10_m": round(p10, 2), "median_m": round(p50, 2),
                      "open_azimuths_gt_5m": int((finite > 5).sum()),
                      "SAFE_R_m": round(SAFE_R, 2),
                      "method": "doc-12 measured cylindrical shell (eye-height band, 5th-pct per 2.5deg bin), margin 0.35m, capped at tested 1.30m"}

R["pipeline"] = {"splat_count": int(n), "ply_mb": round(ply_mb, 2), "spz_kb": round(spz_kb, 1),
                 "compression_x": round(ply_mb * 1e6 / (spz_kb * 1e3), 1),
                 "times_s": {"dav2_cpu": round(t_dav2, 2), "ply_export": round(t_ply, 2),
                             "spz_encode": round(t_spz, 2), "total": round(time.time() - t0, 2)},
                 "calibration": {"scale_k": round(float(k), 3), "cam_h_assumed_m": CAM_H,
                                 "floor_rows": int(mask.sum())},
                 "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}
R["outputs"] = {"ply": ply_path, "spz_lab_asset": f"{LAB_ASSETS}/{scene}_splat.spz"}
json.dump(R, open(f"{OUT_DIR}/phase8_{scene}.json", "w"), indent=1)
print(json.dumps(R, indent=1))
