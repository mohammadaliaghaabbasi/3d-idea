#!/usr/bin/env python3
"""moradi_gen.py — MORADI REAL-CONTENT TEST, Phase B.
Generates SPZ v4 splats for the 10 selected moradi-house scenes with the
LOCKED VQ 1.1 winner parameters (no per-scene tuning — method test):
  stride 2 on the 1022x518 grid, sigma = 1.3 x footprint (clip 0.02*c/0.7..2.0),
  opacity 1.0, CAM_H 1.5 m, depth clip 0.3-60 m — identical math to vq11_gen.py
  (DAV2-small ONNX -> disparity -> floor-median metric scale -> unproject).
QC per scene: exact-Gaussian front-to-back window render at the harness origin
view — alpha coverage min/p5 (V1.0 dots/bleed must NOT return on real content).
Outputs:
  public/labs/engine-v1/assets/moradi_<scene>_splat_v11.spz
  public/assets/panoramas/moradi_<scene>.jpg          (harness pano layer)
  docs/rd-artifacts/engine-v1/moradi_gen.json
"""
import json, math, os, shutil, sys, time
import numpy as np
import cv2
import onnxruntime as ort
from PIL import Image

REPO = "/home/z/my-project/3d-idea"
SRC = "/tmp/moradi/src"
LAB = f"{REPO}/public/labs/engine-v1/assets"
PANO_DIR = f"{REPO}/public/assets/panoramas"
ART = f"{REPO}/docs/rd-artifacts/engine-v1"
GW, GH, STRIDE, CAM_H = 1022, 518, 2, 1.5
C_SIGMA, OP = 1.3, 1.0                      # LOCKED V1.1 winner
SH_C0 = 0.28209479177387814
OUT = "/tmp/moradi"; os.makedirs(f"{OUT}/ply", exist_ok=True)

SCENES = [  # (scene_id, source title)
    ("moradi_main1", "Main_1_moradi"),
    ("moradi_main2", "Main_2_moradi"),
    ("moradi_main3", "Main_3_moradi"),
    ("moradi_main4", "Main_4_moradi"),
    ("moradi_kit1",  "Kitchen_1_moradi"),
    ("moradi_kit2",  "Kitchen_2_moradi"),
    ("moradi_bed1a", "Bedroom_1-1_moradi"),
    ("moradi_bed1b", "Bedroom_1-2_moradi"),
    ("moradi_bed2a", "Bedroom_2-1_moradi"),
    ("moradi_bed3a", "Bedroom_3-1_moradi"),
]

sess = ort.InferenceSession("/tmp/dav2/dav2_small.onnx", providers=["CPUExecutionProvider"])

# ---------- origin-view window render (identical recipe to vq11_gen.py) ----------
VW, VH = 780, 1688
WIN = (slice(int(VH*0.40), int(VH*0.40)+520), slice(int(VW*0.36), int(VW*0.36)+260))
vfov = math.radians(72); fl = (VH/2)/math.tan(vfov/2)
yaw, pitch = -math.pi/2, -0.03
cy_, sy_, cp_, sp_ = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
fwd = np.array([-sy_*cp_, sp_, -cy_*cp_])
up0 = np.array([0,1,0.0]); right = np.cross(fwd, up0); right /= np.linalg.norm(right)
up = np.cross(right, fwd)

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
    spx = (s/zc)*fl
    inwin = (px > xs.start-margin*30) & (px < xs.stop+margin*30) & \
            (py > ys.start-margin*30) & (py < ys.stop+margin*30)
    idx = np.argsort(-zc[inwin])
    px, py, spx = px[inwin][idx], py[inwin][idx], spx[inwin][idx]
    cc = c[inwin][idx]
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
        a = a * (1 - alpha[ya:yb, xa:xb])
        alpha[ya:yb, xa:xb] += a
        img[ya:yb, xa:xb] += a[..., None] * cc[i] * 255.0
    return alpha, img

def gen_scene(scene, title):
    t0 = time.time()
    pano_img = np.array(Image.open(f"{SRC}/{title}.jpg").convert("RGB"))
    rgb = cv2.resize(pano_img, (GW, GH), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    x = (rgb - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    disp = sess.run(None, {sess.get_inputs()[0].name: np.transpose(x, (2, 0, 1))[None]})[0][0]
    depth_rel = 1.0 / np.maximum(disp, 1e-6)
    V = np.linspace(0.5/GH, 1-0.5/GH, GH)[:, None] * np.ones((1, GW))
    phi = np.pi/2 - V*np.pi
    mask = (V > 0.86) & (V < 0.985) & (-np.sin(phi) > 0.25)
    t_floor = CAM_H / (-np.sin(phi))
    k = np.median(t_floor[mask] / depth_rel[mask])
    depth = np.clip(depth_rel * k, 0.3, 60.0)
    U = (np.arange(GW) + 0.5) / GW
    a = U * 2 * np.pi
    dx = -np.cos(a)[None, :] * np.cos(phi)
    dz = np.sin(a)[None, :] * np.cos(phi)
    dy = np.sin(phi)
    P = np.stack([dx*depth, dy*depth, dz*depth], axis=-1)
    footprint = depth * (2*np.pi/GW)
    sel = np.zeros((GH, GW), bool); sel[::STRIDE, ::STRIDE] = True
    pos = P[sel].astype(np.float64)
    sig = np.clip(footprint[sel] * C_SIGMA, 0.02 * C_SIGMA / 0.7, 2.0).astype(np.float64)
    col = rgb[sel]
    n = len(pos)
    t_depth = time.time() - t0

    # QC: origin alpha coverage (dots/bleed must not return)
    al, img = render_window(pos, sig, col, OP)
    qc = {"alpha_min": round(float(al.min()), 3),
          "alpha_p5": round(float(np.percentile(al, 5)), 3),
          "alpha_mean": round(float(al.mean()), 3),
          "bleed_px_pct": round(float((al < 0.97).mean()*100), 2)}
    t_qc = time.time() - t0

    # PLY -> SPZ v4
    import spz
    log_op = np.full(n, 9.21, np.float32)
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
    ply_path = f"{OUT}/ply/{scene}.ply"
    with open(ply_path, "wb") as fh:
        fh.write(("\n".join(hdr)+"\n").encode())
        fh.write(np.stack([v.astype(np.float32) for _, v in fields], axis=1).astype("<f4").tobytes())
    gc_ = spz.load_splat_from_ply(ply_path)
    spz_path = f"{LAB}/{scene}_splat_v11.spz"
    spz.save_spz(gc_, spz.PackOptions(), spz_path)
    # stage the pano for the harness pano layer
    shutil.copy(f"{SRC}/{title}.jpg", f"{PANO_DIR}/{scene}.jpg")
    t_all = time.time() - t0
    rep = {"title": title, "k_metric_scale": round(float(k), 3),
           "depth_clip_lo_pct": round(float((depth <= 0.3).mean()*100), 3),
           "depth_clip_hi_pct": round(float((depth >= 60).mean()*100), 3),
           "n_splats": int(n), "origin_qc": qc,
           "spz_kb": round(os.path.getsize(spz_path)/1e3, 1),
           "pano_kb": round(os.path.getsize(f"{PANO_DIR}/{scene}.jpg")/1e3, 1),
           "t_depth_s": round(t_depth,1), "t_total_s": round(t_all,1)}
    print(f"[gen] {scene}: k={rep['k_metric_scale']:.2f} clip_lo={rep['depth_clip_lo_pct']}% "
          f"clip_hi={rep['depth_clip_hi_pct']}% qc={qc} spz={rep['spz_kb']}KB {t_all:.0f}s", flush=True)
    return rep

if __name__ == "__main__":
    only = sys.argv[1:] or None
    report = {"tool": "moradi_gen.py", "params_locked": {"c_sigma": C_SIGMA, "opacity": OP,
               "stride": STRIDE, "grid": [GW, GH], "cam_h": CAM_H}, "scenes": {}}
    for scene, title in SCENES:
        if only and scene not in only: continue
        report["scenes"][scene] = gen_scene(scene, title)
    json.dump(report, open(f"{ART}/moradi_gen.json", "w"), indent=1)
    print("saved ->", f"{ART}/moradi_gen.json")
