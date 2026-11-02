#!/usr/bin/env python3
"""Approach A prototype v3: Layered 3D from a single 360 pano (anniversary_lounge).

v3: the room shell is MEASURED from depth (per-azimuth cylindrical wall profile +
floor/ceiling planes), scale is fitted by shell-consistency, furniture = pixels
significantly in front of the measured shell. Shell texture behind furniture is
inpainted; furniture becomes independent meshes w/ back caps + colliders. GLB out.

Outputs in /tmp/rd/out/: anniversary_layered.glb, render_*.png, layered_metrics.json
"""
import time, os, json
import numpy as np
import cv2
import trimesh

OUT = "/tmp/rd/out"
PANO_HALF = f"{OUT}/pano_half.jpg"
DEPTH_NPY = f"{OUT}/depth_raw.npy"
GLB_PATH = f"{OUT}/anniversary_layered.glb"
ROOM_H_PRIOR = 2.8          # DB height prior (anniversary_lounge)
FURNITURE_MARGIN = 0.30
MAX_WALL = 9.0              # cap for openings toward other spaces
N_AZ_BINS = 144             # 2.5-deg bins
METRICS = {"timings": {}, "calibration": {}, "furniture": [], "files": {}, "colliders": []}

def log(*a): print(*a, flush=True)

def equirect_dirs(H, W):
    u = np.arange(W, dtype=np.float64) / W * 2 * np.pi
    v = np.arange(H, dtype=np.float64) / H
    phi = np.broadcast_to((0.5 - v[:, None]) * np.pi, (H, W)).copy()
    theta = np.broadcast_to(u[None, :], (H, W)).copy()
    cp, sp = np.cos(phi), np.sin(phi)
    return cp * np.cos(theta), sp, cp * np.sin(theta), phi, theta

def shell_distance(dx, dy, dz, cam_h, ceil_h, wall_rho, theta, phi):
    """Shell = min(wall cylinder per azimuth, floor plane y=0, ceiling plane y=ceil_h)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        cos_phi = np.sqrt(np.maximum(1 - np.sin(phi) ** 2, 1e-12))
        t_wall = wall_rho[(np.floor(theta / (2 * np.pi) * N_AZ_BINS).astype(int) % N_AZ_BINS)] / cos_phi
        t_floor = np.where(-np.sin(phi) > 1e-3, cam_h / np.maximum(-np.sin(phi), 1e-3), np.inf)
        t_ceil = np.where(np.sin(phi) > 1e-3, (ceil_h - cam_h) / np.maximum(np.sin(phi), 1e-3), np.inf)
    t = np.fmin(np.fmin(t_wall, t_floor), t_ceil)
    return np.where(np.isfinite(t) & (t > 0.05), t, np.inf)

def measure_wall_profile(D, theta, phi):
    """Per-azimuth wall radius: p88 of D in the horizon band, circular-smoothed."""
    band = (np.abs(phi) > np.radians(4)) & (np.abs(phi) < np.radians(25))
    prof = np.full(N_AZ_BINS, np.nan)
    for b in range(N_AZ_BINS):
        lo, hi = b / N_AZ_BINS * 2 * np.pi, (b + 1) / N_AZ_BINS * 2 * np.pi
        m = band & (theta >= lo) & (theta < hi)
        if m.sum() > 30:
            prof[b] = min(np.percentile(D[m], 88), MAX_WALL)
    # circular smoothing, 5-bin window
    idx = np.arange(-2, 3)
    sm = np.array([np.nanmean(prof[(np.arange(N_AZ_BINS) + k) % N_AZ_BINS]) for k in [0]])
    vals = prof.copy()
    good = ~np.isnan(vals)
    if good.sum() > 10:
        pad = np.r_[vals[good][-3:], vals[good], vals[good][:3]]
        ker = np.ones(7) / 7
        vals[good] = np.convolve(pad, ker, mode="same")[3:3 + good.sum()]
    vals[np.isnan(vals)] = np.nanpercentile(vals, 50) if np.isfinite(vals).any() else MAX_WALL
    return np.clip(vals, 1.2, MAX_WALL)

def calibrate(inv, theta, phi):
    """Iterative (scale, cam_h) fit + wall profile against the measured shell."""
    t0 = time.time()
    s = 4.8; cam_h = 1.05
    ceil_above = 1.72
    for it in range(3):
        D = inv * s
        wall_rho = measure_wall_profile(D, theta, phi)
        # refine cam_h from far steep-down projections (true floor, not furniture)
        fdown = D[phi < np.radians(-45)] * np.abs(np.sin(phi[phi < np.radians(-45)]))
        cam_h = float(np.clip(np.percentile(fdown, 96), 0.7, 1.9))
        fup = D[phi > np.radians(45)] * np.sin(phi[phi > np.radians(45)])
        ceil_above = float(np.clip(np.percentile(fup, 96), 1.2, 3.2))
        ceil_h = cam_h + ceil_above
        # 1-D scale search maximizing shell consistency
        band = np.abs(phi) < np.radians(30)
        best_s, best_sc = s, -1
        for s_try in np.linspace(3.0, 8.0, 51):
            st = shell_distance(None, None, None, cam_h, ceil_h, wall_rho, theta, phi)
            sc = np.mean(np.abs(s_try * inv[band] - st[band]) < 0.35)
            if sc > best_sc:
                best_s, best_sc = float(s_try), float(sc)
        s = best_s
        log(f"[calib it{it}] scale={s:.2f} cam_h={cam_h:.2f} ceil_h={ceil_h:.2f} "
            f"consistency={best_sc*100:.0f}% wall_rho[min/med/max]={wall_rho.min():.1f}/"
            f"{np.median(wall_rho):.1f}/{wall_rho.max():.1f}m")
    D = inv * s
    wall_rho = measure_wall_profile(D, theta, phi)
    ceil_h = cam_h + ceil_above
    METRICS["calibration"] = {"method": "iterative_measured_shell",
                              "scale": round(s, 3), "cam_h_m": round(cam_h, 3),
                              "ceil_h_m": round(ceil_h, 3),
                              "wall_rho_min_med_max": [round(float(wall_rho.min()), 2),
                                                       round(float(np.median(wall_rho)), 2),
                                                       round(float(wall_rho.max()), 2)]}
    METRICS["timings"]["calibrate_s"] = round(time.time() - t0, 2)
    return s, cam_h, ceil_h, wall_rho

def grid_mesh(mask, D, Px, Py, Pz, rgb, stride=2, name="mesh", back_cap=False):
    H, W = mask.shape
    ys, xs = np.mgrid[0:H:stride, 0:W:stride]
    idx = ys * W + xs
    keep = mask.reshape(-1)[idx] & np.isfinite(D.reshape(-1)[idx])
    if keep.sum() < 16: return None
    node_id = -np.ones_like(keep, dtype=np.int64)
    node_id[keep] = np.arange(keep.sum())
    vx = Px.reshape(-1)[idx][keep]; vy = Py.reshape(-1)[idx][keep]; vz = Pz.reshape(-1)[idx][keep]
    vcol = rgb.reshape(-1, 3)[idx][keep]
    dvals = D.reshape(-1)[idx][keep]
    gh, gw = keep.shape
    ii, jj = np.mgrid[0:gh - 1, 0:gw - 1]
    A = node_id[ii, jj]; B = node_id[ii, jj + 1]; C = node_id[ii + 1, jj + 1]; DQ = node_id[ii + 1, jj]
    okq = (A >= 0) & (B >= 0) & (C >= 0) & (DQ >= 0)
    dmin = np.minimum.reduce([dvals[A], dvals[B], dvals[C], dvals[DQ]])
    dmax = np.maximum.reduce([dvals[A], dvals[B], dvals[C], dvals[DQ]])
    okq &= (dmax - dmin) < np.maximum(0.20, 0.14 * dmin)
    okq &= (dvals[A] > 0.05)
    if okq.sum() < 2: return None
    aa, bb, cc, dd = A[okq], B[okq], C[okq], DQ[okq]
    faces = np.vstack([np.stack([aa, bb, cc], 1), np.stack([aa, cc, dd], 1)])
    verts = np.stack([vx, vy, vz], 1).astype(np.float32)
    colors = np.ascontiguousarray(vcol).astype(np.uint8)
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, vertex_colors=colors,
                           process=False, validate=False)
    if back_cap:
        try:
            open_e = trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)
            ring_idx = np.unique(mesh.edges[open_e].reshape(-1))
            if len(ring_idx) > 8:
                ring_pts = verts[ring_idx]
                cent = ring_pts.mean(0)
                radial = ring_pts - np.array([cent[0], 0.0, cent[2]])
                nrm = np.linalg.norm(radial, axis=1, keepdims=True)
                radial = radial / np.maximum(nrm, 1e-6)
                back_pts = ring_pts + radial * 0.22
                back_pts[:, 1] = np.clip(back_pts[:, 1], 0.02, None)
                base = len(verts)
                all_v = np.vstack([verts, back_pts])
                all_c = np.vstack([colors, colors[ring_idx]])
                n = len(ring_idx)
                cap_faces = []
                for i in range(n):
                    j = (i + 1) % n
                    cap_faces += [[ring_idx[i], ring_idx[j], base + j],
                                  [ring_idx[i], base + j, base + i]]
                fan = all_v.mean(0)
                all_v = np.vstack([all_v, fan[None]])
                all_c = np.vstack([all_c, all_c.mean(0)[None]])
                fc = len(all_v) - 1
                for i in range(n):
                    j = (i + 1) % n
                    cap_faces.append([base + i, fc, base + j])
                mesh = trimesh.Trimesh(vertices=all_v, faces=np.vstack([faces, cap_faces]),
                                       vertex_colors=all_c.astype(np.uint8),
                                       process=False, validate=False)
        except Exception as ex:
            log(f"  [cap] {name} skipped: {ex}")
    mesh.metadata["name"] = name
    return mesh

def splat_render(points, colors, cam_pos, yaw_deg, fov_deg=70, out_w=960, out_h=720):
    t0 = time.time()
    pts = points - np.asarray(cam_pos, np.float64)
    yaw = np.radians(yaw_deg)
    f = np.array([np.cos(yaw), 0, np.sin(yaw)])
    r = np.array([-np.sin(yaw), 0, np.cos(yaw)])
    up = np.array([0, 1, 0])
    zc = pts @ f; xc = pts @ r; yc = pts @ up
    vis = zc > 0.05
    zc, xc, yc, col = zc[vis], xc[vis], yc[vis], colors[vis]
    fl = (out_w / 2) / np.tan(np.radians(fov_deg) / 2)
    px = np.round(out_w / 2 - xc / zc * fl).astype(np.int64)
    py = np.round(out_h / 2 - yc / zc * fl).astype(np.int64)
    inb = (px >= 0) & (px < out_w - 1) & (py >= 0) & (py < out_h - 1)
    px, py, zc, col = px[inb], py[inb], zc[inb], col[inb]
    img = np.zeros((out_h, out_w, 3), np.uint8)
    zbuf = np.full(out_h * out_w, np.inf)
    order = np.argsort(zc)
    px, py, zc, col = px[order], py[order], zc[order], col[order]
    # 2x2 splats for dense coverage
    flats = []
    for ox, oy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        flats.append((py + oy) * out_w + (px + ox))
    for flat in flats:
        np.minimum.at(zbuf, flat, zc)
    for flat in flats:
        win = zbuf[flat] <= zc + 1e-9
        imgv = img.reshape(-1, 3)
        imgv[flat[win]] = col[win]
    holes = (img.sum(2) == 0).astype(np.uint8)
    if holes.any():
        holes = cv2.dilate(holes, np.ones((5, 5), np.uint8))
        img = cv2.inpaint(img, holes, 5, cv2.INPAINT_TELEA)
    return img, round(time.time() - t0, 2)

def pano_crop(pano, yaw_deg, fov_deg=70, out_w=960, out_h=720):
    H, W = pano.shape[:2]
    shift = int(((yaw_deg / 360.0) % 1.0) * W)
    rolled = np.roll(pano, W // 2 - shift, axis=1)
    f = (out_w / 2) / np.tan(np.radians(fov_deg) / 2)
    cx, cy = out_w / 2, out_h / 2
    xs, ys = np.meshgrid(np.arange(out_w), np.arange(out_h))
    xnd = -(xs - cx) / f; ynd = -(ys - cy) / f
    zc = np.ones_like(xnd)
    dirs = np.stack([xnd, ynd, zc], -1).reshape(-1, 3)
    x, y, z = dirs[:, 0], dirs[:, 1], dirs[:, 2]
    theta = np.arctan2(z, x)
    phi = np.arcsin(np.clip(y / np.linalg.norm(dirs, axis=1), -1, 1))
    u = ((((theta + np.pi / 2) / (2 * np.pi)) % 1.0) * W).reshape(out_h, out_w)
    v = ((0.5 - phi / np.pi) * H).reshape(out_h, out_w)
    return cv2.remap(rolled, u.astype(np.float32), v.astype(np.float32),
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

def main():
    t_start = time.time()
    pano = cv2.imread(PANO_HALF)
    raw = np.load(DEPTH_NPY).astype(np.float64)
    H, W = raw.shape
    inv = 1.0 / np.maximum(cv2.medianBlur(raw.astype(np.float32), 5).astype(np.float64), 1e-3)
    inv = cv2.medianBlur(inv.astype(np.float32), 5).astype(np.float64)
    dx, dy, dz, phi, theta = equirect_dirs(H, W)

    s, cam_h, ceil_h, wall_rho = calibrate(inv, theta, phi)
    D = inv * s
    X = D * dx; Y = D * dy + cam_h; Z = D * dz
    cam = np.array([0.0, cam_h, 0.0])

    shell_t = shell_distance(dx, dy, dz, cam_h, ceil_h, wall_rho, theta, phi)
    horiz = np.abs(phi) < np.radians(12)
    log(f"[debug] horizon: d_med={np.median(D[horiz]):.2f}m shell_med={np.median(shell_t[horiz]):.2f}m")

    t0 = time.time()
    furniture_mask = (D < shell_t - FURNITURE_MARGIN) & np.isfinite(shell_t) & (D > 0.15)
    furniture_mask &= (Y > 0.03) & (Y < ceil_h - 0.10)
    fm = cv2.morphologyEx(furniture_mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    fm = cv2.morphologyEx(fm, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    furniture_mask = fm.astype(bool)
    METRICS["timings"]["separate_s"] = round(time.time() - t0, 2)
    log(f"[separate] furniture px={furniture_mask.sum()} ({100.0*furniture_mask.mean():.1f}%)")

    t0 = time.time()
    fm_small = cv2.resize(fm, (W // 2, H // 2), interpolation=cv2.INTER_NEAREST)
    n_lbl, lbl = cv2.connectedComponents(fm_small, connectivity=8)
    lbl_full = cv2.resize(lbl, (W, H), interpolation=cv2.INTER_NEAREST)
    comps = []
    for k in range(1, n_lbl):
        m_small = lbl == k
        if m_small.sum() < 300: continue
        m = lbl_full == k
        yy = Y[m]
        if yy.max() - yy.min() > 2.0: continue
        fx, fz = X[m], Z[m]
        if (fx.max() - fx.min()) > 3.4 or (fz.max() - fz.min()) > 3.4: continue
        comps.append(m)
    METRICS["timings"]["components_s"] = round(time.time() - t0, 2)
    log(f"[components] kept {len(comps)}/{n_lbl-1}")

    t0 = time.time()
    m_dil = cv2.dilate(fm, np.ones((11, 11), np.uint8), iterations=2)
    tex = cv2.inpaint(pano, m_dil, 7, cv2.INPAINT_TELEA)
    METRICS["timings"]["inpaint_s"] = round(time.time() - t0, 2)

    SX = cam[0] + shell_t * dx; SY = cam[1] + shell_t * dy; SZ = cam[2] + shell_t * dz
    rgb_tex = cv2.cvtColor(tex, cv2.COLOR_BGR2RGB)
    rgb_pano = cv2.cvtColor(pano, cv2.COLOR_BGR2RGB)

    t0 = time.time()
    scene = trimesh.Scene()
    shell_mesh = grid_mesh(np.ones_like(fm, bool) & np.isfinite(shell_t), shell_t,
                           SX, SY, SZ, rgb_tex, stride=2, name="room_shell")
    scene.add_geometry(shell_mesh, node_name="room_shell")
    METRICS["files"]["shell_tris"] = int(len(shell_mesh.faces))
    for i, m in enumerate(comps):
        name = f"furniture_{i:02d}"
        mesh = grid_mesh(m, D, X, Y, Z, rgb_pano, stride=1, name=name, back_cap=True)
        if mesh is None or len(mesh.faces) < 8: continue
        scene.add_geometry(mesh, node_name=name)
        ptsx, ptsz, ptsy = X[m], Z[m], Y[m]
        low = ptsy < 1.0
        if low.sum() > 30: ptsx, ptsz = ptsx[low], ptsz[low]
        cx, cz = float(np.mean(ptsx)), float(np.mean(ptsz))
        rad = float(max(np.percentile(np.hypot(ptsx - cx, ptsz - cz), 90), 0.25))
        METRICS["colliders"].append({"id": name, "x": round(cx, 2), "z": round(cz, 2),
                                     "radius_m": round(rad, 2), "type": "cylinder"})
        METRICS["furniture"].append({"name": name, "tris": int(len(mesh.faces)),
                                     "center_xz": [round(cx, 2), round(cz, 2)],
                                     "radius_m": round(rad, 2),
                                     "y_extent_m": [round(float(Y[m].min()), 2),
                                                    round(float(Y[m].max()), 2)],
                                     "distance_m": round(float(np.median(D[m])), 2)})
    scene.export(GLB_PATH)
    METRICS["files"]["glb_bytes"] = os.path.getsize(GLB_PATH)
    METRICS["timings"]["meshing_s"] = round(time.time() - t0, 2)
    log(f"[glb] {METRICS['files']['glb_bytes']/1e6:.1f}MB shell={METRICS['files']['shell_tris']}tris "
        f"+ {len(METRICS['colliders'])} furniture")
    for c in METRICS["colliders"]: log(f"  collider {c}")

    # ---- renders
    t0 = time.time()
    sel = np.isfinite(D.reshape(-1)) & (shell_t.reshape(-1) < 1e6)
    # dense cloud: stride 1 over the half-res grid (2M pts) for smooth splat renders
    dirf = np.stack([dx.reshape(-1)[sel], dy.reshape(-1)[sel], dz.reshape(-1)[sel]], 1)
    Dv = D.reshape(-1)[sel]; shellv = shell_t.reshape(-1)[sel]
    fmask = furniture_mask.reshape(-1)[sel]
    lay_P = cam[None, :] + dirf * np.where(fmask[:, None], Dv[:, None], shellv[:, None])
    lay_C = np.where(fmask[:, None], rgb_pano.reshape(-1, 3)[sel], rgb_tex.reshape(-1, 3)[sel])
    nai_P = cam[None, :] + dirf * shellv[:, None]
    nai_C = rgb_pano.reshape(-1, 3)[sel]

    yaw_sofa = 0.01 * 360.0
    yaw_rad = np.radians(yaw_sofa)
    fwd = np.array([np.cos(yaw_rad), 0, np.sin(yaw_rad)])
    right = np.array([-np.sin(yaw_rad), 0, np.cos(yaw_rad)])
    origin_pos = [0.0, cam_h, 0.0]
    off_pos = [float(right[0] * 1.3 - fwd[0] * 0.8), cam_h, float(right[2] * 1.3 - fwd[2] * 0.8)]
    # keep the sofa cluster in view: yaw from off_pos toward furniture centroid
    if METRICS["colliders"]:
        fx0 = np.mean([c["x"] for c in METRICS["colliders"]])
        fz0 = np.mean([c["z"] for c in METRICS["colliders"]])
        yaw_off = np.degrees(np.arctan2(fz0 - off_pos[2], fx0 - off_pos[0]))
        # choose the LARGEST collider (the seating cluster)
        big = max(METRICS["colliders"], key=lambda c: c["radius_m"])
        yaw_off = np.degrees(np.arctan2(big["z"] - off_pos[2], big["x"] - off_pos[0]))
    else:
        yaw_off = yaw_sofa

    cv2.imwrite(f"{OUT}/render_pano_reference.png", pano_crop(pano, yaw_sofa, 70))
    for k, (P, C, pos, yw) in {
        "origin_layered": (lay_P, lay_C, origin_pos, yaw_sofa),
        "offset_naive":   (nai_P, nai_C, off_pos, yaw_off),
        "offset_layered": (lay_P, lay_C, off_pos, yaw_off),
    }.items():
        img, dt = splat_render(P, C, pos, yw, 70)
        cv2.imwrite(f"{OUT}/render_{k}.png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        log(f"[render] {k} {dt}s yaw={yw:.1f} pos=({pos[0]:.1f},{pos[2]:.1f})")
    METRICS["timings"]["renders_s"] = round(time.time() - t0, 2)
    METRICS["timings"]["total_s"] = round(time.time() - t_start, 1)
    with open(f"{OUT}/layered_metrics.json", "w") as f:
        json.dump(METRICS, f, indent=2)
    log(f"[done] total {METRICS['timings']['total_s']}s")

if __name__ == "__main__":
    main()
