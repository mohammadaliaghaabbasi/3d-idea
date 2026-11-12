#!/usr/bin/env python3
"""
================================================================================
 PANODROME — R&D LOOP  (research → implement → measure → repeat)
================================================================================

The question this loop answers, with numbers instead of opinions:

    From ONE panorama + its metric depth, which splat configuration gives the
    best image as the camera walks away from the capture point?

It needs no GPU and no model, because the test room is ANALYTIC: we know its true
geometry (walls, floor, ceiling, two boxes) and its true surface colours, so a
reference image at ANY camera pose can be ray-cast exactly. A candidate splat
cloud is rendered with an EWA-style footprint splatter and scored with PSNR
against those references at 0.0 / 0.5 / 1.0 m.

Each iteration builds candidates, measures them, keeps the Pareto front, and
shrinks the search around the winner. The loop stops when an iteration improves
the best score by less than `--min-gain` dB (or when the budget runs out), and
prints the configuration it converged on so it can be baked into the engine.

    python3 skills/rd_loop.py --iters 4 --out docs/agent-work/<session>/rd_results.json
================================================================================
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from walkable_layout_selftest import render_depth          # noqa: E402
from make_demo_splat import POLY, CAM_H, CEIL, BOXES, W as PW, H as PH  # noqa: E402
from bake_splat import ENG_directions                     # noqa: E402

FLOOR_Y = -CAM_H
CEIL_Y = CEIL
SH_C0 = 0.28209479177387814

# render settings for the scorer (small = fast, still discriminative)
RW, RH = 320, 180
FOV_Y = math.radians(72.0)
POSES = [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (1.0, 0.0, 0.0)]
YAW = 0.0            # look along -Z (into the room)


# --------------------------------------------------------------------- scene

def surface_colour(p: np.ndarray, kind: np.ndarray) -> np.ndarray:
    """The same rules `make_demo_splat.synth_colour` uses, evaluated per point."""
    x, y, z = p[:, 0], p[:, 1], p[:, 2]
    out = np.zeros((len(p), 3))
    floor = kind == 0
    ceil = kind == 1
    wall = kind == 2
    box = kind == 3
    chk = (np.floor(x / 0.6) + np.floor(z / 0.6)) % 2
    out[floor] = np.where(chk[floor][:, None] > 0, [0.66, 0.47, 0.31], [0.52, 0.35, 0.22])
    out[ceil] = [0.92, 0.93, 0.90]
    lon = np.degrees(np.arctan2(x, z)) % 360.0
    sector = (lon // 90).astype(int) % 4
    wall_cols = np.array([[0.82, 0.74, 0.62], [0.70, 0.76, 0.78],
                          [0.86, 0.78, 0.70], [0.74, 0.70, 0.76]])
    band = ((np.floor(y / 0.35) + np.floor(lon / 12.0)) % 2)[..., None]
    out[wall] = (wall_cols[sector][wall] * np.where(band[wall] > 0, 1.0, 0.90))
    out[box] = np.where((y[box] > -1.0)[:, None], [0.20, 0.36, 0.34], [0.30, 0.30, 0.32])
    return out


def _safe_div(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """Division that never produces NaN/inf warnings: parallel rays give inf."""
    num, den = np.broadcast_arrays(np.asarray(num, dtype=np.float64),
                                   np.asarray(den, dtype=np.float64))
    out = np.full(num.shape, np.inf, dtype=np.float64)
    ok = np.abs(den) > 1e-9
    out[ok] = num[ok] / den[ok]
    return out


def raycast(origin: np.ndarray, dirs: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Exact ray cast into the analytic room.

    Returns (t, point, kind) for the nearest hit; kind 0 floor / 1 ceiling /
    2 wall / 3 box. The room is closed, so every ray must hit something; a ray
    that reaches this function with kind < 0 is a bug and `make_cloud` asserts it
    rather than silently painting it black (that is what produced the dark dots
    in the first, un-calibrated scorer).
    """
    n = len(dirs)
    best_t = np.full(n, np.inf)
    kind = np.full(n, -1, dtype=np.int8)
    o = np.asarray(origin, dtype=np.float64)

    for y_plane, k in ((FLOOR_Y, 0), (CEIL_Y, 1)):
        t = _safe_div(np.full(n, y_plane - o[1]), dirs[:, 1])
        p = o + dirs * t[:, None]
        inside = (t > 0) & (t < best_t) & \
                 (np.abs(p[:, 0]) <= 3.0) & (np.abs(p[:, 2]) <= 2.1)
        best_t[inside] = t[inside]
        kind[inside] = k

    for val, axis in ((-3.0, 0), (3.0, 0), (-2.1, 2), (2.1, 2)):
        t = _safe_div(np.full(n, val - o[axis]), dirs[:, axis])
        p = o + dirs * t[:, None]
        ok = (t > 0) & (t < best_t) & \
             (p[:, 1] >= FLOOR_Y - 1e-9) & (p[:, 1] <= CEIL_Y + 1e-9) & \
             (np.abs(p[:, 0]) <= 3.0 + 1e-9) & (np.abs(p[:, 2]) <= 2.1 + 1e-9)
        best_t[ok] = t[ok]
        kind[ok] = 2

    for (x0, x1, z0, z1, y0, y1) in BOXES:
        lo = np.array([x0, y0, z0], dtype=np.float64)
        hi = np.array([x1, y1, z1], dtype=np.float64)
        t1 = _safe_div(lo - o, dirs)
        t2 = _safe_div(hi - o, dirs)
        tmin = np.max(np.minimum(t1, t2), axis=1)
        tmax = np.min(np.maximum(t1, t2), axis=1)
        ok = (tmax >= tmin) & (tmin > 0) & (tmin < best_t)
        best_t[ok] = tmin[ok]
        kind[ok] = 3

    hit = kind >= 0
    t = np.where(hit, best_t, np.inf)
    p = o + dirs * np.where(hit, t, 0.0)[:, None]
    return t, p, kind


def camera_dirs(pos, yaw=YAW, w=RW, h=RH, fov_y=FOV_Y):
    """Pinhole rays for a camera at `pos` looking along -Z rotated by yaw."""
    fy = h / (2 * math.tan(fov_y / 2))
    fx = fy
    xs = (np.arange(w) + 0.5 - w / 2) / fx
    ys = -(np.arange(h) + 0.5 - h / 2) / fy
    gx, gy = np.meshgrid(xs, ys)
    d = np.stack([gx, gy, -np.ones_like(gx)], axis=-1)
    cy, sy = math.cos(yaw), math.sin(yaw)
    x = d[..., 0] * cy + d[..., 2] * sy
    z = -d[..., 0] * sy + d[..., 2] * cy
    d = np.stack([x, d[..., 1], z], axis=-1)
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    return d.reshape(-1, 3), fx, fy


def reference(pos, yaw=YAW):
    dirs, fx, fy = camera_dirs(pos, yaw)
    _t, p, kind = raycast(np.array(pos, dtype=float), dirs)
    img = np.zeros((len(p), 3))
    hit = kind >= 0
    img[hit] = surface_colour(p[hit], kind[hit])
    img[~hit] = 0.05
    return img.reshape(RH, RW, 3)


# ----------------------------------------------------------------- splatting

def project(points, pos, yaw=YAW):
    """Camera-space projection; returns (u, v, depth, valid)."""
    fy = RH / (2 * math.tan(FOV_Y / 2))
    d = points - np.asarray(pos, dtype=float)
    cy, sy = math.cos(yaw), math.sin(yaw)
    x = d[:, 0] * cy - d[:, 2] * sy
    z = d[:, 0] * sy + d[:, 2] * cy
    y = d[:, 1]
    depth = -z                       # camera looks along -Z
    ok = depth > 1e-3
    u = RW / 2 + fy * x / np.where(ok, depth, 1.0)
    v = RH / 2 - fy * y / np.where(ok, depth, 1.0)
    return u, v, depth, ok, fy


# Splat footprints: the kernel is a real gaussian evaluated over the 2-sigma
# window (the same support the GLSL discards past), tabulated per sigma bucket.
# The first version of this scorer bucketed by integer radius with a fixed
# 0.5*rad falloff, which left the rim of every large splat almost weightless —
# that produced the ring/dot artefacts and a meaningless 8 dB "score".
_SIGMA_BUCKETS = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0)
_KERNELS: dict[float, tuple[np.ndarray, np.ndarray]] = {}
EPS_SIGMA_PX = 0.45          # low-pass, as in the GLSL renderer (+0.3 on Var)
MAX_SIGMA_PX = 6.0           # clamp: a splat this close is a rare sub-pixel case


def kernel_table(sigma_px: float) -> tuple[np.ndarray, np.ndarray]:
    tab = _KERNELS.get(sigma_px)
    if tab is not None:
        return tab
    lim = max(1, int(math.ceil(2.0 * sigma_px)))
    offs, ws = [], []
    for dy in range(-lim, lim + 1):
        for dx in range(-lim, lim + 1):
            d2 = dx * dx + dy * dy
            if d2 > 4.0 * sigma_px * sigma_px:
                continue
            offs.append((dx, dy))
            ws.append(math.exp(-0.5 * d2 / (sigma_px * sigma_px)))
    tab = (np.array(offs, dtype=np.int64), np.array(ws, dtype=np.float64))
    _KERNELS[sigma_px] = tab
    return tab


def render_splats(points, colours, radii_m, pos, yaw=YAW, sigma=1.0):
    """
    Gaussian splatter with a 2-sigma window and a normalised weighted sum
    (order independent, no sorting needed). sigma is the splat radius in metres,
    converted per splat to pixels through the focal length and its own depth, so
    the real failure modes are preserved: over-blur where one gaussian has to
    carry many pixels, holes where coverage is thin.
    """
    u, v, depth, ok, fy = project(points, pos, yaw)
    accC = np.zeros((RH * RW, 3))
    accW = np.zeros(RH * RW)
    idx = np.flatnonzero(ok)
    if not len(idx):
        return accC, accW
    cols = colours[idx]
    sig = np.clip(radii_m[idx] * fy / np.maximum(depth[idx], 1e-3) * sigma,
                  EPS_SIGMA_PX, MAX_SIGMA_PX)
    # floor, not round: pixel centres project to exact .5 and np.round is
    # half-to-even, which maps every second column onto its neighbour and leaves
    # the columns in between empty (that alone cost ~8% coverage and ~16 dB).
    ui = np.floor(u[idx]).astype(np.int64)
    vi = np.floor(v[idx]).astype(np.int64)
    bucket_of = np.abs(sig[:, None] - np.array(_SIGMA_BUCKETS)[None, :]).argmin(axis=1)
    for b in np.unique(bucket_of):
        m = bucket_of == b
        offs, ws = kernel_table(_SIGMA_BUCKETS[b])
        px0, py0, cc = ui[m], vi[m], cols[m]
        for (dx, dy), w in zip(offs, ws):
            px = px0 + dx
            py = py0 + dy
            good = (px >= 0) & (px < RW) & (py >= 0) & (py < RH)
            if not good.any():
                continue
            flat = py[good] * RW + px[good]
            np.add.at(accC, flat, cc[good] * w)
            np.add.at(accW, flat, np.full(int(good.sum()), w))
    return accC, accW


def composite(accC, accW):
    out = np.full((RH * RW, 3), 0.05)
    have = accW > 1e-6
    out[have] = accC[have] / accW[have][:, None]
    return out.reshape(RH, RW, 3)


# ------------------------------------------------------------------ bake + score

_CLOUD_CACHE: dict[float, tuple[np.ndarray, np.ndarray, np.ndarray, int]] = {}


def make_cloud(density: float, sigma_px: float):
    """
    Build a cloud from the analytic room at the capture point.

    density  splats per photographed pixel (continuous: 0.25 .. 2.0 -> the
             nearest `n = density * pixels` ERP samples, evenly spaced; the old
             integer `step = round(1/density)` made 0.5 / 0.75 / 1.0 the same
             cloud, so the search could not tell them apart)
    sigma_px splat radius in PIXEL footprints at its own distance

    There is deliberately no anisotropy knob: this scorer renders 2D footprints,
    so a "depth extent along the normal" term is unobservable here and searching
    it would only rank noise.
    """
    cached = _CLOUD_CACHE.get(density)
    if cached is not None:
        pts, col, d, n = cached
        r = np.maximum(d * (2.0 * math.pi / PW) * sigma_px, 0.002)
        return pts, col, r, n
    depth = render_depth(PH, PW, POLY, FLOOR_Y, CEIL, BOXES)
    valid = np.isfinite(depth) & (depth > 0)
    idx = np.flatnonzero(valid.reshape(-1))
    target = int(round(len(idx) * max(density, 1e-6)))
    target = max(1, min(target, len(idx)))
    idx = idx[np.linspace(0, len(idx) - 1, target).astype(np.int64)]
    dirs = ENG_directions(PH, PW).reshape(-1, 3)[idx]
    d = depth.reshape(-1)[idx]
    pts = dirs * d[:, None]
    _t, hit, kind = raycast(np.zeros(3), dirs)
    if np.any(kind < 0):
        raise AssertionError(f"{int((kind < 0).sum())} ERP rays missed the closed room "
                             "— fix raycast() before trusting any score")
    col = surface_colour(hit, kind)
    # angular size of one ERP pixel at that distance, scaled by sigma_px
    _CLOUD_CACHE[density] = (pts, col, d, int(len(idx)))
    r = np.maximum(d * (2.0 * math.pi / PW) * sigma_px, 0.002)
    return pts, col, r, int(len(idx))


def psnr(a, b):
    mse = float(np.mean((a - b) ** 2))
    return 99.0 if mse <= 1e-12 else 10.0 * math.log10(1.0 / mse)


def evaluate(cfg: dict) -> dict:
    pts, col, r, n = make_cloud(cfg["density"], cfg["sigma_px"])
    scores = {}
    for pos in POSES:
        accC, accW = render_splats(pts, col, r, pos, sigma=1.0)
        img = composite(accC, accW)
        ref = reference(pos)
        covered = float(np.mean(accW > 1e-6))
        scores[f"{pos[0]:.2f}m"] = {"psnr": round(psnr(img, ref), 3),
                                    "coverage": round(covered, 4)}
    mean_psnr = float(np.mean([s["psnr"] for s in scores.values()]))
    # bytes estimate: SPZ v2 is ~8 B/splat measured
    size_mb = n * 8.0 / 1e6
    score = mean_psnr - 0.35 * size_mb          # 0.35 dB per MB, explicit trade
    return {"config": cfg, "splats": n, "size_mb_est": round(size_mb, 2),
            "px_per_splat": round(PW * PH / max(n, 1), 2),
            "per_pose": scores, "mean_psnr": round(mean_psnr, 3),
            "score": round(score, 3)}


# ------------------------------------------------------------ calibration test
def self_test(sigma_px: float = 0.5) -> dict:
    """
    Calibrate the scorer against itself.

    A cloud is built FROM the reference camera (one splat per pixel, at the exact
    hit point, with a sub-pixel radius) and rendered straight back. Nothing is
    sampled, resampled or guessed, so a sound scorer must reproduce the reference
    almost exactly. If this fails, every candidate ranking downstream is noise —
    which is exactly what the 8 dB first run was.
    """
    pos = POSES[0]
    dirs, _fx, fy = camera_dirs(pos)
    t, p, kind = raycast(np.array(pos, dtype=float), dirs)
    if np.any(kind < 0):
        return {"pass": False, "reason": f"{int((kind < 0).sum())} rays missed the room"}
    col = surface_colour(p, kind)
    radii = np.maximum(sigma_px * t / fy, 1e-4)
    accC, accW = render_splats(p, col, radii, pos)
    img = composite(accC, accW)
    ref = reference(pos)
    value = psnr(img, ref)
    cov = float(np.mean(accW > 1e-6))
    return {"psnr": round(value, 2), "coverage": round(cov, 4),
            "threshold_psnr": 30.0, "pass": bool(value >= 30.0 and cov >= 0.985)}


# ---------------------------------------------------------------------- loop

def refine_around(best: dict, iteration: int) -> list[dict]:
    d0, s0 = best["density"], best["sigma_px"]
    dd = 0.25 / (2 ** iteration)
    ds = 0.15 / (2 ** iteration)
    cands = []
    for d in sorted({max(0.1, d0 - dd), d0, d0 + dd}):
        for s in sorted({max(0.3, s0 - ds), s0, s0 + ds}):
            cands.append({"density": round(d, 3), "sigma_px": round(s, 3)})
    return cands


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R&D loop: score splat configs against analytic truth")
    ap.add_argument("--iters", type=int, default=4)
    ap.add_argument("--min-gain", type=float, default=0.05, help="dB")
    ap.add_argument("--quick", action="store_true", help="small grid for a smoke run")
    ap.add_argument("--self-test", action="store_true", help="calibrate the scorer and exit")
    ap.add_argument("--force", action="store_true", help="run even if self-test fails")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "agent-work",
                                                 "2026-11-12-rd-loop", "rd_results.json"))
    args = ap.parse_args(argv)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    st = self_test()
    print(f"self-test  {st.get('psnr')} dB · coverage {st.get('coverage')} -> "
          f"{'PASS' if st.get('pass') else 'FAIL'}")
    if args.self_test:
        return 0 if st.get("pass") else 2
    if not st.get("pass") and not args.force:
        print("refusing to rank candidates on an uncalibrated scorer "
              "(fix the kernel, or pass --force)")
        return 2

    history, best = [], None
    if args.quick:
        grid = [{"density": d, "sigma_px": 0.9} for d in (0.5, 1.0, 2.0)]
    else:
        grid = [{"density": d, "sigma_px": s}
                for d in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0)
                for s in (0.5, 0.75, 0.9, 1.2, 1.5)]
    cands = grid
    for it in range(args.iters):
        t0 = time.time()
        rows = [evaluate(c) for c in cands]
        rows.sort(key=lambda r: -r["score"])
        top = rows[0]
        gain = None if best is None else top["score"] - best["score"]
        print(f"iter {it}: {len(rows)} candidates in {time.time() - t0:.1f}s · "
              f"best score {top['score']} ({top['mean_psnr']} dB, "
              f"{top['splats']} splats, {top['size_mb_est']} MB est) "
              f"density {top['config']['density']} sigma {top['config']['sigma_px']}"
              + (f" · gain {gain:+.3f} dB" if gain is not None else ""))
        history.append({"iteration": it, "evaluated": len(rows),
                        "best": top, "gain_db": None if gain is None else round(gain, 3),
                        "top5": rows[:5]})
        if gain is not None and gain < args.min_gain:
            print(f"  converged: gain {gain:+.3f} dB < {args.min_gain} dB")
            best = top
            break
        best = top
        cands = refine_around(top["config"], it)

    payload = {"self_test": st,
               "poses": [f"{p[0]:.2f}m" for p in POSES],
               "render": {"w": RW, "h": RH, "fov_y_deg": 72.0},
               "objective": "mean PSNR(dB) - 0.35 * estimated MB",
               "iterations": history, "winner": best,
               "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with open(args.out, "w") as fh:
        json.dump(payload, fh, indent=1)
    print(f"\nWINNER  density {best['config']['density']} · sigma {best['config']['sigma_px']} "
          f"· {best['mean_psnr']} dB · {best['px_per_splat']} px/splat · "
          f"{best['size_mb_est']} MB")
    print(f"  -> {os.path.relpath(args.out, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
