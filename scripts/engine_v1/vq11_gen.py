#!/usr/bin/env python3
"""vq11_gen.py — VQ 1.1 root-cause + tuned splat generation (cabin).
A) Rebuild the exact V1.0 splat arrays (stride 2, sigma=0.7*footprint, opacity 0.95)
   and quantify the lattice coverage at the origin view (window render, exact
   Gaussian sprites, front-to-back alpha) -> WHY dots/bleed-through exist.
B) Sweep tuned candidates (sigma multiplier c, opacity, lattice offset) on the
   SAME depth surface (no geometry invention — only coverage density of the
   identical unprojected surface), pick the winner by:
     - alpha coverage min/p5 at origin (kills dots + pano bleed-through)
     - sharpness retention vs pano GT at origin (no extra smear)
     - holes at 0.75/1.30 m offsets (disocclusion unchanged or better)
C) Export winner -> PLY -> SPZ v4 -> public/labs/engine-v1/assets/cabin_splat_v11.spz
   (V1.0 asset cabin_splat.spz stays byte-identical for A/B).
"""
import json, math, os, sys, time
import numpy as np
import cv2
import onnxruntime as ort
from PIL import Image

REPO = "/home/z/my-project/3d-idea"
PANO = f"{REPO}/public/assets/panoramas/cabin.jpg"
LAB = f"{REPO}/public/labs/engine-v1/assets"
ART = f"{REPO}/docs/rd-artifacts/engine-v1"
GW, GH, STRIDE, CAM_H = 1022, 518, 2, 1.5
SH_C0 = 0.28209479177387814
OUT = "/tmp/vq11"; os.makedirs(OUT, exist_ok=True)
os.makedirs("/tmp/splat", exist_ok=True)

report = {"tool": "vq11_gen.py", "scene": "cabin"}

# ---------- 1. depth (identical to engine) ----------
t0 = time.time()
sess = ort.InferenceSession("/tmp/dav2/dav2_small.onnx", providers=["CPUExecutionProvider"])
pano_img = np.array(Image.open(PANO).convert("RGB"))
rgb = cv2.resize(pano_img, (GW, GH), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
x = (rgb - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
disp = sess.run(None, {sess.get_inputs()[0].name: np.transpose(x, (2, 0, 1))[None]})[0][0]
depth_rel = 1.0 / np.maximum(disp, 1e-6)
V = np.linspace(0.5 / GH, 1 - 0.5 / GH, GH)[:, None] * np.ones((1, GW))
phi = np.pi / 2 - V * np.pi
mask = (V > 0.86) & (V < 0.985) & (-np.sin(phi) > 0.25)
t_floor = CAM_H / (-np.sin(phi))
k = np.median(t_floor[mask] / depth_rel[mask])
depth = np.clip(depth_rel * k, 0.3, 60.0)
U = (np.arange(GW) + 0.5) / GW
a = U * 2 * np.pi
dx = -np.cos(a)[None, :] * np.cos(phi)
dz = np.sin(a)[None, :] * np.cos(phi)
dy = np.sin(phi)
P = np.stack([dx * depth, dy * depth, dz * depth], axis=-1)
footprint = depth * (2 * np.pi / GW)          # metres per source pixel at that depth
print(f"[1] depth+unprojection {time.time()-t0:.1f}s  k={k:.3f}")

def build(c, op, row_offset=False):
    """Splat arrays for candidate: sigma = c * footprint, opacity op."""
    sel = np.zeros((GH, GW), bool); sel[::STRIDE, ::STRIDE] = True
    if row_offset:  # odd selected rows shifted 1 source px (hex-like packing)
        sel2 = sel.copy()
        rows = np.arange(0, GH, STRIDE)
        for i, r in enumerate(rows):
            if i % 2 == 1:
                sel2[r, :] = False
                sel2[r, (np.arange(0, GW, STRIDE) + 1) % GW] = True
        sel = sel2
    pos = P[sel]
    sig = np.clip(footprint[sel] * c, 0.02 * c / 0.7, 2.0)
    col = rgb[sel]
    return pos.astype(np.float64), sig.astype(np.float64), col, op

# ---------- 2. window render at origin (exact gaussian sprites, alpha) ----------
# View: identical to harness camera at origin, look -x (yaw -pi/2), pitch -0.03,
# 72deg vfov, 390x844 CSS @ DPR2 -> 780x1688. Window = central 260x520 strip.
VW, VH = 780, 1688
WIN = (slice(int(VH*0.40), int(VH*0.40)+520), slice(int(VW*0.36), int(VW*0.36)+260))
vfov = math.radians(72); fl = (VH/2)/math.tan(vfov/2)
yaw, pitch = -math.pi/2, -0.03
cy_, sy_, cp_, sp_ = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
fwd = np.array([-sy_*cp_, sp_, -cy_*cp_])
up0 = np.array([0,1,0.0]); right = np.cross(fwd, up0); right /= np.linalg.norm(right)
up = np.cross(right, fwd)

def pano_gt(window):
    ys, xs = window
    py = np.arange(ys.start, ys.stop)[:, None] - VH/2
    px = np.arange(xs.start, xs.stop)[None, :] - VW/2
    dirs = fwd[None,None,:] + right[None,None,:]*(px/fl)[...,None] + up[None,None,:]*(-py/fl)[...,None]
    d = dirs / np.linalg.norm(dirs, axis=-1, keepdims=True)
    ph = np.arcsin(np.clip(d[...,1], -1, 1)); az = np.arctan2(d[...,2], -d[...,0]) % (2*np.pi)
    Hp, Wp = pano_img.shape[:2]
    row = np.clip(((math.pi/2-ph)/math.pi)*Hp, 0, Hp-1).astype(int)
    colm = np.clip((az/(2*np.pi))*Wp, 0, Wp-1).astype(int)
    return pano_img[row, colm].astype(np.float64)

def render_window(pos, sig, col, op, cam=(0,0,0), margin=3.0):
    ys, xs = WIN
    wh, ww = ys.stop-ys.start, xs.stop-xs.start
    cam = np.array(cam, np.float64)
    v = pos - cam
    zc = v @ fwd
    ok = zc > 0.2
    v, zc, s, c = v[ok], zc[ok], sig[ok], col[ok]
    xc = v @ right; yc = v @ up
    px = VW/2 + (xc/zc)*fl
    py = VH/2 - (yc/zc)*fl
    spx = (s/zc)*fl                      # screen sigma in px
    inwin = (px > xs.start-margin*30) & (px < xs.stop+margin*30) & \
            (py > ys.start-margin*30) & (py < ys.stop+margin*30)
    idx = np.argsort(-zc[inwin])         # front to back
    px, py, spx = px[inwin][idx], py[inwin][idx], spx[inwin][idx]
    cc, zz = c[inwin][idx], zc[inwin][idx]
    alpha = np.zeros((wh, ww), np.float64)
    img = np.zeros((wh, ww, 3), np.float64)
    for i in range(len(px)):
        x0, y0, r = px[i]-xs.start, py[i]-ys.start, spx[i]
        R = 3.0 * r
        xa, xb = max(0, int(x0-R)), min(ww, int(x0+R)+1)
        ya, yb = max(0, int(y0-R)), min(wh, int(y0+R)+1)
        if xa >= xb or ya >= yb: continue
        yy, xx = np.mgrid[ya:yb, xa:xb]
        d2 = (xx-x0)**2 + (yy-y0)**2
        a = op * np.exp(-0.5 * d2 / (r*r))
        a = a * (1 - alpha[ya:yb, xa:xb])          # front-to-back
        alpha[ya:yb, xa:xb] += a
        img[ya:yb, xa:xb] += a[..., None] * cc[i] * 255.0
    return alpha, img, zz

def lapvar(img):
    g = cv2.cvtColor(np.clip(img,0,255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float64)
    return cv2.Laplacian(g, cv2.CV_64F).var()

def pano_gt_fair(window):
    """Fair sharpness ceiling: the pano DOWNSAMPLED to the splat source grid
    (1022x518) then bilinearly mapped to the window — the best the splat layer
    can represent from its own source data."""
    src_grid = cv2.resize(pano_img, (GW, GH), interpolation=cv2.INTER_AREA).astype(np.float64)
    ys, xs = window
    py = np.arange(ys.start, ys.stop)[:, None] - VH/2
    px = np.arange(xs.start, xs.stop)[None, :] - VW/2
    dirs = fwd[None,None,:] + right[None,None,:]*(px/fl)[...,None] + up[None,None,:]*(-py/fl)[...,None]
    d = dirs / np.linalg.norm(dirs, axis=-1, keepdims=True)
    ph = np.arcsin(np.clip(d[...,1], -1, 1)); az = np.arctan2(d[...,2], -d[...,0]) % (2*np.pi)
    row = ((math.pi/2-ph)/math.pi)*GH
    colm = (az/(2*np.pi))*GW
    return cv2.remap(src_grid, colm.astype(np.float32), row.astype(np.float32), cv2.INTER_LINEAR)

gt_win = pano_gt(WIN)
gt_fair = pano_gt_fair(WIN)
report["origin_gt_lapvar"] = round(lapvar(gt_win), 1)
report["origin_gt_fair_lapvar"] = round(lapvar(gt_fair), 1)   # source-grid ceiling

# ---------- 3. V1.0 root-cause quantification ----------
pos10, sig10, col10, op10 = build(0.7, 0.95)
t0 = time.time()
al10, img10, _ = render_window(pos10, sig10, col10, op10)
comp10 = img10 + (1-al10[...,None])*gt_fair
r10 = {
  "alpha": {"min": round(float(al10.min()),3), "p5": round(float(np.percentile(al10,5)),3),
            "p50": round(float(np.percentile(al10,50)),3), "mean": round(float(al10.mean()),3)},
  "bleed_px_pct": round(float((al10 < 0.97).mean()*100), 1),
  "solo_lapvar": round(lapvar(img10 + (1-al10[...,None])*128), 1),
  "composite_lapvar": round(lapvar(comp10), 1),
  "retention_vs_sourcegrid_pct": round(lapvar(comp10)/lapvar(gt_fair)*100, 1),
  "n_splats": int(len(pos10)),
}
report["v10_rootcause"] = r10
print("[3] V1.0 coverage:", json.dumps(r10["alpha"]), "| bleed px:", r10["bleed_px_pct"],
      "% | retention(src-grid):", r10["retention_vs_sourcegrid_pct"], f"| window render {time.time()-t0:.1f}s")

# ---------- 4. candidate sweep ----------
cands = []
for c in (1.0, 1.15, 1.3):
    for op in (0.95, 1.0):
        cands.append((c, op, False))
cands.append((1.15, 1.0, True))     # lattice offset variant
sweep = []
for c, op, roff in cands:
    pos, sig, col, _ = build(c, op, roff)
    al, img, _ = render_window(pos, sig, col, op)
    comp = img + (1-al[...,None])*gt_fair
    ret = lapvar(comp)/lapvar(gt_fair)*100
    s = {"c_sigma": c, "opacity": op, "row_offset": roff,
         "alpha_min": round(float(al.min()),3), "alpha_p5": round(float(np.percentile(al,5)),3),
         "alpha_mean": round(float(al.mean()),3),
         "bleed_px_pct": round(float((al < 0.97).mean()*100),1),
         "retention_vs_sourcegrid_pct": round(ret,1), "n_splats": int(len(pos))}
    sweep.append(s)
    print("[4]", s)
report["sweep"] = sweep

# ---------- 5. pick winner: coverage first (kills dots+bleed), then sharpness ----------
ok = [s for s in sweep if s["alpha_p5"] >= 0.97]
if not ok:
    ok = sorted(sweep, key=lambda s: -s["alpha_p5"])[:1]
win = sorted(ok, key=lambda s: (-s["alpha_p5"], s["bleed_px_pct"], -s["retention_vs_sourcegrid_pct"]))[0]
report["winner"] = win
print("[5] winner:", win)

# ---------- 6. holes check at offsets for the winner ----------
pos, sig, col, _ = build(win["c_sigma"], win["opacity"], win["row_offset"])
for d in (0.75, 1.30):
    cam = (d, 0, 0)
    al, img, zz = render_window(pos, sig, col, win["opacity"], cam=cam)
    gt = pano_gt(WIN)
    comp = img + (1-al[...,None])*gt_fair
    rep = {"offset_m": d, "alpha_p5": round(float(np.percentile(al,5)),3),
           "visible_hole_pct": round(float((al < 0.30).mean()*100),2),
           "retention_vs_sourcegrid_pct": round(lapvar(comp)/lapvar(gt_fair)*100,1)}
    report.setdefault("winner_offsets", []).append(rep)
    print("[6]", rep)

# ---------- 7. export winner PLY -> SPZ v4 ----------
import spz
n = len(pos)
log_op = np.full(n, math.log(win["opacity"]/(1-win["opacity"])) if win["opacity"] < 1 else 9.21, np.float32)
f_dc = ((col - 0.5)/SH_C0).astype(np.float32)
log_s = np.log(sig.astype(np.float32))
fields = [("x", pos[:,0]), ("y", pos[:,1]), ("z", pos[:,2]),
          ("nx", np.zeros(n)), ("ny", np.zeros(n)), ("nz", np.zeros(n)),
          ("f_dc_0", f_dc[:,0]), ("f_dc_1", f_dc[:,1]), ("f_dc_2", f_dc[:,2])]
fields += [(f"f_rest_{i}", np.zeros(n, np.float32)) for i in range(45)]
fields += [("opacity", log_op), ("scale_0", log_s), ("scale_1", log_s), ("scale_2", log_s),
           ("rot_0", np.ones(n)), ("rot_1", np.zeros(n)), ("rot_2", np.zeros(n)), ("rot_3", np.zeros(n))]
hdr = ["ply", "format binary_little_endian 1.0", f"element vertex {n}"]
for name, _ in fields: hdr.append(f"property float {name}")
hdr.append("end_header")
ply_path = "/tmp/splat/cabin_splat_v11.ply"
with open(ply_path, "wb") as fh:
    fh.write(("\n".join(hdr)+"\n").encode())
    fh.write(np.stack([v.astype(np.float32) for _, v in fields], axis=1).astype("<f4").tobytes())
gc_ = spz.load_splat_from_ply(ply_path)
spz_path = "/tmp/splat/cabin_splat_v11.spz"
spz.save_spz(gc_, spz.PackOptions(), spz_path)
import shutil
shutil.copy(spz_path, f"{LAB}/cabin_splat_v11.spz")
report["export"] = {"ply": ply_path, "spz": spz_path,
                    "ply_mb": round(os.path.getsize(ply_path)/1e6, 2),
                    "spz_kb": round(os.path.getsize(spz_path)/1e3, 1),
                    "n": int(n), "lab_asset": f"{LAB}/cabin_splat_v11.spz"}
json.dump(report, open(f"{ART}/vq11_gen.json", "w"), indent=1)
print("[7]", json.dumps(report["export"]))
print("saved ->", f"{ART}/vq11_gen.json")
