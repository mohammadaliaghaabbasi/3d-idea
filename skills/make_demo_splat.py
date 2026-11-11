#!/usr/bin/env python3
"""
Synthetic end-to-end proof of the splat stage (no GPU, no model, no dataset).

Renders a test room as a coloured equirectangular panorama from analytic
geometry, then runs the real bake:  panorama + metric depth -> 3DGS .ply +
metric geometry + walk budget -> rooms_db.json.

The result is a deliberate TEST PATTERN (checkered walls, wood floor), not a
photograph: it exists to prove the pipeline and to let the runtime be inspected
in a browser before any real depth model is available.

    python3 skills/make_demo_splat.py
"""

import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from walkable_layout_selftest import render_depth  # noqa: E402
from walkable_layout_fit import erp_normals, fit_layout  # noqa: E402
from walk_budget import walk_budget  # noqa: E402
from bake_splat import bake_from_arrays, ENG_directions, commit  # noqa: E402
import panodrome_engine as ENG  # noqa: E402

ROOM_ID = "demo_splat"
W, H = 1024, 512
POLY = np.array([[-3.0, -2.1], [3.0, -2.1], [3.0, 2.1], [-3.0, 2.1]])
CAM_H, CEIL = 1.6, 0.9          # ceiling at 2.5 m above the floor
BOXES = [(0.6, 1.8, 0.4, 1.0, -CAM_H, -0.85),      # sofa
         (-2.4, -1.9, 1.2, 1.7, -CAM_H, -0.45)]    # side table


def synth_colour(depth: np.ndarray) -> np.ndarray:
    """Colourise a depth map into a readable test pattern."""
    h, w = depth.shape
    valid = np.isfinite(depth) & (depth > 0)
    dirs = ENG_directions(h, w)
    pts = dirs * np.where(valid, depth, 0.0)[..., None]
    ny, ok = erp_normals(pts, depth, valid, radius=2, rel_tol=0.06)

    x, y, z = pts[..., 0], pts[..., 1], pts[..., 2]
    out = np.zeros((h, w, 3), dtype=np.float64)

    floor = ok & (np.abs(ny[..., 1]) > 0.85) & (y < -CAM_H + 0.15)
    ceil = ok & (np.abs(ny[..., 1]) > 0.85) & (y > -CAM_H + 0.15)
    wall = ok & ~floor & ~ceil & (np.abs(ny[..., 1]) < 0.3)
    other = valid & ~floor & ~ceil & ~wall

    chk = (np.floor(x / 0.6) + np.floor(z / 0.6)) % 2
    out[floor] = np.where(chk[floor][:, None] > 0, [0.66, 0.47, 0.31], [0.52, 0.35, 0.22])
    out[ceil] = [0.92, 0.93, 0.90]

    lon = np.degrees(np.arctan2(x, z)) % 360.0
    sector = (lon // 90).astype(int) % 4
    wall_cols = np.array([[0.82, 0.74, 0.62], [0.70, 0.76, 0.78],
                          [0.86, 0.78, 0.70], [0.74, 0.70, 0.76]])
    band = ((np.floor(y / 0.35) + np.floor(lon / 12.0)) % 2)[..., None]
    out[wall] = (wall_cols[sector][wall] * np.where(band[wall] > 0, 1.0, 0.90))

    out[other] = np.where((y[other] > -1.0)[:, None], [0.20, 0.36, 0.34], [0.30, 0.30, 0.32])
    out[~valid] = [0.1, 0.1, 0.12]
    return np.clip(out * 255.0, 0, 255).astype(np.uint8)


def main() -> int:
    print(ENG.banner())
    depth = render_depth(H, W, POLY, -CAM_H, CEIL, BOXES)
    rgb = synth_colour(depth)

    from PIL import Image
    os.makedirs(os.path.join(ROOT, "data", "depth"), exist_ok=True)
    np.save(os.path.join(ROOT, "data", "depth", f"{ROOM_ID}.npy"), depth)
    png = os.path.join(ROOT, "public", "assets", "panoramas", f"{ROOM_ID}.jpg")
    Image.fromarray(rgb).save(png, quality=92)
    print(f"  panorama    {os.path.relpath(png, ROOT)} (synthetic test pattern)")

    out = os.path.join(ROOT, "public", "assets", "splats", f"{ROOM_ID}.ply")
    info = bake_from_arrays(rgb, depth, out, max_splats=400_000)
    print(f"  splat       {info['splats']} gaussians, {info['file_mb']} MB")

    geom = fit_layout(depth)
    geom["engine"] = {"id": ENG.ENGINE_ID, "version": "1.1.0"}
    geom["source"] = {"kind": "measured", "pano": os.path.relpath(png, ROOT),
                      "depth_file": f"data/depth/{ROOM_ID}.npy",
                      "stage": "synthetic-selftest", "synthetic": True}
    budget = walk_budget(depth)
    geom["walk_budget"] = budget
    geom["level"] = "L2"
    appearance = {"mode": "splat", "asset": f"assets/splats/{ROOM_ID}.ply",
                  "source": "synthetic", "splats": info["splats"],
                  "engine": f"{ENG.ENGINE_ID}/1.1.0", "invented_fraction": 0.0}

    print(f"  geometry    {geom['area_m2']} m2 · {len(geom['floor_polygon'])} vertices · "
          f"{len(geom['obstacles'])} obstacles · gates "
          f"{'PASS' if geom['gates']['all_pass'] else 'FAIL'}")
    print(f"  walk budget 5% -> {budget['radius_5pct_m']} m · 15% -> {budget['radius_15pct_m']} m")

    room = {
        "id": ROOM_ID, "room_type": "living_room",
        "name": {"en": "Engine Test Room (splat)", "fa": "اتاق آزمایش موتور (splat)"},
        "description": {"en": "Synthetic validation room baked through the splat stage.",
                        "fa": "اتاق آزمایشی برای اعتبارسنجی مرحلهٔ splat."},
        "panorama": f"assets/panoramas/{ROOM_ID}.jpg",
        "portals": [],
        "attribution": {"creator": "Panodrome engine selftest", "source": "synthetic",
                        "license": "internal"},
    }
    # The demo room is a TEST PATTERN: it goes into a scratch database, never
    # into the shipped one. Pass --into-db only when deliberately inspecting it
    # inside the live app.
    if "--into-db" in sys.argv:
        dbs = [os.path.join(ROOT, p) for p in ENG.DEFAULT_DBS]
    else:
        dbs = [os.path.join(ROOT, "data", "selftest_rooms_db.json")]
        if not os.path.exists(dbs[0]):
            ENG.save_db(dbs[0], ENG.load_db(os.path.join(ROOT, ENG.DEFAULT_DBS[0])))
    written = commit(dbs, ROOM_ID, geom, appearance, create=True)
    # commit() creates a bare record; make sure metadata exists on both files
    for path in written:
        db = ENG.load_db(path)
        rec = ENG.find_room(db, ROOM_ID)
        rec.update({k: v for k, v in room.items() if k != "id"})
        ENG.save_db(path, db)
        print(f"  wrote       {os.path.relpath(path, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
