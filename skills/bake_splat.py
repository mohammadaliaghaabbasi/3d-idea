#!/usr/bin/env python3
"""
================================================================================
 PANODROME — SPLAT BAKE  (the Marble-class stage of the same engine)
================================================================================

One 360 panorama + its metric depth  ->  a walkable photoreal splat (.ply, 3DGS
layout)  +  the metric geometry  +  the walk budget, all stamped with:

    engine.id      = "walkable-truth"
    engine.version = "1.1.0"

This is the appearance lane (Lane B2 in docs/17). It does NOT invent anything:
it lifts every photographed pixel into 3D at the distance the depth map measured.
What the photograph never saw stays unseen — and `walk_budget` says exactly how
far you can move before that matters.

    python3 skills/bake_splat.py --pano public/assets/panoramas/cabin.jpg \
        --depth depth/cabin.npy --id cabin

Output:
  public/assets/splats/<id>.ply        binary 3DGS (x,y,z,nx,ny,nz,f_dc,opacity,scale,rot)
  data/rooms_db.json + public/data/rooms_db.json
      geometry{...}  appearance{mode:"splat"}  walk_budget{...}  level:"L2"
================================================================================
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from walkable_layout_fit import erp_normals, fit_layout  # noqa: E402
from walk_budget import walk_budget  # noqa: E402
import panodrome_engine as ENG  # noqa: E402

SH_C0 = 0.28209479177387814
ENGINE_VERSION = "1.1.0"


# ----------------------------------------------------------------------------
# PLY (3D Gaussian Splatting, binary little endian — the de-facto format)
# ----------------------------------------------------------------------------

PLY_PROPS = [
    "x", "y", "z",
    "nx", "ny", "nz",
    "f_dc_0", "f_dc_1", "f_dc_2",
    "opacity",
    "scale_0", "scale_1", "scale_2",
    "rot_0", "rot_1", "rot_2", "rot_3",
]


def write_ply(path: str, data: dict) -> None:
    n = len(data["x"])
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {n}"]
    header += [f"property float {p}" for p in PLY_PROPS]
    header.append("end_header")
    cols = [np.asarray(data[p], dtype="<f4") for p in PLY_PROPS]
    body = np.stack(cols, axis=1).astype("<f4").tobytes()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(("\n".join(header) + "\n").encode("ascii"))
        fh.write(body)


# ----------------------------------------------------------------------------
# rotation: align the splat's local +Z with the measured surface normal
# ----------------------------------------------------------------------------

def quat_from_z(n: np.ndarray) -> np.ndarray:
    """Quaternion (w,x,y,z) rotating +Z onto unit vector n, vectorised."""
    z = np.array([0.0, 0.0, 1.0])
    d = n @ z                                   # n.z
    out = np.zeros((len(n), 4), dtype=np.float64)
    parallel = d > 1.0 - 1e-6
    anti = d < -1.0 + 1e-6
    mid = ~(parallel | anti)
    out[parallel] = (1.0, 0.0, 0.0, 0.0)
    out[anti] = (0.0, 1.0, 0.0, 0.0)            # 180 deg about X
    if np.any(mid):
        nm = n[mid]
        axis = np.cross(np.broadcast_to(z, nm.shape), nm)
        w = 1.0 + d[mid]
        q = np.concatenate([w[:, None], axis], axis=1)
        q /= np.linalg.norm(q, axis=1, keepdims=True)
        out[mid] = q
    return out


# ----------------------------------------------------------------------------
# bake
# ----------------------------------------------------------------------------

def bake_from_arrays(rgb: np.ndarray, depth: np.ndarray, out_path: str,
                     max_splats: int = 900_000, opacity: float = 0.98,
                     footprint: float = 1.15) -> dict:
    """
    Lift a panorama into gaussians.

    rgb     : (H,W,3) uint8, same grid as depth
    depth   : (H,W) float, metres
    opacity : per-splat alpha (logit stored, as 3DGS expects)
    footprint: splat radius in pixel-footprints at its own distance
    """
    h, w = depth.shape
    valid = np.isfinite(depth) & (depth > 0)
    dirs = ENG_directions(h, w)
    pts = dirs * np.where(valid, depth, 0.0)[..., None]
    normals, _ok = erp_normals(pts, depth, valid, radius=2, rel_tol=0.06)
    normals = np.where(np.isfinite(normals), normals, np.array([0.0, 1.0, 0.0]))
    norm = np.linalg.norm(normals, axis=-1, keepdims=True)
    normals = normals / np.maximum(norm, 1e-9)

    flat = valid.reshape(-1)
    idx = np.flatnonzero(flat)
    stride = max(1, int(math.ceil(len(idx) / float(max_splats))))
    idx = idx[::stride]

    P = pts.reshape(-1, 3)[idx]
    N = normals.reshape(-1, 3)[idx]
    D = depth.reshape(-1)[idx]
    C = rgb.reshape(-1, 3)[idx].astype(np.float64) / 255.0

    # angular size of one ERP pixel at that distance, as a splat radius
    scale = np.maximum(D * (2.0 * math.pi / w) * footprint, 0.004)
    scale = np.minimum(scale, 0.5)
    q = quat_from_z(N)
    op = np.full(len(idx), math.log(opacity / (1.0 - opacity)))

    data = {
        "x": P[:, 0], "y": P[:, 1], "z": P[:, 2],
        "nx": N[:, 0], "ny": N[:, 1], "nz": N[:, 2],
        "f_dc_0": (C[:, 0] - 0.5) / SH_C0,
        "f_dc_1": (C[:, 1] - 0.5) / SH_C0,
        "f_dc_2": (C[:, 2] - 0.5) / SH_C0,
        "opacity": op,
        # ISOTROPIC on purpose: a flat (pancake) gaussian is edge-on whenever its
        # measured normal is even slightly off, and a grazing disc projects to a
        # dark splinter. Small isotropic blobs stay round from every angle.
        "scale_0": np.log(scale), "scale_1": np.log(scale), "scale_2": np.log(scale),
        "rot_0": q[:, 0], "rot_1": q[:, 1], "rot_2": q[:, 2], "rot_3": q[:, 3],
    }
    write_ply(out_path, data)
    return {
        "splats": int(len(idx)),
        "stride": stride,
        "file_mb": round(os.path.getsize(out_path) / 1e6, 2),
        "bbox": {
            "min": [round(float(v), 3) for v in P.min(axis=0)],
            "max": [round(float(v), 3) for v in P.max(axis=0)],
        },
    }


def ENG_directions(h: int, w: int) -> np.ndarray:
    phi = (np.arange(w) + 0.5) / w * 2.0 * math.pi - math.pi
    theta = (np.arange(h) + 0.5) / h * math.pi
    th, ph = np.meshgrid(theta, phi, indexing="ij")
    st = np.sin(th)
    return np.stack([st * np.sin(ph), np.cos(th), st * np.cos(ph)], axis=-1)


def load_rgb(path: str, size: tuple[int, int]) -> np.ndarray:
    from PIL import Image
    im = Image.open(path).convert("RGB").resize((size[1], size[0]), Image.LANCZOS)
    return np.asarray(im)


def commit(dbs: list[str], room_id: str, geom: dict, appearance: dict,
           create: bool) -> list[str]:
    written = []
    for path in dbs:
        if not os.path.exists(path):
            continue
        db = ENG.load_db(path)
        room = ENG.find_room(db, room_id)
        if room is None:
            if not create:
                print(f"  ! {path}: no room '{room_id}' (use --create-room)")
                continue
            room = {"id": room_id, "room_type": "living_room",
                    "name": {"en": room_id.replace("_", " ").title(), "fa": room_id},
                    "portals": []}
            ENG.rooms_of(db).append(room)
        room["geometry"] = geom
        room["appearance"] = appearance
        room["walk"] = ENG.walk_block(geom)
        ENG.save_db(path, db)
        written.append(path)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="360 pano + metric depth -> 3DGS splat")
    ap.add_argument("--pano", required=True)
    ap.add_argument("--depth", required=True, help=".npy metric ERP depth")
    ap.add_argument("--id", required=True)
    ap.add_argument("--out", default=None, help="default public/assets/splats/<id>.ply")
    ap.add_argument("--max-splats", type=int, default=900_000)
    ap.add_argument("--db", action="append")
    ap.add_argument("--create-room", action="store_true")
    ap.add_argument("--no-budget", action="store_true", help="skip walk-budget (fast)")
    args = ap.parse_args(argv)

    print(ENG.banner())
    depth = ENG.load_depth(args.depth)
    rgb = load_rgb(args.pano, depth.shape)
    out = args.out or os.path.join(ROOT, "public", "assets", "splats", f"{args.id}.ply")

    info = bake_from_arrays(rgb, depth, out, args.max_splats)
    print(f"  splat       {info['splats']} gaussians, {info['file_mb']} MB -> "
          f"{os.path.relpath(out, ROOT)}")

    geom = fit_layout(depth)
    geom["engine"] = {"id": ENG.ENGINE_ID, "version": ENGINE_VERSION}
    geom["source"] = {"kind": "measured", "pano": os.path.relpath(args.pano, ROOT),
                      "pano_sha256_16": ENG.sha256_file(args.pano),
                      "depth_file": os.path.relpath(args.depth, ROOT),
                      "stage": "splat-bake"}
    budget = {"skipped": True} if args.no_budget else walk_budget(depth)
    geom["walk_budget"] = budget
    geom["level"] = "L2"

    appearance = {
        "mode": "splat",
        "asset": os.path.relpath(out, os.path.join(ROOT, "public")),
        "source": "panorama",
        "splats": info["splats"],
        "engine": f"{ENG.ENGINE_ID}/{ENGINE_VERSION}",
        # nothing painted in: the bake lifts photographed pixels only
        "invented_fraction": 0.0,
    }

    print(f"  area        {geom['area_m2']} m2  ·  ceiling {geom['ceiling_h']} m")
    print(f"  gates       {'ALL PASS' if geom['gates']['all_pass'] else 'FAILED'}")
    if not budget.get("skipped"):
        print(f"  walk budget 5% -> {budget['radius_5pct_m']} m   "
              f"15% -> {budget['radius_15pct_m']} m   "
              f"(curve {budget['curve']})")

    dbs = args.db or [p for p in ENG.DEFAULT_DBS if os.path.exists(os.path.join(ROOT, p))]
    dbs = [p if os.path.isabs(p) else os.path.join(ROOT, p) for p in dbs]
    written = commit(dbs, args.id, geom, appearance, args.create_room)
    for w in written:
        print(f"  wrote       {os.path.relpath(w, ROOT)}")
    ENG.write_engine_manifest()
    return 0 if geom["gates"]["all_pass"] else 2


if __name__ == "__main__":
    sys.exit(main())
