#!/usr/bin/env python3
# ============================================================================
# ⛔ STAGE 1.6.1 QUARANTINE NOTICE (owner live-site audit, 2026-11-02) ⛔
# The outputs of this converter are BANNED FROM PRODUCTION:
#   · depth-cut furniture GLBs (edge tearing + back-caps) exploded into
#     spiky shards / saw-tooth skirts on the live iPhone build (cabin,
#     anniversary_lounge);
#   · the 122px Telea parallax-guard shells left huge blurry smudges on
#     the 4K walls.
# DO NOT RUN against the production DB/assets.  Superseded by:
#   skills/stage161_dome_relief.py  (smooth σ=18px radial relief fields)
#   + public/js/room.js buildDomeGeometry (watertight relief dome).
# Kept for history/R&D only.
# ============================================================================
"""
PANODROME — skill_360_to_walkable_3d.py  (STAGE 1.6 PRODUCTION SKILL)
====================================================================
Converts each curated 360 equirect panorama into a TRUE walkable 3D
two-layer scene (owner-approved architecture, 2026-11-02):

  LAYER 1 — Clean inpainted room shell texture (shell_inpainted)
  LAYER 2 — Independent 3D furniture meshes (.glb) at true metric (x,y,z)
  LAYER 3 — Exact physics colliders in data/rooms_db.json (walk.obstacles)

Owner decisions implemented (see MEMORY_STATE active_decisions):
  D1  Hybrid layered architecture: furniture = pixels with
      depth < measured_shell - 0.30 m become standalone volumetric meshes
      (depth-discontinuity edge tearing + radial back-caps); the shell
      behind them is inpainted so ZERO furniture stays painted flat.
  D2  WEBGL SIZE LAW: shell texture + furniture GLB < 2.5 MB per room —
      adaptive grid stride (low-poly far from silhouette detail is fine,
      full density only where the depth surface bends), UV-mapped JPEG
      textures (not vertex colors), compact custom binary GLB
      (no normals — KHR_materials_unlit photo materials), quality ladder
      until the numeric budget holds.
  D3  Inpainting: furniture mask dilated 12 px (full-res) BEFORE filling;
      multi-scale Telea (1/4 scale structure pass) + Navier-Stokes
      (full-res boundary band) + directional floor/wall texture
      continuation (per-column vertical fill in the floor band, matching
      the radial nadir projection) + median seam cleanup.
  D4  Edge-preserving Guided filter (cv2.ximgproc.guidedFilter, RGB pano
      as guide) applied to the INVERTED DAV2 depth BEFORE furniture
      masks are cut — crisp silhouettes, no halos. Fallback: bilateral.
  D5  --ai-objects (Hunyuan3D-2 HF Space) is an OPTIONAL flag for hero
      pieces; the fast local layered-depth mesh is the reliable DEFAULT.

PERMANENT LAW (R&D, doc 12): DAV2 ONNX raw output is DISPARITY — invert
(1/x) first, always. Scale is fitted per room by the measured-shell
method (per-azimuth wall profile + floor/ceiling planes + 1-D search).

Usage:
  python3 skills/skill_360_to_walkable_3d.py --rooms anniversary_lounge
  python3 skills/skill_360_to_walkable_3d.py --all [--force] [--dry-run]
  python3 skills/skill_360_to_walkable_3d.py --all --ai-objects   # D5, optional

Outputs per CONVERTED room (SKIPPED rooms keep their Stage-1.5 setup):
  public/assets/shells/<id>.jpg          inpainted equirect shell texture
  public/assets/furniture/<id>.glb       compact furniture layer (unlit GLB)
  data/rooms_db.json + public/data/rooms_db.json  (shell_texture, furniture,
      measured, walk.obstacles auto-colliders, refined camera.y)
  docs/rd-artifacts/stage16_convert_report.json   (per-room QA report)

Caches: assets/depth/<id>_disp.npy (raw disparity, half-res — git-ignored,
regenerable in ~20 s). Rerun without --force skips rooms whose outputs
already exist and whose DB entry is up to date.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import struct
import sys
import time
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "data" / "rooms_db.json"
DB_PUBLIC = REPO / "public" / "data" / "rooms_db.json"
SHELL_DIR = REPO / "public" / "assets" / "shells"
FURN_DIR = REPO / "public" / "assets" / "furniture"
DISP_DIR = REPO / "assets" / "depth"
REPORT_PATH = REPO / "docs" / "rd-artifacts" / "stage16_convert_report.json"
DAV2_ONNX = os.environ.get("PANODROME_DAV2_ONNX", "/tmp/rd/models/hf/onnx/model.onnx")

# ---- budgets (D2) ----------------------------------------------------------
TOTAL_BUDGET_KB = 2500          # shell texture + furniture GLB together
GLB_BUDGET_KB = 900             # furniture layer alone
SHELL_TARGET_LONG_EDGE = 4096   # start at full 4K, ladder down if needed

# ---- pipeline constants (owner-approved) -----------------------------------
FURNITURE_MARGIN_M = 0.30       # D1: depth < shell - 0.30
DILATE_PX = 12                  # D3: mask dilation at full res
BACK_CAP_M = 0.22               # radial back-cap extrusion
FURN_MAX_DIST_M = 8.0           # nothing furniture-like beyond this
COMP_MIN_PX_HALF = 300          # component size at half-res grid
COMP_MAX_SPAN_M = 2.2           # y span
COMP_MAX_FOOTPRINT_M = 3.4      # per-axis footprint
TARGET_QUADS = 12000            # adaptive stride target per component
GUIDED_RADIUS = 8               # D4 guided filter radius (half-res px)

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

LABELS = {  # fallback names if the router is unavailable
    "default": {"en": "Furniture", "fa": "مبلمان"},
}


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------- #
# Depth (DAV2-small ONNX) — raw output is DISPARITY, invert FIRST (permanent law)
# --------------------------------------------------------------------------- #
def run_depth(pano_bgr_full: np.ndarray) -> np.ndarray:
    """Half-res disparity (H2, W2) — cached as assets/depth/<id>_disp.npy."""
    H, W = pano_bgr_full.shape[:2]
    H2, W2 = H // 2, W // 2
    cache = DISP_DIR / "disp_cache" / f"{ROOM_ID}_disp.npy"
    if cache.is_file() and not FORCE:
        d = np.load(cache)
        if d.shape == (H2, W2):
            log("  [depth] cache hit")
            return d.astype(np.float32)
    import onnxruntime as ort

    def to_multiple(x, m=14):
        return max(m, int(round(x / m)) * m)

    tw, th = to_multiple(W / 2), to_multiple(H / 2)  # 2044 x 1036
    rgb = cv2.cvtColor(pano_bgr_full, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    resized = cv2.resize(rgb, (tw, th), interpolation=cv2.INTER_AREA)
    x = (resized - IMAGENET_MEAN) / IMAGENET_STD
    x = np.transpose(x, (2, 0, 1))[None].astype(np.float32)
    so = ort.SessionOptions()
    so.intra_op_num_threads = 2
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(DAV2_ONNX, so, providers=["CPUExecutionProvider"])
    t0 = time.time()
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0]
    log(f"  [depth] DAV2-small {tw}x{th} in {time.time()-t0:.1f}s (raw = disparity)")
    d = out[0].astype(np.float32)
    if d.shape != (th, tw):
        d = cv2.resize(d, (tw, th), interpolation=cv2.INTER_CUBIC)
    disp = cv2.resize(d, (W2, H2), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, disp)
    return disp


# --------------------------------------------------------------------------- #
# D4 — edge-preserving inverse depth (guided filter with the RGB pano as guide)
# --------------------------------------------------------------------------- #
def guided_inverse_depth(disp: np.ndarray, rgb_half: np.ndarray):
    """Returns (inv_raw, inv_guided). Calibration uses inv_raw (robust, R&D-proven);
    furniture masks/meshes use inv_guided (D4 edge-aligned silhouettes)."""
    t0 = time.time()
    d = cv2.medianBlur(disp, 5)
    inv = 1.0 / np.maximum(d.astype(np.float64), 1e-3)
    inv_raw = cv2.medianBlur(inv.astype(np.float32), 5).astype(np.float64)
    inv = inv_raw
    try:
        from cv2 import ximgproc  # opencv-contrib

        guide = cv2.GaussianBlur(rgb_half, (5, 5), 0).astype(np.float32) / 255.0
        inv = ximgproc.guidedFilter(
            guide=guide, src=inv.astype(np.float32),
            radius=GUIDED_RADIUS, eps=1e-3,   # [0,1]-scaled guide: mild edge-align
        ).astype(np.float64)
        method = "guidedFilter(r=8, eps=1e-3, float RGB guide)"
    except Exception as exc:  # fallback: plain bilateral (still edge-preserving)
        inv = cv2.bilateralFilter(inv.astype(np.float32), 9, 0.05, 9).astype(np.float64)
        method = f"bilateral fallback ({exc.__class__.__name__})"
    inv_guided = cv2.medianBlur(inv.astype(np.float32), 3).astype(np.float64)
    log(f"  [D4 edge-align] {method} in {time.time()-t0:.1f}s")
    return inv_raw, inv_guided


# --------------------------------------------------------------------------- #
# Equirect geometry + measured-shell calibration (from the R&D prototype)
# --------------------------------------------------------------------------- #
def equirect_dirs(H, W):
    """Equirect pixel -> unit ray, in the SAME convention as room.js:
    u = atan2(d.z, -d.x) / 2pi  (u=0 faces -x, u=0.25 faces +z, u=0.5 +x)."""
    u = np.arange(W, dtype=np.float64) / W * 2 * np.pi
    v = np.arange(H, dtype=np.float64) / H
    phi = np.broadcast_to((0.5 - v[:, None]) * np.pi, (H, W)).copy()
    theta = np.broadcast_to(u[None, :], (H, W)).copy()
    cp, sp = np.cos(phi), np.sin(phi)
    return -cp * np.cos(theta), sp, cp * np.sin(theta), phi, theta


class ShellModel:
    def __init__(self, n_az=144):
        self.n_az = n_az

    def distance(self, cam_h, ceil_h, wall_rho, theta, phi):
        with np.errstate(divide="ignore", invalid="ignore"):
            cos_phi = np.sqrt(np.maximum(1 - np.sin(phi) ** 2, 1e-12))
            bins = (np.floor(theta / (2 * np.pi) * self.n_az).astype(int)) % self.n_az
            t_wall = wall_rho[bins] / cos_phi
            t_floor = np.where(-np.sin(phi) > 1e-3,
                               cam_h / np.maximum(-np.sin(phi), 1e-3), np.inf)
            t_ceil = np.where(np.sin(phi) > 1e-3,
                              (ceil_h - cam_h) / np.maximum(np.sin(phi), 1e-3), np.inf)
        t = np.fmin(np.fmin(t_wall, t_floor), t_ceil)
        return np.where(np.isfinite(t) & (t > 0.05), t, np.inf)

    def wall_profile(self, D, theta, phi, max_wall):
        n = self.n_az
        band = (np.abs(phi) > np.radians(4)) & (np.abs(phi) < np.radians(25))
        prof = np.full(n, np.nan)
        for b in range(n):
            lo, hi = b / n * 2 * np.pi, (b + 1) / n * 2 * np.pi
            m = band & (theta >= lo) & (theta < hi)
            if m.sum() > 30:
                prof[b] = min(np.percentile(D[m], 88), max_wall)
        vals = prof.copy()
        good = ~np.isnan(vals)
        if good.sum() > 10:
            pad = np.r_[vals[good][-3:], vals[good], vals[good][:3]]
            ker = np.ones(7) / 7
            vals[good] = np.convolve(pad, ker, mode="same")[3:3 + good.sum()]
        if np.isfinite(vals).any():
            vals[np.isnan(vals)] = float(np.nanpercentile(vals, 50))
        else:
            vals[:] = max_wall
        return np.clip(vals, 1.2, max_wall)


def _calibrate_once(inv, theta, phi, room_shape, s0, cam_h0, ceil0, s_lo, s_hi):
    """One iterative (scale, cam_h, ceil) run — returns (s, cam_h, ceil_h, wall_rho, sc).
    NOTE: shell_distance is s_try-INDEPENDENT (depends only on cam_h/ceil/wall_rho)
    — hoisted out of the 1-D search (the R&D recomputed it 51x per iteration)."""
    sh = ShellModel()
    h = room_shape["height"]
    max_wall = float(np.clip(max(room_shape["width"], room_shape["depth"], h) * 1.6, 6.0, 25.0))
    s, cam_h, ceil_above = s0, cam_h0, ceil0
    band = np.abs(phi) < np.radians(30)      # R&D-proven horizon band (walls)
    inv_band = inv[band]
    s_grid = np.linspace(s_lo, s_hi, 81)
    consistency = 0.0
    for _it in range(3):
        D = inv * s
        wall_rho = sh.wall_profile(D, theta, phi, max_wall)
        down = D[phi < np.radians(-45)] * np.abs(np.sin(phi[phi < np.radians(-45)]))
        cam_h = float(np.clip(np.percentile(down, 96), 0.7, 1.9)) if down.size else cam_h
        up = D[phi > np.radians(45)] * np.sin(phi[phi > np.radians(45)])
        ceil_above = (float(np.clip(np.percentile(up, 96), max(1.2, h * 0.3),
                                    min(h * 1.05, 4.5))) if up.size else ceil_above)
        ceil_h = cam_h + ceil_above
        st = sh.distance(cam_h, ceil_h, wall_rho, theta, phi)
        st_band = st[band]
        best_s, best_sc = s, -1.0
        for s_try in s_grid:
            sc = np.mean(np.abs(s_try * inv_band - st_band) < 0.35)
            if sc > best_sc:
                best_s, best_sc = float(s_try), float(sc)
        s, consistency = best_s, best_sc
    D = inv * s
    wall_rho = sh.wall_profile(D, theta, phi, max_wall)
    return s, cam_h, cam_h + ceil_above, wall_rho, consistency


def box_shell_distance(dx, dy, dz, cam, hw, hd, h):
    """Ray distance to the AUTHORED room box surface, from the camera inside it.
    This is the shell the runtime actually renders — open-plan directions are
    clamped at the box walls so distant open-space content is never mistaken
    for furniture."""
    with np.errstate(divide="ignore", invalid="ignore"):
        tx = np.where(dx > 1e-6, (hw - cam[0]) / dx,
                      np.where(dx < -1e-6, (-hw - cam[0]) / dx, np.inf))
        ty = np.where(dy > 1e-6, (h - cam[1]) / dy,
                      np.where(dy < -1e-6, (0.0 - cam[1]) / dy, np.inf))
        tz = np.where(dz > 1e-6, (hd - cam[2]) / dz,
                      np.where(dz < -1e-6, (-hd - cam[2]) / dz, np.inf))
    t = np.minimum(np.minimum(tx, ty), tz)
    return np.where(np.isfinite(t) & (t > 0.05), t, np.inf)


def calibrate(inv, theta, phi, room_shape, camera=(0.0, 0.0)):
    """Multi-start measured-shell fit, arbitrated by physical plausibility AND
    fit to the AUTHORED room box (the geometric SSOT): the winning scale puts
    the measured walls at the box half-dims and the ceiling under the box
    height, so furniture islands land INSIDE the Stage-1.5 room volume."""
    w, d, h = room_shape["width"], room_shape["depth"], room_shape["height"]
    horizon = np.abs(phi) < np.radians(30)
    s_db = float(np.clip((min(w, d) / 2) / max(np.median(inv[horizon]), 1e-3), 1.0, 20.0))
    best = None
    s_lo = max(0.8, s_db * 0.30)             # wide range like the R&D 3.0–8.0
    s_hi = s_db * 2.60
    hw, hd = w / 2.0, d / 2.0
    exp_min_wall = max(min(hw - abs(camera[0]), hd - abs(camera[1])), 0.6)
    for s0_mult in (0.6, 1.0, 1.5):
        for cam_h0 in (1.05, 1.6):
            r = _calibrate_once(inv, theta, phi, room_shape,
                                float(np.clip(s_db * s0_mult, 1.2, 16.0)), cam_h0,
                                min(h * 0.6, 2.0), s_lo, s_hi)
            sc = r[4]
            # physical-plausibility penalties: a "shell wrapped around the
            # furniture" optimum scores high on consistency but is nonsense
            if r[1] <= 0.72 or r[1] >= 1.88:      # cam_h pinned at a clip bound
                sc -= 0.15
            if r[2] < 0.80 * h:                   # ceiling way under the DB room
                sc -= 0.06
            # BOX-FIT (decisive for the two-layer scene): the winning scale
            # must land the measured walls near the authored box half-dims and
            # keep the ceiling under the authored height — else furniture
            # islands poke through the Stage-1.5 room volume.
            box_wall_err = abs(float(r[3].min()) - exp_min_wall) / exp_min_wall
            sc -= 0.35 * box_wall_err
            if r[2] > h * 1.06:                   # ceiling pokes through the box
                sc -= 0.12
            if best is None or sc > best[5]:
                best = (r[0], r[1], r[2], r[3], r[4], sc)
    s, cam_h, ceil_h, wall_rho, consistency = best[0], best[1], best[2], best[3], best[4]
    med = {"scale": round(s, 3), "cam_h_m": round(cam_h, 3), "ceil_h_m": round(ceil_h, 3),
           "consistency": round(consistency, 3),
           "box_min_wall_expected_m": round(exp_min_wall, 2),
           "wall_rho_min_med_max": [round(float(wall_rho.min()), 2),
                                    round(float(np.median(wall_rho)), 2),
                                    round(float(wall_rho.max()), 2)],
           "method": "dav2-small + guided edge-align + multi-start measured shell v1.6"}
    return s, cam_h, ceil_h, wall_rho, med


# --------------------------------------------------------------------------- #
# D1 — furniture separation
# --------------------------------------------------------------------------- #
def separate_furniture(D, shell_t, Y, ceil_h, X, Z):
    H2, W2 = D.shape
    rows = (np.arange(H2) / H2 - 0.5) * np.pi          # phi per row
    keep_rows = np.abs(rows) < np.radians(75)          # drop nadir/zenith cones
    row_ok = np.broadcast_to(keep_rows[:, None], (H2, W2))
    mask = (D < shell_t - FURNITURE_MARGIN_M) & np.isfinite(shell_t) & (D > 0.15)
    mask &= (D < FURN_MAX_DIST_M)
    mask &= (Y > 0.03) & (Y < ceil_h - 0.10)
    mask &= row_ok
    fm = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    fm = cv2.morphologyEx(fm, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    H2, W2 = fm.shape
    fm_small = cv2.resize(fm, (W2 // 2, H2 // 2), interpolation=cv2.INTER_NEAREST)
    n_lbl, lbl = cv2.connectedComponents(fm_small, connectivity=8)
    lbl_full = cv2.resize(lbl, (W2, H2), interpolation=cv2.INTER_NEAREST)
    rows = (np.arange(H2) / H2 - 0.5) * np.pi
    row_ok = np.broadcast_to((np.abs(rows) < np.radians(75))[:, None], (H2, W2))
    # D1 halo band: ANY foreground (≥5 cm in front of the shell) — used to grow
    # the confident core (−0.30 m) into wall-hugging sofa backs etc.
    halo = ((D < shell_t - 0.05) & np.isfinite(shell_t) & (D > 0.15)
            & (Y > 0.03) & (Y < ceil_h - 0.10) & row_ok).astype(np.uint8)
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    comps = []
    for k in range(1, n_lbl):
        if (lbl == k).sum() < COMP_MIN_PX_HALF // 2:
            continue
        m = lbl_full == k
        yy = Y[m]
        if yy.max() - yy.min() > COMP_MAX_SPAN_M:
            continue
        fx, fz = X[m], Z[m]
        if (fx.max() - fx.min()) > COMP_MAX_FOOTPRINT_M or (fz.max() - fz.min()) > COMP_MAX_FOOTPRINT_M:
            continue
        # halo-grow: bounded dilation ∩ foreground band (≤10 rounds ≈ 40 cm)
        grown = m.astype(np.uint8)
        for _ in range(10):
            add = ((cv2.dilate(grown, kern) > 0) & (halo > 0) & (grown == 0))
            if add.sum() < 40:
                break
            grown = grown | add.astype(np.uint8)
        grown = grown.astype(bool)
        # FLOOR-STANDING LAW: only furniture with real mass below 1.2 m becomes
        # a 3D volume (sofas, beds, tables, pianos). Hanging pieces (chandeliers,
        # wall art — zero low mass) stay painted on the shell: they are flat or
        # above the player anyway, and they are the riskiest mesh blobs.
        if (Y[grown] < 1.2).sum() < 0.25 * grown.sum():
            continue
        # FLAT-SLAB LAW: near-floor slabs (carpets, thresholds — y span < 18 cm)
        # and wall-flat panels (doors, boards — radial spread < 12 cm) are NOT
        # volumetric furniture; they stay painted on the shell.
        gy = Y[grown]
        if gy.max() - gy.min() < 0.18:
            continue
        gx, gz = X[grown], Z[grown]
        rad = np.hypot(gx - gx.mean(), gz - gz.mean())
        if float(np.percentile(rad, 95)) < 0.12:
            continue
        comps.append(grown)
    return fm.astype(bool), comps


# --------------------------------------------------------------------------- #
# D3 — multi-scale inpainting with directional floor continuation
# --------------------------------------------------------------------------- #
def _mirror_tile(strip, n, axis=0):
    """Tile a source strip along `axis` to length n with alternating mirror flips."""
    if strip.shape[axis] == 0:
        return None
    parts, flip, total = [], False, 0
    while total < n:
        parts.append(np.flip(strip, axis) if flip else strip)
        flip = not flip
        total += strip.shape[axis]
    cat = np.concatenate(parts, axis=axis)
    sl = [slice(None)] * cat.ndim
    sl[axis] = slice(n)
    return cat[tuple(sl)]


def inpaint_shell(pano_bgr_full, mask_half, dilate_px=DILATE_PX, floor_bg_half=None):
    """D3 — fringe dilation (12 px, owner spec) + PARALLAX GUARD BAND, then
    DIRECTIONAL TEXTURE CONTINUATION: floor holes fill with mirror-tiled
    crossfaded vertical strips (nadir projection = floor texture runs
    vertically); walls go to structure-aware Telea (tiling would duplicate
    windows/paintings); leftovers to coarse Telea (1/2) + NS band + median.

    The parallax guard is geometrically REQUIRED by the two-layer scene:
    the shell projects the pano from the CAPTURE point, so walking ~1.5 m
    sideways reveals painted furniture BESIDE the 3D mesh (double image)
    unless a band of background around each piece is erased and inpainted.
    Guard width ≈ t_walk · (1/d_obj − 1/d_bg) in radians ≈ 60–110 px here.
    """
    t0 = time.time()
    H, W = pano_bgr_full.shape[:2]
    m = cv2.resize(mask_half.astype(np.uint8) * 255, (W, H), interpolation=cv2.INTER_NEAREST)
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                     (2 * dilate_px + 1, 2 * dilate_px + 1))
    m = cv2.dilate(m, kern, 1)                     # D3 fringe + parallax guard
    hole = m > 0
    out = pano_bgr_full.copy()
    if floor_bg_half is not None:
        # exact per-pixel classification from the shell model: a hole pixel is
        # FLOOR background when the floor plane is the nearest shell surface
        floor_band = cv2.resize(floor_bg_half.astype(np.uint8), (W, H),
                                interpolation=cv2.INTER_NEAREST) > 0
    else:
        rows_idx = np.arange(H)
        floor_band = rows_idx > H * 0.64
    wall_band = ~floor_band
    filled = np.zeros_like(hole)

    # (1a) FLOOR: per-column mirror-tiled vertical strips from the nearest
    # clean floor above the hole run
    fl = hole & floor_band
    if fl.any():
        cols = np.where(fl.any(0))[0]
        for c in cols:
            rs = np.where(fl[:, c])[0]
            # split into runs
            runs, s = [], rs[0]
            for a, b in zip(rs, np.r_[rs[1:], -9]):
                if b != a + 1:
                    runs.append((s, a)); s = b
            for r0, r1 in runs:
                need = r1 - r0 + 1
                src_end = r0
                while src_end > 0 and (hole[src_end, c] or not floor_band[src_end, c]):
                    src_end -= 1
                strip_h = 0
                while (strip_h < 48 and src_end - strip_h - 1 >= 0
                       and not hole[src_end - strip_h - 1, c]
                       and floor_band[src_end - strip_h - 1, c]):
                    strip_h += 1
                strip_h = min(strip_h, need)
                # bottom source (below the hole run, clean floor)
                src_b = r1 + 1
                strip_b = 0
                while (strip_b < 48 and src_b + strip_b < H
                       and not hole[src_b + strip_b, c]
                       and floor_band[src_b + strip_b, c]):
                    strip_b += 1
                strip_b = min(strip_b, need)
                if strip_h >= 4:
                    top = _mirror_tile(out[src_end - strip_h:src_end, c].astype(np.float64), need)
                    if strip_b >= 4:   # crossfade top→bottom across the run
                        bot = _mirror_tile(out[src_b:src_b + strip_b, c].astype(np.float64), need)
                        wgt = (np.arange(need) + 0.5) / need
                        fill = top * (1 - wgt[:, None]) + bot * wgt[:, None]
                    else:
                        fill = top
                    out[r0:r1 + 1, c] = fill.astype(np.uint8)
                    filled[r0:r1 + 1, c] = True

    # (1b) WALLS: NO tiling — structured walls (windows, paintings, panels)
    # must not be mirror-tiled; wall holes go to the structure-aware Telea
    # pass below. (v1's horizontal tiling duplicated window frames.)
    wl = np.zeros_like(hole)          # walls → structure-aware Telea below
    if False and wl.any():
        rws = np.where(wl.any(1))[0]
        for r in rws:
            cs = np.where(wl[r])[0]
            runs, s = [], cs[0]
            for a, b in zip(cs, np.r_[cs[1:], -9]):
                if b != a + 1:
                    runs.append((s, a)); s = b
            for c0, c1 in runs:
                need = c1 - c0 + 1
                src_end = c0
                while src_end > 0 and (hole[r, src_end] or not wall_band[r]):
                    src_end -= 1
                strip_w = 0
                while (strip_w < 64 and src_end - strip_w - 1 >= 0
                       and not hole[r, src_end - strip_w - 1]):
                    strip_w += 1
                strip_w = min(strip_w, need)
                # right source (after the hole run, clean wall)
                src_r = c1 + 1
                strip_r = 0
                while (strip_r < 64 and src_r + strip_r < W
                       and not hole[r, src_r + strip_r]):
                    strip_r += 1
                strip_r = min(strip_r, need)
                if strip_w >= 4:
                    left = _mirror_tile(out[r, src_end - strip_w:src_end].astype(np.float64), need)
                    if strip_r >= 4:    # crossfade left→right across the run
                        right = _mirror_tile(out[r, src_r:src_r + strip_r].astype(np.float64), need)
                        wgt = (np.arange(need) + 0.5) / need
                        fill = left * (1 - wgt[:, None]) + right * wgt[:, None]
                    else:
                        fill = left
                    out[r, c0:c1 + 1] = fill.astype(np.uint8)
                    filled[r, c0:c1 + 1] = True

    # (2) leftovers: coarse Telea at 1/2 scale
    rest = hole & ~filled
    if rest.any():
        half = cv2.resize(out, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
        mhalf = cv2.resize((rest * 255).astype(np.uint8), (W // 2, H // 2),
                           interpolation=cv2.INTER_NEAREST)
        if mhalf.any():
            half = cv2.inpaint(half, mhalf, 9, cv2.INPAINT_TELEA)
            up = cv2.resize(half, (W, H), interpolation=cv2.INTER_LINEAR)
            out[rest] = up[rest]

    # (3) boundary refinement — full-res NS on a 10 px band around fills
    if filled.any():
        inner = cv2.erode(filled.astype(np.uint8), np.ones((11, 11), np.uint8)) > 0
        bandm = (filled & ~inner).astype(np.uint8) * 255
        if bandm.any():
            out = cv2.inpaint(out, bandm, 4, cv2.INPAINT_NS)

    # (4) seam cleanup — median only inside the filled region
    if (m > 0).any():
        med = cv2.medianBlur(out, 5)
        sel = m > 0
        out[sel] = med[sel]
    log(f"  [D3 inpaint] directional+Telea done in {time.time()-t0:.1f}s "
        f"({int((m>0).sum())} px of {H*W}, floor/wall strips covered "
        f"{int(filled.sum())})")
    return out


# --------------------------------------------------------------------------- #
# D2 — UV-mapped furniture mesh (adaptive stride, back-caps, edge tearing)
# --------------------------------------------------------------------------- #
def wrap_crop(img, x0, x1, y0, y1):
    """Crop with horizontal equirect wrap; vertical clamp."""
    H, W = img.shape[:2]
    y0, y1 = max(0, y0), min(H, y1)
    xw = x1 - x0
    if x0 >= 0 and x1 <= W:
        return img[y0:y1, x0:x1].copy(), x0
    rolled = np.roll(img, -x0, axis=1)
    x1r = xw if x1 - x0 <= W else W
    return rolled[y0:y1, 0:max(1, x1r)], x0


def build_uv_mesh(comp, D, X, Y, Z, cam_off, pano_full_rgb, stride):
    """Grid mesh over the component with UVs into a pano crop + back-caps."""
    H2, W2 = comp.shape
    ys, xs = np.mgrid[0:H2:stride, 0:W2:stride]
    keep = comp[ys, xs] & np.isfinite(D[ys, xs])
    if keep.sum() < 16:
        return None
    nid = -np.ones(keep.shape, dtype=np.int64)
    nid[keep] = np.arange(keep.sum())
    vx = X[ys, xs][keep] + cam_off[0]
    vy = Y[ys, xs][keep]
    vz = Z[ys, xs][keep] + cam_off[1]
    dv = D[ys, xs][keep]
    # full-res pixel coords → UV into the (later) crop box
    fx = (xs[keep].astype(np.float64) + 0.5) * 2.0
    fy = (ys[keep].astype(np.float64) + 0.5) * 2.0

    gh, gw = keep.shape
    ii, jj = np.mgrid[0:gh - 1, 0:gw - 1]
    A, B, C, DQ = nid[ii, jj], nid[ii, jj + 1], nid[ii + 1, jj + 1], nid[ii + 1, jj]
    okq = (A >= 0) & (B >= 0) & (C >= 0) & (DQ >= 0)
    dmin = np.minimum.reduce([dv[A], dv[B], dv[C], dv[DQ]])
    dmax = np.maximum.reduce([dv[A], dv[B], dv[C], dv[DQ]])
    okq &= (dmax - dmin) < np.maximum(0.20, 0.14 * dmin)     # edge tearing (D1)
    okq &= dmin > 0.05
    if okq.sum() < 2:
        return None
    aa, bb, cc, dd = A[okq], B[okq], C[okq], DQ[okq]
    faces = np.vstack([np.stack([aa, bb, cc], 1), np.stack([aa, cc, dd], 1)])
    verts = np.stack([vx, vy, vz], 1)
    uv_px = np.stack([fx, fy], 1)

    # ---- radial back-cap so the piece is a closed volume (D1) ----
    try:
        import trimesh
        tmp = trimesh.Trimesh(vertices=verts, faces=faces, process=False, validate=False)
        open_e = trimesh.grouping.group_rows(tmp.edges_sorted, require_count=1)
        ring_idx = np.unique(tmp.edges[open_e].reshape(-1))
        if len(ring_idx) > 8:
            ring_pts = verts[ring_idx]
            cent = ring_pts.mean(0)
            radial = ring_pts - np.array([cent[0], 0.0, cent[2]])
            nrm = np.linalg.norm(radial, axis=1, keepdims=True)
            radial = radial / np.maximum(nrm, 1e-6)
            back = ring_pts + radial * BACK_CAP_M
            back[:, 1] = np.clip(back[:, 1], 0.02, None)
            base = len(verts)
            verts = np.vstack([verts, back])
            uv_px = np.vstack([uv_px, uv_px[ring_idx]])
            n = len(ring_idx)
            caps = []
            for i in range(n):
                j = (i + 1) % n
                caps += [[ring_idx[i], ring_idx[j], base + j],
                         [ring_idx[i], base + j, base + i]]
            fan_uv = uv_px[ring_idx].mean(0)
            verts = np.vstack([verts, verts.mean(0)[None]])
            uv_px = np.vstack([uv_px, fan_uv[None]])
            fc = len(verts) - 1
            for i in range(n):
                j = (i + 1) % n
                caps.append([base + i, fc, base + j])
            faces = np.vstack([faces, np.array(caps)])
    except Exception as ex:
        log(f"    [cap] skipped: {ex}")

    # ---- ground the piece: floor-standing furniture rests EXACTLY at y=0
    # (any residual calibration scale error would otherwise hover/sink feet);
    # hanging pieces (chandeliers — bottom above 0.45 m) are left untouched.
    vy_min = float(np.percentile(verts[:, 1], 3))
    if verts[:, 1].min() < 0.45 and -0.15 < vy_min < 0.35:
        verts[:, 1] -= vy_min

    # ---- texture crop from the ORIGINAL pano (sharp, un-inpainted) ----
    H, W = pano_full_rgb.shape[:2]
    x0 = int(max(0, np.floor(uv_px[:, 0].min()) - 24))
    x1 = int(min(W, np.ceil(uv_px[:, 0].max()) + 24))
    y0 = int(max(0, np.floor(uv_px[:, 1].min()) - 24))
    y1 = int(min(H, np.ceil(uv_px[:, 1].max()) + 24))
    crop, crop_x0 = wrap_crop(pano_full_rgb, x0, x1, y0, y1)
    ch, cw = crop.shape[:2]
    uv = np.empty_like(uv_px)
    uv[:, 0] = (uv_px[:, 0] - crop_x0) / max(cw, 1)
    uv[:, 1] = (uv_px[:, 1] - y0) / max(ch, 1)
    return {"verts": verts.astype(np.float32), "faces": faces.astype(np.int64),
            "uv": np.clip(uv, 0, 1).astype(np.float32), "crop": crop,
            "tris": int(len(faces))}


def make_collider(comp, X, Y, Z, cam_off, label):
    """Floor-standing furniture → box/cylinder collider. Hanging pieces
    (chandeliers, pendant lamps — mass above 1.2 m) get NO collider: you
    walk under them."""
    pts_y = Y[comp]
    if (pts_y < 1.2).sum() < 30:
        return None
    low = pts_y < 1.0
    px = X[comp][low] + cam_off[0] if low.sum() > 30 else X[comp] + cam_off[0]
    pz = Z[comp][low] + cam_off[1] if low.sum() > 30 else Z[comp] + cam_off[1]
    cx, cz = float(np.mean(px)), float(np.mean(pz))
    ex = float(np.percentile(np.abs(px - cx), 92)) + 0.05
    ez = float(np.percentile(np.abs(pz - cz), 92)) + 0.05
    col = {"label": label, "x": round(cx, 2), "z": round(cz, 2)}
    if max(ex, ez) / max(min(ex, ez), 1e-3) > 1.8:
        col.update({"type": "box", "hw": round(ex, 2), "hd": round(ez, 2)})
    else:
        col.update({"type": "cylinder", "r": round(max(ex, ez), 2)})
    return col


# --------------------------------------------------------------------------- #
# D2 — compact custom GLB writer (JPEG textures, KHR_materials_unlit, no normals)
# --------------------------------------------------------------------------- #
def jpeg_bytes(bgr_img, quality):
    ok, buf = cv2.imencode(".jpg", bgr_img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else b""


def encode_items(items, quality):
    """items: [{name, built:{verts,faces,uv,crop|jpeg}}] → GLB payload (D2 ladder)."""
    payload = []
    for it in items:
        b = it["built"]
        if "jpeg" not in b:
            crop = b["crop"]
            ch, cw = crop.shape[:2]
            if max(ch, cw) > 1024:
                sc = 1024 / max(ch, cw)
                crop = cv2.resize(crop, (int(cw * sc), int(ch * sc)),
                                  interpolation=cv2.INTER_AREA)
            b = {**b, "jpeg": jpeg_bytes(crop[:, :, ::-1].copy(), quality)}
        payload.append({"name": it["name"], "verts": b["verts"],
                        "faces": b["faces"], "uv": b["uv"], "jpeg": b["jpeg"]})
    return payload


def export_glb(items):
    """items: [{name, verts(f32 Nx3), faces(Mx3), uv(f32 Nx2), jpeg(bytes)}] → glb bytes"""
    bin_parts, views, accessors = [], [], []
    images, textures, materials, meshes, nodes = [], [], [], [], []

    def add_view(data: bytes) -> int:
        pad = (-len(data)) % 4
        if pad:
            data = data + b"\x00" * pad
        off = sum(len(p) for p in bin_parts)
        bin_parts.append(data)
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(data)})
        return len(views) - 1

    for it in items:
        pos = np.ascontiguousarray(it["verts"], dtype="<f4")
        acc_pos = {"bufferView": add_view(pos.tobytes()), "componentType": 5126,
                   "count": len(pos), "type": "VEC3",
                   "min": pos.min(0).tolist(), "max": pos.max(0).tolist()}
        uv = np.ascontiguousarray(it["uv"], dtype="<f4")
        acc_uv = {"bufferView": add_view(uv.tobytes()), "componentType": 5126,
                  "count": len(uv), "type": "VEC2"}
        big = len(pos) >= 65536
        idx = np.ascontiguousarray(it["faces"].ravel(),
                                   dtype="<u4" if big else "<u2")
        acc_ix = {"bufferView": add_view(idx.tobytes()),
                  "componentType": 5125 if big else 5123,
                  "count": len(idx), "type": "SCALAR"}
        images.append({"mimeType": "image/jpeg", "bufferView": add_view(it["jpeg"])})
        textures.append({"source": len(images) - 1, "sampler": 0})
        materials.append({
            "pbrMetallicRoughness": {"baseColorTexture": {"index": len(textures) - 1}},
            "metallicFactor": 0.0, "roughnessFactor": 1.0,
            "extensions": {"KHR_materials_unlit": {}}})
        meshes.append({"name": it["name"], "primitives": [{
            "attributes": {"POSITION": len(accessors), "TEXCOORD_0": len(accessors) + 1},
            "indices": len(accessors) + 2, "material": len(materials) - 1, "mode": 4}]})
        accessors += [acc_pos, acc_uv, acc_ix]
        nodes.append({"mesh": len(meshes) - 1, "name": it["name"]})

    total_bin = sum(len(p) for p in bin_parts)
    gltf = {
        "asset": {"version": "2.0", "generator": "panodrome skill_360_to_walkable_3d v1.0"},
        "scene": 0, "scenes": [{"name": "PanodromeFurniture",
                                "nodes": list(range(len(nodes)))}],
        "nodes": nodes, "meshes": meshes, "materials": materials,
        "textures": textures,
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071}],
        "images": images, "accessors": accessors, "bufferViews": views,
        "buffers": [{"byteLength": total_bin}],
        "extensionsUsed": ["KHR_materials_unlit"],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    js += b" " * ((-len(js)) % 4)
    binp = b"".join(bin_parts)
    total = 12 + 8 + len(js) + (8 + len(binp) if binp else 0)
    out = io.BytesIO()
    out.write(b"glTF" + struct.pack("<II", 2, total))
    out.write(struct.pack("<I", len(js)) + b"JSON" + js)
    if binp:
        out.write(struct.pack("<I", len(binp)) + b"BIN\x00" + binp)
    return out.getvalue()


# --------------------------------------------------------------------------- #
# Furniture naming via the Smart Model Router (TIER 2 — Persian vision QA)
# --------------------------------------------------------------------------- #
def load_router():
    try:
        spec = importlib.util.spec_from_file_location(
            "ai_router", REPO / "skills" / "ai_router.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["ai_router"] = mod          # py3.12 dataclasses needs this
        spec.loader.exec_module(mod)
        return mod.Router(verbose=False)
    except Exception as exc:
        log(f"  [labels] router unavailable ({exc.__class__.__name__}) — using fallback")
        return None


def name_piece(router, crop_bgr, room_id, idx):
    tmp = Path("/tmp/s16_labels")
    tmp.mkdir(parents=True, exist_ok=True)
    p = tmp / f"{room_id}_{idx}.jpg"
    cv2.imwrite(str(p), crop_bgr)
    if router is None:
        return dict(LABELS["default"])
    try:
        out = router.generate(
            prompt=("Name the main furniture object in this 360-photo crop. "
                    'Reply ONLY compact JSON: {"en":"<one English word>",'
                    '"fa":"<یک کلمه فارسی>"}'),
            images=[p], tier=2, task="furniture-label")
        txt = out["text"].strip().strip("`")
        if txt.startswith("json"):
            txt = txt[4:]
        d = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        en = str(d.get("en", ""))[:20] or "Furniture"
        fa = str(d.get("fa", ""))[:24] or "مبلمان"
        return {"en": en, "fa": fa}
    except Exception:
        return dict(LABELS["default"])


# --------------------------------------------------------------------------- #
# D5 — optional Hunyuan3D-2 hero meshes (flag --ai-objects)
# --------------------------------------------------------------------------- #
def hunyuan_hero_mesh(comp, X, Y, Z, cam_off, pano_full_rgb, room_id):
    """Replace the crude depth mesh of the LARGEST piece with a Hunyuan3D-2
    GLB rescaled to the measured footprint. Experimental; falls back to None."""
    try:
        spec = importlib.util.spec_from_file_location(
            "rd_remote", REPO / "scripts" / "rd_remote_spaces.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["rd_remote"] = mod
        spec.loader.exec_module(mod)
        # perspective crop of the piece for the Space
        H2, W2 = comp.shape
        ys, xs = np.nonzero(comp)
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        crop, _ = wrap_crop(pano_full_rgb, x0 * 2, x1 * 2, y0 * 2, y1 * 2)
        outp = Path(f"/tmp/s16_hunyuan_{room_id}.glb")
        if not outp.is_file():
            # rd_remote_spaces exposes a helper; keep robust to its absence
            fn = getattr(mod, "hunyuan_generate_glb", None)
            if fn is None:
                log("  [D5] rd_remote_spaces.hunyuan_generate_glb not found — skip")
                return None
            fn(crop, outp)
        import trimesh
        scene = trimesh.load(str(outp), force="scene")
        geo = max(scene.geometry.values(), key=lambda g: len(g.faces))
        # measured footprint → rescale the normalized Hunyuan mesh
        px, py, pz = X[comp] + cam_off[0], Y[comp], Z[comp] + cam_off[1]
        ext = np.array([px.max() - px.min(), max(py.max() - py.min(), 0.1),
                        pz.max() - pz.min()])
        bmin, bmax = geo.bounds
        size = np.maximum(bmax - bmin, 1e-3)
        scale = float(np.median(ext / size))
        v = (geo.vertices - (bmin + bmax) / 2) * scale
        v[:, 1] -= v[:, 1].min()                       # floor-snap
        v[:, 0] += (px.min() + px.max()) / 2
        v[:, 2] += (pz.min() + pz.max()) / 2
        uv = np.asarray(getattr(geo.visual, "uv", None), dtype=np.float32)
        if uv is None or len(uv) != len(v):
            return None
        img = getattr(getattr(geo.visual, "material", None), "baseColorTexture", None)
        if img is None:
            return None
        arr = np.array(img.convert("RGB"))[:, :, ::-1]      # PIL → BGR
        return {"name": "furniture_hunyuan", "verts": v.astype(np.float32),
                "faces": np.asarray(geo.faces, dtype=np.int64), "uv": uv,
                "jpeg": jpeg_bytes(arr, 78)}
    except Exception as exc:
        log(f"  [D5] Hunyuan hero mesh skipped: {exc}")
        return None


# --------------------------------------------------------------------------- #
# Per-room pipeline
# --------------------------------------------------------------------------- #
ROOM_ID = "?"
FORCE = False


def process_room(room, args, router):
    global ROOM_ID
    ROOM_ID = room["id"]
    t_start = time.time()
    rid = room["id"]
    res = {"id": rid, "status": "?", "timings": {}}

    shell_path = SHELL_DIR / f"{rid}.jpg"
    glb_path = FURN_DIR / f"{rid}.glb"
    db_fresh = (room.get("shell_texture") == f"assets/shells/{rid}.jpg"
                and room.get("furniture", {}).get("glb") == f"assets/furniture/{rid}.glb")
    if not args.force and shell_path.is_file() and glb_path.is_file() and db_fresh:
        res.update({"status": "CACHED", "note": "outputs + DB entry already present"})
        return res

    pano = cv2.imread(str(REPO / "public" / room["panorama"]))
    if pano is None:
        res.update({"status": "SKIPPED", "reason": "panorama missing"})
        return res
    H, W = pano.shape[:2]
    H2, W2 = H // 2, W // 2

    # 1) depth (cached disparity) + D4 edge-aligned inverse depth
    t0 = time.time()
    disp = run_depth(pano)
    rgb_half = cv2.cvtColor(cv2.resize(pano, (W2, H2), interpolation=cv2.INTER_AREA),
                            cv2.COLOR_BGR2RGB)
    inv_raw, inv_guided = guided_inverse_depth(disp, rgb_half)
    res["timings"]["depth_s"] = round(time.time() - t0, 1)

    # 2) measured-shell calibration — on the RAW (median-only) inverse depth
    t0 = time.time()
    dx, dy, dz, phi, theta = equirect_dirs(H2, W2)
    s, cam_h, ceil_h, wall_rho, med = calibrate(inv_raw, theta, phi, room["room_shape"],
                                                 (room["camera"]["x"], room["camera"]["z"]))
    res["timings"]["calibrate_s"] = round(time.time() - t0, 1)
    res["measured"] = med
    log(f"  [calib] scale={s:.2f} cam_h={cam_h:.2f} ceil={ceil_h:.2f} "
        f"consistency={med['consistency']:.0%}")

    # 3) world points (camera-centred x/z + DB camera offset; Y absolute, floor 0)
    #    D = GUIDED inverse depth scaled by the raw-depth calibration (D4)
    D = inv_guided * s
    cam_off = (float(room["camera"]["x"]), float(room["camera"]["z"]))
    X = D * dx
    Yw = D * dy + cam_h
    Z = D * dz

    # 4) furniture separation (D1) — against min(measured shell, AUTHORED BOX):
    #    the box is what the engine renders and clamps open-plan directions.
    t0 = time.time()
    meas_t = ShellModel().distance(cam_h, ceil_h, wall_rho, theta, phi)
    box_t = box_shell_distance(
        dx, dy, dz, (cam_off[0], cam_h, cam_off[1]),
        room["room_shape"]["width"] / 2, room["room_shape"]["depth"] / 2,
        room["room_shape"]["height"])
    shell_t = np.minimum(meas_t, box_t)
    fmask, comps = separate_furniture(D, shell_t, Yw, ceil_h, X, Z)
    res["timings"]["separate_s"] = round(time.time() - t0, 1)
    res["components_raw"] = len(comps)
    if not comps:
        res.update({"status": "SKIPPED",
                    "reason": "no furniture components passed the D1 filters "
                              "(empty room / outdoor scene) — Stage 1.5 setup kept"})
        return res

    # 5) furniture meshes — adaptive stride, UV crops, colliders, labels
    #    (label crops come from the COMPONENT bbox → router-cache-friendly)
    t0 = time.time()
    pano_rgb = cv2.cvtColor(pano, cv2.COLOR_BGR2RGB)

    def comp_label_crop(comp):
        ys_, xs_ = np.nonzero(comp)
        crop, _ = wrap_crop(pano_rgb, int(xs_.min()) * 2, int(xs_.max()) * 2 + 1,
                            int(ys_.min()) * 2, int(ys_.max()) * 2 + 1)
        return crop

    def build_all(stride_scale):
        its, obs, fis, masks = [], [], [], []
        for rank, i in enumerate(order):
            comp = comps[i]
            area = int(comp.sum())
            stride = max(1, int(round(np.sqrt(area / TARGET_QUADS) * stride_scale)))
            built = build_uv_mesh(comp, D, X, Yw, Z, cam_off, pano_rgb, stride)
            if built is None or built["tris"] < 8:
                continue
            label = name_piece(router, cv2.cvtColor(comp_label_crop(comp),
                                                    cv2.COLOR_RGB2BGR), rid, rank)
            col = make_collider(comp, X, Yw, Z, cam_off, label)
            if col is not None:
                obs.append(col)
            fis.append({
                "label": label, "tris": built["tris"], "stride": stride,
                "x": (col or {}).get("x", round(float(X[comp].mean()) + cam_off[0], 2)),
                "z": (col or {}).get("z", round(float(Z[comp].mean()) + cam_off[1], 2)),
                "collider": col is not None,
                "y_extent_m": [round(float(Yw[comp].min()), 2),
                               round(float(Yw[comp].max()), 2)],
                "median_distance_m": round(float(np.median(D[comp])), 2)})
            masks.append(comp)
            its.append({"name": f"furniture_{rank:02d}", "built": built,
                        "comp_index": i})
            log(f"    piece {rank}: area={area}px stride={stride} "
                f"tris={built['tris']} label={label['en']}/{label['fa']}")
        return its, obs, fis, masks

    # D1 box law: furniture islands must live INSIDE the authored room volume
    # (open-plan openings reveal distant rooms — their pieces are not ours)
    hw_box, hd_box = (room["room_shape"]["width"] / 2,
                      room["room_shape"]["depth"] / 2)
    def inside_box(m):
        cx_ = float(np.mean(X[m])) + cam_off[0]
        cz_ = float(np.mean(Z[m])) + cam_off[1]
        return abs(cx_) < hw_box - 0.05 and abs(cz_) < hd_box - 0.05
    n0 = len(comps)
    comps = [c for c in comps if inside_box(c)]
    log(f"  [box-fit] kept {len(comps)}/{n0} components inside the room volume")
    if not comps:
        res.update({"status": "SKIPPED",
                    "reason": "no furniture components inside the authored box"})
        return res

    order = sorted(range(len(comps)), key=lambda i: -int(comps[i].sum()))
    if len(order) > 8:                       # D2: cap piece count for budget
        order = order[:8]
        comps = [comps[i] for i in order]
        log(f"  [D2 budget] capped to top {len(comps)} pieces")
    items, obstacles, furniture_items, used_masks = build_all(1.0)
    if not items:
        res.update({"status": "SKIPPED", "reason": "all component meshes empty"})
        return res

    # 6) compact GLB export under the D2 budget — stride ladder, then drop the
    #    smallest piece if still over
    t0 = time.time()
    glb = b""
    for stride_scale in (1.0, 1.35, 1.8, 2.4):
        for quality in (82, 74):
            glb = export_glb(encode_items(items, quality))
            if len(glb) <= GLB_BUDGET_KB * 1024:
                break
        if len(glb) <= GLB_BUDGET_KB * 1024:
            break
        log(f"  [D2 budget] {len(glb)//1024}KB > {GLB_BUDGET_KB}KB "
            f"— rebuilding at stride ×{stride_scale * 1.35:.2f}")
        items, obstacles, furniture_items, used_masks = build_all(stride_scale * 1.35)
    while len(glb) > GLB_BUDGET_KB * 1024 and len(items) > 1:
        log(f"  [D2 budget] dropping smallest of {len(items)} pieces "
            f"({len(glb)//1024}KB over)")
        order = order[:-1]
        comps = [comps[i] for i in order]
        items, obstacles, furniture_items, used_masks = build_all(2.4)
        glb = export_glb(encode_items(items, 74))
    if len(glb) > GLB_BUDGET_KB * 1024:
        res.update({"status": "SKIPPED",
                    "reason": f"GLB {len(glb)//1024}KB exceeds {GLB_BUDGET_KB}KB budget"})
        return res

    # optional D5: swap the hero piece for a Hunyuan hero mesh (decimated to budget)
    if args.ai_objects:
        hero = hunyuan_hero_mesh(comps[items[0]["comp_index"]], X, Yw, Z,
                                 cam_off, pano_rgb, rid)
        if hero is not None and len(hero["faces"]) <= 120000:
            hero["tris"] = len(hero["faces"])
            items[0] = {"name": "furniture_hunyuan", "built": hero}
            glb = export_glb(encode_items(items, 82))
        elif hero is not None:
            log(f"  [D5] hero mesh too dense ({len(hero['faces'])} faces) — kept local mesh")
    res["timings"]["mesh_s"] = round(time.time() - t0, 1)

    # 7) inpainted shell texture (D3) + JPEG ladder inside the TOTAL budget
    t0 = time.time()
    shell_budget_kb = TOTAL_BUDGET_KB - len(glb) // 1024 - 20
    mask_u = np.zeros((H2, W2), bool)
    for m in used_masks:
        mask_u |= m
    # parallax guard: erase the background band that walking will reveal
    # beside each piece (t_walk budget 1.6 m; angular reveal in half-res px)
    with np.errstate(divide="ignore", invalid="ignore"):
        reveal = 1.6 * np.abs(1.0 / np.maximum(D, 0.3) - 1.0 / np.maximum(shell_t, 0.3))
        guard_half = reveal / (2 * np.pi / W2)              # half-res px
        gvals = guard_half[mask_u & np.isfinite(guard_half)]
        guard_px = int(np.clip(np.percentile(gvals, 80) if gvals.size else 12,
                               12, 55)) * 2 + DILATE_PX      # → full-res px
    log(f"  [D3 guard] parallax guard = {guard_px}px full-res "
        f"(fringe {DILATE_PX}px + reveal band)")
    # exact floor-background rays: floor plane is the nearest shell surface
    t_floor = np.where(-dy > 1e-3, cam_h / np.maximum(-dy, 1e-3), np.inf)
    with np.errstate(divide="ignore", invalid="ignore"):
        cos_phi = np.sqrt(np.maximum(1 - dy ** 2, 1e-12))
        bins = (np.floor(theta / (2 * np.pi) * 144).astype(int)) % 144
        t_wall = wall_rho[bins] / cos_phi
    floor_bg = (t_floor <= t_wall) & (t_floor < np.inf) & (phi < np.radians(-4))
    shell_img = inpaint_shell(pano, mask_u, dilate_px=guard_px, floor_bg_half=floor_bg)
    shell_bytes = b""
    for long_edge, q in [(SHELL_TARGET_LONG_EDGE, 80), (SHELL_TARGET_LONG_EDGE, 74),
                         (3584, 76), (3072, 74)]:
        img = shell_img if long_edge == W else cv2.resize(
            shell_img, (long_edge, long_edge // 2), interpolation=cv2.INTER_AREA)
        shell_bytes = jpeg_bytes(img, q)
        if len(shell_bytes) <= shell_budget_kb * 1024:
            break
    res["timings"]["inpaint_s"] = round(time.time() - t0, 1)
    total_kb = (len(glb) + len(shell_bytes)) // 1024
    if total_kb > TOTAL_BUDGET_KB:
        res.update({"status": "SKIPPED",
                    "reason": f"total {total_kb}KB exceeds the 2500KB D2 budget"})
        return res

    if args.dry_run:
        res.update({"status": "CONVERTED (dry-run)", "glb_kb": len(glb) // 1024,
                    "shell_kb": len(shell_bytes) // 1024, "total_kb": total_kb,
                    "meshes": len(items), "tris": sum(f["tris"] for f in furniture_items),
                    "obstacles": obstacles, "furniture_items": furniture_items})
        return res

    # 8) write outputs + mutate the DB (both copies, byte-identical)
    SHELL_DIR.mkdir(parents=True, exist_ok=True)
    FURN_DIR.mkdir(parents=True, exist_ok=True)
    shell_path.write_bytes(shell_bytes)
    glb_path.write_bytes(glb)

    room["shell_texture"] = f"assets/shells/{rid}.jpg"
    room["furniture"] = {
        "glb": f"assets/furniture/{rid}.glb",
        "meshes": len(items),
        "tris": sum(f["tris"] for f in furniture_items),
        "bytes_glb": len(glb), "bytes_shell": len(shell_bytes),
        "items": furniture_items,
    }
    # MERGE POLICY: auto colliders replace AUTHORED ones they overlap (same
    # object, re-measured), but VLM-verified authored colliders the depth pass
    # missed (e.g. the ballroom grand piano) are PRESERVED.
    authored = room["walk"].get("obstacles", []) or []

    def _radius(o):
        return float(o.get("r") or max(o.get("hw", 0), o.get("hd", 0)) or 0)

    def _overlaps(col, o):
        if col["type"] == "cylinder":
            cx, cz, rr = col["x"], col["z"], col["r"]
        else:
            cx, cz, rr = col["x"], col["z"], max(col["hw"], col["hd"])
        dx = abs(cx - float(o["x"]))
        dz = abs(cz - float(o["z"]))
        return (dx * dx + dz * dz) ** 0.5 < rr + _radius(o) + 0.25

    keep_authored = [o for o in authored
                     if not any(_overlaps(c, o) for c in obstacles)]
    room["walk"]["obstacles"] = obstacles + keep_authored
    if keep_authored:
        log(f"  [merge] kept {len(keep_authored)} authored collider(s) "
            f"not covered by auto: {[o['label']['en'] for o in keep_authored]}")
    room["measured"] = med
    if med["consistency"] >= 0.60 and abs(cam_h - room["camera"]["y"]) > 0.05:
        res["camera_y"] = {"from": room["camera"]["y"], "to": round(cam_h, 2)}
        room["camera"]["y"] = round(cam_h, 2)

    res.update({"status": "CONVERTED", "glb_kb": len(glb) // 1024,
                "shell_kb": len(shell_bytes) // 1024, "total_kb": total_kb,
                "meshes": len(items), "tris": sum(f["tris"] for f in furniture_items),
                "obstacles": obstacles, "furniture_items": furniture_items,
                "timings": {**res["timings"],
                            "total_s": round(time.time() - t_start, 1)}})
    return res


# --------------------------------------------------------------------------- #
def save_db(db):
    txt = json.dumps(db, ensure_ascii=False, indent=2) + "\n"
    DB_PATH.write_text(txt, encoding="utf-8")
    DB_PUBLIC.write_text(txt, encoding="utf-8")
    import hashlib
    a = hashlib.md5(DB_PATH.read_bytes()).hexdigest()
    b = hashlib.md5(DB_PUBLIC.read_bytes()).hexdigest()
    assert a == b, "DB md5 sync FAILED"


def main():
    global FORCE
    ap = argparse.ArgumentParser(description="Panodrome 360 → walkable 3D (Stage 1.6)")
    ap.add_argument("--rooms", help="comma-separated room ids")
    ap.add_argument("--all", action="store_true", help="process every room in the DB")
    ap.add_argument("--force", action="store_true", help="ignore output caches")
    ap.add_argument("--dry-run", action="store_true", help="no file/DB writes")
    ap.add_argument("--ai-objects", action="store_true",
                    help="D5: swap the hero piece for a Hunyuan3D-2 mesh (experimental)")
    args = ap.parse_args()
    FORCE = args.force
    if not (args.rooms or args.all):
        ap.error("choose --rooms <ids> or --all")

    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    ids = args.rooms.split(",") if args.rooms else [r["id"] for r in db["rooms"]]
    router = load_router()
    results = []
    t0 = time.time()
    for room in db["rooms"]:
        if room["id"] not in ids:
            continue
        log(f"\n=== {room['id']} ===")
        try:
            res = process_room(room, args, router)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            res = {"id": room["id"], "status": "ERROR", "reason": str(exc)[:200]}
        results.append(res)
        log(f"  → {res['status']}")

    if not args.dry_run and any(r["status"].startswith("CONVERTED") for r in results):
        db["stage"] = "stage1.6_layered_3d_walk"
    if not args.dry_run:
        save_db(db)

    conv = [r for r in results if r["status"].startswith("CONVERTED")]
    skipped = [r for r in results if r["status"] in ("SKIPPED", "ERROR")]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(
        {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "results": results,
         "summary": {"converted": len(conv), "skipped": len(skipped),
                     "total_min": round((time.time() - t0) / 60, 1),
                     "budget_kb": TOTAL_BUDGET_KB}}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    log(f"\n==== SUMMARY: {len(conv)} converted, {len(skipped)} skipped/err "
        f"in {(time.time()-t0)/60:.1f} min → {REPORT_PATH}")
    for r in results:
        extra = (f" {r.get('total_kb')}KB ({r.get('meshes')} meshes / "
                 f"{r.get('tris')} tris)" if r.get("total_kb") else
                 f" — {r.get('reason', '')[:60]}")
        log(f"  {r['id']:26s} {r['status']:22s}{extra}")


if __name__ == "__main__":
    main()
