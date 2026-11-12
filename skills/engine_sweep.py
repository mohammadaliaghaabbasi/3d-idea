#!/usr/bin/env python3
"""
================================================================================
 PANODROME — ENGINE SWEEP  (one harness, three populations)
================================================================================

    python3 skills/engine_sweep.py --group moradi
    python3 skills/engine_sweep.py --group houses
    python3 skills/engine_sweep.py --group villa

It answers three questions with numbers instead of impressions:

  A · MORADI (10 live scenes, owner's real 360 set)
      For each scene: panorama pixels, gaussian count from the SPZ header, and
      px_per_splat — the sharpness ceiling of that cloud — then a COVERAGE test:
      the point cloud is re-projected from a camera moved by 0.25/0.5/1.0/1.5 m
      and the fraction of viewing directions with no splat at all is measured.
      That is "what breaks when I walk", measured on the owner's own assets.

  B · HOUSES (10 curated 4K panos in this repo)
      Lane A status (a metric proxy needs 360 depth — absent here, reported as
      blocked, never faked) plus a real collision test: 20,000 random capsule
      steps per room through the runtime resolution rules (bounds clamp + box /
      cylinder push-out) asserting the player never leaves the room and never
      enters a collider footprint.

  C · VILLA (modern_3d_villa — the true-3D room)
      Same collision test against the authored collider set, plus the geometry
      inventory (bounds, collider count/type, walkable area, GLB size).

Every run writes docs/agent-work/2026-11-12-engine-sweep/results.json.
Nothing outside docs/agent-work/<this session>/ is written.
================================================================================
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import math
import os
import struct
import sys
import urllib.request

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collision_probe import probe_room  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIVE = "https://mohammadaliaghaabbasi.github.io/panodrome"
LAB = f"{LIVE}/labs/engine-v1"
OUT_DIR = os.path.join(ROOT, "docs", "agent-work", "2026-11-12-engine-sweep")

MORADI = ["moradi_bed1a", "moradi_bed1b", "moradi_bed2a", "moradi_bed3a",
          "moradi_kit1", "moradi_kit2", "moradi_main1", "moradi_main2",
          "moradi_main3", "moradi_main4"]

GRID_W, GRID_H = 256, 128           # ERP grid for the coverage test
OFFSETS = [0.0, 0.25, 0.5, 1.0, 1.5]


# --------------------------------------------------------------------- helpers

def fetch(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "panodrome-sweep/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def image_size(path_or_bytes) -> tuple[int, int]:
    from PIL import Image
    im = Image.open(io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes)
                    else path_or_bytes)
    return im.size


def _decode_v4(blob: bytes) -> dict:
    """SPZ v4 = 'NGSP' header (16 B) + a zstd frame somewhere after it.

    Measured on the owner's assets: the decompressed stream is exactly n*20 bytes
    (positions 9n, alphas n, colours 3n, scales 3n, rotations 4n) and the zstd
    frame starts at byte 112 — the header is followed by an extension block, so
    the frame is located by its magic rather than by a fixed offset.
    """
    n = struct.unpack_from("<I", blob, 8)[0]
    frac = blob[13]
    i = blob.find(b"\x28\xb5\x2f\xfd")
    if i < 0:
        raise ValueError("SPZ v4 without a zstd frame")
    try:
        import io as _io
        import zstandard
    except ImportError as e:                                   # noqa: BLE001
        raise RuntimeError("SPZ v4 needs the 'zstandard' package") from e
    with zstandard.ZstdDecompressor().stream_reader(_io.BytesIO(blob[i:])) as r:
        body = r.read()
    raw = np.frombuffer(body, dtype=np.uint8, count=n * 9).reshape(n, 9)
    pos = np.empty((n, 3), dtype=np.float64)
    for a in range(3):
        u = (raw[:, a * 3].astype(np.int64)
             | (raw[:, a * 3 + 1].astype(np.int64) << 8)
             | (raw[:, a * 3 + 2].astype(np.int64) << 16))
        pos[:, a] = np.where(u >= (1 << 23), u - (1 << 24), u) / (1 << frac)
    alpha = np.frombuffer(body, dtype=np.uint8, count=n, offset=9 * n) / 255.0
    sb = np.frombuffer(body, dtype=np.uint8, count=n * 3, offset=13 * n).reshape(n, 3)
    scale = np.exp(sb / 16.0 - 10.0)
    return {"positions": pos, "alpha": alpha, "scale": scale,
            "version": 4, "sh": blob[12], "frac": frac}


def spz_points(blob: bytes) -> dict:
    """Minimal SPZ reader: v4 (zstd) and v2/v3 (gzip) — positions + scales + alpha."""
    if blob[:4] == b"NGSP":
        return _decode_v4(blob)
    body = gzip.decompress(blob) if blob[:2] == b"\x1f\x8b" else blob
    magic, version, n, sh, frac, flags, _ = struct.unpack_from("<IIIBBBB", body, 0)
    if magic != 0x5053474E:
        raise ValueError(f"not SPZ (magic {magic:#x})")
    o = 16
    raw = np.frombuffer(body, dtype=np.uint8, count=n * 9, offset=o).reshape(n, 9)
    o += n * 9
    pos = np.empty((n, 3), dtype=np.float64)
    for a in range(3):
        u = (raw[:, a * 3].astype(np.int64)
             | (raw[:, a * 3 + 1].astype(np.int64) << 8)
             | (raw[:, a * 3 + 2].astype(np.int64) << 16))
        pos[:, a] = np.where(u >= (1 << 23), u - (1 << 24), u) / (1 << frac)
    alpha = np.frombuffer(body, dtype=np.uint8, count=n, offset=o) / 255.0
    o += n
    o += n * 3                                     # colours (dc)
    sb = np.frombuffer(body, dtype=np.uint8, count=n * 3, offset=o).reshape(n, 3)
    scale = np.exp(sb / 16.0 - 10.0)
    return {"positions": pos, "alpha": alpha, "scale": scale,
            "version": version, "sh": sh, "frac": frac}


def coverage(points: np.ndarray, scale: np.ndarray, offset: tuple[float, float, float],
             w: int = GRID_W, h: int = GRID_H, cap_cells: int = 6) -> float:
    """
    Fraction of ERP directions that receive at least one splat when the camera
    moves by `offset`. Splat angular radius is respected (each point paints a
    small square), so a dense cloud reads ~1.0 and a sparse one shows holes.
    """
    p = points - np.asarray(offset, dtype=np.float64)
    d = np.linalg.norm(p, axis=1)
    ok = d > 1e-3
    p, d = p[ok], d[ok]
    if not len(p):
        return 0.0
    lon = np.arctan2(p[:, 0], p[:, 2])
    lat = np.arcsin(np.clip(p[:, 1] / d, -1.0, 1.0))
    u = ((lon + math.pi) / (2 * math.pi) * w).astype(np.int64) % w
    v = ((math.pi / 2 - lat) / math.pi * h).astype(np.int64)
    np.clip(v, 0, h - 1, out=v)
    # angular radius of the splat in cells
    ang_per_cell = 2 * math.pi / w
    sel = np.arange(0, len(p), max(1, len(p) // 60000))
    rad = np.arctan(scale[ok][sel][:, 0] / d[sel])
    cells = np.clip(np.ceil(rad / ang_per_cell).astype(np.int64), 1, cap_cells)

    grid = np.zeros((h, w), dtype=bool)
    uu, vv, cc = u[sel], v[sel], cells
    for du in range(-cap_cells, cap_cells + 1):
        for dv in range(-cap_cells, cap_cells + 1):
            m = (np.abs(du) <= cc) & (np.abs(dv) <= cc)
            if not np.any(m):
                continue
            grid[np.clip(vv[m] + dv, 0, h - 1), (uu[m] + du) % w] = True
    return float(grid.mean())


# ------------------------------------------------------------------ A · moradi

def sweep_moradi(scenes: list[str] | None = None) -> dict:
    rows = []
    for scene in (scenes or MORADI):
        row = {"scene": scene}
        try:
            pano = fetch(f"{LIVE}/assets/panoramas/{scene}.jpg")
            pw, ph = image_size(pano)
            row["pano_px"] = (pw, ph)
            row["pano_bytes"] = len(pano)
        except Exception as e:                                   # noqa: BLE001
            row["error_pano"] = str(e)
            rows.append(row)
            continue
        # the live lab carries TWO baked generations per scene (v11, v12)
        row["gens"] = {}
        for gen in ("v11", "v12"):
            try:
                blob = fetch(f"{LAB}/assets/{scene}_splat_{gen}.spz")
                pts = spz_points(blob)
                g = {
                    "spz_bytes": len(blob),
                    "splats": int(len(pts["positions"])),
                    "px_per_splat": round(pw * ph / len(pts["positions"]), 1),
                    "bbox_m": [[round(float(x), 2) for x in pts["positions"].min(axis=0)],
                               [round(float(x), 2) for x in pts["positions"].max(axis=0)]],
                }
                cov = {}
                for off in OFFSETS:
                    cov[f"{off:.2f}m"] = round(coverage(
                        pts["positions"], pts["scale"], (off, 0.0, 0.0)), 4)
                g["coverage"] = cov
                g["verdict"] = ("sharp-capable" if g["px_per_splat"] <= 1.5 else
                                "resampled" if g["px_per_splat"] <= 4 else
                                "cannot carry the photograph")
                row["gens"][gen] = g
            except Exception as e:                               # noqa: BLE001
                row["gens"][gen] = {"error": str(e)}
        # row summary = newest generation that loaded
        best = row["gens"].get("v12") or row["gens"].get("v11") or {}
        row["splats"] = best.get("splats")
        row["px_per_splat"] = best.get("px_per_splat")
        row["coverage"] = best.get("coverage")
        row["verdict"] = best.get("verdict")
        rows.append(row)
        print(f"  {scene:<16} {row.get('splats') or '?'} splats · "
              f"{row.get('px_per_splat') or '?'} px/splat · "
              f"coverage {row.get('coverage') or '{}'}")
    return {"group": "moradi", "count": len(rows), "rows": rows}


# ----------------------------------------------------------- collision engine
# Mirrors public/js/collider.js: bounds clamp first, then box/cylinder push-out.

def resolve(x: float, z: float, walk: dict) -> tuple[float, float, float]:
    r = float(walk.get("player_radius", 0.3))
    b = walk.get("bounds") or {}
    worst = 0.0
    x = min(max(x, b.get("minX", -1e9) + r), b.get("maxX", 1e9) - r)
    z = min(max(z, b.get("minZ", -1e9) + r), b.get("maxZ", 1e9) - r)
    obs = walk.get("obstacles") or walk.get("colliders") or []
    for o in obs:
        kind = (o.get("type") or "box").lower()
        ox, oz = float(o.get("x", 0.0)), float(o.get("z", 0.0))
        rot = float(o.get("rot", 0.0))
        cr, sr = math.cos(-rot), math.sin(-rot)
        dx, dz = x - ox, z - oz
        lx, lz = cr * dx - sr * dz, sr * dx + cr * dz
        if kind == "cylinder":
            rad = float(o.get("radius", o.get("r", 0.5))) + r
            d = math.hypot(lx, lz)
            worst = max(worst, rad - d)
            if d < rad and d > 1e-9:
                lx, lz = lx / d * rad, lz / d * rad
        else:
            hw = float(o.get("hw", 0.5)) + r
            hd = float(o.get("hd", 0.5)) + r
            cx, cz = max(-hw, min(hw, lx)), max(-hd, min(hd, lz))
            ex, ez = lx - cx, lz - cz
            d = math.hypot(ex, ez)
            inside = abs(lx) < hw and abs(lz) < hd
            if inside:
                px, pz = hw - abs(lx), hd - abs(lz)
                worst = max(worst, min(px, pz))
                if px < pz:
                    lx = math.copysign(hw, lx or 1.0)
                else:
                    lz = math.copysign(hd, lz or 1.0)
            elif d < 1e-9:
                pass
        fcr, fsr = math.cos(rot), math.sin(rot)
        x = ox + (fcr * lx - fsr * lz)
        z = oz + (fsr * lx + fcr * lz)
    return x, z, worst


def walk_test(walk: dict, steps: int = 20000, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    b = walk.get("bounds") or {}
    b = {"minX": b.get("minX", -2.0), "maxX": b.get("maxX", 2.0),
         "minZ": b.get("minZ", -2.0), "maxZ": b.get("maxZ", 2.0)}
    x = (b["minX"] + b["maxX"]) / 2
    z = (b["minZ"] + b["maxZ"]) / 2
    worst = 0.0
    escaped = 0
    for _ in range(steps):
        ang = rng.uniform(0, 2 * math.pi)
        step = rng.uniform(0.02, 0.85)
        x, z, pen = resolve(x + math.cos(ang) * step, z + math.sin(ang) * step, walk)
        worst = max(worst, pen)
        r = float(walk.get("player_radius", 0.3))
        if not (b["minX"] - 1e-6 <= x <= b["maxX"] + 1e-6
                and b["minZ"] - 1e-6 <= z <= b["maxZ"] + 1e-6):
            escaped += 1
    return {"steps": steps, "escaped": escaped,
            "worst_penetration_mm": round(worst * 1000, 2),
            "final_xz": [round(x, 3), round(z, 3)]}


# ------------------------------------------------------------------ B · houses

def sweep_houses() -> dict:
    db = json.load(open(os.path.join(ROOT, "public", "data", "rooms_db.json")))
    rows = []
    for room in db["rooms"]:
        if room.get("type") == "true_3d":
            continue
        rid = room["id"]
        p = os.path.join(ROOT, "public", "assets", "panoramas", f"{rid}.jpg")
        row = {"room": rid}
        if os.path.exists(p):
            row["pano_px"] = list(image_size(p))
        depth = os.path.join(ROOT, "data", "depth", f"{rid}.npy")
        row["lane_a"] = "measured-depth present" if os.path.exists(depth) else "blocked: no 360 depth"
        walk = room.get("walk") or {}
        row["bounds"] = walk.get("bounds")
        row["obstacles"] = len(walk.get("obstacles", []))
        if walk.get("bounds") or walk.get("polygon"):
            # two regimes: normal per-frame movement (<=0.10 m) and an
            # adversarial teleport probe (<=0.85 m) that shows where the
            # wall-then-obstacle order can eject the player.
            row["collision"] = probe_room(walk, step_max=0.10)
            row["collision_adversarial"] = probe_room(walk, step_max=0.85)
        else:
            row["collision"] = {"skipped": "no walk data"}
        rows.append(row)
        c = row["collision"]
        print(f"  {rid:<26} {str(row.get('pano_px')):<12} obstacles {row['obstacles']:>2} "
              f"· {c.get('mode','-')} · egress {c.get('egress_steps','-')} "
              f"· outside {c.get('outside_mm_max','-')} mm "
              f"· residual {c.get('residual_overlap_mm_max','-')} mm")
    return {"group": "houses", "count": len(rows), "rows": rows}


# ------------------------------------------------------------------- C · villa

def sweep_villa() -> dict:
    path = os.path.join(ROOT, "docs", "rd-artifacts", "true3d", "villa_room.json")
    v = json.load(open(path))
    walk = v.get("walk") or {}
    if not walk.get("bounds"):
        # authored room geometry: build a walk block from room_shape if needed
        shape = v.get("room_shape") or {}
        w, d = float(shape.get("width", 8.0)), float(shape.get("depth", 6.0))
        walk = {"player_radius": 0.3,
                "bounds": {"minX": -w / 2 + 0.6, "maxX": w / 2 - 0.6,
                           "minZ": -d / 2 + 0.6, "maxZ": d / 2 - 0.6},
                "obstacles": v.get("colliders") or v.get("obstacles") or []}
    glb = v.get("glb") or "assets/true3d/modern_3d_villa.glb"
    glb_path = os.path.join(ROOT, "public", glb)
    test = probe_room(walk, step_max=0.10)
    hard = probe_room(walk, step_max=0.85)
    obstacles = walk.get("obstacles") or []
    kinds = {}
    for o in obstacles:
        kinds[(o.get("type") or "box").lower()] = kinds.get((o.get("type") or "box").lower(), 0) + 1
    b = walk["bounds"]
    area = (b["maxX"] - b["minX"]) * (b["maxZ"] - b["minZ"])
    out = {
        "group": "villa", "room": v.get("id", "modern_3d_villa"),
        "glb": glb, "glb_bytes": os.path.getsize(glb_path) if os.path.exists(glb_path) else None,
        "walkable_area_m2": round(area, 2),
        "bounds": b, "colliders": len(obstacles), "collider_kinds": kinds,
        "collision": test,
        "collision_adversarial": hard,
    }
    print(f"  villa: {out['colliders']} colliders {kinds} · area {out['walkable_area_m2']} m2 "
          f"· {test['mode']} · egress {test['egress_steps']} "
          f"· outside {test['outside_mm_max']} mm "
          f"· residual {test['residual_overlap_mm_max']} mm")
    return out


# ---------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="engine sweep over moradi / houses / villa")
    ap.add_argument("--group", default="all", choices=["all", "moradi", "houses", "villa"])
    ap.add_argument("--scenes", default="", help="comma-separated moradi scene subset")
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "results.json"))
    args = ap.parse_args(argv)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    result = {}
    if os.path.exists(args.out):
        try:
            result = json.load(open(args.out))
        except Exception:                                        # noqa: BLE001
            result = {}

    scenes = [s for s in args.scenes.split(",") if s] or None
    if args.group in ("all", "moradi"):
        print("== A · moradi (10 live scenes) ==")
        new = sweep_moradi(scenes)
        by = {r["scene"]: r for r in result.get("moradi", {}).get("rows", [])}
        by.update({r["scene"]: r for r in new["rows"]})
        result["moradi"] = {"group": "moradi", "count": len(by),
                            "rows": [by[k] for k in MORADI if k in by]}
    if args.group in ("all", "houses"):
        print("== B · houses (10 curated rooms) ==")
        result["houses"] = sweep_houses()
    if args.group in ("all", "villa"):
        print("== C · villa ==")
        result["villa"] = sweep_villa()

    result["generated_at"] = "2026-11-12"
    with open(args.out, "w") as fh:
        json.dump(result, fh, indent=1)
    print(f"\n  -> {os.path.relpath(args.out, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
