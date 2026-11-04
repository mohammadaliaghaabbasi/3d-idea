#!/usr/bin/env python3
"""
Panodrome R&D 2026-11-04 — CPU-only Pano -> 3D Gaussian Splat prototype.
The "DA360-style" production-safe route: DAV2-small ONNX (Apache-2.0 weights)
depth on CPU -> equirect unprojection (room.js u=atan2(dz,-dx) convention)
-> INRIA 3DGS .ply + off-centre CPU preview renders (parallax proof).
No GPU, no CUDA, no per-scene training. Mirrors SPAG4d's DA360 backend idea.
"""
import json, time, sys
import numpy as np
import cv2
import onnxruntime as ort
from PIL import Image

PANO = "/home/z/my-project/3d-idea/public/assets/panoramas/cabin.jpg"
OUT_DIR = "/tmp/splat"
GW, GH = 1022, 518          # DAV2 input grid (multiples of 14)
STRIDE = 2                  # splat decimation
CAM_H = 1.5                 # assumed capture height (m) for metric calibration
SH_C0 = 0.28209479177387814

import os
os.makedirs(OUT_DIR, exist_ok=True)

# ---------- 1. DAV2-small depth on CPU ----------
t0 = time.time()
sess = ort.InferenceSession("/tmp/dav2/dav2_small.onnx", providers=["CPUExecutionProvider"])
img = Image.open(PANO).convert("RGB")
rgb = cv2.resize(np.array(img), (GW, GH), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
x = (rgb - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / np.array([0.229, 0.224, 0.225], dtype=np.float32)
x = np.transpose(x, (2, 0, 1))[None]
disp = sess.run(None, {sess.get_inputs()[0].name: x})[0][0]  # (GH,GW) relative disparity
t_depth = time.time() - t0
print(f"[1] DAV2-small ONNX CPU depth {GW}x{GH}: {t_depth:.2f}s  disp range [{disp.min():.3f},{disp.max():.3f}]")

# ---------- 2. disparity -> metric depth (floor-plane robust fit) ----------
depth_rel = 1.0 / np.maximum(disp, 1e-6)
V = np.linspace(0.5 / GH, 1 - 0.5 / GH, GH)[:, None] * np.ones((1, GW))
phi = np.pi / 2 - V * np.pi                      # pitch, top=+pi/2
mask = (V > 0.86) & (V < 0.985) & (-np.sin(phi) > 0.25)
t_floor = CAM_H / (-np.sin(phi))
if mask.sum() > 200:
    k = np.median(t_floor[mask] / depth_rel[mask])
else:
    k = 3.0 / np.median(depth_rel)
depth = depth_rel * k
# clamp absurd depths (sky/occlusions)
depth = np.clip(depth, 0.3, 60.0)
print(f"[2] metric calibration: scale k={k:.3f} (floor rows {int(mask.sum())})  depth median {np.median(depth):.2f} m  p99 {np.percentile(depth,99):.1f} m")

# ---------- 3. equirect unprojection (room.js convention) ----------
U = (np.arange(GW) + 0.5) / GW
a = U * 2 * np.pi                                # a = atan2(dz, -dx)
dx = -np.cos(a)[None, :] * np.cos(phi)
dz = np.sin(a)[None, :] * np.cos(phi)
dy = np.sin(phi)
P = np.stack([dx * depth, dy * depth, dz * depth], axis=-1)  # (GH,GW,3)
ang_px = (2 * np.pi / GW)
scales = np.clip(depth * ang_px * 0.7, 0.02, 2.0)
colors = rgb
t_unproj = time.time() - t0 - t_depth
print(f"[3] unprojection: {t_unproj:.2f}s")

# ---------- 4. INRIA 3DGS .ply export ----------
sel = np.zeros((GH, GW), bool)
sel[::STRIDE, ::STRIDE] = True
pos = P[sel].astype(np.float32)
scl = scales[sel].astype(np.float32)
col = colors[sel]
n = len(pos)
opacity = np.full(n, 0.95, np.float32)
f_dc = ((col - 0.5) / SH_C0).astype(np.float32)
log_op = np.log(opacity / (1 - opacity))
log_s = np.log(scl)

t1 = time.time()
fields = [
    ("x", pos[:, 0]), ("y", pos[:, 1]), ("z", pos[:, 2]),
    ("nx", np.zeros(n, np.float32)), ("ny", np.zeros(n, np.float32)), ("nz", np.zeros(n, np.float32)),
    ("f_dc_0", f_dc[:, 0]), ("f_dc_1", f_dc[:, 1]), ("f_dc_2", f_dc[:, 2]),
]
for i in range(45):  # SH degree 3 zeroed -> universally accepted schema
    fields.append((f"f_rest_{i}", np.zeros(n, np.float32)))
fields += [
    ("opacity", log_op), ("scale_0", log_s), ("scale_1", log_s), ("scale_2", log_s),
    ("rot_0", np.ones(n, np.float32)), ("rot_1", np.zeros(n, np.float32)),
    ("rot_2", np.zeros(n, np.float32)), ("rot_3", np.zeros(n, np.float32)),
]
hdr = ["ply", "format binary_little_endian 1.0", f"element vertex {n}"]
for name, _ in fields:
    hdr.append(f"property float {name}")
hdr.append("end_header")
ply_path = f"{OUT_DIR}/cabin_splat.ply"
with open(ply_path, "wb") as f:
    f.write(("\n".join(hdr) + "\n").encode())
    arr = np.stack([v for _, v in fields], axis=1).astype("<f4")
    f.write(arr.tobytes())
t_ply = time.time() - t1
size_mb = os.path.getsize(ply_path) / 1e6
print(f"[4] PLY export: {n:,} splats, {size_mb:.1f} MB in {t_ply:.2f}s")

# ---------- 5. CPU off-centre preview renders (parallax proof) ----------
def render(cam_pos, forward, name, fovx=70 * np.pi / 180, W=900, H=512):
    f = np.array(forward, np.float64); f /= np.linalg.norm(f)
    up = np.array([0, 1, 0], np.float64)
    right = np.cross(f, up); right /= np.linalg.norm(right)
    upv = np.cross(right, f)
    fl = (W / 2) / np.tan(fovx / 2)
    v = pos - np.array(cam_pos, np.float64)
    zc = v @ f
    ok = zc > 0.2
    vv, zz, ss, cc = v[ok], zc[ok], scl[ok], col[ok]
    xc = vv @ right; yc = vv @ upv
    px = W / 2 + (xc / zz) * fl
    py = H / 2 - (yc / zz) * fl
    r_px = np.clip(ss / zz * fl, 0.5, 40)
    order = np.argsort(-zz)
    img = np.zeros((H, W, 3), np.uint8)
    for i in order[::1]:
        r = r_px[i]
        x0, y0 = int(px[i]), int(py[i])
        if x0 < -50 or x0 > W + 50 or y0 < -50 or y0 > H + 50:
            continue
        c = np.clip(cc[i] * 255, 0, 255)
        cv2.circle(img, (x0, y0), int(np.ceil(r)), (int(c[0]), int(c[1]), int(c[2])), -1)
    p = f"{OUT_DIR}/{name}.jpg"
    cv2.imwrite(p, cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(f"[5] render {name}: cam={cam_pos} -> {p}")

t2 = time.time()
render([0, 0, 0], [-1, 0, 0], "cabin_center")
render([1.3, 0, 0], [-1, 0.05, 0], "cabin_offset_1p3m")
t_render = time.time() - t2

stats = {
    "route": "DAV2-small ONNX (Apache-2.0) + equirect unprojection — CPU only, zero training",
    "pano": "cabin.jpg 4096x2048", "depth_grid": [GW, GH], "stride": STRIDE,
    "splat_count": int(n), "ply_mb": round(size_mb, 2),
    "times_s": {"dav2_cpu": round(t_depth, 2), "unproj": round(t_unproj, 2),
                "ply_export": round(t_ply, 2), "2_cpu_renders": round(t_render, 1),
                "total": round(t_depth + t_unproj + t_ply, 2)},
    "calibration": {"scale_k": round(float(k), 3), "cam_h_assumed_m": CAM_H,
                    "floor_rows_used": int(mask.sum())},
}
with open("/home/z/my-project/3d-idea/docs/rd-artifacts/survey/cpu_splat_test.json", "w") as f:
    json.dump(stats, f, indent=1)
print(json.dumps(stats, indent=1))
