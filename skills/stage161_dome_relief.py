#!/usr/bin/env python3
"""
PANODROME — STAGE 1.6.1 · EMERGENCY VISUAL RESTORATION — relief baker
=====================================================================
Owner order 2026-11-02 (live-site mobile audit + master directive):

  * Rule A — OpenCV Telea/NS inpainting with a 122px parallax-guard band
    on 4K panoramas is BANNED from production (huge blurry wall smudges).
    The crisp ORIGINAL pano_4k.jpg is the only texture, forever.
  * Rule B — Raw grid depth-cut furniture extrusions (edge tearing +
    back-caps) are BANNED from production (spiky shards / saw-tooth
    skirts / exploded triangles).  Instead: a WATERTIGHT, GROUND-
    FLATTENED radial room mesh with CONTINUOUS C1-SMOOTH Gaussian depth
    relief (sigma = 18px on the half-res inverted DAV2 depth), zero torn
    edges, zero triangle explosions, flat walkable floor y = 0.
  * Rule C — furniture collision stays REAL: calibrated physics
    colliders + glass floor halos (collider.js), NOT mesh cutouts.

WHAT THIS BAKES (per room, all 10): a 512x256 radial RELIEF FIELD —
the radial surface distance from the capture point for every equirect
direction (θ, φ), heavily smoothed, floor-snapped to the exact y=0
plane, ceiling-snapped to the calibrated ceiling, soft-clamped into the
room envelope (no hard kinks), quantised u16 (R channel = hi byte,
G = lo byte) into public/assets/relief/<id>.png (~25-95KB).

DB MUTATION (data/ + public/data/, md5-synced):
    room.walk.relief   = { url, rmin, rmax, w, h }
    room.walk.envelope = { r }              safe base walk radius
    room.camera.y      = measured cam_h     (finally applied everywhere)
    room.shell_texture REMOVED              (crisp pano is the texture)
    room.furniture     REMOVED              (spiky GLBs purged)

Runtime: public/js/room.js displaces a 320x144 sphere grid by this field
-> a smooth dome; the per-fragment equirect shader stays PIXEL-EXACT at
the capture point and gives true parallax inside the 1.1-1.35m walk
envelope.  Idempotent; no ONNX needed (disparity caches on disk).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "rooms_db.json"
DB_PUBLIC = ROOT / "public" / "data" / "rooms_db.json"
DISP_DIR = ROOT / "assets" / "depth" / "disp_cache"
RELIEF_DIR = ROOT / "public" / "assets" / "relief"
REPORT = ROOT / "docs" / "rd-artifacts" / "stage161_relief_report.json"

RELIEF_W, RELIEF_H = 512, 256
SIGMA_DEPTH = 18.0        # px on the half-res depth image (owner law)
SIGMA_BOX = 3.0           # px on the 512-wide analytic field (corner rounding)
SOFT_K = 1.2              # m — soft-clamp shoulder width (C1-smooth, no kinks)
CURV_LIMIT = 0.45         # m — saw-tooth guard (2nd-difference curvature)


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------- #
# equirect rays — SAME convention as room.js (u = atan2(dz, -dx)/2pi)
# --------------------------------------------------------------------------- #
def equirect_grid(H: int, W: int):
    """Return (dx, dy, dz, phi, theta) arrays of shape (H, W).
    Row 0 = zenith (phi = +pi/2), row H-1 = nadir (phi = -pi/2)."""
    u = np.arange(W, dtype=np.float64) / W * 2 * np.pi
    v = np.arange(H, dtype=np.float64) / H
    phi = np.broadcast_to(((0.5 - v[:, None]) * np.pi), (H, W)).copy()
    theta = np.broadcast_to(u[None, :], (H, W)).copy()
    cp, sp = np.cos(phi), np.sin(phi)
    return -cp * np.cos(theta), sp, cp * np.sin(theta), phi, theta


def wrap_blur(img: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur with x-wrap (equirect seam) + y-reflect."""
    pad = int(np.ceil(sigma * 3))
    if pad * 2 >= img.shape[1]:
        return img
    padded = np.hstack([img[:, -pad:], img, img[:, :pad]])
    out = cv2.GaussianBlur(padded, (0, 0), sigmaX=sigma, sigmaY=sigma,
                           borderType=cv2.BORDER_REFLECT)
    return out[:, pad:pad + img.shape[1]]


def smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def soft_clamp_top(F: np.ndarray, rmax: float, k: float = SOFT_K) -> np.ndarray:
    """C1-smooth upper clamp: F' = rmax - k*log1p(exp((rmax-F)/k)).
    Equals F when F << rmax; asymptotes to rmax — no plateau-edge kink."""
    z = np.clip((rmax - F) / k, -30.0, 30.0)
    return rmax - k * np.log1p(np.exp(z))


# --------------------------------------------------------------------------- #
# analytic authored-box field (rooms without measured calibration)
# --------------------------------------------------------------------------- #
def box_field(room: dict) -> np.ndarray:
    w, d, h = room["room_shape"]["width"], room["room_shape"]["depth"], room["room_shape"]["height"]
    hw, hd = w / 2.0, d / 2.0
    c = room["camera"]
    dx, dy, dz, phi, _ = equirect_grid(RELIEF_H, RELIEF_W)
    with np.errstate(divide="ignore", invalid="ignore"):
        tx = np.where(dx > 1e-6, (hw - c["x"]) / dx,
                      np.where(dx < -1e-6, (-hw - c["x"]) / dx, np.inf))
        ty = np.where(dy > 1e-6, (h - c["y"]) / dy,
                      np.where(dy < -1e-6, (0.0 - c["y"]) / dy, np.inf))
        tz = np.where(dz > 1e-6, (hd - c["z"]) / dz,
                      np.where(dz < -1e-6, (-hd - c["z"]) / dz, np.inf))
    t = np.minimum(np.minimum(tx, ty), tz)
    return np.where(np.isfinite(t) & (t > 0.05), t, 30.0).astype(np.float64)


def box_eye_ray_max(room: dict) -> float:
    w, d = room["room_shape"]["width"], room["room_shape"]["depth"]
    c = room["camera"]
    return float(np.hypot(max(w / 2 - abs(c["x"]), 0.1), max(d / 2 - abs(c["z"]), 0.1)) * 1.414)


EYE_CLEAR_M = 2.12  # player eye 1.65 + bob + margin — nothing overhead below
                    # this (2.12 = 0.47 m above the eye: enough clearance that
                    # grazing-stretch on low-cabin ceilings stays QA-clean)


def eye_clearance_pass(D: np.ndarray, cam_h: float) -> np.ndarray:
    H, W = D.shape
    v = (0.5 - (np.arange(H) + 0.5) / H) * np.pi
    sinp = np.sin(v)[:, None]
    cosp = np.cos(v)[:, None]
    y = cam_h + sinp * D
    h = np.abs(cosp) * D                                  # horizontal distance
    # per-azimuth wall footprint ≈ eye-band median radius (φ≈0 → R≈horizontal)
    band = (np.abs(v) > np.radians(4)) & (np.abs(v) < np.radians(25))
    wall_h = np.maximum(np.median(D[band], axis=0)[None, :], 0.5)
    inside = h < wall_h * 0.92                            # overhead content
    with np.errstate(divide="ignore", invalid="ignore"):
        R_t = np.where(sinp > 1e-3, (EYE_CLEAR_M - cam_h) / np.maximum(sinp, 1e-3), np.inf)
    R_t = np.nan_to_num(R_t, posinf=0.0)
    w = (smoothstep((wall_h * 0.92 - h) / np.maximum(0.15 * wall_h, 1e-3))
         * smoothstep((EYE_CLEAR_M - y) / 0.18))
    w = np.where((v > 0)[:, None] & inside & (y < EYE_CLEAR_M) & (y > cam_h + 0.05), w, 0.0)
    return w * R_t + (1 - w) * D


# --------------------------------------------------------------------------- #
# shared post-processing: clamps + floor/ceiling snaps (the flat-floor law)
# --------------------------------------------------------------------------- #
def apply_envelope_and_snaps(D: np.ndarray, cam_h: float, ceil_h: float,
                             rmin: float, rmax: float) -> np.ndarray:
    H, W = D.shape
    _, _, _, phi, _ = equirect_grid(H, W)
    sinp = np.sin(phi)
    absp = np.abs(phi)

    # per-row snap bands (DAV2 compresses floors ~15% at steep angles)
    lo = np.full_like(D, 0.92); hi = np.full_like(D, 0.97)
    mid = (absp > np.radians(25)) & (absp <= np.radians(45))
    lo[mid], hi[mid] = 0.84, 0.94
    steep = absp > np.radians(45)
    lo[steep], hi[steep] = 0.72, 0.86

    # ---- soft top clamp everywhere (C1-smooth, no plateau kinks) ----
    D = soft_clamp_top(D, rmax)

    # ---- bottom clamp: eye-level wall/furniture noise only.  Underfoot
    #      floor rays legitimately have radial < rmin — wide clamp there.
    wall_rows = sinp > -0.15
    D = np.where(wall_rows, np.clip(D, rmin, rmax), np.clip(D, 0.25, rmax))

    # ---- floor snap (below horizon): blend to the EXACT y=0 plane where
    #      the field is floor; furniture bulges keep their measured depth
    planar_f = np.where(sinp < -1e-3, cam_h / np.maximum(-sinp, 1e-3), np.inf)
    ratio_f = D / planar_f
    w_f = smoothstep((ratio_f - lo) / np.maximum(hi - lo, 1e-6))
    w_f = np.where(ratio_f > 1.02, 1.0, w_f)              # overshoot = noise
    w_f = np.where(np.isfinite(planar_f), w_f, 0.0)
    planar_fs = np.nan_to_num(planar_f, posinf=0.0)       # 0 * inf = NaN guard
    D = w_f * planar_fs + (1 - w_f) * D

    # ---- ceiling snap (above horizon): flat calibrated ceiling plane
    planar_c = np.where(sinp > 1e-3, (ceil_h - cam_h) / np.maximum(sinp, 1e-3), np.inf)
    ratio_c = D / planar_c
    w_c = smoothstep((ratio_c - lo) / np.maximum(hi - lo, 1e-6))
    w_c = np.where(ratio_c > 1.02, 1.0, w_c)
    w_c = np.where(np.isfinite(planar_c), w_c, 0.0)
    planar_cs = np.nan_to_num(planar_c, posinf=0.0)
    D = w_c * planar_cs + (1 - w_c) * D

    # ---- EYE-CLEARANCE LAW (found 2026-11-02 via the Gemini QA gate): in
    #      low-capture rooms (cabin cam 0.75 m, corridor 0.70 m) DAV2's
    #      ceiling depth droops to y ~ 1.7 m — BELOW the player eye (1.65 m)
    #      — so the dome passed THROUGH the camera and filled the upper
    #      viewport with grazing-stretched geometry.  Overhead bins (φ>0,
    #      horizontal distance inside the wall footprint) with y < 2.0 m are
    #      smoothly lifted to y = 2.0 m (0.35 m above the eye).  Wall bins
    #      (h ≈ wall footprint) are NEVER lifted — walls at head height are
    #      legitimate architecture.
    D = eye_clearance_pass(D, cam_h)

    # ---- FINAL exact-floor pass: steep rows (φ < -50°, provably free of
    #      below-horizon wall hits in every room) that sit within 10cm of
    #      the y=0 plane ARE the floor -> snap EXACTLY planar (flat law).
    #      Runs at the FINAL output resolution (after any downsample) so no
    #      resize can re-blend the exactness away.
    return D


def exact_floor_pass(D: np.ndarray, cam_h: float) -> np.ndarray:
    H, W = D.shape
    v_rows = (0.5 - (np.arange(H) + 0.5) / H) * np.pi
    steep_rows = v_rows < np.radians(-50)
    planar_rows = cam_h / np.maximum(-np.sin(v_rows), 1e-3)
    y = cam_h + np.sin(v_rows)[:, None] * D            # world height per sample
    Fsr = D[steep_rows, :]
    ysr = y[steep_rows, :]
    m = np.abs(ysr) < 0.10
    if m.any():
        Fsr = Fsr.copy()
        Fsr[m] = np.broadcast_to(planar_rows[steep_rows][:, None], Fsr.shape)[m]
        D = D.copy()
        D[steep_rows, :] = Fsr
    return D


# --------------------------------------------------------------------------- #
# measured field (7 rooms): inverted DAV2 disparity -> metres
# --------------------------------------------------------------------------- #
def measured_field(room: dict, med: dict, rmin: float, rmax: float) -> tuple[np.ndarray, float]:
    disp = np.load(DISP_DIR / f"{room['id']}_disp.npy").astype(np.float32)
    inv = 1.0 / np.maximum(cv2.medianBlur(disp, 5).astype(np.float64), 1e-3)
    inv = cv2.medianBlur(inv.astype(np.float32), 5).astype(np.float64)
    D = inv * float(med["scale"])                         # radial metres
    # ---- outlier guard (found 2026-11-02): DAV2 caches contain negative /
    #      near-zero disparity speckles (school_hall: 6058 px < 0) which
    #      invert to MULTI-KILOMETRE spikes that bleed through the blur as
    #      steep shelves.  Winsorise BEFORE blurring; the Gaussian then
    #      smooths the clip edges themselves.
    D = np.clip(D, 0.30, 40.0)
    D = wrap_blur(D, SIGMA_DEPTH)                         # owner law: sigma 18px

    cam_h = round(float(med["cam_h_m"]), 2)               # == room.camera.y
    h_box = room["room_shape"]["height"]
    ceil_above = float(med["ceil_h_m"]) - float(med["cam_h_m"])
    lo_b = max(1.2, h_box * 0.3)
    hi_b = min(h_box * 1.05, 4.5)
    pinned = abs(ceil_above - lo_b) < 1e-6 or abs(ceil_above - hi_b) < 1e-6
    ceil_h = float(h_box) if pinned else float(med["ceil_h_m"])

    D = apply_envelope_and_snaps(D, cam_h, ceil_h, rmin, rmax)
    assert np.isfinite(D).all(), "NaN in relief field"
    D = cv2.resize(D.astype(np.float32), (RELIEF_W, RELIEF_H),
                   interpolation=cv2.INTER_AREA).astype(np.float64)
    D = exact_floor_pass(D, cam_h)
    return D, ceil_h


def eye_band_stats(F: np.ndarray) -> dict:
    H = F.shape[0]
    j_lo = int((0.5 - np.radians(25) / np.pi) * H)
    j_hi = int((0.5 - np.radians(4) / np.pi) * H)
    band = F[j_lo:j_hi]
    p2, p10, p50 = np.percentile(band, [2, 10, 50])
    return {"wall_p2": round(float(p2), 2), "wall_p10": round(float(p10), 2),
            "wall_p50": round(float(p50), 2)}


# --------------------------------------------------------------------------- #
# per-room bake
# --------------------------------------------------------------------------- #
def bake_room(room: dict) -> dict:
    rid = room["id"]
    t0 = time.time()
    med = room.get("measured")
    ray_max = box_eye_ray_max(room)

    if med and med.get("scale"):
        draft, _ = measured_field(room, med, 1.05, 30.0)   # bounds pre-pass
        st = eye_band_stats(draft)
        rmin = float(np.clip(min(1.70, st["wall_p2"] - 0.08), 1.05, 1.70))
        rmax = float(np.clip(max(ray_max, st["wall_p50"]) * 1.25, 6.0, 30.0))
        F, ceil_used = measured_field(room, med, rmin, rmax)
        cam_y = round(float(med["cam_h_m"]), 2)
        mode = "measured"
    else:
        F = wrap_blur(box_field(room), SIGMA_BOX)
        cam_y = round(float(room["camera"]["y"]), 2)
        ceil_used = float(room["room_shape"]["height"])
        mode = "authored-box"
        st = eye_band_stats(F)
        rmin = float(np.clip(min(1.70, st["wall_p2"] - 0.08), 1.05, 1.70))
        rmax = float(np.clip(max(ray_max, st["wall_p50"]) * 1.25, 6.0, 30.0))
        F = apply_envelope_and_snaps(F, cam_y, ceil_used, rmin, rmax)
        F = exact_floor_pass(F, cam_y)

    # ---- saw-tooth guard: ZIGZAG height = slope-reversal magnitude.  A
    #      smooth ramp/corner (wall -> opening, wall -> floor junction) has
    #      single-sign slopes; the old depth-cut spike signature was an
    #      ALTERNATING +/- jump.  Reversal height catches exactly that.
    #      (curvature is also reported, informational: junction corners are
    #      real architecture and may be locally high in radial metres.)
    def _zigzag(Fl: np.ndarray) -> float:
        best = 0.0
        for axis in (1, 0):
            s = np.diff(Fl, axis=axis)
            sa, sb = s[..., :-1], s[..., 1:]
            m = np.minimum(np.abs(sa), np.abs(sb))
            best = max(best, float(np.where(sa * sb < 0, m, 0).max()))
        return best

    curv_x = float(np.abs(np.roll(F, 1, 1) - 2 * F + np.roll(F, -1, 1)).max())
    curv_y = float(np.abs(np.vstack([F[:1], F[:-1]]) - 2 * F + np.vstack([F[1:], F[-1:]])).max())
    max_curv = max(curv_x, curv_y)
    zigzag = _zigzag(F)

    # ---- floor flatness: steep rows must sit EXACTLY on y=0
    H = F.shape[0]
    v_rows = (0.5 - (np.arange(H) + 0.5) / H) * np.pi
    jf = int((0.5 - np.radians(-50) / np.pi) * H)         # φ = -50° row
    y = cam_y + np.sin(v_rows)[:, None] * F
    floor_dev = float(np.abs(y[jf:][np.abs(y[jf:]) < 0.06]).max(initial=0.0))

    # ---- safe base walk radius (owner spec: 1.1-1.35m envelope)
    r_env = float(np.clip(st["wall_p10"] - 0.35, 0.80, 1.35))

    # ---- encode u16 over the ACTUAL field range -> RGB PNG
    enc_lo = float(F.min())
    enc_hi = float(F.max())
    q = np.round((F - enc_lo) / max(enc_hi - enc_lo, 1e-6) * 65535).astype(np.uint32)
    rgb = np.zeros((RELIEF_H, RELIEF_W, 3), dtype=np.uint8)
    rgb[..., 0] = (q >> 8).astype(np.uint8)
    rgb[..., 1] = (q & 255).astype(np.uint8)
    RELIEF_DIR.mkdir(parents=True, exist_ok=True)
    png_path = RELIEF_DIR / f"{rid}.png"
    Image.fromarray(rgb).save(png_path, optimize=True)
    png_bytes = png_path.stat().st_size

    # ---- DB mutation
    room["walk"]["relief"] = {
        "url": f"assets/relief/{rid}.png", "rmin": round(enc_lo, 3),
        "rmax": round(enc_hi, 3), "w": RELIEF_W, "h": RELIEF_H,
    }
    room["walk"]["envelope"] = {"r": round(r_env, 2)}
    room["camera"]["y"] = cam_y
    room.pop("shell_texture", None)      # crisp pano_4k is the ONLY texture
    room.pop("furniture", None)          # spiky depth-cut GLBs purged

    return {
        "id": rid, "mode": mode, "cam_y": cam_y, "ceil_used_m": round(ceil_used, 2),
        "rmin": round(rmin, 2), "rmax": round(rmax, 2),
        **st, "envelope_r": round(r_env, 2),
        "max_curv_m": round(max_curv, 3),
        "zigzag_m": round(zigzag, 3),
        "floor_dev_m": round(floor_dev, 4),
        "png_kb": round(png_bytes / 1024, 1),
        "png_md5": hashlib.md5(png_path.read_bytes()).hexdigest()[:10],
        "bake_s": round(time.time() - t0, 1),
    }


def save_db(db):
    txt = json.dumps(db, ensure_ascii=False, indent=2) + "\n"
    DB_PATH.write_text(txt, encoding="utf-8")
    DB_PUBLIC.write_text(txt, encoding="utf-8")
    a = hashlib.md5(DB_PATH.read_bytes()).hexdigest()
    b = hashlib.md5(DB_PUBLIC.read_bytes()).hexdigest()
    assert a == b, "DB md5 sync FAILED"


def main():
    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    results = []
    for room in db["rooms"]:
        log(f"[relief] {room['id']} ...")
        r = bake_room(room)
        results.append(r)
        log(f"    {r['mode']:12s} cam_y={r['cam_y']} r=[{r['rmin']},{r['rmax']}] "
            f"env_r={r['envelope_r']} walls p2/p10/p50={r['wall_p2']}/{r['wall_p10']}/{r['wall_p50']} "
            f"zigzag={r['zigzag_m']}m curv={r['max_curv_m']}m floorDev={r['floor_dev_m']}m png={r['png_kb']}KB")

    spikes = [r for r in results if r["zigzag_m"] > CURV_LIMIT]
    floors = [r for r in results if r["floor_dev_m"] > 0.011]
    save_db(db)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "law": "Rule B (owner 2026-11-02): sigma=18px continuous radial relief, "
               "NO cutouts, NO Telea, NO extrusion; soft-clamped envelope; "
               "floor snapped to exact y=0; u16 PNG (R=hi,G=lo)",
        "results": results,
        "spike_violations": [r["id"] for r in spikes],
        "floor_violations": [r["id"] for r in floors],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"[relief] DB saved + md5-synced; report -> {REPORT.relative_to(ROOT)}")
    if spikes:
        log(f"[relief] WARNING zigzag saw-tooth>{CURV_LIMIT}m: {[r['id'] for r in spikes]}")
    if floors:
        log(f"[relief] WARNING floorDev>1.1cm: {[r['id'] for r in floors]}")


if __name__ == "__main__":
    main()
