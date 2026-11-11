#!/usr/bin/env python3
"""
Lane C — WALK BUDGET.

A panorama records one viewpoint. Move away from it and part of the view starts
to show what the camera never saw. This module measures exactly how much, from
the depth map alone (no model, no GPU): it forward-projects the ERP depth to a
translated viewpoint and counts the pixels that end up with no source sample.

    radius_5pct_m = the largest translation where <= 5% of the view is unknown

That number is what lets the product be honest: inside it the photograph is
photographic; past it, pixels would have to be invented.

Deterministic by construction (fixed azimuth ring, no sampling randomness), so
the same room always yields the same budget.
"""

from __future__ import annotations

import math

import numpy as np

# a translation is judged on a fixed ring, so no direction is favoured
AZIMUTHS = 16
DISTANCES = (0.25, 0.5, 1.0, 1.5, 2.0, 3.0)


def _downsample(depth: np.ndarray, res: tuple[int, int]) -> np.ndarray:
    """Box-average the ERP depth onto a smaller grid (valid pixels only)."""
    h, w = res
    H, W = depth.shape
    if (H, W) == (h, w):
        return depth
    fy, fx = H // h, W // w
    d = depth[:h * fy, :w * fx]
    d = d.reshape(h, fy, w, fx)
    ok = np.isfinite(d) & (d > 0)
    tot = np.where(ok, d, 0.0).sum(axis=(1, 3))
    cnt = ok.sum(axis=(1, 3))
    return np.where(cnt > 0, tot / np.maximum(cnt, 1), 0.0)


def _directions(h: int, w: int) -> np.ndarray:
    """Unit rays for an equirectangular grid (y up, x right, z forward)."""
    phi = (np.arange(w) + 0.5) / w * 2.0 * math.pi - math.pi      # longitude
    theta = (np.arange(h) + 0.5) / h * math.pi                     # colatitude
    th, ph = np.meshgrid(theta, phi, indexing="ij")
    st = np.sin(th)
    return np.stack([st * np.sin(ph), np.cos(th), st * np.cos(ph)], axis=-1)


def _project(points: np.ndarray, t: np.ndarray, h: int, w: int) -> np.ndarray:
    """Project world points into an ERP camera at t -> flat pixel indices."""
    rel = points - t
    x, y, z = rel[..., 0], rel[..., 1], rel[..., 2]
    r = np.sqrt(x * x + y * y + z * z)
    safe = np.maximum(r, 1e-9)
    colat = np.arccos(np.clip(y / safe, -1.0, 1.0))        # 0 at +Y (up)
    lon = np.arctan2(x, z)                                  # 0 at +Z
    u = ((lon + math.pi) / (2 * math.pi) * w).astype(np.int64) % w
    v = (colat / math.pi * h).astype(np.int64)
    np.clip(v, 0, h - 1, out=v)
    return (v * w + u).ravel(), r.ravel()


def _dilate(mask: np.ndarray) -> np.ndarray:
    """One-pixel dilation: a point splat covers its pixel footprint."""
    m = mask
    m = m | np.roll(m, 1) | np.roll(m, -1)
    m = m | np.roll(m, 1, axis=0) | np.roll(m, -1, axis=0)
    return m


def unknown_fraction(depth: np.ndarray, offset: np.ndarray,
                     res: tuple[int, int] = (192, 384), block: int = 4) -> float:
    """
    Fraction of the view with no source sample after `offset`.

    Judged per BLOCK (4x4 pixels), never per pixel: a single translated point
    splat changes its sampling density, which would fake pinholes everywhere.
    A block is unknown only when nothing at all lands in it. Validated against
    analytic rooms: a convex empty room must read ~0 at every interior offset
    (every surface is visible from every interior point), and a room with a
    sofa must grow behind the sofa.
    """
    h, w = res
    d = _downsample(np.asarray(depth, dtype=np.float64), res)
    valid = np.isfinite(d) & (d > 0)
    dirs = _directions(h, w)
    pts = (dirs * np.where(valid, d, 0.0)[..., None]).reshape(-1, 3)
    keep = valid.reshape(-1)
    idx, _r = _project(pts[keep], np.asarray(offset, dtype=np.float64), h, w)

    # Footprint-aware splatting: a surface close to the camera (a ceiling 0.4 m
    # away, a table edge) grows enormously when the viewpoint moves, so a
    # one-pixel dot would leave fake holes there. Each point is painted with a
    # radius that follows the translation/distance ratio; without this a convex
    # closed room reads 40% "unknown", which is physically impossible.
    dsel = d.reshape(-1)[keep]
    need = np.clip(np.ceil(1.0 + 2.0 * float(np.hypot(*(np.asarray(offset)[[0, 2]])))
                           / np.maximum(dsel, 0.2)), 1, 8).astype(int)
    covered = np.zeros(h * w, dtype=bool)
    for rad in np.unique(need):
        m = np.zeros(h * w, dtype=bool)
        m[idx[need == rad]] = True
        m = m.reshape(h, w)
        for _ in range(int(rad) - 1):
            m = _dilate(m)
        covered |= m.reshape(-1)
    covered = covered.reshape(h, w)

    bh, bw = h // block, w // block
    cov_b = covered[:bh * block, :bw * block].reshape(bh, block, bw, block).sum(axis=(1, 3))
    val_b = valid[:bh * block, :bw * block].reshape(bh, block, bw, block).sum(axis=(1, 3))
    judge = val_b > (block * block) // 2
    unknown = ((cov_b == 0) & judge).sum()
    return float(unknown) / max(int(judge.sum()), 1)


def walk_budget(depth: np.ndarray,
                distances=DISTANCES,
                azimuths: int = AZIMUTHS,
                res: tuple[int, int] = (192, 384)) -> dict:
    """
    Walk budget for one panorama.

    Returns the worst-case hole fraction at each distance (mean over a fixed
    azimuth ring and the worst azimuth), plus the two radii the runtime uses.
    """
    d = np.asarray(depth, dtype=np.float64)
    mean_curve, worst_curve = {}, {}
    for t in distances:
        fracs = []
        for k in range(1, azimuths + 1):        # exclude 0: it is the capture point
            a = 2.0 * math.pi * k / azimuths
            off = (t * math.cos(a), 0.0, t * math.sin(a))
            fracs.append(unknown_fraction(d, off, res))
        mean_curve[t] = float(np.mean(fracs))
        worst_curve[t] = float(np.max(fracs))

    def radius(curve: dict, target: float) -> float:
        xs = sorted(curve)
        if curve[xs[0]] > target:
            return 0.0
        for a, b in zip(xs, xs[1:]):
            if curve[b] >= target:
                fa, fb = curve[a], curve[b]
                f = 0.0 if fb == fa else (target - fa) / (fb - fa)
                return round(a + f * (b - a), 2)
        return float(xs[-1])

    return {
        "curve": {f"{k:g}m": round(v, 4) for k, v in mean_curve.items()},
        "curve_worst_azimuth": {f"{k:g}m": round(v, 4) for k, v in worst_curve.items()},
        "radius_5pct_m": radius(mean_curve, 0.05),
        "radius_15pct_m": radius(mean_curve, 0.15),
        "worst_radius_5pct_m": radius(worst_curve, 0.05),
        "policy": "soft",       # photo inside 5% · matte geometry fill 5-15% · refuse beyond
        "measured_at_capture": round(float(unknown_fraction(
            d, (0.0, 0.0, 0.0), res)), 4),
    }


if __name__ == "__main__":  # tiny self-check on an analytic room
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from walkable_layout_selftest import render_depth
    poly = np.array([[-3, -2.1], [3, -2.1], [3, 2.1], [-3, 2.1]])
    depth = render_depth(512, 1024, poly, -1.6, 0.4, [])
    b = walk_budget(depth)
    print("capture-point holes (must be ~0):", b["measured_at_capture"])
    print("curve:", b["curve"])
    print("radius 5%:", b["radius_5pct_m"], "m · 15%:", b["radius_15pct_m"], "m")
