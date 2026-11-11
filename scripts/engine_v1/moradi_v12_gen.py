#!/usr/bin/env python3
"""moradi_v12_gen.py — VQ 1.2 content upgrade: the Marble §7 program on Moradi.

Owner order 2026-11-11: «تمامی تجربه‌هایی که الان داری دقیقاً یک نمونهٔ تکمیلی از
خواستهٔ ما را روی مرادی پیاده کن … با کمک ماربل و الان هم این مدل هانیوان …
یک نمونهٔ دقیق بدون ایراد برای بررسی بساز، روی گیت‌هاب پوش کن و لینک سایت را بده»

LOCKED (identical math to moradi_gen.py / vq11_gen.py — method lock untouched):
  DAV2-small ONNX depth @ 1022x518, floor-median metric scale k (CAM_H 1.5 m),
  spherical unprojection u = atan2(dz,-dx)/2pi (top row = sky), depth clip 0.3-60 m,
  colour from the same downsampled grid, PLY (62 props) -> SPZ v4 via nianticlabs spz.

VQ 1.2 CHANGES (all content-side; renderer/format/locks untouched) — each item is a
measured recommendation of docs/engine-upgrade-v1/marble_reverse_engineering.md §7
plus the native-filter analog of worldmirror_reverse_engineering.md §6-2:
  1. fog-cull (§7-1): robust room diameter D = 2 x P97.5(radial |P|) per scene
     (documented, measured); cull splats with radial distance > D. Kills the DAV2
     far-edge / depth-clip "fog splats" that veiled the room (v11 p99 sigma ~0.47 m
     at up to 60 m, bbox inflated to ~100 m).
  2. density (§7-5): stride 2 -> stride 1 on the same locked grid
     (132,349 -> ~531k splats = Marble 500k class, same surface, no new geometry).
  3. anisotropy (§7-3): surface-adhering gaussians — tangent sigma = C_T x local
     cell size (from the depth grid itself), normal sigma = C_N x min tangent
     (thin disk), rotation = quaternion of the local surface frame. Edge/degenerate
     cells (relative depth gradient >= threshold) fall back to isotropic v11-style
     splats with the EDGE alpha — the confidence/edge filter analog of the
     HunyuanWorld-Mirror demo's native «Filter low confidence & depth/normal edges».
  4. alpha structure (§7-4): opacity lerp(A_SMOOTH -> A_EDGE, edge-confidence)
     instead of uniform 1.0 (Marble profile: median alpha 0.29-0.57).
  5. sigma cap = 0.02 x D (Marble p99-equivalent threshold) on every axis — kills
     tangent blowups at depth discontinuities; each splat sits at its own pixel.

QC = exact EWA gaussian projection (per-splat 2x2 screen covariance, front-to-back
alpha) at the harness origin camera; gates:
  alpha_p5 >= 0.97 over the CONTENT region (pixels the stride-1 no-cull isotropic
  control covers — no new bleed/holes inside real content), holes@0.75 m no worse
  than the v11 control, sharpness retention (lapvar composite vs source-grid
  ceiling) not below the v11 control.

Outputs (all additive; v11 assets stay byte-identical for A/B):
  public/labs/engine-v1/assets/{scene}_splat_v12.spz
  docs/rd-artifacts/engine-v1/moradi_v12_gen.json  (sweep + per-scene record)
"""
import json, math, os, sys, time
import numpy as np
import cv2
import onnxruntime as ort
from PIL import Image

REPO = "/home/z/my-project/3d-idea"
PANO_DIR = f"{REPO}/public/assets/panoramas"
LAB = f"{REPO}/public/labs/engine-v1/assets"
ART = f"{REPO}/docs/rd-artifacts/engine-v1"
GW, GH, CAM_H = 1022, 518, 1.5
SH_C0 = 0.28209479177387814
OUT = "/tmp/v12"; os.makedirs(f"{OUT}/ply", exist_ok=True)

SCENES = ["moradi_main1", "moradi_main2", "moradi_main3", "moradi_main4",
          "moradi_kit1", "moradi_kit2", "moradi_bed1a", "moradi_bed1b",
          "moradi_bed2a", "moradi_bed3a"]
SWEEP_SCENE = "moradi_main1"
ALSO = ["cabin"]                    # CC0 Poly Haven — A/B + WM comparison anchor

# V1.1 locked control (for the sweep baseline + gates)
V11 = dict(stride=2, c_sigma=1.3, opacity=1.0)

# VQ 1.2 candidate grid (Marble-profile targets: aniso_med 2.0-2.4, alpha_med 0.29-0.57)
# NOTE (measured 2026-11-11 sweep run 1): a_smooth 0.9/0.8 FAIL the no-bleed gate
# (content alpha p5 < 0.97) at stride-1 density — Marble's soft-alpha profile needs
# their overlap density; at ~531k splats the gate wins. C3_alpha_090 is kept as the
# measured rejection evidence.
CANDS = {
    "C1_iso_densified": dict(c_t=0.65, c_n=1.0,  a_smooth=1.0, a_edge=1.0),   # density+fog-cull only
    "C2_aniso":         dict(c_t=0.65, c_n=0.45, a_smooth=1.0, a_edge=1.0),   # + anisotropy (Marble band)
    "C3_alpha_090":     dict(c_t=0.65, c_n=0.45, a_smooth=0.9, a_edge=0.55),  # measured rejection candidate
    "C5_aniso_strong":  dict(c_t=0.65, c_n=0.35, a_smooth=1.0, a_edge=1.0),   # thin disk (aniso ~2.9)
    "C6_aniso_mild":    dict(c_t=0.65, c_n=0.55, a_smooth=1.0, a_edge=1.0),   # mild (aniso ~1.8)
}
G_LO, G_HI = 0.08, 0.35            # relative depth-gradient band for edge confidence
SIGMA_MIN = 0.02                   # per-axis sigma floor (m)
# Radial cull — MEASURED WRONG TWICE, REJECTED BOTH TIMES (honest record):
#   attempt 1 (2 x D_room): deleted moradi_main2's entire +x view (100% absent)
#     + 21.75% of main4 — room diameter ignores real content seen through openings.
#   attempt 2 (absolute 45 m): fixed main2/main4 but the REAL-Spark battery caught
#     moradi_main1's mz view @0.75m with 20.8% magenta holes — the +z region holds
#     real 45-60 m content (outdoors through windows) that the QC +x window never
#     saw. Radial culls delete real photographed views in single-pano content.
# The veil (§7-1) is killed by the OWN-PIXEL SIGMA CAP below instead: far splats
# become ~2 px dust (correct pixel size at their depth), not 2 m fog blobs.
# => NO RADIAL CULL. Every photographed pixel keeps its splat (v11 completeness
#    parity, measured: absent/holes = 0 everywhere + far-view battery).
CULL_R = None
# Sigma rule (§7-1 + §7-3): each splat sits at its own source pixel — tangent
# sigma = c_t x local cell, hard-capped at the LOCAL source-pixel size
# (1.3 x footprint of that splat's own depth) so depth-edge cells (whose 2-cell
# span explodes across a discontinuity) can never blow up into fog blobs.
# No global room-percentage cap: far real content needs its (large) own pixel.
SIGMA_EDGE_CAP_K = 1.3

sess = ort.InferenceSession("/tmp/dav2/dav2_small.onnx", providers=["CPUExecutionProvider"])

# ---------------- harness origin camera + window (identical to moradi_gen.py) ----------------
VW, VH = 780, 1688
WIN = (slice(int(VH*0.40), int(VH*0.40)+520), slice(int(VW*0.36), int(VW*0.36)+260))
vfov = math.radians(72); fl = (VH/2)/math.tan(vfov/2)
yaw, pitch = -math.pi/2, -0.03
cy_, sy_, cp_, sp_ = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
fwd = np.array([-sy_*cp_, sp_, -cy_*cp_])
up0 = np.array([0,1,0.0]); right = np.cross(fwd, up0); right /= np.linalg.norm(right)
up = np.cross(right, fwd)
BAS = np.stack([right, up, fwd])            # world -> view (x,y,z) rows

def pano_gt_fair(pano_img, window):
    """Sharpness ceiling: pano downsampled to the splat source grid, mapped to window."""
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

def lapvar(img):
    g = cv2.cvtColor(np.clip(img,0,255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float64)
    return cv2.Laplacian(g, cv2.CV_64F).var()

# ---------------- per-scene locked depth + unprojection (identical math) ----------------
def depth_grid(scene):
    pano_img = np.array(Image.open(f"{PANO_DIR}/{scene}.jpg").convert("RGB"))
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
    dx = -np.cos(a)[None, :]*np.cos(phi)
    dz = np.sin(a)[None, :]*np.cos(phi)
    dy = np.sin(phi)
    P = np.stack([dx*depth, dy*depth, dz*depth], axis=-1)
    footprint = depth * (2*np.pi/GW)
    return pano_img, rgb, depth, P, footprint, float(k)

def grid_frames(depth, P, footprint):
    """Local surface frames from the depth grid (wrap u, one-sided v edges)."""
    ju = np.roll(P, -1, axis=1) - np.roll(P, 1, axis=1)          # 2 cells along u
    tv = np.empty_like(P)
    tv[1:-1] = P[2:] - P[:-2]
    tv[0] = P[1] - P[0]; tv[-1] = P[-1] - P[-2]                  # 2 cells along v
    du_ = np.empty_like(depth); dv_ = np.empty_like(depth)
    du_[1:-1] = depth[2:] - depth[:-2]; du_[0] = depth[1]-depth[0]; du_[-1] = depth[-1]-depth[-2]
    dv_ = np.roll(depth, -1, axis=1) - np.roll(depth, 1, axis=1)
    g = np.maximum(np.abs(du_)/np.maximum(depth, 1e-6), np.abs(dv_)/np.maximum(depth, 1e-6))
    conf = np.clip((G_HI - g) / (G_HI - G_LO), 0.0, 1.0)          # 1 smooth .. 0 hard edge
    return ju, tv, g, conf

def build_v11(depth, P, footprint, rgb):
    sel = np.zeros((GH, GW), bool); sel[::V11["stride"], ::V11["stride"]] = True
    pos = P[sel].astype(np.float64)
    sig = np.clip(footprint[sel]*V11["c_sigma"], 0.02*V11["c_sigma"]/0.7, 2.0).astype(np.float64)
    col = rgb[sel]
    n = len(pos)
    rot = np.zeros((n, 4)); rot[:, 0] = 1.0
    return dict(pos=pos, sig=np.stack([sig, sig, sig], 1), col=col,
                alpha=np.full(n, V11["opacity"]), rot=rot, iso=True)

def room_diameter(P):
    """Robust room diameter from the measured floor band (y in -1.8..-1.2 m).
    The floor IS the room footprint; P90 of its horizontal radius kills the
    grazing tail beyond the walls (measured /tmp/v12_diag.json: floor-band P90
    horizontal = 1.7-6.5 m across the 11 scenes, while radial P97.5 = 9-30 m
    poisoned by the far tail — first sweep run measured D=60.5 m with it)."""
    floor = (P[..., 1] < -1.2) & (P[..., 1] > -1.8)
    if floor.sum() < 100:
        return float(2.0*np.percentile(np.linalg.norm(P, axis=-1), 90))
    horiz = np.linalg.norm(P[..., [0, 2]], axis=-1)
    return float(2.0*np.percentile(horiz[floor], 90))

def build_v12(depth, P, footprint, rgb, ju, tv, conf, prm):
    """VQ 1.2 arrays: fog-cull + stride-1 + anisotropic surface frame + alpha structure."""
    D_room = room_diameter(P)
    radial = np.linalg.norm(P, axis=-1)
    keep = radial <= CULL_R if CULL_R else np.ones_like(radial, bool)   # no radial cull (measured rejection)
    idx = np.argwhere(keep)                                        # stride 1 (§7-5)
    pos = P[idx[:,0], idx[:,1]].astype(np.float64)
    col = rgb[idx[:,0], idx[:,1]]
    fp = footprint[idx[:,0], idx[:,1]]
    cf = conf[idx[:,0], idx[:,1]]
    # cell sizes (central differences = 2 cells); cap at the splat's OWN
    # source-pixel size (1.3 x its footprint) — edge cells can never fog-blob
    caploc = np.maximum(SIGMA_EDGE_CAP_K * fp, SIGMA_MIN)
    cu = np.linalg.norm(ju[idx[:,0], idx[:,1]], axis=-1) / 2.0
    cv = np.linalg.norm(tv[idx[:,0], idx[:,1]], axis=-1) / 2.0
    su = np.clip(prm["c_t"]*cu, SIGMA_MIN, caploc)
    sv = np.clip(prm["c_t"]*cv, SIGMA_MIN, caploc)
    sn = np.clip(prm["c_n"]*np.minimum(su, sv), SIGMA_MIN*prm["c_n"], caploc)
    # alpha structure (§7-4): smooth -> A_SMOOTH, hard edge -> A_EDGE
    alpha = prm["a_edge"] + (prm["a_smooth"]-prm["a_edge"])*cf
    # frames: edges (conf < 0.5) + degenerate cells -> isotropic fallback (v11-style)
    t1 = ju[idx[:,0], idx[:,1]]; t2 = tv[idx[:,0], idx[:,1]]
    deg = (np.linalg.norm(t1, axis=-1) < 1e-9) | (np.linalg.norm(t2, axis=-1) < 1e-9) | (cf < 0.5)
    t1n = t1 / np.maximum(np.linalg.norm(t1, axis=-1, keepdims=True), 1e-12)
    t2p = t2 - (t2*t1n).sum(-1, keepdims=True)*t1n
    t2n = t2p / np.maximum(np.linalg.norm(t2p, axis=-1, keepdims=True), 1e-12)
    nn = np.cross(t1n, t2n); nn /= np.maximum(np.linalg.norm(nn, axis=-1, keepdims=True), 1e-12)
    M = np.stack([t1n, t2n, nn], axis=-1)                          # columns = local axes
    det = np.linalg.det(M)
    flip = det < 0
    nn[flip] *= -1.0
    M = np.stack([t1n, t2n, nn], axis=-1)
    iso_sig = np.clip(fp*prm["c_t"], SIGMA_MIN, caploc)
    su[deg] = iso_sig[deg]; sv[deg] = iso_sig[deg]; sn[deg] = iso_sig[deg]
    M[deg] = np.eye(3)
    rot = quat_from_mats(M)
    sig = np.stack([su, sv, sn], 1)
    return dict(pos=pos, sig=sig, col=col, alpha=alpha, rot=rot, iso=False,
                D_room=D_room, far=CULL_R,
                culled_pct=round(float((~keep).mean()*100), 2),
                deg_pct=round(float(deg.mean()*100), 2))

def quat_from_mats(M):
    """Batched quaternion (w,x,y,z) from rotation matrices (columns = local axes)."""
    m = M; n = len(m)
    tr = m[:,0,0]+m[:,1,1]+m[:,2,2]
    q = np.zeros((n,4))
    c1 = tr > 0
    s = np.sqrt(np.maximum(tr[c1]+1.0, 1e-12))*2
    q[c1,0] = 0.25*s
    q[c1,1] = (m[c1,2,1]-m[c1,1,2])/s; q[c1,2] = (m[c1,0,2]-m[c1,2,0])/s; q[c1,3] = (m[c1,1,0]-m[c1,0,1])/s
    rest = ~c1
    if rest.any():
        mr = m[rest]
        d = np.stack([mr[:,0,0], mr[:,1,1], mr[:,2,2]], 1)
        am = d.argmax(1)
        qr = np.zeros((len(mr),4))
        for case in (0,1,2):
            sel = am == case
            if not sel.any(): continue
            mm = mr[sel]
            i, j, kk = case, (case+1)%3, (case+2)%3
            s = np.sqrt(np.maximum(1.0 + mm[:,i,i]-mm[:,j,j]-mm[:,kk,kk], 1e-12))*2
            qr[sel, i+1] = 0.25*s
            qr[sel, 0]  = (mm[:,kk,j]-mm[:,j,kk])/s
            qr[sel, j+1] = (mm[:,i,j]+mm[:,j,i])/s
            qr[sel, kk+1] = (mm[:,i,kk]+mm[:,kk,i])/s
        q[rest] = qr
    q /= np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-12)
    return q

# ---------------- exact EWA window render (anisotropic, per-splat alpha) ----------------
def render_window(pano_img, arr, cam=(0,0,0), margin=3.0):
    ys, xs = WIN
    wh, ww = ys.stop-ys.start, xs.stop-xs.start
    cam = np.array(cam, np.float64)
    pos, sig, col, al, rot = arr["pos"], arr["sig"], arr["col"], arr["alpha"], arr["rot"]
    v = pos - cam
    zc = v @ fwd
    ok = zc > 0.2
    v, zc = v[ok], zc[ok]
    col, al, sig, rot = col[ok], al[ok], sig[ok], rot[ok]
    xc = v @ right; yc = v @ up
    px = VW/2 + (xc/zc)*fl
    py = VH/2 - (yc/zc)*fl
    inwin = (px > xs.start-margin*30) & (px < xs.stop+margin*30) & \
            (py > ys.start-margin*30) & (py < ys.stop+margin*30)
    idx = np.argsort(-zc[inwin])                                   # front to back
    px, py = px[inwin][idx], py[inwin][idx]
    cc, aa, zz = col[inwin][idx], al[inwin][idx], zc[inwin][idx]
    sg, rt = sig[inwin][idx], rot[inwin][idx]
    # world covariance per splat: R diag(s^2) R^T
    S2 = sg*sg
    Rw = rt_to_mat(rt)
    SigW = np.einsum('nij,nj,nkj->nik', Rw, S2, Rw)
    SigV = np.einsum('ij,njk,lk->nil', BAS, SigW, BAS)            # view-frame 3x3
    # EWA Jacobian: px = VW/2 + fl*xc/zc ; py = VH/2 - fl*yc/zc
    xcv = v[inwin][idx] @ right; ycv = v[inwin][idx] @ up
    z = np.maximum(zz, 1e-6)
    a11 = fl/z; a13 = -fl*xcv/(z*z); a22 = fl/z; a23 = -fl*ycv/(z*z)
    SigS = np.empty((len(z), 2, 2))
    SigS[:,0,0] = a11*a11*SigV[:,0,0] + a13*a13*SigV[:,2,2] + 2*a11*a13*SigV[:,0,2]
    SigS[:,1,1] = a22*a22*SigV[:,1,1] + a23*a23*SigV[:,2,2] + 2*a22*a23*SigV[:,1,2]
    SigS[:,0,1] = SigS[:,1,0] = a11*a22*SigV[:,0,1] + a11*a23*SigV[:,0,2] + a13*a22*SigV[:,2,1] + a13*a23*SigV[:,2,2]
    alpha = np.zeros((wh, ww), np.float64)
    img = np.zeros((wh, ww, 3), np.float64)
    for i in range(len(px)):
        x0, y0 = px[i]-xs.start, py[i]-ys.start
        A, Bc, Cc = SigS[i,0,0], SigS[i,0,1], SigS[i,1,1]
        tr2 = 0.5*(A+Cc); dsc = math.sqrt(max(0.25*(A-Cc)**2 + Bc*Bc, 1e-18))
        l1, l2 = tr2+dsc, max(tr2-dsc, 1e-12)
        s1 = math.sqrt(l1); s2 = math.sqrt(l2)
        if l1 <= 1e-12: continue
        th = 0.5*math.atan2(2*Bc, A-Cc)
        ct, st = math.cos(th), math.sin(th)
        R = 3.0*s1
        xa, xb = max(0, int(x0-R)), min(ww, int(x0+R)+1)
        ya, yb = max(0, int(y0-R)), min(wh, int(y0+R)+1)
        if xa >= xb or ya >= yb: continue
        yy, xx = np.mgrid[ya:yb, xa:xb]
        u = (xx-x0)*ct + (yy-y0)*st
        w_ = -(xx-x0)*st + (yy-y0)*ct
        g = np.exp(-0.5*(u*u/l1 + w_*w_/l2))
        a = aa[i]*g*(1.0-alpha[ya:yb, xa:xb])
        alpha[ya:yb, xa:xb] += a
        img[ya:yb, xa:xb] += a[..., None]*cc[i]*255.0
    return alpha, img

def rt_to_mat(q):
    w, x, y, z = q[:,0], q[:,1], q[:,2], q[:,3]
    m = np.empty((len(q), 3, 3))
    m[:,0,0] = 1-2*(y*y+z*z); m[:,0,1] = 2*(x*y-z*w);  m[:,0,2] = 2*(x*z+y*w)
    m[:,1,0] = 2*(x*y+z*w);   m[:,1,1] = 1-2*(x*x+z*z); m[:,1,2] = 2*(y*z-x*w)
    m[:,2,0] = 2*(x*z-y*w);   m[:,2,1] = 2*(y*z+x*w);  m[:,2,2] = 1-2*(x*x+y*y)
    return m

def qc(pano_img, arr, content_mask=None, offsets=(0.0,)):
    """Coverage / holes / retention gates. content_mask = pixels the no-cull control covers."""
    out = {}
    gt_fair = pano_gt_fair(pano_img, WIN)
    ceil = lapvar(gt_fair)
    for off in offsets:
        cam = (off, 0, 0) if off else (0, 0, 0)
        al, img = render_window(pano_img, arr, cam=cam)
        comp = img + (1-al[..., None])*gt_fair
        rec = {
            "alpha_min": round(float(al.min()), 3),
            "alpha_p5": round(float(np.percentile(al, 5)), 3),
            "absent_pct": round(float((al < 0.05).mean()*100), 2),
            "hole_pct": round(float((al < 0.30).mean()*100), 2),
            "retention_pct": round(float(lapvar(comp)/ceil*100), 1),
        }
        if content_mask is not None:
            cm = content_mask
            rec["content_alpha_p5"] = round(float(np.percentile(al[cm], 5)), 3)
            rec["content_bleed_pct"] = round(float((al[cm] < 0.97).mean()*100), 2)
        out[f"off_{off}"] = rec
    return out, ceil

# ---------------- PLY -> SPZ v4 export (identical 62-prop layout to v11) ----------------
def export_spz(scene, arr, tag):
    import spz
    n = len(arr["pos"])
    a = np.clip(arr["alpha"], 0.01, 0.999)
    log_op = np.log(a/(1.0-a)).astype(np.float32)
    f_dc = ((arr["col"] - 0.5)/SH_C0).astype(np.float32)
    log_s = np.log(arr["sig"].astype(np.float32))
    # SH degree 0 (VQ 1.2, honest + Marble-profile): we have NO view-dependency
    # data — all 45 f_rest columns would be zeros (v1.0/v11 carried them as layout
    # inertia = sh3 shader cost with zero information). sh0 cuts the SPZ payload
    # and the per-splat fragment math ~4x (measured: sh3 529k died in SwiftShader
    # settle; Marble's 500k sh0 renders 24.9 fps in the same harness).
    fields = [("x", arr["pos"][:,0]), ("y", arr["pos"][:,1]), ("z", arr["pos"][:,2]),
              ("nx", np.zeros(n)), ("ny", np.zeros(n)), ("nz", np.zeros(n)),
              ("f_dc_0", f_dc[:,0]), ("f_dc_1", f_dc[:,1]), ("f_dc_2", f_dc[:,2])]
    fields += [("opacity", log_op), ("scale_0", log_s[:,0]), ("scale_1", log_s[:,1]),
               ("scale_2", log_s[:,2]),
               ("rot_0", arr["rot"][:,0]), ("rot_1", arr["rot"][:,1]),
               ("rot_2", arr["rot"][:,2]), ("rot_3", arr["rot"][:,3])]
    hdr = ["ply", "format binary_little_endian 1.0", f"element vertex {n}"]
    for name, _ in fields: hdr.append(f"property float {name}")
    hdr.append("end_header")
    ply_path = f"{OUT}/ply/{scene}_{tag}.ply"
    with open(ply_path, "wb") as fh:
        fh.write(("\n".join(hdr)+"\n").encode())
        fh.write(np.stack([v.astype(np.float32) for _, v in fields], axis=1).astype("<f4").tobytes())
    gc_ = spz.load_splat_from_ply(ply_path)
    spz_path = f"{LAB}/{scene}_splat_{tag}.spz"
    spz.save_spz(gc_, spz.PackOptions(), spz_path)
    os.remove(ply_path)                                    # 132 MB PLYs: keep /tmp lean
    return {"ply_mb": round(n*62*4/1e6, 1), "spz_kb": round(os.path.getsize(spz_path)/1e3, 1),
            "n": int(n), "spz": spz_path}

def profile(arr):
    """Marble-profile stats of the built arrays (pre-quantization)."""
    smax = arr["sig"].max(axis=1); smin = arr["sig"].min(axis=1)
    return {"n": int(len(arr["pos"])),
            "sigma_p99": round(float(np.percentile(smax, 99)), 4),
            "sigma_p99_over_D": round(float(np.percentile(smax, 99)/arr["D_room"]), 5) if "D_room" in arr else None,
            "aniso_median": round(float(np.median(smax/np.maximum(smin, 1e-9))), 2),
            "alpha_median": round(float(np.median(arr["alpha"])), 3),
            "alpha_below_01_pct": round(float((arr["alpha"] < 0.1).mean()*100), 1),
            "alpha_above_09_pct": round(float((arr["alpha"] > 0.9).mean()*100), 1)}

# ============================================================================
if __name__ == "__main__":
    MODE = sys.argv[1] if len(sys.argv) > 1 else "all"        # all | sweep | gen
    t_all = time.time()
    report = {"tool": "moradi_v12_gen.py", "locked": {
                "grid": [GW, GH], "cam_h": CAM_H, "depth": "DAV2-small ONNX (identical to v11)",
                "fog_rule": "NO radial cull (2 x D_room and 45 m both measured WRONG - they deleted real photographed views: main2 +x 100%, main4 21.75%, main1 mz 20.8% @0.75m); the veil is killed by the own-pixel sigma cap (tangent sigma <= 1.3 x the splat's own footprint) - far splats = ~2 px dust, not fog blobs",
                "edge_rule": f"relative depth gradient band [{G_LO},{G_HI}] -> conf; conf<0.5 = isotropic fallback + A_EDGE"},
              "scenes": {}}

    # ---------------- Stage A: sweep on SWEEP_SCENE ----------------
    # gen mode: reuse the saved sweep winner (no re-run; RAM-tight sandbox)
    if MODE == "gen":
        prev = json.load(open(f"{ART}/moradi_v12_gen.json"))
        WINNER = prev["winner"]; wprm = prev.get("winner_params", CANDS[WINNER])
        print(f"=== STAGE A: skipped (gen mode) — winner from artifact: {WINNER} ===", flush=True)
        report["winner"] = WINNER; report["winner_params"] = wprm
        report["sweep_reused_from"] = "docs/rd-artifacts/engine-v1/moradi_v12_gen.json"
    else:
        print(f"=== STAGE A: sweep on {SWEEP_SCENE} ===", flush=True)
        pano_img, rgb, depth, P, footprint, k = depth_grid(SWEEP_SCENE)
        ju, tv, g, conf = grid_frames(depth, P, footprint)
        ctl = build_v11(depth, P, footprint, rgb)
        assert len(ctl["pos"]) == 132349, f"v11 control must be 132,349, got {len(ctl['pos'])}"
        ctl_qc, ceil = qc(pano_img, ctl, offsets=(0.0, 0.75))
        print(f"[control v11] qc={json.dumps(ctl_qc)}", flush=True)
    # content mask: pixels the FOG-CULLED stride-1 isotropic densified control covers
    # (the real-content region for the no-new-bleed gate; fog pixels are absent in
    #  the control too — the cull working is NOT counted as new bleed)
        keep_flat = (np.linalg.norm(P, axis=-1) <= CULL_R).reshape(-1)
        n_keep = int(keep_flat.sum())
        nocull = dict(pos=P.reshape(-1, 3)[keep_flat].astype(np.float64),
                      col=rgb.reshape(-1, 3)[keep_flat],
                      alpha=np.full(n_keep, 1.0), iso=True,
                      sig=np.stack([np.clip(footprint.reshape(-1)[keep_flat]*0.65, 0.02, 2.0)]*3, 1))
        nocull["rot"] = np.zeros((n_keep, 4)); nocull["rot"][:, 0] = 1.0
        al_mask, _ = render_window(pano_img, nocull)
        content_mask = al_mask >= 0.97
        print(f"[mask] content pixels = {content_mask.mean()*100:.1f}% of window", flush=True)

        sweep = {}
        for name, prm in CANDS.items():
            t0 = time.time()
            arr = build_v12(depth, P, footprint, rgb, ju, tv, conf, prm)
            arr_qc, _ = qc(pano_img, arr, content_mask=content_mask, offsets=(0.0, 0.75))
            pr = profile(arr)
            gates = {
                "pass_content_alpha": bool(arr_qc["off_0.0"]["content_alpha_p5"] >= 0.97),
                "pass_holes": bool(arr_qc["off_0.75"]["hole_pct"] <= ctl_qc["off_0.75"]["hole_pct"] + 0.5),
                "pass_retention": bool(arr_qc["off_0.0"]["retention_pct"] >= ctl_qc["off_0.0"]["retention_pct"] - 1.0),
            }
            sweep[name] = {"params": prm, "profile": pr, "qc": arr_qc, "gates": gates,
                           "D_room": round(arr["D_room"], 2), "culled_pct": arr["culled_pct"],
                           "deg_pct": arr["deg_pct"], "cull_r_m": arr["far"],
                           "t_s": round(time.time()-t0, 1)}
            print(f"[sweep {name}] {json.dumps(pr)} gates={gates} D={arr['D_room']:.1f}m "
                  f"culled={arr['culled_pct']}% {time.time()-t0:.0f}s", flush=True)
        report["sweep_scene"] = SWEEP_SCENE
        report["v11_control"] = {"qc": ctl_qc, "profile": profile(ctl)}
        report["sweep"] = sweep
    # winner: all gates, then closest to the Marble profile (aniso med in 2.0-2.4 first, then alpha med in 0.29-0.57)
        ok = [n for n, s in sweep.items() if all(s["gates"].values())]
        def score(n):
            s = sweep[n]; an = s["profile"]["aniso_median"]; am = s["profile"]["alpha_median"]
            return (0 if 1.8 <= an <= 2.6 else 1,            # Marble aniso band first
                    0 if 0.25 <= am <= 0.65 else 1,          # then Marble alpha band
                    -s["qc"]["off_0.0"]["retention_pct"])    # then retention
        WINNER = sorted(ok, key=score)[0] if ok else sorted(sweep, key=lambda n: -sweep[n]["qc"]["off_0.0"]["content_alpha_p5"])[0]
        report["winner"] = WINNER
        print(f"[winner] {WINNER} (of gates-passing: {ok})", flush=True)

    if MODE == "sweep":
        json.dump(report, open(f"{ART}/moradi_v12_gen.json", "w"), indent=1, ensure_ascii=False)
        print(f"saved (sweep-only) -> {ART}/moradi_v12_gen.json"); sys.exit(0)

    # ---------------- Stage B: all scenes + cabin with the winner ----------------
    print(f"=== STAGE B: generate all scenes with {WINNER} ===", flush=True)
    if MODE != "gen":
        wprm = dict(CANDS[WINNER]); report["winner_params"] = wprm
    for scene in SCENES + ALSO:
        t0 = time.time()
        if MODE == "gen" or scene != SWEEP_SCENE:       # gen mode has no cached grids
            pano_img, rgb, depth, P, footprint, k = depth_grid(scene)
            ju, tv, g, conf = grid_frames(depth, P, footprint)
        arr = build_v12(depth, P, footprint, rgb, ju, tv, conf, wprm)
        arr_qc, _ = qc(pano_img, arr, content_mask=None, offsets=(0.0, 0.75))
        pr = profile(arr)
        exp = export_spz(scene, arr, "v12")
        rep = {"k_metric_scale": round(k, 3), "D_room_m": round(arr["D_room"], 2),
               "culled_pct": arr["culled_pct"], "iso_fallback_pct": arr["deg_pct"],
               "profile": pr, "qc": arr_qc, "export": exp,
               "t_s": round(time.time()-t0, 1)}
        report["scenes"][scene] = rep
        print(f"[gen {scene}] n={pr['n']} D={rep['D_room_m']}m culled={rep['culled_pct']}% "
              f"aniso={pr['aniso_median']} alpha_med={pr['alpha_median']} "
                  f"spz={exp['spz_kb']}KB qc0={arr_qc['off_0.0']} {rep['t_s']}s", flush=True)

    # ---------------- delivered-file truth: parse the saved SPZ ----------------
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import marble_spz_compare as MSC
    stats = {}
    for scene in SCENES + ALSO:
        row = MSC.stats(f"{LAB}/{scene}_splat_v12.spz", f"OURS {scene} gen-v12")
        stats[scene] = {k: row[k] for k in ("num_splats", "bbox_diag", "scale_p99",
                                            "scale_over_diag_median", "aniso_median",
                                            "alpha_median", "alpha_below_01_pct",
                                            "alpha_above_09_pct", "bytes_per_splat",
                                            "splats_per_diag", "file_kb")}
        # v11 comparison on the same parser (same-file truth for the doc table)
        row11 = MSC.stats(f"{LAB}/{scene}_splat_v11.spz", f"OURS {scene} gen-v11")
        stats[scene]["v11"] = {k: row11[k] for k in ("num_splats", "bbox_diag", "scale_p99",
                                                     "aniso_median", "alpha_median", "file_kb")}
        print(f"[spz-truth {scene}] v12 n={stats[scene]['num_splats']} diag={stats[scene]['bbox_diag']:.1f} "
              f"p99={stats[scene]['scale_p99']:.3f} aniso={stats[scene]['aniso_median']} "
              f"alpha={stats[scene]['alpha_median']} | v11 n={stats[scene]['v11']['num_splats']} "
              f"diag={stats[scene]['v11']['bbox_diag']:.1f} p99={stats[scene]['v11']['scale_p99']:.3f}", flush=True)
    report["spz_truth"] = stats
    report["t_total_s"] = round(time.time()-t_all, 1)

    json.dump(report, open(f"{ART}/moradi_v12_gen.json", "w"), indent=1, ensure_ascii=False)
    print(f"saved -> {ART}/moradi_v12_gen.json  (total {report['t_total_s']}s)", flush=True)
