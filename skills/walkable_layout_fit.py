#!/usr/bin/env python3
"""
PANODROME — WALKABLE TRUTH ENGINE :: geometry core (v1)
======================================================

Turns a **metric ERP depth map** (one 360 equirectangular panorama) into a
**metric, collidable room layout**:

    floor plan polygon  +  floor/ceiling heights  +  obstacle OBBs  +  confidence

Design laws (see docs/15-walkable-truth-engine.md):
  * This module NEVER displaces, warps or bends the panorama. The photograph
    stays a pristine sphere; this only *measures* the room behind it.
  * Metric, not relative: every number is metres. A bad input scale produces a
    failed gate, never a pretty lie.
  * Deterministic and offline. Runs at bake time (skills/), never in the browser.
  * The output drives two consumers that must agree: exact collision, and the
    true-3D overlay.

Pipeline
  1. ERP depth -> metric point cloud, camera-facing normals (wide stencil).
  2. Gravity from the floor slab (histogram mode, not a mean).
  3. Vertical-plane connected components: a wall reaches from floor to ceiling,
     a wardrobe does not. This is what keeps furniture out of the floor plan.
  4. Floor plan = radial profile of *wall* points -> Manhattan wall lines ->
     orthogonal polygon by intersecting consecutive wall lines.
  5. Obstacles = everything neither floor/ceiling/wall -> XZ clusters -> OBBs.
  6. Gates: a layout that fails them must not ship.

Input : depth (H, W) float metres, ERP, row 0 = zenith, col 0 = theta 0
Output: JSON-serialisable dict.

CLI
  python3 skills/walkable_layout_fit.py depth.npy [--json-out out.json]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field

import numpy as np

EPS = 1e-9


# ----------------------------------------------------------------------------
# 1. ERP <-> Cartesian
# ----------------------------------------------------------------------------

def erp_directions(h: int, w: int) -> np.ndarray:
    """Unit direction per ERP pixel, Y-up world frame, theta = 0 at +Z."""
    theta = (np.arange(w, dtype=np.float64) + 0.5) / w * 2.0 * np.pi - np.pi
    phi = np.pi / 2.0 - (np.arange(h, dtype=np.float64) + 0.5) / h * np.pi
    ct, st = np.cos(theta)[None, :], np.sin(theta)[None, :]
    cp, sp = np.cos(phi)[:, None], np.sin(phi)[:, None]
    d = np.empty((h, w, 3), dtype=np.float64)
    d[..., 0] = cp * st                        # +X
    d[..., 1] = np.broadcast_to(sp, (h, w))    # +Y up
    d[..., 2] = cp * ct                        # +Z
    return d


def erp_to_points(depth: np.ndarray):
    h, w = depth.shape
    d = erp_directions(h, w)
    valid = np.isfinite(depth) & (depth > 0.05) & (depth < 120.0)
    pts = d * np.where(valid, depth, 0.0)[..., None]
    return pts, d, valid, depth


# ----------------------------------------------------------------------------
# 2. Normals (central differences, wide stencil)
# ----------------------------------------------------------------------------

def smooth_depth(depth: np.ndarray, k: int = 1) -> np.ndarray:
    """
    3x3 (or larger) median of the depth field, invalid kept invalid.

    Median, never mean: a mean across a silhouette invents a surface halfway
    between the chair and the wall behind it. The median removes the metric
    model's per-pixel ripple while leaving every real edge on one side.
    """
    a = np.where(depth > 0, depth, np.nan)
    stack = [np.roll(np.roll(a, dv, 0), du, 1)
             for dv in range(-k, k + 1) for du in range(-k, k + 1)]
    out = np.nanmedian(np.stack(stack), axis=0)
    return np.where(np.isfinite(out), out, 0.0)


def erp_normals(pts: np.ndarray, depth: np.ndarray, valid: np.ndarray,
                radius: int = 4, rel_tol: float = 0.06) -> tuple[np.ndarray, np.ndarray]:
    """
    A one-pixel stencil is hopeless: a depth model's per-pixel ripple is the same
    size as the one-pixel tangent (both ~0.6% of range), so the normal is noise.
    A +/- radius stencil makes the tangent radius-times longer while the noise
    stays put, i.e. SNR grows with the radius. Silhouettes are rejected by a
    continuity test across the whole span.
    """
    h, w = depth.shape
    r = max(1, int(radius))
    safe = np.where(valid, depth, np.nan)

    def shift(a, dy, dx):
        return np.roll(np.roll(a, dy, axis=0), dx, axis=1)

    rows = np.arange(h)[:, None]
    row_ok = (rows >= r) & (rows < h - r)

    p_u2, p_u1 = shift(pts, 0, r), shift(pts, 0, -r)
    p_v2, p_v1 = shift(pts, r, 0), shift(pts, -r, 0)
    d_u2, d_u1 = shift(safe, 0, r), shift(safe, 0, -r)
    d_v2, d_v1 = shift(safe, r, 0), shift(safe, -r, 0)

    with np.errstate(invalid="ignore", divide="ignore"):
        cont_u = np.abs(d_u2 / d_u1 - 1.0) < rel_tol
        cont_v = np.abs(d_v2 / d_v1 - 1.0) < rel_tol

    n = np.cross(p_u2 - p_u1, p_v2 - p_v1)
    nrm = np.linalg.norm(n, axis=2)
    # Near the poles the horizontal tangent collapses (cos phi -> 0), so a normal
    # there is pure noise. Require both tangents to be physically long enough.
    t_u = np.linalg.norm(p_u2 - p_u1, axis=2)
    t_v = np.linalg.norm(p_v2 - p_v1, axis=2)
    ok = (valid & cont_u & cont_v & row_ok & np.isfinite(nrm) & (nrm > 1e-9)
          & (t_u > 0.03) & (t_v > 0.03))
    n = np.divide(n, np.where(ok, nrm, 1.0)[..., None])

    facing = np.sum(n * pts, axis=2)
    n[facing > 0.0] *= -1.0
    return n, ok


# ----------------------------------------------------------------------------
# 3. Linear algebra helpers
# ----------------------------------------------------------------------------

def plane_from_points(p: np.ndarray) -> tuple[np.ndarray, float]:
    c = p.mean(axis=0)
    _, _, vt = np.linalg.svd(p - c, full_matrices=False)
    n = vt[-1]
    n = n / (np.linalg.norm(n) + EPS)
    return n, float(np.dot(n, c))


def rodrigues(axis: np.ndarray, angle: float) -> np.ndarray:
    x, y, z = axis
    k = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]], dtype=np.float64)
    return np.eye(3) + math.sin(angle) * k + (1.0 - math.cos(angle)) * (k @ k)


def rotation_from_to(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = a / (np.linalg.norm(a) + EPS)
    b = b / (np.linalg.norm(b) + EPS)
    v, c = np.cross(a, b), float(np.dot(a, b))
    if c < -0.999999:
        axis = np.cross(a, np.array([1.0, 0.0, 0.0]))
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, np.array([0.0, 0.0, 1.0]))
        return rodrigues(axis / np.linalg.norm(axis), np.pi)
    if np.linalg.norm(v) < 1e-12:
        return np.eye(3)
    return rodrigues(v / np.linalg.norm(v), math.atan2(np.linalg.norm(v), c))


def dominant_offset(vals: np.ndarray, bin_m: float = 0.01,
                    inlier_m: float = 0.06) -> float:
    """
    The strongest horizontal surface in a height distribution.

    A mean or a global plane fit is ruined by table tops and shelf boards: they
    are horizontal too, but small and high. The floor is the largest horizontal
    support, so histogram peak + tight inlier window is the honest estimator.
    """
    if len(vals) < 20:
        return float(np.median(vals)) if len(vals) else 0.0
    lo, hi = np.percentile(vals, [0.5, 99.5])
    if hi - lo < bin_m:
        return float(np.median(vals))
    edges = np.arange(lo, hi + bin_m, bin_m)
    hist, _ = np.histogram(vals, bins=edges)
    peak = 0.5 * (edges[int(np.argmax(hist))] + edges[int(np.argmax(hist)) + 1])
    inl = vals[np.abs(vals - peak) <= inlier_m]
    return float(np.median(inl)) if len(inl) else float(peak)


@dataclass
class Gravity:
    up: np.ndarray = field(default_factory=lambda: np.array([0.0, 1.0, 0.0]))
    tilt_deg: float = 0.0


def estimate_gravity(pts: np.ndarray, normals: np.ndarray, ok: np.ndarray) -> Gravity:
    cand = ok & (normals[..., 1] > 0.85) & (pts[..., 1] < 0.05)
    if int(cand.sum()) < 200:
        return Gravity()
    y0 = dominant_offset(pts[cand][:, 1])
    inl = cand & (np.abs(pts[..., 1] - y0) <= 0.06)
    if int(inl.sum()) < 200:
        return Gravity()
    n_f, _ = plane_from_points(pts[inl])
    if n_f[1] < 0:
        n_f = -n_f
    return Gravity(up=n_f, tilt_deg=math.degrees(math.acos(float(np.clip(n_f[1], -1, 1)))))


# ----------------------------------------------------------------------------
# 4. Connected components on the ERP grid (coarse, wrap-aware)
# ----------------------------------------------------------------------------

def component_labels(mask: np.ndarray, step: int = 4) -> np.ndarray:
    """
    Label connected regions of a boolean ERP mask on a coarse grid.

    Needed because "vertical surface" is not the same as "wall": a wardrobe side
    is a vertical plane too. What separates them is *vertical extent* — a wall
    spans floor to ceiling, furniture does not (checked by the caller).
    """
    h, w = mask.shape
    hs, ws = h // step, w // step
    small = mask[: hs * step, : ws * step].reshape(hs, step, ws, step).mean(axis=(1, 3)) > 0.5
    labels = np.zeros((hs, ws), dtype=np.int32)
    cur = 0
    for i in range(hs):
        for j in range(ws):
            if not small[i, j] or labels[i, j]:
                continue
            cur += 1
            stack = [(i, j)]
            labels[i, j] = cur
            while stack:
                a, b = stack.pop()
                for da in (-1, 0, 1):
                    for db in (-1, 0, 1):
                        na, nb = a + da, (b + db) % ws
                        if 0 <= na < hs and small[na, nb] and not labels[na, nb]:
                            labels[na, nb] = cur
                            stack.append((na, nb))
    return np.repeat(np.repeat(labels, step, axis=0), step, axis=1)[:h, :w]


def filter_wall_components(mask: np.ndarray, pts: np.ndarray,
                           min_height_frac: float = 0.62,
                           min_pixels: int = 400) -> np.ndarray:
    """Keep only vertical components whose vertical extent reads as a wall."""
    if int(mask.sum()) < min_pixels:
        return mask & False
    labels = component_labels(mask)
    out = np.zeros_like(mask)
    room_h = float(np.ptp(pts[mask][:, 1])) if int(mask.sum()) else 1.0
    for lab in np.unique(labels):
        if lab == 0:
            continue
        sel = (labels == lab) & mask
        if int(sel.sum()) < min_pixels:
            continue
        y = pts[sel][:, 1]
        if float(np.ptp(y)) >= min_height_frac * room_h:
            out |= sel
    return out


# ----------------------------------------------------------------------------
# 5. Classification
# ----------------------------------------------------------------------------

def classify(pts: np.ndarray, normals: np.ndarray, ok: np.ndarray,
             floor_y: float, ceil_y: float,
             poly: np.ndarray | None = None,
             wall_margin: float = 0.20) -> dict[str, np.ndarray]:
    """
    Floor / ceiling / wall / content.

    'Wall' is defined by the room boundary, not by surface orientation: a
    wardrobe side is a vertical plane too, and a wardrobe standing against a wall
    is connected to it in the image, so connected components cannot separate
    them. Once the floor plan exists, a wall is simply the outermost surface at
    that boundary; everything vertical and further inside is furniture.
    """
    y = pts[..., 1]
    ny = normals[..., 1]
    floor = ok & (ny > 0.85) & (np.abs(y - floor_y) < 0.10)
    ceiling = ok & (ny < -0.85) & (np.abs(y - ceil_y) < 0.12)
    vertical = ok & (np.abs(ny) < 0.25) & (y > floor_y + 0.05) & (y < ceil_y - 0.05)

    if poly is not None and len(poly) >= 3:
        d = np.full(y.shape, np.inf)
        vr = vertical
        if int(vr.sum()):
            d[vr] = dist_to_polygon(pts[vr][:, [0, 2]], poly)
        walls = vertical & (d < wall_margin)
    else:
        walls = vertical
    other = ok & ~floor & ~ceiling & ~walls
    return {"floor": floor, "ceiling": ceiling, "wall": walls,
            "vertical_raw": vertical, "other": other}


# ----------------------------------------------------------------------------
# 6. Radial profile of the walls
# ----------------------------------------------------------------------------

def radial_profile(pts: np.ndarray, mask: np.ndarray, bins: int = 720,
                   quantile: float = 0.5,
                   min_count: int = 6) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Room boundary radius per azimuth bin. A vertical wall's horizontal radius IS
    the distance to that wall, so the median over a bin is its foot, no
    extrapolation. Floor points are a fallback only (a high quantile, because the
    floor fills the area and the outline is its outermost extent).
    """
    centres = (np.arange(bins) + 0.5) / bins * 2 * np.pi - np.pi
    prof = np.full(bins, np.nan)
    counts = np.zeros(bins, dtype=np.int64)

    p = pts[mask]
    if len(p) < 50:
        return centres, prof, counts

    ang = np.arctan2(p[:, 0], p[:, 2])
    rad = np.linalg.norm(p[:, [0, 2]], axis=1)
    idx = np.clip(((ang + np.pi) / (2 * np.pi) * bins).astype(np.int64), 0, bins - 1)
    order = np.argsort(idx, kind="stable")
    idx_s, rad_s = idx[order], rad[order]
    bounds = np.searchsorted(idx_s, np.arange(bins + 1))
    for b in range(bins):
        lo, hi = bounds[b], bounds[b + 1]
        counts[b] = hi - lo
        if counts[b] >= min_count:
            prof[b] = float(np.quantile(rad_s[lo:hi], quantile))
    return centres, prof, counts


def fill_circular(prof: np.ndarray) -> np.ndarray:
    good = np.isfinite(prof)
    if good.sum() < len(prof) * 0.10:
        return np.zeros(0)
    if good.all():
        return prof
    gi = np.where(good)[0]
    return np.interp(np.arange(len(prof)), gi, prof[gi], period=len(prof))


# ----------------------------------------------------------------------------
# 7. Profile -> Manhattan wall lines -> orthogonal polygon
# ----------------------------------------------------------------------------

def estimate_yaw(normals: np.ndarray, wall_mask: np.ndarray) -> float:
    """
    Dominant wall orientation in degrees, folded into (-45, 45].

    Wall normals are perpendicular to their wall, and a regular building has two
    orthogonal wall families, so the data has a 90-degree period. Circular *mean*
    cannot be used (two families sit exactly 180 degrees apart after doubling and
    cancel each other), so this is a smoothed circular histogram peak.
    """
    if int(wall_mask.sum()) < 100:
        return 0.0
    nn = normals[wall_mask]
    ang = np.degrees(np.arctan2(nn[:, 0], nn[:, 2])) % 90.0
    nb = 180
    hist, _ = np.histogram(ang, bins=nb, range=(0.0, 90.0))
    k = np.array([1.0, 2.0, 3.0, 2.0, 1.0])
    padded = np.concatenate([hist[-2:], hist, hist[:2]])
    sm = np.convolve(padded, k / k.sum(), mode="same")[2:-2]
    yaw = (int(np.argmax(sm)) + 0.5) * (90.0 / nb)
    if yaw > 45.0:
        yaw -= 90.0
    return float(yaw)


def _runs(labels: np.ndarray) -> list[tuple[int, int, int]]:
    """Circular runs of equal labels -> [(label, start, end_exclusive)]."""
    n = len(labels)
    if n == 0:
        return []
    # rotate so that the array starts at a label change
    change = np.where(labels != np.roll(labels, 1))[0]
    if len(change) == 0:
        return [(int(labels[0]), 0, n)]
    s0 = int(change[0])
    labels = np.roll(labels, -s0)
    out, start = [], 0
    for i in range(1, n + 1):
        if i == n or labels[i] != labels[start]:
            out.append((int(labels[start]), (start + s0) % n, (i + s0) % n))
            start = i
    return out


def manhattan_walls(centres: np.ndarray, prof: np.ndarray, yaw: float,
                    snap_tol: float = 0.18) -> list[dict]:
    """
    Radial profile -> a small set of orthogonal wall lines.

    Doing the snapping in vertex space was wrong: a wall's footprint sweeps a
    continuous range of coordinates, so single-linkage clustering chained the
    whole room into one point. The correct object to quantise is the *wall line*:
    split the boundary into runs of constant orientation, take each run's median
    constant coordinate, and merge runs that agree within snap_tol.
    """
    if len(prof) == 0:
        return []
    x = prof * np.sin(centres)
    z = prof * np.cos(centres)

    # rotate by +yaw: estimate_yaw already returns the angle that *undoes* the
    # room's rotation (wall normals are perpendicular to their wall).
    yr = math.radians(yaw)
    c, s = math.cos(yr), math.sin(yr)
    xr = x * c - z * s
    zr = x * s + z * c

    p = np.stack([xr, zr], axis=1)
    tangent = np.roll(p, -1, axis=0) - p
    # orientation: wall along +x  => constant z ; wall along +z => constant x
    along_x = np.abs(tangent[:, 0]) >= np.abs(tangent[:, 1])
    labels = np.where(along_x, 1, 2)          # 1: z = const, 2: x = const

    walls = []
    for lab, a, b in _runs(labels):
        idx = np.arange(a, b) if b > a else np.concatenate([np.arange(a, len(p)), np.arange(0, b)])
        if len(idx) < 3:
            continue
        seg = p[idx]
        const = seg[:, 1] if lab == 1 else seg[:, 0]
        vary = seg[:, 0] if lab == 1 else seg[:, 1]
        walls.append({
            "orientation": "z" if lab == 1 else "x",   # axis the wall runs along
            "line": float(np.median(const)),
            "lo": float(vary.min()),
            "hi": float(vary.max()),
            "angle": float(np.median(centres[idx])),
            "samples": int(len(idx)),
        })
    if not walls:
        return []

    # merge neighbours on the same axis with the same line
    merged: list[dict] = []
    for w in walls:
        if merged and merged[-1]["orientation"] == w["orientation"] and \
                abs(merged[-1]["line"] - w["line"]) <= snap_tol:
            m = merged[-1]
            n = m["samples"] + w["samples"]
            m["line"] = (m["line"] * m["samples"] + w["line"] * w["samples"]) / n
            m["lo"], m["hi"] = min(m["lo"], w["lo"]), max(m["hi"], w["hi"])
            m["samples"] = n
            continue
        merged.append(dict(w))

    # circular merge of first/last
    if len(merged) > 1 and merged[0]["orientation"] == merged[-1]["orientation"] and \
            abs(merged[0]["line"] - merged[-1]["line"]) <= snap_tol:
        a, b = merged[0], merged.pop()
        n = a["samples"] + b["samples"]
        a["line"] = (a["line"] * a["samples"] + b["line"] * b["samples"]) / n
        a["lo"], a["hi"] = min(a["lo"], b["lo"]), max(a["hi"], b["hi"])
        a["samples"] = n
    return merged


def polygon_from_walls(walls: list[dict]) -> np.ndarray:
    """Intersect consecutive perpendicular wall lines -> orthogonal polygon."""
    if len(walls) < 3:
        return np.zeros((0, 2))
    order = sorted(range(len(walls)), key=lambda i: walls[i]["angle"])
    verts = []
    for k in range(len(order)):
        a = walls[order[k]]
        b = walls[order[(k + 1) % len(order)]]
        if a["orientation"] == b["orientation"]:
            continue
        if a["orientation"] == "z" and b["orientation"] == "x":
            verts.append([b["line"], a["line"]])        # x from b, z from a
        else:
            verts.append([a["line"], b["line"]])
    if len(verts) < 3:
        return np.zeros((0, 2))
    return np.asarray(verts, dtype=float)


def degrees_to_world(poly: np.ndarray, yaw: float) -> np.ndarray:
    """Inverse of the snapping rotation: back to world XZ."""
    if len(poly) == 0:
        return poly
    yr = math.radians(-yaw)
    c, s = math.cos(yr), math.sin(yr)
    return np.stack([poly[:, 0] * c - poly[:, 1] * s,
                     poly[:, 0] * s + poly[:, 1] * c], axis=1)


def refine_edges(pts: np.ndarray, vertical: np.ndarray, poly: np.ndarray,
                 frame_yaw: float, margin: float = 0.40,
                 min_points: int = 250) -> np.ndarray:
    """
    Re-fit every polygon edge to the wall pixels that actually belong to it.

    The radial profile cannot resolve a face seen at a very grazing angle: within
    one azimuth bin that face and its neighbour are blended, so a 1.00 m wall is
    reported as 1.25 m. The pixels of that face are few but they are on the
    plane, so a per-edge line fit recovers the true value. Vertices are then the
    intersections of consecutive edges, which keeps the polygon perfectly
    orthogonal.
    """
    if len(poly) < 3 or int(vertical.sum()) < 500:
        return poly
    vp = pts[vertical][:, [0, 2]]

    yr = math.radians(-frame_yaw)
    c, s = math.cos(yr), math.sin(yr)
    vr = np.stack([vp[:, 0] * c - vp[:, 1] * s,
                   vp[:, 0] * s + vp[:, 1] * c], axis=1)      # frame coords

    pp = np.stack([poly[:, 0] * c - poly[:, 1] * s,
                   poly[:, 0] * s + poly[:, 1] * c], axis=1)

    edges: list[tuple[str, float]] = []
    n = len(pp)
    for i in range(n):
        a, b = pp[i], pp[(i + 1) % n]
        d = b - a
        axis = "z" if abs(d[0]) >= abs(d[1]) else "x"      # constant coord
        k = 1 if axis == "z" else 0
        val = 0.5 * (a[k] + b[k])
        lo, hi = sorted((a[1 - k], b[1 - k]))
        sel = (np.abs(vr[:, k] - val) < margin) & (vr[:, 1 - k] > lo - margin) & \
              (vr[:, 1 - k] < hi + margin)
        if int(sel.sum()) >= min_points:
            val = float(np.median(vr[sel, k]))
        edges.append((axis, val))

    verts = []
    for i in range(n):
        ax_prev, v_prev = edges[i - 1]
        ax_cur, v_cur = edges[i]
        if ax_prev == ax_cur:
            continue
        x = v_prev if ax_prev == "x" else v_cur
        z = v_prev if ax_prev == "z" else v_cur
        verts.append([x, z])
    if len(verts) < 3:
        return poly
    verts = np.asarray(verts, dtype=float)
    # back to world
    cb, sb = math.cos(-yr), math.sin(-yr)
    return np.stack([verts[:, 0] * cb - verts[:, 1] * sb,
                     verts[:, 0] * sb + verts[:, 1] * cb], axis=1)


def polygon_area(poly: np.ndarray) -> float:
    if len(poly) < 3:
        return 0.0
    x, z = poly[:, 0], poly[:, 1]
    return float(abs(np.dot(x, np.roll(z, -1)) - np.dot(z, np.roll(x, -1))) / 2.0)


def polygon_ccw(poly: np.ndarray) -> np.ndarray:
    if len(poly) < 3:
        return poly
    a = 0.5 * (np.dot(poly[:, 0], np.roll(poly[:, 1], -1))
               - np.dot(poly[:, 1], np.roll(poly[:, 0], -1)))
    return poly if a > 0 else poly[::-1]


def dist_to_polygon(q: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Per-point distance from XZ points to the nearest polygon edge."""
    if len(poly) < 2 or len(q) == 0:
        return np.full(len(q), np.inf)
    ab = np.roll(poly, -1, axis=0) - poly
    denom = (ab ** 2).sum(axis=1) + EPS
    ap = q[:, None, :] - poly[None, :, :]
    t = np.clip((ap * ab[None, :, :]).sum(axis=2) / denom[None, :], 0.0, 1.0)
    proj = poly[None, :, :] + t[..., None] * ab[None, :, :]
    return np.linalg.norm(q[:, None, :] - proj, axis=2).min(axis=1)


def mean_dist_to_polygon(q: np.ndarray, poly: np.ndarray, stride: int = 3) -> float:
    if len(poly) < 3 or len(q) == 0:
        return 0.0
    return float(dist_to_polygon(q[::stride], poly).mean())


# ----------------------------------------------------------------------------
# 8. Obstacles
# ----------------------------------------------------------------------------

def _convex_hull(points: np.ndarray) -> np.ndarray:
    p = np.unique(np.round(points, 4), axis=0)
    if len(p) < 3:
        return p
    p = p[np.lexsort((p[:, 1], p[:, 0]))]

    def cr(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for q in p:
        while len(lower) >= 2 and cr(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in p[::-1]:
        while len(upper) >= 2 and cr(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return np.array(lower[:-1] + upper[:-1])


def min_area_box(pts_xz: np.ndarray, prefer_yaw: float | None = None,
                 prefer_tolerance: float = 1.12):
    """
    Oriented bounding rectangle of a footprint.

    A pure minimum-area search is unstable on a jagged hull: it happily rotates
    30 degrees off a wall to shave 4% of area, and furniture that is visibly
    skewed destroys the sense of a real room. When the room frame is known, an
    axis-aligned candidate is preferred unless it is clearly worse.
    """
    hull = _convex_hull(pts_xz)
    if len(hull) < 3:
        c = pts_xz.mean(axis=0)
        return c, np.eye(2), np.ptp(pts_xz, axis=0)
    best = None
    for i in range(len(hull)):
        e = hull[(i + 1) % len(hull)] - hull[i]
        n = np.linalg.norm(e)
        if n < 1e-9:
            continue
        u = e / n
        v = np.array([-u[1], u[0]])
        pu, pv = hull @ u, hull @ v
        ext = np.array([pu.max() - pu.min(), pv.max() - pv.min()])
        area = float(ext[0] * ext[1])
        if best is None or area < best[0]:
            centre = 0.5 * (pu.max() + pu.min()) * u + 0.5 * (pv.max() + pv.min()) * v
            best = (area, centre, np.stack([u, v]), ext)
    if best is None:
        return pts_xz.mean(axis=0), np.eye(2), np.ptp(pts_xz, axis=0)

    if prefer_yaw is not None:
        phi = math.radians(prefer_yaw)
        u = np.array([math.cos(phi), math.sin(phi)])
        v = np.array([-u[1], u[0]])
        pu, pv = hull @ u, hull @ v
        ext = np.array([pu.max() - pu.min(), pv.max() - pv.min()])
        area_pref = float(ext[0] * ext[1])
        if area_pref <= prefer_tolerance * best[0]:
            centre = 0.5 * (pu.max() + pu.min()) * u + 0.5 * (pv.max() + pv.min()) * v
            return centre, np.stack([u, v]), ext
    return best[1], best[2], best[3]


def polygon_frame_yaw(poly: np.ndarray) -> float:
    """Dominant edge orientation of a polygon, folded into (-45, 45]."""
    if len(poly) < 3:
        return 0.0
    e = np.roll(poly, -1, axis=0) - poly
    ang = np.degrees(np.arctan2(e[:, 1], e[:, 0]))
    w = np.linalg.norm(e, axis=1)
    nb = 90
    hist, _ = np.histogram((ang % 90.0), bins=nb, range=(0.0, 90.0), weights=w)
    yaw = (int(np.argmax(hist)) + 0.5) * (90.0 / nb)
    return float(yaw - 90.0 if yaw > 45.0 else yaw)


def find_obstacles(pts: np.ndarray, mask: np.ndarray, floor_y: float, ceil_y: float,
                   poly: np.ndarray | None = None, cell: float = 0.10,
                   min_pts: int = 250, min_area: float = 0.04,
                   edge_margin: float = 0.12) -> list[dict]:
    """
    Everything that is neither floor, ceiling nor wall, clustered into solids.

    The union of these three classes is not clean at seams: the wall/floor crease
    and the wall/ceiling crease always leave a few centimetres of unclassified
    fringe, and that fringe runs around the whole room, so a naive clustering
    reports one obstacle shaped like the room. Seam fringes are therefore cut by
    distance to the floor, ceiling and wall polygon before clustering.
    """
    frame_yaw = polygon_frame_yaw(poly) if poly is not None else None
    p = pts[mask]
    if len(p) < min_pts:
        return []
    p = p[(p[:, 1] > floor_y + 0.05) & (p[:, 1] < ceil_y - 0.05)]
    if len(p) < min_pts:
        return []
    if poly is not None and len(poly) >= 3:
        d = dist_to_polygon(p[:, [0, 2]], poly)
        p = p[d > edge_margin]
    if len(p) < min_pts:
        return []

    ij = np.floor(p[:, [0, 2]] / cell).astype(np.int64)
    cells: dict[tuple[int, int], list[int]] = {}
    for k, key in enumerate(ij):
        cells.setdefault((int(key[0]), int(key[1])), []).append(k)

    def neighbours(c):
        i, j = c
        out = []
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                nb = (i + di, j + dj)
                if nb in cells:
                    out.append(nb)
        return out

    seen, comps = set(), []
    for c in cells:
        if c in seen:
            continue
        stack, comp = [c], []
        seen.add(c)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nb in neighbours(cur):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        comps.append(comp)

    out = []
    for comp in comps:
        idx = [k for c in comp for k in cells[c]]
        if len(idx) < min_pts:
            continue
        q = p[idx]
        centre, axes, ext = min_area_box(q[:, [0, 2]], prefer_yaw=frame_yaw)
        if ext[0] * ext[1] < min_area:
            continue
        y0, y1 = float(np.quantile(q[:, 1], 0.02)), float(np.quantile(q[:, 1], 0.98))
        # Anything under ~15 cm is a threshold or a floor sliver, not an obstacle:
        # the capsule steps over it and a collider there only makes the walk jerky.
        if y1 - y0 < 0.15:
            continue
        out.append({
            "centre_xz": [round(float(centre[0]), 4), round(float(centre[1]), 4)],
            "yaw_deg": round(float(math.degrees(math.atan2(axes[0][1], axes[0][0]))), 2),
            "extent_xz": [round(float(ext[0]), 4), round(float(ext[1]), 4)],
            "base_y": round(float(y0), 4),
            "top_y": round(float(y1), 4),
            "points": int(len(idx)),
        })
    out.sort(key=lambda d: -d["points"])
    return out


# ----------------------------------------------------------------------------
# 9. Gates
# ----------------------------------------------------------------------------

GATES = {
    "floor_flat_rms_m": 0.02,
    "wall_plumb_deg": 1.5,
    "ceiling_h_m": (2.20, 6.00),
    "area_m2": (3.0, 1200.0),
    "coverage": 0.45,
    "manhattan_resid_m": 0.22,
}


def run_gates(res: dict) -> dict:
    c = res["confidence"]
    checks = {
        "floor_flat": c["floor_flat_rms_m"] <= GATES["floor_flat_rms_m"],
        "wall_plumb": c["wall_plumb_deg"] <= GATES["wall_plumb_deg"],
        "ceiling_height": GATES["ceiling_h_m"][0] <= res["ceiling_h"] <= GATES["ceiling_h_m"][1],
        "area": GATES["area_m2"][0] <= res["area_m2"] <= GATES["area_m2"][1],
        "coverage": c["coverage"] >= GATES["coverage"],
        "manhattan": c["manhattan_resid_m"] <= GATES["manhattan_resid_m"],
        "polygon_closed": len(res["floor_polygon"]) >= 3,
    }
    checks["all_pass"] = all(checks.values())
    return {k: bool(v) for k, v in checks.items()}


# ----------------------------------------------------------------------------
# 10. Public API
# ----------------------------------------------------------------------------

def fit_layout(depth: np.ndarray, *, profile_bins: int = 720,
               snap_tol: float = 0.18) -> dict:
    """Metric ERP depth (metres) -> collidable room layout. Deterministic."""
    depth = np.asarray(depth, dtype=np.float64)
    depth = smooth_depth(depth)
    pts, _dirs, valid, _ = erp_to_points(depth)
    normals, ok = erp_normals(pts, depth, valid, radius=2, rel_tol=0.06)
    if int(ok.sum()) < 500:
        raise ValueError("depth map has too few usable pixels")

    grav = estimate_gravity(pts, normals, ok)
    if grav.tilt_deg > 0.30:
        R = rotation_from_to(grav.up, np.array([0.0, 1.0, 0.0]))
        pts = pts @ R.T
        normals = normals @ R.T

    # --- planes -----------------------------------------------------------
    down = ok & (normals[..., 1] > 0.85) & (pts[..., 1] < 0.05)
    if int(down.sum()) < 300:
        raise ValueError("no floor detected")
    floor_y = dominant_offset(pts[down][:, 1])
    inl_floor = down & (np.abs(pts[..., 1] - floor_y) <= 0.06)
    n_f, d_f = plane_from_points(pts[inl_floor])
    if n_f[1] < 0:
        n_f, d_f = -n_f, -d_f
    if abs(n_f[1]) > 0.9:
        floor_y = float(d_f / n_f[1])
    floor_res = np.abs(pts[inl_floor][:, 1] - floor_y)

    up = ok & (normals[..., 1] < -0.85) & (pts[..., 1] > max(floor_y + 0.5, 0.3))
    ceil_y = dominant_offset(pts[up][:, 1]) if int(up.sum()) > 100 else floor_y + 2.8

    # --- floor plan: the outermost vertical surface per azimuth is a wall ---
    vertical = ok & (np.abs(normals[..., 1]) < 0.25) & \
        (pts[..., 1] > floor_y + 0.05) & (pts[..., 1] < ceil_y - 0.05)
    if int(vertical.sum()) < 500:
        raise ValueError("no wall surfaces: depth is not a metric interior panorama")

    centres, wall_prof, _ = radial_profile(pts, vertical, bins=profile_bins,
                                            quantile=0.92, min_count=8)
    floor_cand = ok & (normals[..., 1] > 0.85) & (np.abs(pts[..., 1] - floor_y) < 0.10)
    _, floor_prof, _ = radial_profile(pts, floor_cand, bins=profile_bins,
                                       quantile=0.99, min_count=4)
    prof = fill_circular(np.where(np.isfinite(wall_prof), wall_prof, floor_prof))
    if len(prof) == 0:
        raise ValueError("floor plan could not be recovered")

    yaw = estimate_yaw(normals, vertical)
    walls = manhattan_walls(centres, prof, yaw, snap_tol=snap_tol)
    poly_snapped = polygon_from_walls(walls)
    poly = degrees_to_world(poly_snapped, yaw) if len(poly_snapped) >= 3 else np.zeros((0, 2))
    poly = polygon_ccw(poly)

    # Pass 2: with a boundary available, the wall pixels can be selected by
    # distance, so the profile can use the median (the wall foot itself) instead
    # of the outer quantile that was only there to reject furniture in pass 1.
    if len(poly) >= 3:
        d_v = np.full(pts[..., 1].shape, np.inf)
        if int(vertical.sum()):
            d_v[vertical] = dist_to_polygon(pts[vertical][:, [0, 2]], poly)
        wall_near = vertical & (d_v < 0.30)
        if int(wall_near.sum()) > 500:
            c2, p2, _cnt = radial_profile(pts, wall_near, bins=profile_bins,
                                           quantile=0.5, min_count=8)
            p2 = fill_circular(np.where(np.isfinite(p2), p2, prof))
            w2 = manhattan_walls(c2, p2, yaw, snap_tol=snap_tol)
            poly2 = polygon_from_walls(w2)
            if len(poly2) >= 3:
                poly2 = polygon_ccw(degrees_to_world(poly2, yaw))
                a0, a1 = polygon_area(poly), polygon_area(poly2)
                if a0 > 0 and 0.7 < a1 / a0 < 1.4:
                    poly, walls, prof, centres = poly2, w2, p2, c2

    poly = polygon_ccw(refine_edges(pts, vertical, poly, polygon_frame_yaw(poly)))
    cls = classify(pts, normals, ok, floor_y, ceil_y, poly=poly)

    bx, bz = prof * np.sin(centres), prof * np.cos(centres)
    boundary = np.stack([bx, bz], axis=1)
    man_res = mean_dist_to_polygon(boundary, poly) if len(poly) >= 3 else 99.0
    area = polygon_area(poly)

    # --- plumb from fitted wall planes (not from pixel normals) ------------
    plumb = _plumb_from_walls(pts, cls["wall"], centres, walls, yaw, ceil_y - floor_y)

    obstacles = find_obstacles(pts, cls["other"], floor_y, ceil_y, poly=poly)

    res = {
        "schema": "panodrome.room_geometry/1",
        "units": "metres",
        "gravity": {"tilt_deg": round(grav.tilt_deg, 3), "yaw_deg": round(yaw, 3)},
        "camera_height_m": round(float(floor_y * -1.0), 4),
        "floor_y": round(float(floor_y), 4),
        "ceiling_h": round(float(ceil_y - floor_y), 4),
        "floor_polygon": [[round(float(a), 4), round(float(b), 4)] for a, b in poly],
        "walls": [{"orientation": w["orientation"], "line": round(w["line"], 4),
                   "samples": w["samples"]} for w in walls],
        "area_m2": round(float(area), 3),
        "obstacles": obstacles,
        "confidence": {
            "coverage": round(float(ok.sum()) / ok.size, 4),
            "floor_flat_rms_m": round(float(np.sqrt((floor_res ** 2).mean())), 4),
            "wall_plumb_deg": round(float(plumb), 3),
            "manhattan_resid_m": round(float(man_res), 4),
            "classified_floor_px": int(cls["floor"].sum()),
            "classified_wall_px": int(cls["wall"].sum()),
            "classified_other_px": int(cls["other"].sum()),
        },
    }
    res["gates"] = run_gates(res)
    return res


def _plumb_from_walls(pts: np.ndarray, wall_mask: np.ndarray, centres: np.ndarray,
                      walls: list[dict], yaw: float, room_h: float) -> float:
    """
    Worst wall-plane deviation from vertical, in degrees.

    Per-pixel normals cannot answer this question: at 4 degrees of stencil
    estimate noise they would fail every honest wall. The physical property is
    the *plane*, so each wall is fitted as a plane and checked once.
    """
    if not walls or int(wall_mask.sum()) < 200:
        return 90.0
    wp = pts[wall_mask]
    wang = np.arctan2(wp[:, 0], wp[:, 2])
    worst = 0.0
    for w in walls:
        if w["samples"] < 12:
            continue
        d = np.abs(((wang - w["angle"] + np.pi) % (2 * np.pi)) - np.pi)
        sel = d < 0.35
        if int(sel.sum()) < 200:
            continue
        q = wp[sel]
        if len(q) < 200:
            continue
        n, _ = plane_from_points(q)
        tilt = math.degrees(math.asin(float(np.clip(abs(n[1]), 0.0, 1.0))))
        worst = max(worst, tilt)
    return worst if worst > 0 else 0.0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Metric ERP depth -> collidable room layout")
    ap.add_argument("depth", help=".npy (H,W) metric depth in metres")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--bins", type=int, default=720)
    args = ap.parse_args(argv)

    depth = np.load(args.depth)
    res = fit_layout(depth, profile_bins=args.bins)
    out = json.dumps(res, ensure_ascii=False, indent=2)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
        print(f"wrote {args.json_out}")
    else:
        print(out)
    return 0 if res["gates"]["all_pass"] else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
