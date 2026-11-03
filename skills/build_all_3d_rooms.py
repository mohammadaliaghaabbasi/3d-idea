#!/usr/bin/env python3
# ============================================================================
# PANODROME — STAGE 2.1 · BUILD ALL TRUE-3D ROOMS (owner order 2026-11-03)
# ============================================================================
# "EVERY room in Panodrome must have its own matched True-3D Architectural
#  Model so the user can actually WALK meters through every room with a
#  locked FOV, lift the roof into a Dollhouse view, switch materials on tap,
#  and toggle to the pure 360° reference photo anytime."
#
# Expands skills/build_true_3d_room.py (villa-only, Stage 2.0) into the full
# 11-room architectural suite.  The .glb files carry GEOMETRY ONLY; materials
# are named "x_<paletteKey>#<kind>" and resolved at runtime from the shared
# palette (public/assets/true3d/mats/) — so all rooms together cost ONE
# small texture download and material switching is instant.
#
# Furniture layouts are placed at the VLM-verified collider positions from
# rooms_db.json (the same bodies the collision world uses), so what you bump
# into is exactly what you see.
#
# Output:
#   public/assets/true3d/<id>.glb           (11 rooms)
#   public/assets/true3d/mats/*.jpg + palette.json
#   data/rooms_db.json                     (merged: glb, sky, mats, walk)
#   public/data/rooms_db.json              (mirror)
# ============================================================================
import json
import os
import sys
import copy
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills"))

import trimesh
from true3d_lib import (
    export_palette, mbox, mcyl, mtorus, barrel_vault, mat,
    parts_sofa, parts_armchair, parts_bed_single, parts_bunk_bed,
    parts_table_round, parts_cafe_table, parts_chair, parts_piano_grand,
    parts_easel, parts_chandelier, parts_pendant, parts_plant, parts_tree,
    parts_fireplace, parts_stove, add_parts,
)

DB_PATH = os.path.join(ROOT, "data", "rooms_db.json")
DB_PUBLIC = os.path.join(ROOT, "public", "data", "rooms_db.json")
OUT_DIR = os.path.join(ROOT, "public", "assets", "true3d")
MATS_DIR = os.path.join(OUT_DIR, "mats")
WALL_T = 0.15
DOOR_H = 2.05


# ================================================================= shells
def _wall_frame(side, hw, hd):
    """Perpendicular center + thickness of a wall slab.

    'n' interior face at z=-hd (slab -hd-T..-hd) · 's' at +hd ·
    'w' at x=-hw · 'e' at +hw.  Returns (perp_center, perp_thickness).
    """
    if side == "n":
        return (-hd - WALL_T / 2, WALL_T)
    if side == "s":
        return (hd + WALL_T / 2, WALL_T)
    if side == "w":
        return (-hw - WALL_T / 2, WALL_T)
    return (hw + WALL_T / 2, WALL_T)


def _wall_box(side, a0, a1, hw, hd):
    """Box placement for a wall piece: along-wall [a0,a1] × perpendicular slab."""
    pc, pt = _wall_frame(side, hw, hd)
    if side in ("n", "s"):
        return ((a0 + a1) / 2, pc, a1 - a0, pt)
    return (pc, (a0 + a1) / 2, pt, a1 - a0)


def _wall_segments(scene, side, span_a, span_b, openings, key, name, height, hw, hd):
    """One wall: box segments around openings.

    side 'n'/'s': wall along x at z=∓hd · span = (x_lo, x_hi)
    side 'e'/'w': wall along z at x=±hw
    openings: [(c_lo, c_hi, y0, y1)] in wall-axis coords.
    """
    y_top = height
    for i, (a0, a1) in enumerate(_split_span(span_a, span_b, openings)):
        cx, cz, ex, ez = _wall_box(side, a0, a1, hw, hd)
        scene.add_geometry(
            mbox((ex, y_top, ez), key, center=(cx, y_top / 2, cz), kind="wall"),
            node_name=f"{name}_s{i}")

    for j, (c0, c1, y0, y1) in enumerate(openings):
        # lintel / sill segments
        if y1 < y_top:
            cx, cz, ex, ez = _wall_box(side, c0, c1, hw, hd)
            scene.add_geometry(
                mbox((ex, y_top - y1, ez), key, center=(cx, y1 + (y_top - y1) / 2, cz), kind="wall"),
                node_name=f"{name}_head{j}")
        if y0 > 0:
            cx, cz, ex, ez = _wall_box(side, c0, c1, hw, hd)
            scene.add_geometry(
                mbox((ex, y0, ez), key, center=(cx, y0 / 2, cz), kind="wall"),
                node_name=f"{name}_sill{j}")
        # casing
        cx, cz, ex, ez = _wall_box(side, c0 - 0.05, c1 + 0.05, hw, hd)
        cy = (y0 + y1) / 2
        scene.add_geometry(
            mbox((ex, 0.07, ez), "walnut", center=(cx, y1 + 0.035, cz), kind="wall"),
            node_name=f"{name}_case_top{j}")
        for cc in (c0 - 0.02, c1 + 0.02):
            cx, cz, ex, ez = _wall_box(side, cc - 0.02, cc + 0.02, hw, hd)
            scene.add_geometry(
                mbox((ex, y1 - y0, ez), "walnut", center=(cx, cy, cz), kind="wall"),
                node_name=f"{name}_case_side{j}")


def _split_span(lo, hi, openings):
    segs = []
    cur = lo
    for (c0, c1, _, _) in sorted(openings):
        if c0 > cur:
            segs.append((cur, min(c0, hi)))
        cur = max(cur, c1)
    if cur < hi:
        segs.append((cur, hi))
    return segs


def door_side(room, ring):
    """Which wall is nearest to the doorway ring? -> ('n'|'s'|'e'|'w', c, width)"""
    W = room["room_shape"]["width"] / 2
    D = room["room_shape"]["depth"] / 2
    rx, rz = ring[0], ring[2]
    cand = [
        ("e", abs(W - rx), rz, W),
        ("w", abs(-W - rx), rz, -W),
        ("s", abs(D - rz), rx, D),
        ("n", abs(-D - rz), rx, -D),
    ]
    side = min(cand, key=lambda t: t[1])
    return side[0], side[2]


def build_shell(scene, room, ring, floor_key, wall_key, ceil_key="plaster",
                windows=(), ceiling=True, baseboard_key=None):
    """Floor + walls with a door opening + optional windows + ceiling."""
    W = room["room_shape"]["width"]
    D = room["room_shape"]["depth"]
    H = room["room_shape"]["height"]
    hw, hd = W / 2, D / 2

    # floor (named floor_* — the material switcher target)
    scene.add_geometry(
        mbox((W + 2 * WALL_T, 0.12, D + 2 * WALL_T), floor_key, center=(0, -0.06, 0), kind="floor"),
        node_name="floor_main")

    side, door_c = door_side(room, ring)
    dw = 1.0
    if side in ("n", "s"):
        d0 = np.clip(door_c - dw / 2, -hw + 0.12, hw - 0.12 - dw)
        d1 = d0 + dw
    else:
        d0 = np.clip(door_c - dw / 2, -hd + 0.12, hd - 0.12 - dw)
        d1 = d0 + dw
    door_open = (d0, d1, 0.0, DOOR_H)

    walls = {
        "n": dict(span=(-hw, hw), open=[door_open] if side == "n" else []),
        "s": dict(span=(-hw, hw), open=[door_open] if side == "s" else []),
        "e": dict(span=(-hd, hd), open=[door_open] if side == "e" else []),
        "w": dict(span=(-hd, hd), open=[door_open] if side == "w" else []),
    }
    # windows: dict(side=..., c=..., w=..., y0=..., y1=...)
    for wspec in windows:
        ws = walls[wspec["side"]]
        c, w0 = wspec["c"], wspec["w"]
        ws["open"].append((c - w0 / 2, c + w0 / 2, wspec["y0"], wspec["y1"]))

    for side_k, spec in walls.items():
        _wall_segments(scene, side_k, spec["span"][0], spec["span"][1],
                       spec["open"], wall_key, f"wall_{side_k}", H, hw, hd)

    # baseboards
    if baseboard_key:
        for side_k, (ex, ez, cx, cz) in {
            "n": (W, 0.04, 0, -hd + 0.02), "s": (W, 0.04, 0, hd - 0.02),
            "e": (0.04, D, hw - 0.02, 0), "w": (0.04, D, -hw + 0.02, 0),
        }.items():
            scene.add_geometry(mbox((ex, 0.10, ez), baseboard_key, center=(cx, 0.05, cz), kind="wall"),
                              node_name=f"wall_bb_{side_k}")

    if ceiling:
        scene.add_geometry(
            mbox((W + 2 * WALL_T, 0.12, D + 2 * WALL_T), ceil_key, center=(0, H + 0.06, 0), kind="ceiling"),
            node_name="ceiling_main")
    return side


def add_art(scene, name, w, h, cx, cy, cz, art_key, face="z"):
    d = 0.05
    if face == "x":
        scene.add_geometry(mbox((d, h + 0.11, w + 0.11), "walnut", center=(cx, cy, cz), kind="furn", tile=False), node_name=f"{name}_fr")
        scene.add_geometry(mbox((d + 0.015, h, w), art_key, center=(cx - 0.012, cy, cz), kind="furn", tile=False), node_name=name)
    else:
        scene.add_geometry(mbox((w + 0.11, h + 0.11, d), "walnut", center=(cx, cy, cz), kind="furn", tile=False), node_name=f"{name}_fr")
        scene.add_geometry(mbox((w, h, d + 0.015), art_key, center=(cx, cy, cz + 0.012), kind="furn", tile=False), node_name=name)


# ================================================================= recipes
def recipe_villa(room):
    W, D, H = 6.4, 5.2, 3.0
    scene = trimesh.Scene()
    room["room_shape"] = {"width": W, "height": H, "depth": D}
    # shell: west windows x2, north door
    ring = [1.8, 1.3, -hd_of(D) + 0.32] if False else [1.8, 1.3, -2.28]
    scene.add_geometry(mbox((W + 2 * WALL_T, 0.12, D + 2 * WALL_T), "oak", center=(0, -0.06, 0), kind="floor"), node_name="floor_main")
    hw, hd = W / 2, D / 2
    win = [(z0, z1) for z0, z1 in ((-1.35 - 0.75, -1.35 + 0.75), (1.35 - 0.75, 1.35 + 0.75))]
    _wall_segments(scene, "w", -hd, hd,
                   [(win[0][0], win[0][1], 0.85, 2.35), (win[1][0], win[1][1], 0.85, 2.35)],
                   "plaster", "wall_w", H, hw, hd)
    # window frames + glass (west)
    for i, (zl, zh) in enumerate(win):
        for (fy0, fy1) in ((0.79, 0.85), (2.35, 2.41)):
            scene.add_geometry(mbox((0.13, 0.06, zh - zl + 0.10), "iron_dark", center=(-hw - 0.06, (fy0 + fy1) / 2, (zl + zh) / 2), kind="furn", tile=False), node_name=f"win{i+1}_h")
        scene.add_geometry(mbox((0.05, 1.5, zh - zl), "glass", center=(-hw - 0.05, 1.6, (zl + zh) / 2), kind="furn", tile=False), node_name=f"win{i+1}_glass")
    _wall_segments(scene, "e", -hd, hd, [], "plaster", "wall_e", H, hw, hd)
    _wall_segments(scene, "s", -hw, hw, [], "plaster", "wall_s", H, hw, hd)
    dl, dr = 1.3, 2.3
    _wall_segments(scene, "n", -hw, hw, [(dl, dr, 0.0, 2.1)], "plaster", "wall_n", H, hw, hd)
    for name, ex, ez, cx, cz in (("wall_bb_w", 0.05, D, -hw + 0.025, 0), ("wall_bb_e", 0.05, D, hw - 0.025, 0),
                                 ("wall_bb_s", W, 0.05, 0, hd - 0.025), ("wall_bb_n", W, 0.05, 0, -hd + 0.025)):
        scene.add_geometry(mbox((ex, 0.10, ez), "walnut", center=(cx, 0.05, cz), kind="wall"), node_name=name)
    scene.add_geometry(mbox((W + 2 * WALL_T, 0.12, D + 2 * WALL_T), "plaster", center=(0, H + 0.06, 0), kind="ceiling"), node_name="ceiling_main")
    for i, (lx, lz) in enumerate(((1.5, 1.2), (-1.5, 1.2), (1.5, -1.2), (-1.5, -1.2))):
        scene.add_geometry(mcyl(0.085, 0.025, "iron_dark", center=(lx, H - 0.032, lz), kind="furn", tile=False), node_name=f"spot_trim{i+1}")
        scene.add_geometry(mcyl(0.062, 0.012, "lamp_glow", center=(lx, H - 0.048, lz), kind="furn", tile=False), node_name=f"spot_glow{i+1}")
    scene.add_geometry(mbox((3.4, 0.012, 2.4), "rug_villa", center=(0.15, 0.006, 0.75), kind="furn"), node_name="rug")
    add_parts(scene, parts_sofa(-0.6, 0.6, np.pi / 2, length=2.16, depth=0.86, name="sofa"))
    scene.add_geometry(mbox((1.15, 0.07, 0.55), "travertine", center=(0.75, 0.365, 0.6), kind="furn"), node_name="table_top")
    for i, dx in enumerate((-0.42, 0.42)):
        scene.add_geometry(mbox((0.09, 0.33, 0.45), "travertine", center=(0.75 + dx, 0.165, 0.6), kind="furn"), node_name=f"table_leg{i+1}")
    scene.add_geometry(mbox((0.44, 0.62, 1.8), "walnut", center=(hw - 0.24, 0.35, -0.9), kind="furn"), node_name="sideboard_body")
    scene.add_geometry(mbox((0.46, 0.035, 1.84), "travertine", center=(hw - 0.24, 0.685, -0.9), kind="furn"), node_name="sideboard_top")
    scene.add_geometry(mcyl(0.16, 0.025, "iron_dark", center=(0.95, 0.012, -1.3), kind="furn", tile=False), node_name="lamp_base")
    scene.add_geometry(mcyl(0.016, 1.42, "iron_dark", center=(0.95, 0.72, -1.3), kind="furn", tile=False), node_name="lamp_pole")
    scene.add_geometry(mcyl(0.185, 0.27, "lamp_glow", center=(0.95, 1.36, -1.3), kind="furn", r2=0.135, tile=False), node_name="lamp_shade")
    scene.add_geometry(mbox((0.42, 1.0, 0.42), "travertine", center=(-2.35, 0.5, -1.7), kind="furn"), node_name="plinth")
    scene.add_geometry(mtorus(0.155, 0.052, "brass", center=(-2.35, 1.19, -1.7), axis="x"), node_name="torus_sculpture")
    add_art(scene, "art_east", 0.95, 1.25, hw - 0.05, 1.78, -0.9, "art_field", "x")
    add_art(scene, "art_s1", 0.62, 0.86, -1.5, 1.62, hd - 0.05, "art_line", "z")
    add_art(scene, "art_s2", 0.62, 0.86, 0.9, 1.62, hd - 0.05, "art_field", "z")

    obstacles = [
        dict(type="box", x=-0.6, z=0.6, hw=0.50, hd=1.32, h=0.92, rot=0.0, source="authored", label=dict(en="Sofa", fa="مبل")),
        dict(type="box", x=0.75, z=0.6, hw=0.62, hd=0.32, h=0.40, rot=0.0, source="authored", label=dict(en="Coffee Table", fa="میز عسلی")),
        dict(type="box", x=hw - 0.24, z=-0.9, hw=0.26, hd=0.95, h=0.72, rot=0.0, source="authored", label=dict(en="Sideboard", fa="بوفه")),
        dict(type="cylinder", x=0.95, z=-1.3, r=0.21, h=1.63, rot=0.0, source="authored", label=dict(en="Floor Lamp", fa="چراغ ایستاده")),
        dict(type="box", x=-2.35, z=-1.7, hw=0.26, hd=0.26, h=1.28, rot=0.0, source="authored", label=dict(en="Sculpture Plinth", fa="پایهٔ مجسمه")),
    ]
    lights = [
        {"type": "sun", "pos": [-14, 18, 5], "intensity": 2.6, "color": "#fff1de"},
        {"type": "spot", "pos": [1.5, 2.72, 1.2], "intensity": 0.5, "color": "#ffe7c6", "distance": 8},
        {"type": "spot", "pos": [-1.5, 2.72, 1.2], "intensity": 0.5, "color": "#ffe7c6", "distance": 8},
        {"type": "spot", "pos": [1.5, 2.72, -1.2], "intensity": 0.5, "color": "#ffe7c6", "distance": 8},
        {"type": "spot", "pos": [-1.5, 2.72, -1.2], "intensity": 0.5, "color": "#ffe7c6", "distance": 8},
    ]
    return scene, obstacles, lights, dict(
        floor=["oak", "calacatta", "herringbone", "travertine", "microcement"],
        wall=["plaster", "plaster_warm", "microcement", "calacatta"],
        furn=["boucle", "velvet_green", "fabric_ochre", "walnut"],
    )


def hd_of(D):
    return D / 2


def recipe_anniversary_lounge(room):
    scene = trimesh.Scene()
    ring = room["portals"][0]["position"]
    build_shell(scene, room, ring, floor_key="parquet_dark", wall_key="plaster_warm",
                ceil_key="plaster_warm", baseboard_key="walnut",
                windows=[dict(side="e", c=0.3, w=1.6, y0=0.75, y1=2.25)])
    # curtain panels flanking the east window (decor)
    scene.add_geometry(mbox((0.10, 2.0, 0.34), "curtain", center=(1.98, 1.30, 0.3 - 0.95), kind="furn"), node_name="curtain_l")
    scene.add_geometry(mbox((0.10, 2.0, 0.34), "curtain", center=(1.98, 1.30, 0.3 + 0.95), kind="furn"), node_name="curtain_r")
    # patterned rug
    scene.add_geometry(mbox((2.6, 0.012, 2.6), "rug_classic", center=(-0.1, 0.006, -0.6), kind="furn"), node_name="rug")
    # green tufted sofas & armchairs (at the VLM-verified colliders)
    add_parts(scene, parts_sofa(1.01, -1.41, np.pi / 2, length=1.9, depth=0.8, key="velvet_green", cushion="velvet_green", name="sofa"))
    add_parts(scene, parts_armchair(-1.10, -2.35, np.pi * 0.72, name="armchair1"))
    add_parts(scene, parts_armchair(-1.50, 1.10, -np.pi * 0.42, name="armchair2"))
    add_parts(scene, parts_armchair(-1.50, -0.70, -np.pi * 0.18, name="armchair3"))
    # glass coffee table (authored collider below)
    scene.add_geometry(mbox((1.0, 0.035, 1.0), "glass", center=(0, 0.40, -0.55), kind="furn", tile=False), node_name="glass_table_top")
    scene.add_geometry(mcyl(0.03, 0.38, "brass", center=(0, 0.19, -0.55), kind="furn", tile=False), node_name="glass_table_stem")
    scene.add_geometry(mcyl(0.18, 0.02, "brass", center=(0, 0.01, -0.55), kind="furn", tile=False), node_name="glass_table_foot")
    # sideboard with flower arrangement (south wall)
    add_parts(scene, [(mbox((1.7, 0.62, 0.55), "walnut", center=(0.9, 0.35, 2.72), kind="furn"), "sideboard_body"),
                      (mbox((1.74, 0.035, 0.58), "walnut", center=(0.9, 0.685, 2.72), kind="furn"), "sideboard_top")])
    scene.add_geometry(mcyl(0.05, 0.18, "white_paint", center=(0.9, 0.78, 2.72), kind="furn", tile=False), node_name="vase")
    for k in range(3):
        scene.add_geometry(mcyl(0.012, 0.16, "foliage", center=(0.9 + (k - 1) * 0.03, 0.94, 2.72 + (k % 2) * 0.03), kind="furn", r2=0.002, sections=8, tile=False), node_name=f"flower{k}")
    # curio cabinet (cyl collider r0.69)
    scene.add_geometry(mbox((0.8, 1.35, 0.55), "walnut", center=(1.67, 0.675, 1.11), kind="furn"), node_name="curio_body")
    scene.add_geometry(mbox((0.02, 1.1, 0.42), "glass", center=(1.25, 0.85, 1.11), kind="furn", tile=False), node_name="curio_glass")
    # side table + lamp (cyl r0.3)
    add_parts(scene, parts_table_round(-1.05, -1.45, r=0.28, h=0.5, name="side_table"))
    scene.add_geometry(mcyl(0.09, 0.16, "lamp_glow", center=(-1.05, 0.58, -1.45), kind="furn", r2=0.06, tile=False), node_name="side_lamp")
    # chandelier
    ch_parts = []
    parts_chandelier(ch_parts, 0, 2.45, -0.6, drop=0.45)
    add_parts(scene, ch_parts)
    lights = [
        {"type": "sun", "pos": [10, 6, 2], "intensity": 1.5, "color": "#ffeeda"},
        {"type": "spot", "pos": [0, 2.1, -0.6], "intensity": 0.7, "color": "#ffd9a8", "distance": 6},
        {"type": "spot", "pos": [1.4, 1.9, 1.4], "intensity": 0.45, "color": "#ffe6c4", "distance": 6},
        {"type": "spot", "pos": [-1.6, 1.4, -2.2], "intensity": 0.4, "color": "#ffdcae", "distance": 5},
    ]
    obstacles = [
        dict(type="cylinder", x=1.01, z=-1.41, r=1.02, h=0.82, rot=0.0, source="vlm-verified", label=dict(en="Green Sofa", fa="مبل سبز")),
        dict(type="cylinder", x=-1.10, z=-2.35, r=0.55, h=0.85, rot=0.45, source="vlm-verified", label=dict(en="Armchair", fa="صندلی راحتی")),
        dict(type="cylinder", x=-1.50, z=1.10, r=0.45, h=0.85, rot=0.0, source="vlm-verified", label=dict(en="Armchair", fa="صندلی راحتی")),
        dict(type="cylinder", x=-1.50, z=-0.70, r=0.45, h=0.85, rot=0.0, source="vlm-verified", label=dict(en="Armchair", fa="صندلی راحتی")),
        dict(type="box", x=0.0, z=-0.55, hw=0.55, hd=0.55, h=0.42, rot=0.0, source="authored", label=dict(en="Glass Coffee Table", fa="میز قهوه شیشه‌ای")),
        dict(type="box", x=0.90, z=2.75, hw=0.85, hd=0.30, h=0.92, rot=0.0, source="vlm-verified", label=dict(en="Sideboard", fa="بوفه")),
        dict(type="cylinder", x=1.67, z=1.11, r=0.69, h=0.92, rot=0.0, source="vlm-verified", label=dict(en="Curio Cabinet", fa="ویترینی")),
        dict(type="cylinder", x=-1.05, z=-1.45, r=0.30, h=0.5, rot=0.0, source="vlm-verified", label=dict(en="Side Table", fa="میز کنسول")),
    ]
    return scene, obstacles, lights, dict(
        floor=["parquet_dark", "calacatta", "herringbone", "travertine", "microcement"],
        wall=["plaster_warm", "plaster", "cream_gold", "microcement"],
        furn=["velvet_green", "boucle", "fabric_ochre", "walnut"],
    )


def recipe_cabin(room):
    scene = trimesh.Scene()
    ring = room["portals"][0]["position"]
    build_shell(scene, room, ring, floor_key="oak", wall_key="timber",
                ceil_key="timber", baseboard_key="walnut",
                windows=[dict(side="n", c=1.0, w=0.9, y0=0.9, y1=1.8)])
    # bunk bed (west wall) + single bed NE + brown sofa + round table + dresser
    add_parts(scene, parts_bunk_bed(-1.15, -0.5, 0, name="bunk"))
    add_parts(scene, parts_bed_single(1.0, -1.35, -np.pi / 2, size=(1.0, 1.9), name="bed_ne"))
    add_parts(scene, parts_sofa(1.22, 0.19, np.pi / 2, length=1.3, depth=0.68, key="fabric_ochre", cushion="boucleL", name="sofa"))
    add_parts(scene, parts_table_round(0.75, 0.75, r=0.35, h=0.45, name="round_table"))
    add_parts(scene, [(mbox((0.75, 0.78, 0.78), "walnut", center=(1.25, 0.39, 1.75), kind="furn"), "cabinet_body"),
                      (mbox((0.78, 0.03, 0.80), "walnut", center=(1.25, 0.80, 1.75), kind="furn"), "cabinet_top")])
    # warm wall painting (south wall) + ceiling pendant
    add_art(scene, "art_cabin", 0.62, 0.5, -0.4, 1.45, 2.24, "art_landscape", "z")
    pend = parts_pendant(0.75, 2.34, 0.75, name="pendant", r=0.14)
    add_parts(scene, pend)
    # rug
    scene.add_geometry(mbox((1.4, 0.012, 1.1), "rug_villa", center=(0.4, 0.006, 0.6), kind="furn"), node_name="rug")
    lights = [
        {"type": "spot", "pos": [0.75, 2.1, 0.75], "intensity": 0.85, "color": "#ffd9a4", "distance": 6},
        {"type": "spot", "pos": [-0.9, 1.3, -0.5], "intensity": 0.35, "color": "#ffc98e", "distance": 4},
        {"type": "sun", "pos": [4, 8, -6], "intensity": 0.9, "color": "#dfe8f5"},
    ]
    obstacles = [
        dict(type="box", x=-1.15, z=-0.5, hw=0.45, hd=1.55, h=1.55, rot=0.0, source="vlm-verified", label=dict(en="Bunk Bed", fa="تخت طبقه‌دار")),
        dict(type="box", x=1.0, z=-1.35, hw=0.55, hd=0.7, h=0.8, rot=0.0, source="vlm-verified", label=dict(en="Bed", fa="تخت")),
        dict(type="cylinder", x=1.22, z=0.19, r=0.72, h=0.85, rot=0.0, source="vlm-verified", label=dict(en="sofa", fa="مبل")),
        dict(type="cylinder", x=0.75, z=0.75, r=0.35, h=0.45, rot=0.0, source="vlm-verified", label=dict(en="Round Table", fa="میز گرد")),
        dict(type="box", x=1.25, z=1.75, hw=0.4, hd=0.42, h=0.8, rot=0.0, source="vlm-verified", label=dict(en="Cabinet", fa="کمد")),
    ]
    return scene, obstacles, lights, dict(
        floor=["oak", "timber", "calacatta", "herringbone", "microcement"],
        wall=["timber", "plaster_warm", "plaster", "microcement"],
        furn=["fabric_ochre", "velvet_green", "boucle", "walnut"],
    )


def recipe_ballroom(room):
    scene = trimesh.Scene()
    ring = room["portals"][0]["position"]
    W, D, H = 9.0, 14.0, 5.5
    build_shell(scene, room, ring, floor_key="herringbone", wall_key="cream_gold",
                ceil_key="plaster_warm", baseboard_key="marble_black",
                windows=[
                    dict(side="w", c=-3.5, w=1.4, y0=0.9, y1=3.6),
                    dict(side="w", c=0.0, w=1.4, y0=0.9, y1=3.6),
                    dict(side="w", c=3.5, w=1.4, y0=0.9, y1=3.6),
                    dict(side="e", c=-3.5, w=1.4, y0=0.9, y1=3.6),
                    dict(side="e", c=0.0, w=1.4, y0=0.9, y1=3.6),
                    dict(side="e", c=3.5, w=1.4, y0=0.9, y1=3.6),
                ])
    # wall pilasters + cornice (cream/gold molding)
    for c in np.linspace(-4.25, 4.25, 6):
        scene.add_geometry(mbox((0.16, H - 0.35, 0.10), "cream_gold", center=(-4.42, (H - 0.35) / 2 + 0.17, c), kind="wall"), node_name=f"pilaster_w{abs(int(c*10))}")
        scene.add_geometry(mbox((0.10, H - 0.35, 0.16), "cream_gold", center=(4.42, (H - 0.35) / 2 + 0.17, c), kind="wall"), node_name=f"pilaster_e{abs(int(c*10))}")
    for side, (ex, ez, cx, cz) in {"n": (W, 0.14, 0, -6.93), "s": (W, 0.14, 0, 6.93), "e": (0.14, D, 4.43, 0), "w": (0.14, D, -4.43, 0)}.items():
        scene.add_geometry(mbox((ex, 0.22, ez), "cream_gold", center=(cx, H - 0.11, cz), kind="wall"), node_name=f"cornice_{side}")
        scene.add_geometry(mbox((ex * 0.98, 0.14, ez * 0.98), "marble_black", center=(cx, 0.07 + 0.10, cz), kind="wall"), node_name=f"base_{side}")
    # mirrors on the north wall
    for cx in (-2.4, 0.0, 2.4):
        scene.add_geometry(mbox((1.15, 2.3, 0.06), "walnut", center=(cx, 1.95, -6.94), kind="furn", tile=False), node_name=f"mirror_fr_{abs(int(cx*10))}")
        scene.add_geometry(mbox((1.0, 2.15, 0.03), "mirror", center=(cx, 1.95, -6.915), kind="furn", tile=False), node_name=f"mirror_{abs(int(cx*10))}")
    # classical paintings
    add_art(scene, "art_c1", 0.9, 1.2, -4.44, 2.6, -2.0, "art_classic1", "x")
    add_art(scene, "art_c2", 0.9, 1.2, 4.44, 2.6, -2.0, "art_classic2", "x")
    add_art(scene, "art_c3", 1.1, 0.9, -2.0, 2.9, 6.94, "art_classic2", "z")
    add_art(scene, "art_c4", 1.1, 0.9, 1.5, 2.9, 6.94, "art_classic1", "z")
    # grand piano (VLM-verified at (-3.6, 2.3))
    add_parts(scene, parts_piano_grand(-3.6, 2.3, 0.5))
    # two chandeliers
    for i, z in enumerate((-2.2, 2.6)):
        ch = []
        parts_chandelier(ch, 0, 4.9, z, drop=0.6, r=0.42, name=f"chandelier{i+1}")
        add_parts(scene, ch)
    lights = [
        {"type": "sun", "pos": [-10, 10, 0], "intensity": 1.8, "color": "#fff3e2"},
        {"type": "spot", "pos": [0, 3.9, -2.2], "intensity": 0.9, "color": "#ffd9a8", "distance": 9},
        {"type": "spot", "pos": [0, 3.9, 2.6], "intensity": 0.9, "color": "#ffd9a8", "distance": 9},
        {"type": "spot", "pos": [-3.6, 2.5, 2.3], "intensity": 0.35, "color": "#fff0dd", "distance": 5},
        {"type": "spot", "pos": [3.5, 2.5, -4.0], "intensity": 0.35, "color": "#ffe8cd", "distance": 5},
    ]
    obstacles = [
        dict(type="box", x=-3.6, z=2.3, hw=0.85, hd=1.1, h=1.1, rot=0.0, source="vlm-verified", label=dict(en="Grand Piano", fa="پیانو گرند")),
    ]
    return scene, obstacles, lights, dict(
        floor=["herringbone", "calacatta", "marble_black", "terrazzo", "microcement"],
        wall=["cream_gold", "plaster_warm", "plaster", "calacatta"],
        furn=["black_gloss", "walnut", "brass", "velvet_green"],
    )


def recipe_comfy_cafe(room):
    scene = trimesh.Scene()
    ring = room["portals"][0]["position"]
    build_shell(scene, room, ring, floor_key="oak", wall_key="plaster_warm",
                ceil_key="plaster_warm", baseboard_key="walnut",
                windows=[dict(side="w", c=1.2, w=1.5, y0=0.8, y1=2.3),
                         dict(side="w", c=-1.6, w=1.5, y0=0.8, y1=2.3)])
    # booths & sofas at the verified colliders
    add_parts(scene, parts_sofa(-1.30, 0.63, np.pi / 2, length=1.4, depth=0.66, key="fabric_ochre", cushion="boucleL", name="booth1"))
    add_parts(scene, parts_sofa(0.11, 2.13, np.pi, length=1.8, depth=0.7, key="fabric_ochre", cushion="boucleL", name="booth2"))
    add_parts(scene, parts_sofa(-1.82, -1.42, np.pi / 2, length=1.1, depth=0.6, key="fabric_ochre", cushion="boucleL", name="booth3"))
    add_parts(scene, parts_sofa(-0.66, -2.83, 0, length=1.05, depth=0.55, key="fabric_ochre", cushion="boucleL", name="booth4"))
    add_parts(scene, parts_cafe_table(1.90, 1.90, r=0.55, name="cafe_table1"))
    add_parts(scene, parts_table_round(-0.58, 1.60, r=0.65, h=0.74, key="walnut", name="big_table"))
    add_parts(scene, parts_cafe_table(-1.27, -2.34, r=0.42, name="cafe_table2"))
    add_parts(scene, parts_chair(1.35, 1.90, -np.pi / 2, name="chair1"))
    add_parts(scene, parts_chair(0.05, -2.2, 0.5, name="chair2"))
    add_parts(scene, parts_plant(2.17, 0.60, s=1.0))
    # counter along the east wall (in the unreachable strip)
    scene.add_geometry(mbox((0.35, 0.95, 3.2), "walnut", center=(2.28, 0.475, 0.2), kind="furn"), node_name="counter_body")
    scene.add_geometry(mbox((0.38, 0.04, 3.24), "oak", center=(2.28, 0.97, 0.2), kind="furn"), node_name="counter_top")
    for i, z in enumerate((-0.9, 1.3)):
        scene.add_geometry(mbox((0.3, 0.12, 0.3), "iron_dark", center=(2.2, 1.08, z), kind="furn", tile=False), node_name=f"espresso{i}")
    # warm pendants over tables
    for i, (px, pz) in enumerate(((1.9, 1.9), (-0.58, 1.6), (-1.27, -2.34), (0.11, 2.13))):
        add_parts(scene, parts_pendant(px, 2.94, pz, name=f"pendant{i+1}", r=0.12))
    lights = [
        {"type": "sun", "pos": [-8, 8, 0], "intensity": 1.2, "color": "#ffeeda"},
        {"type": "spot", "pos": [1.9, 2.5, 1.9], "intensity": 0.55, "color": "#ffd9a8", "distance": 6},
        {"type": "spot", "pos": [-0.6, 2.5, 1.6], "intensity": 0.55, "color": "#ffd9a8", "distance": 6},
        {"type": "spot", "pos": [-1.3, 2.5, -2.3], "intensity": 0.45, "color": "#ffd9a8", "distance": 6},
        {"type": "spot", "pos": [0.1, 2.5, 2.1], "intensity": 0.5, "color": "#ffd9a8", "distance": 6},
    ]
    obstacles = [
        dict(type="cylinder", x=-1.30, z=0.63, r=0.79, h=0.8, rot=0.0, source="vlm-verified", label=dict(en="Booth Bench", fa="نیمکت بوت")),
        dict(type="cylinder", x=0.11, z=2.13, r=0.99, h=0.8, rot=0.0, source="vlm-verified", label=dict(en="Booth Sofa", fa="مبل بوت")),
        dict(type="cylinder", x=-1.82, z=-1.42, r=0.64, h=0.8, rot=0.0, source="vlm-verified", label=dict(en="Booth Bench", fa="نیمکت بوت")),
        dict(type="cylinder", x=-0.66, z=-2.83, r=0.61, h=0.8, rot=0.0, source="vlm-verified", label=dict(en="Booth Bench", fa="نیمکت بوت")),
        dict(type="cylinder", x=1.90, z=1.90, r=0.55, h=0.75, rot=0.0, source="vlm-verified", label=dict(en="Café Table", fa="میز کافه")),
        dict(type="cylinder", x=-0.58, z=1.60, r=0.74, h=0.75, rot=0.0, source="vlm-verified", label=dict(en="Sharing Table", fa="میز مشترک")),
        dict(type="cylinder", x=-1.27, z=-2.34, r=0.55, h=0.75, rot=0.0, source="vlm-verified", label=dict(en="Café Table", fa="میز کافه")),
        dict(type="cylinder", x=2.17, z=0.60, r=0.38, h=1.2, rot=0.0, source="vlm-verified", label=dict(en="Plant", fa="گلدان")),
    ]
    return scene, obstacles, lights, dict(
        floor=["oak", "herringbone", "terrazzo", "calacatta", "microcement"],
        wall=["plaster_warm", "plaster", "microcement", "calacatta"],
        furn=["fabric_ochre", "velvet_green", "boucle", "walnut"],
    )


def recipe_art_studio(room):
    scene = trimesh.Scene()
    ring = room["portals"][0]["position"]
    build_shell(scene, room, ring, floor_key="microcement", wall_key="plaster",
                ceil_key="plaster", baseboard_key="white_paint",
                windows=[dict(side="n", c=-0.6, w=3.0, y0=1.15, y1=2.75)])
    # work table (verified) + supplies
    add_parts(scene, [(mbox((1.15, 0.06, 2.0), "walnut", center=(-1.80, 0.76, 1.30), kind="furn"), "worktable_top")])
    for dx, dz in ((-0.48, -0.8), (0.48, -0.8), (-0.48, 0.8), (0.48, 0.8)):
        scene.add_geometry(mbox((0.06, 0.73, 0.06), "walnut", center=(-1.80 + dx, 0.365, 1.30 + dz), kind="furn", tile=False), node_name="worktable_leg")
    for i, (dx, dz, key) in enumerate(((-0.2, -0.3, "calacatta"), (0.15, 0.4, "velvet_green"), (-0.05, 0.9, "brass"), (0.3, -0.6, "fabric_ochre"))):
        scene.add_geometry(mcyl(0.05, 0.16, key, center=(-1.80 + dx, 0.87, 1.30 + dz), kind="furn", tile=False), node_name=f"paintcup{i}")
    # mezzanine stairs (verified box)
    for i in range(6):
        scene.add_geometry(mbox((1.2, 0.24, 0.42), "walnut", center=(-0.40, 0.12 + i * 0.25, 3.10 - 1.05 + i * 0.42), kind="furn"), node_name=f"stair_step{i}")
    # studio rack with canvases (verified cyl)
    add_parts(scene, [(mbox((0.5, 1.9, 1.45), "walnut", center=(1.86, 0.95, -2.28), kind="furn"), "rack_body")])
    for k in range(4):
        scene.add_geometry(mbox((0.02, 0.62, 0.5), "art_field" if k % 2 else "art_line", center=(1.58, 1.2 + (k % 2) * 0.35, -2.28 - 0.42 + k * 0.28), kind="furn", tile=False), node_name=f"rack_canvas{k}")
    # flat file cabinet (verified cyl)
    add_parts(scene, [(mbox((0.85, 0.55, 1.5), "white_paint", center=(0.16, 0.28, -1.90), kind="furn"), "flatfile_body")])
    for k in range(3):
        scene.add_geometry(mbox((0.87, 0.02, 0.12), "iron_dark", center=(0.16, 0.12 + k * 0.18, -1.18), kind="furn", tile=False), node_name=f"flatfile_drawer{k}")
    # tall cabinet (verified box, east wall)
    add_parts(scene, [(mbox((0.85, 1.95, 0.45), "walnut", center=(2.03, 0.975, 2.50), kind="furn"), "cabinet_tall")])
    # easels with canvases (decor)
    add_parts(scene, parts_easel(0.9, -1.0, -2.4, "art_landscape", name="easel1"))
    add_parts(scene, parts_easel(-0.6, 3.6, -0.9, "art_field", name="easel2"))
    lights = [
        {"type": "sun", "pos": [-2, 9, -9], "intensity": 2.2, "color": "#eef3ff"},      # cool north light
        {"type": "spot", "pos": [1.86, 2.4, -2.28], "intensity": 0.4, "color": "#ffe6c4", "distance": 6},
        {"type": "spot", "pos": [-1.8, 2.6, 1.3], "intensity": 0.45, "color": "#ffe6c4", "distance": 6},
    ]
    obstacles = [
        dict(type="cylinder", x=-1.80, z=1.30, r=0.65, h=0.8, rot=0.0, source="vlm-verified", label=dict(en="Work Table", fa="میز کار")),
        dict(type="box", x=-0.40, z=3.10, hw=0.65, hd=0.5, h=1.6, rot=0.0, source="vlm-verified", label=dict(en="Studio Stairs", fa="پلهٔ استودیو")),
        dict(type="cylinder", x=1.86, z=-2.28, r=0.83, h=1.9, rot=0.0, source="vlm-verified", label=dict(en="Canvas Rack", fa="قفسهٔ بوم")),
        dict(type="cylinder", x=0.16, z=-1.90, r=0.53, h=0.55, rot=0.0, source="vlm-verified", label=dict(en="Flat File", fa="کابینت نقشه")),
        dict(type="box", x=2.03, z=2.50, hw=0.45, hd=0.95, h=1.95, rot=0.0, source="vlm-verified", label=dict(en="Cabinet", fa="کمد")),
    ]
    return scene, obstacles, lights, dict(
        floor=["microcement", "oak", "calacatta", "terrazzo", "travertine"],
        wall=["plaster", "plaster_warm", "microcement", "calacatta"],
        furn=["walnut", "white_paint", "walnut", "walnut"],
    )


def recipe_large_corridor(room):
    scene = trimesh.Scene()
    ring = room["portals"][0]["position"]
    build_shell(scene, room, ring, floor_key="stonefloor", wall_key="plaster",
                ceil_key="plaster", baseboard_key="stonefloor",
                windows=[dict(side="e", c=2.6, w=0.9, y0=1.6, y1=3.1),
                         dict(side="e", c=-2.4, w=0.9, y0=1.6, y1=3.1)])
    # two tiled stoves at the verified boxes
    add_parts(scene, parts_stove(1.45, 4.90, -np.pi / 2, name="stove1"))
    add_parts(scene, parts_stove(-1.45, 0.70, np.pi / 2, name="stove2"))
    # wall sconces + frames (decor)
    for i, z in enumerate((-4.6, -1.8, 1.6, 4.2)):
        scene.add_geometry(mcyl(0.05, 0.09, "lamp_glow", center=(-1.62, 2.5, z), kind="furn", tile=False), node_name=f"sconce_w{i}")
        scene.add_geometry(mbox((0.06, 0.09, 0.22), "brass", center=(-1.64, 2.38, z), kind="furn", tile=False), node_name=f"sconce_arm_w{i}")
    add_art(scene, "art_cor1", 0.7, 0.95, 1.64, 2.5, -3.0, "art_classic2", "x")
    add_art(scene, "art_cor2", 0.7, 0.95, 1.64, 2.5, 3.4, "art_classic1", "x")
    lights = [
        {"type": "sun", "pos": [9, 7, 0], "intensity": 1.1, "color": "#ffeeda"},
        {"type": "spot", "pos": [-1.5, 2.4, -4.6], "intensity": 0.35, "color": "#ffc98e", "distance": 5},
        {"type": "spot", "pos": [-1.5, 2.4, -1.8], "intensity": 0.35, "color": "#ffc98e", "distance": 5},
        {"type": "spot", "pos": [-1.5, 2.4, 1.6], "intensity": 0.35, "color": "#ffc98e", "distance": 5},
        {"type": "spot", "pos": [-1.5, 2.4, 4.2], "intensity": 0.35, "color": "#ffc98e", "distance": 5},
    ]
    obstacles = [
        dict(type="box", x=1.45, z=4.90, hw=0.45, hd=0.45, h=1.9, rot=0.0, source="vlm-verified", label=dict(en="Ceramic Stove", fa="اجاق سفالی")),
        dict(type="box", x=-1.45, z=0.70, hw=0.45, hd=0.45, h=1.9, rot=0.0, source="vlm-verified", label=dict(en="Tiled Stove", fa="اجاق کاشی‌کاری")),
    ]
    return scene, obstacles, lights, dict(
        floor=["stonefloor", "calacatta", "terrazzo", "oak", "microcement"],
        wall=["plaster", "plaster_warm", "cream_gold", "microcement"],
        furn=["tiles_stove", "walnut", "walnut", "walnut"],
    )


def recipe_castle_cellar(room):
    scene = trimesh.Scene()
    ring = room["portals"][0]["position"]
    W, D, H = 3.6, 10.0, 2.9
    build_shell(scene, room, ring, floor_key="stonefloor", wall_key="brick",
                ceil_key="brick", baseboard_key="stonefloor", ceiling=False)
    # barrel vault (ceiling — hidden in dollhouse)
    scene.add_geometry(barrel_vault(1.8, D, "brick", kind="ceiling", center=(0, 1.1, 0)), node_name="ceiling_vault")
    # wine barrels along the walls (decor, inside the unreachable strip)
    for i, (x, z, yaw) in enumerate(((1.42, -3.4, np.pi / 2), (1.42, -2.3, np.pi / 2), (-1.42, 1.4, -np.pi / 2), (-1.42, 2.5, -np.pi / 2))):
        scene.add_geometry(mcyl(0.32, 0.9, "timber", center=(x, 0.45, z), kind="furn", sections=18, tile=False), node_name=f"barrel{i}")
        scene.add_geometry(mtorus(0.32, 0.02, "iron_dark", center=(x, 0.65, z), axis="x"), node_name=f"barrel_hoop{i}")
    # bottle racks (decor)
    for k in range(2):
        x0 = -1.5 if k == 0 else 1.5
        scene.add_geometry(mbox((0.24, 1.05, 1.8), "timber", center=(x0, 0.525, 5.4 if k == 0 else -5.4), kind="furn"), node_name=f"rack{k}")
        for b in range(6):
            scene.add_geometry(mcyl(0.035, 0.26, "velvet_green", center=(x0 + (0.06 if k else -0.06), 0.25 + (b % 3) * 0.3, (5.4 if k == 0 else -5.4) - 0.7 + (b // 3) * 0.6), kind="furn", tile=False), node_name=f"bottle{k}_{b}")
    # torch sconces (decor + light anchors)
    for i, z in enumerate((-3.6, 0.0, 3.6)):
        scene.add_geometry(mbox((0.05, 0.34, 0.05), "iron_dark", center=(-1.66, 1.55, z), kind="furn", tile=False), node_name=f"torch_arm{i}")
        scene.add_geometry(mcyl(0.05, 0.12, "lamp_glow", center=(-1.72, 1.78, z), kind="furn", tile=False), node_name=f"torch{i}")
    lights = [
        {"type": "spot", "pos": [-1.5, 1.8, -3.6], "intensity": 0.9, "color": "#ff9c4a", "distance": 5},
        {"type": "spot", "pos": [-1.5, 1.8, 0.0], "intensity": 0.9, "color": "#ff9c4a", "distance": 5},
        {"type": "spot", "pos": [-1.5, 1.8, 3.6], "intensity": 0.9, "color": "#ff9c4a", "distance": 5},
        {"type": "spot", "pos": [0, 2.6, -5.0], "intensity": 0.4, "color": "#ffae5e", "distance": 6},
        {"type": "spot", "pos": [0, 2.6, 5.0], "intensity": 0.4, "color": "#ffae5e", "distance": 6},
    ]
    obstacles = [
        dict(type="box", x=1.42, z=-2.85, hw=0.33, hd=0.65, h=0.9, rot=0.0, source="authored", label=dict(en="Wine Barrels", fa="بشکه‌های شراب")),
        dict(type="box", x=-1.42, z=1.95, hw=0.33, hd=0.65, h=0.9, rot=0.0, source="authored", label=dict(en="Wine Barrels", fa="بشکه‌های شراب")),
        dict(type="box", x=-1.5, z=5.4, hw=0.24, hd=0.9, h=1.05, rot=0.0, source="authored", label=dict(en="Bottle Rack", fa="قفسهٔ بطری")),
        dict(type="box", x=1.5, z=-5.4, hw=0.24, hd=0.9, h=1.05, rot=0.0, source="authored", label=dict(en="Bottle Rack", fa="قفسهٔ بطری")),
    ]
    return scene, obstacles, lights, dict(
        floor=["stonefloor", "travertine", "microcement", "oak", "calacatta"],
        wall=["brick", "stonefloor", "microcement", "timber"],
        furn=["timber", "walnut", "walnut", "walnut"],
    )


def recipe_school_hall(room):
    scene = trimesh.Scene()
    ring = room["portals"][0]["position"]
    build_shell(scene, room, ring, floor_key="oak", wall_key="plaster",
                ceil_key="plaster", baseboard_key="walnut",
                windows=[dict(side="w", c=-4.2, w=1.3, y0=1.6, y1=4.2),
                         dict(side="w", c=0.0, w=1.3, y0=1.6, y1=4.2),
                         dict(side="w", c=4.2, w=1.3, y0=1.6, y1=4.2),
                         dict(side="n", c=-2.6, w=1.3, y0=1.6, y1=4.2),
                         dict(side="n", c=2.6, w=1.3, y0=1.6, y1=4.2)])
    # stage (verified: full-width platform at the north end)
    scene.add_geometry(mbox((9.0, 0.45, 3.2), "walnut", center=(0, 0.225, -6.8), kind="furn"), node_name="stage_platform")
    scene.add_geometry(mbox((9.0, 0.5, 0.06), "velvet_green", center=(0, 2.0, -7.92), kind="furn"), node_name="stage_curtain")
    scene.add_geometry(mbox((0.6, 1.1, 0.4), "walnut", center=(1.6, 1.0, -6.4), kind="furn", tile=False), node_name="podium")
    # chair rows (4 rows; merged collider covers all)
    for r, z in enumerate((-5.2, -4.55, -3.9, -3.25)):
        scene.add_geometry(mbox((6.8, 0.06, 0.42), "walnut", center=(0, 0.44, z), kind="furn"), node_name=f"row_seat{r}")
        scene.add_geometry(mbox((6.8, 0.45, 0.05), "walnut", center=(0, 0.66, z - 0.185), kind="furn"), node_name=f"row_back{r}")
        scene.add_geometry(mbox((6.8, 0.42, 0.05), "fabric_ochre", center=(0, 0.66, z - 0.14), kind="furn"), node_name=f"row_cushion{r}")
        for dx in np.linspace(-3.3, 3.3, 12):
            scene.add_geometry(mbox((0.03, 0.40, 0.42), "iron_dark", center=(dx, 0.22, z), kind="furn", tile=False), node_name=f"row_legs{r}")
    # upright piano (verified cyl)
    add_parts(scene, [(mbox((0.38, 1.15, 1.35), "black_gloss", center=(-3.52, 0.58, -0.83), kind="furn", tile=False), "piano_body"),
                      (mbox((0.30, 0.05, 0.32), "white_paint", center=(-3.30, 0.72, -0.35), kind="furn", tile=False), "piano_keys"),
                      (mbox((0.42, 0.09, 1.45), "black_gloss", center=(-3.52, 0.30, -0.83), kind="furn", tile=False), "piano_base"),
                      (mbox((0.34, 0.48, 0.28), "black_gloss", center=(-2.85, 0.24, -0.83), kind="furn", tile=False), "piano_bench")])
    # wall sconces + stage floods
    for i, z in enumerate((-6.5, -2.0, 2.5, 6.0)):
        scene.add_geometry(mcyl(0.05, 0.1, "lamp_glow", center=(-4.42, 3.4, z), kind="furn", tile=False), node_name=f"sconce_w{i}")
        scene.add_geometry(mcyl(0.05, 0.1, "lamp_glow", center=(4.42, 3.4, z), kind="furn", tile=False), node_name=f"sconce_e{i}")
    lights = [
        {"type": "sun", "pos": [-9, 10, 0], "intensity": 1.9, "color": "#fff3e2"},
        {"type": "spot", "pos": [0, 5.4, -5.2], "intensity": 1.0, "color": "#ffd9a8", "distance": 10},
        {"type": "spot", "pos": [-3.52, 2.4, -0.83], "intensity": 0.4, "color": "#ffe6c4", "distance": 5},
        {"type": "spot", "pos": [0, 5.2, 2.0], "intensity": 0.5, "color": "#ffe6c4", "distance": 10},
    ]
    obstacles = [
        dict(type="box", x=0.0, z=-6.8, hw=4.5, hd=1.6, h=0.9, rot=0.0, source="vlm-verified", label=dict(en="Stage", fa="سکو")),
        dict(type="box", x=0.0, z=-4.22, hw=3.4, hd=1.05, h=0.9, rot=0.0, source="vlm-verified", label=dict(en="Chair Rows", fa="ردیف صندلی‌ها")),
        dict(type="cylinder", x=-3.52, z=-0.83, r=0.82, h=1.15, rot=0.0, source="vlm-verified", label=dict(en="Piano", fa="پیانو")),
    ]
    return scene, obstacles, lights, dict(
        floor=["oak", "herringbone", "calacatta", "terrazzo", "microcement"],
        wall=["plaster", "plaster_warm", "cream_gold", "microcement"],
        furn=["walnut", "fabric_ochre", "velvet_green", "walnut"],
    )


def recipe_leipzig_festsaal(room):
    scene = trimesh.Scene()
    ring = room["portals"][0]["position"]
    build_shell(scene, room, ring, floor_key="parquet_dark", wall_key="cream_gold",
                ceil_key="plaster_warm", baseboard_key="marble_black",
                windows=[dict(side="w", c=-4.5, w=1.4, y0=1.0, y1=4.4),
                         dict(side="w", c=0.0, w=1.4, y0=1.0, y1=4.4),
                         dict(side="w", c=4.5, w=1.4, y0=1.0, y1=4.4)])
    # stone fireplace (verified)
    add_parts(scene, parts_fireplace(4.55, 0.30, np.pi / 2, name="fireplace"))
    # statue on plinth (verified cyl)
    scene.add_geometry(mcyl(0.42, 0.9, "travertine", center=(3.70, 0.45, -2.70), kind="furn", sections=20, tile=False), node_name="statue_plinth")
    scene.add_geometry(mcyl(0.16, 0.5, "travertine", center=(3.70, 1.15, -2.70), kind="furn", r2=0.20, sections=18, tile=False), node_name="statue_bust")
    scene.add_geometry(mcyl(0.09, 0.22, "travertine", center=(3.70, 1.50, -2.70), kind="furn", r2=0.05, sections=14, tile=False), node_name="statue_head")
    # banquet table (authored collider)
    add_parts(scene, [(mbox((1.15, 0.07, 4.6), "walnut", center=(0, 0.76, 1.5), kind="furn"), "banquet_top")])
    for dx, dz in ((-0.45, -2.0), (0.45, -2.0), (-0.45, 2.0), (0.45, 2.0)):
        scene.add_geometry(mbox((0.09, 0.72, 0.09), "walnut", center=(dx, 0.36, 1.5 + dz), kind="furn", tile=False), node_name="banquet_leg")
    scene.add_geometry(mbox((0.9, 0.012, 4.0), "rug_classic", center=(0, 0.805, 1.5), kind="furn"), node_name="banquet_runner")
    for cx in (-1.2, 0, 1.2):
        scene.add_geometry(mcyl(0.025, 0.3, "brass", center=(cx, 0.95, 1.5), kind="furn", tile=False), node_name="candelabra_stem")
        scene.add_geometry(mcyl(0.06, 0.03, "brass", center=(cx, 1.11, 1.5), kind="furn", tile=False), node_name="candelabra_cup")
    # chandeliers ×2 + portraits
    for i, z in enumerate((-2.5, 2.2)):
        ch = []
        parts_chandelier(ch, 0, 6.4, z, drop=0.7, r=0.46, name=f"chan{i+1}")
        add_parts(scene, ch)
    add_art(scene, "art_le1", 1.0, 1.5, -4.93, 3.2, -3.0, "art_classic1", "x")
    add_art(scene, "art_le2", 1.0, 1.5, -4.93, 3.2, 2.0, "art_classic2", "x")
    add_art(scene, "art_le3", 1.2, 1.1, 4.93, 3.4, -4.0, "art_classic2", "x")
    add_art(scene, "art_le4", 1.2, 1.1, 4.93, 3.4, 4.5, "art_classic1", "x")
    lights = [
        {"type": "sun", "pos": [-10, 12, 0], "intensity": 2.0, "color": "#fff3e2"},
        {"type": "spot", "pos": [0, 5.4, -2.5], "intensity": 0.9, "color": "#ffd9a8", "distance": 10},
        {"type": "spot", "pos": [0, 5.4, 2.2], "intensity": 0.9, "color": "#ffd9a8", "distance": 10},
        {"type": "spot", "pos": [4.3, 0.9, 0.30], "intensity": 0.8, "color": "#ff8a3c", "distance": 4},
        {"type": "spot", "pos": [3.7, 2.0, -2.7], "intensity": 0.35, "color": "#ffe6c4", "distance": 5},
    ]
    obstacles = [
        dict(type="box", x=4.70, z=0.30, hw=0.32, hd=0.95, h=1.5, rot=0.0, source="vlm-verified", label=dict(en="Stone Fireplace", fa="شومینهٔ سنگی")),
        dict(type="cylinder", x=3.70, z=-2.70, r=0.45, h=1.7, rot=0.0, source="vlm-verified", label=dict(en="Statue", fa="مجسمه")),
        dict(type="box", x=0.0, z=1.5, hw=0.72, hd=2.4, h=0.8, rot=0.0, source="authored", label=dict(en="Banquet Table", fa="میز ضیافت")),
    ]
    return scene, obstacles, lights, dict(
        floor=["parquet_dark", "calacatta", "herringbone", "terrazzo", "microcement"],
        wall=["cream_gold", "plaster_warm", "plaster", "calacatta"],
        furn=["walnut", "velvet_green", "walnut", "brass"],
    )


def recipe_quadrangle_sunny(room):
    scene = trimesh.Scene()
    W, D = 24.0, 24.0
    hw = W / 2
    # gravel ground
    scene.add_geometry(mbox((W + 6, 0.10, D + 6), "gravel", center=(0, -0.05, 0), kind="floor"), node_name="floor_main")
    # lawn strips (decor)
    for x0 in (-8.5, 8.5):
        scene.add_geometry(mbox((5.0, 0.03, D - 4), "grass", center=(x0, 0.02, 0), kind="furn"), node_name=f"lawn_{'w' if x0<0 else 'e'}")
    # colonnade: columns + architrave + low stub walls (perimeter, outside walk bounds)
    xs = np.linspace(-hw + 1.0, hw - 1.0, 9)
    zs = np.linspace(-hw + 1.0, hw - 1.0, 9)
    for i, x in enumerate(xs):
        for z in (-hw + 0.2, hw - 0.2):
            scene.add_geometry(mcyl(0.19, 3.2, "travertine", center=(x, 1.6, z), sections=16, tile=False), node_name=f"col_x{i}_{'n' if z<0 else 's'}")
    for i, z in enumerate(zs):
        for x in (-hw + 0.2, hw - 0.2):
            scene.add_geometry(mcyl(0.19, 3.2, "travertine", center=(x, 1.6, z), sections=16, tile=False), node_name=f"col_z{i}_{'w' if x<0 else 'e'}")
    for side, (ex, ez, cx, cz) in {"n": (W - 1.2, 0.5, 0, -hw + 0.2), "s": (W - 1.2, 0.5, 0, hw - 0.2),
                                   "w": (0.5, D - 1.2, -hw + 0.2, 0), "e": (0.5, D - 1.2, hw - 0.2, 0)}.items():
        scene.add_geometry(mbox((ex, 0.35, ez), "travertine", center=(cx, 3.37, cz), kind="furn"), node_name=f"architrave_{side}")
    # manicured hedge (verified) + trees (verified)
    scene.add_geometry(mbox((6.4, 0.75, 1.1), "hedge", center=(0, 0.42, 11.20), kind="furn"), node_name="hedge_main")
    scene.add_geometry(mcyl(0.55, 0.18, "hedge", center=(0, 0.86, 11.20), sections=14, tile=False), node_name="hedge_crown")
    add_parts(scene, parts_tree(-11.0, 2.5, h=4.2, name="tree1"))
    add_parts(scene, parts_tree(-11.1, -3.5, h=3.8, name="tree2"))
    # central fountain (authored collider) + gravel paths
    scene.add_geometry(mcyl(1.5, 0.35, "travertine", center=(0, 0.17, 6.5), sections=24, tile=False), node_name="fountain_rim")
    scene.add_geometry(mcyl(1.25, 0.28, "calacatta", center=(0, 0.20, 6.5), sections=24, tile=False), node_name="fountain_basin")
    scene.add_geometry(mcyl(0.16, 0.8, "travertine", center=(0, 0.75, 6.5), sections=16, tile=False), node_name="fountain_stem")
    scene.add_geometry(mcyl(0.42, 0.06, "travertine", center=(0, 1.18, 6.5), sections=16, tile=False), node_name="fountain_top")
    scene.add_geometry(mcyl(0.30, 0.05, "mirror", center=(0, 1.22, 6.5), sections=16, tile=False), node_name="fountain_water")
    lights = [
        {"type": "sun", "pos": [-18, 26, 10], "intensity": 3.0, "color": "#fff6e8"},
        {"type": "spot", "pos": [0, 6, 6.5], "intensity": 0.3, "color": "#cfe8ff", "distance": 12},
    ]
    obstacles = [
        dict(type="box", x=0.0, z=11.20, hw=3.2, hd=0.55, h=0.8, rot=0.0, source="vlm-verified", label=dict(en="Manicured Hedge", fa="بوتهٔ چمن‌زنی")),
        dict(type="cylinder", x=-11.0, z=2.5, r=0.8, h=4.2, rot=0.0, source="vlm-verified", label=dict(en="Tree", fa="درخت")),
        dict(type="cylinder", x=-11.1, z=-3.5, r=0.8, h=3.8, rot=0.0, source="vlm-verified", label=dict(en="Tree", fa="درخت")),
        dict(type="cylinder", x=0.0, z=6.5, r=1.5, h=1.25, rot=0.0, source="authored", label=dict(en="Fountain", fa="فواره")),
    ]
    return scene, obstacles, lights, dict(
        floor=["gravel", "stonefloor", "terrazzo", "travertine", "microcement"],
        wall=["travertine", "stonefloor", "microcement", "calacatta"],
        furn=["hedge", "travertine", "walnut", "travertine"],
    )


RECIPES = {
    "modern_3d_villa": recipe_villa,
    "anniversary_lounge": recipe_anniversary_lounge,
    "cabin": recipe_cabin,
    "ballroom": recipe_ballroom,
    "comfy_cafe": recipe_comfy_cafe,
    "art_studio": recipe_art_studio,
    "large_corridor": recipe_large_corridor,
    "castle_zavelstein_cellar": recipe_castle_cellar,
    "school_hall": recipe_school_hall,
    "leipzig_festsaal": recipe_leipzig_festsaal,
    "quadrangle_sunny": recipe_quadrangle_sunny,
}

SKY_BY_STYLE = {
    "modern": {"zenith": "#7db3e8", "horizon": "#eef2f4", "sun": "#fff3dd", "sun_dir": [-0.62, 0.55, 0.22]},
    "classic": {"zenith": "#8fbbe0", "horizon": "#f2eee4", "sun": "#ffeecc", "sun_dir": [-0.5, 0.6, 0.3]},
    "cozy": {"zenith": "#86aed6", "horizon": "#f4ead8", "sun": "#ffe9c0", "sun_dir": [0.4, 0.55, -0.4]},
    "historic": {"zenith": "#7ba6cc", "horizon": "#efe9dc", "sun": "#ffe8bc", "sun_dir": [-0.55, 0.5, 0.35]},
}
SKY_OVERRIDE = {
    "castle_zavelstein_cellar": {"zenith": "#1c2430", "horizon": "#2c3442", "sun": "#4a5468", "sun_dir": [0.3, 0.8, -0.2]},
    "quadrangle_sunny": {"zenith": "#6fa8e8", "horizon": "#f6f2e6", "sun": "#fffbe8", "sun_dir": [-0.55, 0.62, 0.3]},
    "modern_3d_villa": {"zenith": "#7db3e8", "horizon": "#eef2f4", "sun": "#fff3dd", "sun_dir": [-0.62, 0.55, 0.22]},
}

WALK_BADGE = {
    "en": "🚶 True-3D Walk · 🌐 360° Photo",
    "fa": "🚶 قدم‌زدن سه‌بعدی · 🌐 عکس ۳۶۰ اصلی",
}
VILLA_BADGE = {
    "en": "🧊 True 3D space (LiDAR / 3D Mesh)",
    "fa": "🧊 فضای سه‌بعدی واقعی (LiDAR / 3D Mesh)",
}


def build_all(only=None):
    os.makedirs(OUT_DIR, exist_ok=True)
    export_palette(MATS_DIR)
    db = json.load(open(DB_PATH, encoding="utf-8"))
    total_bytes = 0
    for room in db["rooms"]:
        rid = room["id"]
        if rid not in RECIPES:
            continue
        if only and rid != only:
            continue
        recipe = RECIPES[rid]
        scene, obstacles, lights, mats = recipe(copy.deepcopy(room))
        path = os.path.join(OUT_DIR, rid + ".glb")
        glb = scene.export(file_type="glb")
        with open(path, "wb") as f:
            f.write(glb)
        total_bytes += len(glb)

        W = room["room_shape"]["width"]
        D = room["room_shape"]["depth"]
        # ---- merge into the DB record ----
        if rid != "modern_3d_villa":
            room["type"] = "hybrid"
            room["badge"] = dict(WALK_BADGE)
            room["glb"] = "assets/true3d/" + rid + ".glb"
        else:
            room["badge"] = dict(VILLA_BADGE)
        room["sky"] = dict(SKY_OVERRIDE.get(rid) or SKY_BY_STYLE.get(room.get("style_family"), SKY_BY_STYLE["modern"]))
        room["mats"] = mats
        walk = room.setdefault("walk", {})
        walk["player_radius"] = walk.get("player_radius", 0.3)
        walk["bounds"] = {"minX": -(W / 2 - 0.42), "maxX": W / 2 - 0.42,
                          "minZ": -(D / 2 - 0.42), "maxZ": D / 2 - 0.42}
        if rid == "modern_3d_villa":
            walk["bounds"] = {"minX": -2.75, "maxX": 2.75, "minZ": -2.15, "maxZ": 2.15}
        walk["obstacles"] = obstacles
        walk["lights"] = lights
        n_mesh = len(scene.geometry)
        n_tris = sum(len(g.faces) for g in scene.geometry.values())
        print(f"  {rid:26s} → {len(glb)/1024:7.0f} KB · {n_mesh:3d} meshes · {n_tris:6d} tris")
    json.dump(db, open(DB_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(db, open(DB_PUBLIC, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  DB merged → {DB_PATH} (+ mirror)")
    print(f"  TOTAL GLB: {total_bytes/1024:.0f} KB")
    return db


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    print("== PANODROME · building ALL 11 true-3D rooms ==")
    build_all(only)
