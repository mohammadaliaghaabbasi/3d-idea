#!/usr/bin/env python3
"""
Faitfhul Python mirror of public/js/collider.js `resolve()` for offline sweeps.

The first version of this sweep clamped to an axis-aligned box and pushed out of
obstacles without re-checking the walls, which reported hundreds of "escapes"
that were the harness's fault, not the engine's. This module reproduces the real
order and the real maths:

  1. walls
       polygon  -> circle-vs-segment push over ALL boundary segments, 2 passes
                   (concave-safe; this is what collider.js uses when Lane A has
                   produced walk.polygon)
       no poly  -> axis-aligned clamp against walk.bounds (legacy tangent slide)
  2. obstacles (after walls, no re-clamp — exactly like the runtime)
       cyl   -> radius = hw + R
       box   -> clamp into the yaw-rotated footprint, push along the closest
                edge; when the centre is inside, push along the shallowest axis

Measured afterwards, on the FINAL position:
    outside_mm   how far the capsule centre ended up outside the room boundary
    residual_mm  how far it still overlaps a collider (tolerance ~0 expected)
    egress       number of steps whose final position is outside the boundary
"""

from __future__ import annotations

import math

import numpy as np


def _circle_segment(x: float, z: float, ax: float, az: float,
                    bx: float, bz: float, R: float) -> tuple[float, float] | None:
    ex, ez = bx - ax, bz - az
    L2 = ex * ex + ez * ez
    if L2 < 1e-9:
        return None
    t = ((x - ax) * ex + (z - az) * ez) / L2
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    px, pz = ax + ex * t, az + ez * t
    dx, dz = x - px, z - pz
    d = math.hypot(dx, dz)
    if d >= R:
        return None
    if d < 1e-6:
        L = math.sqrt(L2)
        nx, nz = -ez / L, ex / L          # inward normal for CCW winding
        d = 0.0
    else:
        nx, nz = dx / d, dz / d
    push = R - d
    return nx * push, nz * push


def _obb_push(x: float, z: float, o: dict, R: float) -> tuple[float, float] | None:
    ox, oz = float(o.get("x", 0.0)), float(o.get("z", 0.0))
    hw, hd = float(o.get("hw", 0.5)), float(o.get("hd", 0.5))
    rot = float(o.get("rot", 0.0))
    cr, sr = math.cos(-rot), math.sin(-rot)
    rx, rz = x - ox, z - oz
    lx, lz = cr * rx - sr * rz, sr * rx + cr * rz
    cx = max(-hw, min(hw, lx))
    cz = max(-hd, min(hd, lz))
    dx, dz = lx - cx, lz - cz
    d = math.hypot(dx, dz)
    if d >= R:
        return None
    if d < 1e-6:
        px = (hw + R) - abs(lx)
        pz = (hd + R) - abs(lz)
        if px < pz:
            lnx, lnz, push = (1.0 if lx >= 0 else -1.0), 0.0, px
        else:
            lnx, lnz, push = 0.0, (1.0 if lz >= 0 else -1.0), pz
    else:
        lnx, lnz, push = dx / d, dz / d, R - d
    fcr, fsr = math.cos(rot), math.sin(rot)
    wx = fcr * lnx - fsr * lnz
    wz = fsr * lnx + fcr * lnz
    return wx * push, wz * push


def _cyl_push(x: float, z: float, o: dict, R: float) -> tuple[float, float] | None:
    ox, oz = float(o.get("x", 0.0)), float(o.get("z", 0.0))
    rad = float(o.get("radius", o.get("r", o.get("hw", 0.5))))
    rr = rad + R
    dx, dz = x - ox, z - oz
    d = math.hypot(dx, dz)
    if d >= rr:
        return None
    if d < 1e-6:
        return (rr, 0.0)
    push = rr - d
    return dx / d * push, dz / d * push


def is_cyl(o: dict) -> bool:
    return (o.get("type") or "box").lower() in ("cyl", "cylinder", "circle")


def boundary_margin(x: float, z: float, walk: dict, R: float) -> float:
    """Signed distance to the room boundary: >0 inside, <0 outside (metres)."""
    poly = walk.get("polygon")
    if poly:
        # distance to the nearest segment, signed by the nearest-edge normal
        best = 1e9
        inside = True
        n = len(poly)
        for i in range(n):
            ax, az = poly[i][0], poly[i][1]
            bx, bz = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
            ex, ez = bx - ax, bz - az
            L2 = ex * ex + ez * ez or 1e-12
            t = max(0.0, min(1.0, ((x - ax) * ex + (z - az) * ez) / L2))
            d = math.hypot(x - (ax + ex * t), z - (az + ez * t))
            best = min(best, d)
            # cross product sign: inside is left of a CCW edge
            if (ex * (z - az) - ez * (x - ax)) < 0:
                inside = False
        return best if inside else -best
    b = walk.get("bounds") or {}
    m = min(x - b.get("minX", -1e9), b.get("maxX", 1e9) - x,
            z - b.get("minZ", -1e9), b.get("maxZ", 1e9) - z)
    return m


def obstacle_overlap(x: float, z: float, o: dict, R: float) -> float:
    """How deep the capsule still overlaps this collider (0 = clear)."""
    ox, oz = float(o.get("x", 0.0)), float(o.get("z", 0.0))
    if is_cyl(o):
        rad = float(o.get("radius", o.get("r", o.get("hw", 0.5))))
        return max(0.0, (rad + R) - math.hypot(x - ox, z - oz))
    hw, hd = float(o.get("hw", 0.5)), float(o.get("hd", 0.5))
    rot = float(o.get("rot", 0.0))
    cr, sr = math.cos(-rot), math.sin(-rot)
    rx, rz = x - ox, z - oz
    lx, lz = cr * rx - sr * rz, sr * rx + cr * rz
    cx = max(-hw, min(hw, lx))
    cz = max(-hd, min(hd, lz))
    return max(0.0, R - math.hypot(lx - cx, lz - cz))


def resolve(x: float, z: float, walk: dict) -> tuple[float, float]:
    R = float(walk.get("player_radius", walk.get("playerR", 0.3)))
    poly = walk.get("polygon")
    if poly:
        for _ in range(2):
            for i in range(len(poly)):
                a = poly[i]
                b = poly[(i + 1) % len(poly)]
                p = _circle_segment(x, z, a[0], a[1], b[0], b[1], R)
                if p:
                    x += p[0]
                    z += p[1]
    else:
        b = walk.get("bounds") or {}
        x = min(max(x, b.get("minX", -1e9) + R), b.get("maxX", 1e9) - R)
        z = min(max(z, b.get("minZ", -1e9) + R), b.get("maxZ", 1e9) - R)
    for o in walk.get("obstacles") or walk.get("colliders") or []:
        p = _cyl_push(x, z, o, R) if is_cyl(o) else _obb_push(x, z, o, R)
        if p:
            x += p[0]
            z += p[1]
    return x, z


def probe_room(walk: dict, steps: int = 20000, seed: int = 7,
               step_max: float = 0.10) -> dict:
    R = float(walk.get("player_radius", walk.get("playerR", 0.3)))
    b = walk.get("bounds") or {}
    poly = walk.get("polygon")
    if poly:
        cx = sum(p[0] for p in poly) / len(poly)
        cz = sum(p[1] for p in poly) / len(poly)
    else:
        cx = (b.get("minX", -2.0) + b.get("maxX", 2.0)) / 2
        cz = (b.get("minZ", -2.0) + b.get("maxZ", 2.0)) / 2
    x, z = resolve(cx, cz, walk)
    rng = np.random.default_rng(seed)
    outside_worst = 0.0
    residual_worst = 0.0
    egress = 0
    obs = walk.get("obstacles") or walk.get("colliders") or []
    for _ in range(steps):
        ang = rng.uniform(0.0, 2 * math.pi)
        step = rng.uniform(0.02, step_max)
        x, z = resolve(x + math.cos(ang) * step, z + math.sin(ang) * step, walk)
        m = boundary_margin(x, z, walk, R)
        if m < 0:
            egress += 1
            outside_worst = max(outside_worst, -m)
        for o in obs:
            residual_worst = max(residual_worst, obstacle_overlap(x, z, o, R))
    return {
        "steps": steps,
        "step_max_m": step_max,
        "mode": "polygon" if poly else "bounds",
        "obstacles": len(obs),
        "egress_steps": egress,
        "outside_mm_max": round(outside_worst * 1000, 2),
        "residual_overlap_mm_max": round(residual_worst * 1000, 4),
        "final_xz": [round(x, 3), round(z, 3)],
    }
