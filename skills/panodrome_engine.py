#!/usr/bin/env python3
"""
================================================================================
 PANODROME — THE WALKABLE ENGINE
================================================================================

This file is THE engine. When you ask "which engine made this room 3D?", the
answer is always this one, and every room it touches carries its fingerprint:

    engine.id      = "walkable-truth"
    engine.version = "1.0.0"

One command turns a chosen 360 panorama into a metric, collidable 3D space:

    python3 skills/panodrome_engine.py build \
        --pano public/assets/panoramas/cabin.jpg \
        --depth depth/cabin.npy \
        --id cabin

and it writes `geometry` (+ a ready `walk` block) into the rooms database, only
if the quality gates pass.

WHY THIS ENGINE AND NOT THE OLDER ONES
  Older stages built the room by displacing the panorama's vertices with a depth
  map (relief dome, shoebox, plumb patches). Those are permanently banned: they
  bend straight lines. This engine keeps the photograph on a pristine sphere and
  measures a SEPARATE metric proxy — floor polygon, floor/ceiling planes,
  obstacle boxes. Collision and parallax read the proxy; the eye reads the photo.

INPUTS (one of these, explicitly named so nothing is hidden)
  --depth   metric ERP depth: .npy float metres, or 16-bit PNG (+ --depth-scale)
            => source.kind = "measured"    (best: PaGeR-metric-depth / DA-V2)
  --depth-cmd  a shell command that writes a .npy from the pano (model hook)
            => source.kind = "estimated"
  --plan    an architect's plan, rect:6x4.2:2.8 or a JSON floor polygon
            => source.kind = "declared"    (no depth model needed at all)

OUTPUT (per room, in data/rooms_db.json + public/data/rooms_db.json)
  geometry : schema, engine, source, camera_height_m, floor_y, ceiling_h,
             floor_polygon, walls, obstacles, area_m2, confidence, gates
  walk     : polygon + obstacle list in the exact shape public/js/collider.js
             already consumes (bounds kept as an AABB fallback)

COMMANDS
  info                       identity card: engine id, version, laws, gates
  build --pano ... --id ...  convert one panorama into a walkable room
  verify                     re-check every room that carries geometry
  list                       which rooms are engine-built, and how
================================================================================
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from walkable_layout_fit import (  # noqa: E402
    GATES, fit_layout, polygon_area, run_gates,
)
from walk_budget import walk_budget  # noqa: E402

ENGINE_ID = "walkable-truth"
ENGINE_VERSION = "1.0.0"
SCHEMA = "panodrome.room_geometry/1"
DEFAULT_DBS = ("data/rooms_db.json", "public/data/rooms_db.json")


# ----------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------

def banner() -> str:
    return (f"PANODROME WALKABLE ENGINE  v{ENGINE_VERSION}  "
            f"[{ENGINE_ID}/{ENGINE_VERSION}]")


def sha256_file(path: str, limit: int = 8 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        remaining = limit
        while remaining > 0:
            chunk = fh.read(min(1 << 20, remaining))
            if not chunk:
                break
            h.update(chunk)
            remaining -= len(chunk)
    return h.hexdigest()[:16]


def load_depth(path: str, scale: float | None = None) -> np.ndarray:
    """Metric ERP depth from .npy, or 16-bit PNG where value/scale = metres."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".npy":
        d = np.load(path).astype(np.float64)
    elif ext in (".png", ".tif", ".tiff"):
        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("16-bit depth needs Pillow: pip install pillow") from exc
        d = np.asarray(Image.open(path)).astype(np.float64)
        if scale is None:
            raise SystemExit("--depth-scale is required for image depth "
                             "(metres = pixel / scale)")
        d = d / float(scale)
    else:
        raise SystemExit(f"unsupported depth format: {ext} (use .npy or 16-bit PNG)")
    if d.ndim != 2:
        raise SystemExit(f"depth must be a single 2-D ERP map, got shape {d.shape}")
    if not np.isfinite(d).any():
        raise SystemExit("depth map has no finite values")
    return d


def global_bbox(poly: np.ndarray) -> dict:
    return {"minX": round(float(poly[:, 0].min()), 4),
            "maxX": round(float(poly[:, 0].max()), 4),
            "minZ": round(float(poly[:, 1].min()), 4),
            "maxZ": round(float(poly[:, 1].max()), 4)}


def walk_block(geom: dict) -> dict:
    """
    The runtime contract used by public/js/collider.js.

    `polygon` is the exact boundary (concave included); `bounds` stays as the
    AABB fallback for older builds; obstacles use the existing box/cylinder
    vocabulary so the halo and proxy meshes keep working unchanged.
    """
    poly = np.asarray(geom["floor_polygon"], dtype=float)
    obstacles = []
    for o in geom.get("obstacles", []):
        obstacles.append({
            "type": "box",
            "x": o["centre_xz"][0],
            "z": o["centre_xz"][1],
            "hw": round(o["extent_xz"][0] / 2.0, 4),
            "hd": round(o["extent_xz"][1] / 2.0, 4),
            "rot": math.radians(o.get("yaw_deg", 0.0)),
            "label": {"en": "Furniture", "fa": "مبلمان"},
            "height": round(o["top_y"] - o["base_y"], 4),
            "base": round(o["base_y"], 4),
            "engine": f"{ENGINE_ID}/{ENGINE_VERSION}",
        })
    out = {
        "player_radius": 0.28,
        "bounds": global_bbox(poly),
        "polygon": [[round(float(x), 4), round(float(z), 4)] for x, z in poly],
        "ceiling_h": geom["ceiling_h"],
        "floor_y": geom["floor_y"],
        "obstacles": obstacles,
        "engine": f"{ENGINE_ID}/{ENGINE_VERSION}",
    }
    return out


def geometry_from_plan(plan: dict, pano: str | None) -> dict:
    """
    Build geometry from a human-declared plan — no depth model involved.

    This exists because a panorama on its own carries no metric information. For
    an arbitrary 360 the honest fast path is: state the room outline (or click
    its corners) and let the engine assemble a correct, gate-checked collider.
    """
    poly = np.asarray(plan["floor_polygon"], dtype=float)
    if poly.ndim != 2 or poly.shape[1] != 2 or len(poly) < 3:
        raise SystemExit("plan.floor_polygon must be [[x,z], ...] with >= 3 points")
    ceil_h = float(plan.get("ceiling_h", 2.8))
    cam_h = float(plan.get("camera_height_m", 1.6))
    obstacles = []
    for o in plan.get("obstacles", []):
        cx, cz = o["centre_xz"]
        w, d = o["extent_xz"]
        obstacles.append({
            "centre_xz": [float(cx), float(cz)],
            "yaw_deg": float(o.get("yaw_deg", 0.0)),
            "extent_xz": [float(w), float(d)],
            "base_y": float(o.get("base_y", -cam_h)),
            "top_y": float(o.get("top_y", -cam_h + float(o.get("height", 0.75)))),
            "points": 0,
        })
    area = polygon_area(poly)
    geom = {
        "schema": SCHEMA,
        "units": "metres",
        "engine": {"id": ENGINE_ID, "version": ENGINE_VERSION},
        "source": {"kind": "declared", "detail": plan.get("source_note", "architect plan")},
        "gravity": {"tilt_deg": 0.0, "yaw_deg": float(plan.get("yaw_deg", 0.0))},
        "camera_height_m": cam_h,
        "floor_y": -cam_h,
        "ceiling_h": ceil_h,
        "floor_polygon": [[round(float(x), 4), round(float(z), 4)] for x, z in poly],
        "walls": [],
        "area_m2": round(float(area), 3),
        "obstacles": obstacles,
        "confidence": {
            "coverage": None,
            "floor_flat_rms_m": 0.0,
            "wall_plumb_deg": 0.0,
            "manhattan_resid_m": 0.0,
            "declared": True,
        },
    }
    ok = (len(poly) >= 3
          and GATES["area_m2"][0] <= area <= GATES["area_m2"][1]
          and GATES["ceiling_h_m"][0] <= ceil_h <= GATES["ceiling_h_m"][1])
    geom["gates"] = {
        "polygon_closed": len(poly) >= 3,
        "area": GATES["area_m2"][0] <= area <= GATES["area_m2"][1],
        "ceiling_height": GATES["ceiling_h_m"][0] <= ceil_h <= GATES["ceiling_h_m"][1],
        "declared_plan": True,
        "all_pass": bool(ok),
    }
    return geom


def run_engine(depth: np.ndarray | None, plan: dict | None, pano: str,
               source_kind: str, source_detail: str,
               depth_path: str | None = None) -> dict:
    """One entry point, one engine, one output shape."""
    if depth is not None:
        geom = fit_layout(depth)
        # Lane C: how far the photograph can be walked before pixels are unknown
        try:
            geom["walk_budget"] = walk_budget(depth)
            geom["level"] = "L1"
        except Exception as exc:  # never block a bake on the budget
            print(f"  ! walk budget failed: {exc}")
        geom["engine"] = {"id": ENGINE_ID, "version": ENGINE_VERSION}
        geom["source"] = {"kind": source_kind, "detail": source_detail}
        if depth_path:
            geom["source"]["depth_file"] = os.path.relpath(depth_path, ROOT)
        n = int(np.count_nonzero(np.isfinite(depth) & (depth > 0)))
        geom["confidence"]["depth_pixels"] = n
    elif plan is not None:
        geom = geometry_from_plan(plan, pano)
    else:  # pragma: no cover - guarded by CLI
        raise SystemExit("the engine needs depth or a plan")
    geom["source"]["pano"] = os.path.relpath(pano, ROOT) if pano else None
    geom["source"]["pano_sha256_16"] = sha256_file(pano) if pano and os.path.exists(pano) else None
    geom["built_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return geom


# ----------------------------------------------------------------------------
# database
# ----------------------------------------------------------------------------

def load_db(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_db(path: str, db: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(db, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    os.replace(tmp, path)


def rooms_of(db: dict) -> list[dict]:
    return db["rooms"] if isinstance(db, dict) and "rooms" in db else db


def find_room(db: dict, room_id: str) -> dict | None:
    for r in rooms_of(db):
        if r.get("id") == room_id:
            return r
    return None


def write_geometry(dbs: list[str], room_id: str, geom: dict, create: bool,
                   sync_walk: bool) -> list[str]:
    written = []
    for path in dbs:
        if not os.path.exists(path):
            continue
        db = load_db(path)
        room = find_room(db, room_id)
        if room is None:
            if not create:
                print(f"  ! {path}: no room '{room_id}' (use --create-room)")
                continue
            room = {"id": room_id, "room_type": "living_room",
                    "name": {"en": room_id.replace("_", " ").title(), "fa": room_id},
                    "panorama": geom.get("source", {}).get("pano"),
                    "portals": []}
            rooms_of(db).append(room)
        room["geometry"] = geom
        if sync_walk:
            room["walk"] = walk_block(geom)
        save_db(path, db)
        written.append(path)
    return written


def write_engine_manifest() -> None:
    path = os.path.join(ROOT, "data", "engine.json")
    data = {
        "engine": {"id": ENGINE_ID, "version": ENGINE_VERSION},
        "role": "The ONLY converter from a 360 panorama to a collidable 3D room.",
        "laws": [
            "the panorama sphere is never displaced (zero-warp law)",
            "geometry is metric and measured or explicitly declared",
            "a room whose gates fail is not written to the database",
            "collision reads geometry.floor_polygon + obstacles, never the photo",
        ],
        "command": "python3 skills/panodrome_engine.py build --pano <pano> --depth <depth.npy> --id <room>",
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# ----------------------------------------------------------------------------
# commands
# ----------------------------------------------------------------------------

def cmd_info(_args) -> int:
    print(banner())
    print("-" * 78)
    print("Turns a chosen 360 equirectangular panorama into a metric, walkable 3D")
    print("space: an exact floor polygon, floor/ceiling heights and obstacle boxes.")
    print()
    print("  photo  -> pristine sphere, never deformed")
    print("  geometry -> separate metric proxy, the authority for collision")
    print()
    print("Depth sources (explicit, recorded per room):")
    print("  measured   --depth room.npy | room16.png --depth-scale 1000")
    print("             (PaGeR-metric-depth, DepthMaster, DA-V2-Hypersim ...)")
    print("  estimated  --depth-cmd 'python3 my_depth_model.py {pano} {out}'")
    print("  declared   --plan rect:6x4.2:2.8   or   --plan room_plan.json")
    print()
    print("Gates that must pass before a room is written:")
    for k, v in GATES.items():
        print(f"  {k:<20} {v}")
    print()
    print("Commands:")
    print("  info                          this card")
    print("  build  --pano P --id ID ...   convert one panorama")
    print("  verify                        re-check every engine-built room")
    print("  list                          which rooms are engine-built")
    print()
    print("Every room this engine writes carries:")
    print(f'  "geometry": {{ "engine": {{ "id": "{ENGINE_ID}", "version": "{ENGINE_VERSION}" }}, ... }}')
    return 0


def cmd_build(args) -> int:
    print(banner())
    pano = os.path.abspath(args.pano) if args.pano else ""
    if pano and not os.path.exists(pano):
        raise SystemExit(f"panorama not found: {pano}")

    depth = None
    plan = None
    kind, detail = "", ""

    if args.depth:
        depth = load_depth(args.depth, args.depth_scale)
        kind, detail = "measured", f"metric ERP depth file ({os.path.basename(args.depth)})"
    elif args.depth_cmd:
        tmpdir = tempfile.mkdtemp(prefix="pano_depth_")
        out = os.path.join(tmpdir, "depth.npy")
        cmd = args.depth_cmd.format(pano=pano, out=out)
        print(f"  running depth backend: {cmd}")
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode != 0 or not os.path.exists(out):
            print(res.stdout[-2000:])
            print(res.stderr[-2000:])
            raise SystemExit("depth backend failed")
        depth = load_depth(out)
        kind, detail = "estimated", f"external backend: {args.depth_cmd}"
    elif args.plan:
        if args.plan.startswith("rect:"):
            parts = args.plan.split(":")
            w, d = float(parts[1].split("x")[0]), float(parts[1].split("x")[1])
            ceil_h = float(parts[2]) if len(parts) > 2 else 2.8
            plan = {"floor_polygon": [[-w / 2, -d / 2], [w / 2, -d / 2],
                                      [w / 2, d / 2], [-w / 2, d / 2]],
                    "ceiling_h": ceil_h, "source_note": f"rectangular plan {w}x{d} m"}
        else:
            with open(args.plan, "r", encoding="utf-8") as fh:
                plan = json.load(fh)
        kind, detail = "declared", "architect-supplied plan (no depth model)"
    else:
        raise SystemExit(
            "no geometry source given.\n"
            "  --depth measured.npy   (best)\n"
            "  --depth-cmd '...'      (model hook)\n"
            "  --plan rect:6x4.2:2.8  (declared)\n"
            "The engine will not invent a room from a photograph alone."
        )

    geom = run_engine(depth, plan, pano, kind, detail, args.depth)
    g = geom["gates"]
    print(f"  source      {kind}: {detail}")
    print(f"  area        {geom['area_m2']} m2")
    print(f"  ceiling     {geom['ceiling_h']} m   (camera {geom['camera_height_m']} m)")
    print(f"  polygon     {len(geom['floor_polygon'])} vertices")
    print(f"  obstacles   {len(geom['obstacles'])}")
    c = geom["confidence"]
    if c.get("coverage") is not None:
        print(f"  confidence  coverage={c['coverage']}  wall_plumb={c['wall_plumb_deg']}deg  "
              f"floor_rms={c['floor_flat_rms_m']}m  manhattan={c['manhattan_resid_m']}m")
    print(f"  gates       {'ALL PASS' if g['all_pass'] else 'FAILED'}")

    if not g["all_pass"] and not args.force:
        bad = [k for k, v in g.items() if not v and k != "all_pass"]
        print(f"\n  REFUSED: {', '.join(bad)} failed. Nothing was written.")
        print("  Fix the depth, or pass --force to store it flagged as failing.")
        return 2

    dbs = args.db or [p for p in DEFAULT_DBS if os.path.exists(os.path.join(ROOT, p))]
    dbs = [p if os.path.isabs(p) else os.path.join(ROOT, p) for p in dbs]
    if not dbs:
        raise SystemExit("no database file found")
    written = write_geometry(dbs, args.id, geom, args.create_room, not args.no_sync_walk)
    if not written:
        print("\n  nothing written (missing room id?)")
        return 3
    for w in written:
        print(f"  wrote       {os.path.relpath(w, ROOT)}")
    print(f"\n  {ENGINE_ID}/{ENGINE_VERSION} built '{args.id}'.")
    return 0


def cmd_verify(args) -> int:
    print(banner())
    dbs = args.db or [p for p in DEFAULT_DBS if os.path.exists(os.path.join(ROOT, p))]
    dbs = [p if os.path.isabs(p) else os.path.join(ROOT, p) for p in dbs]
    if not dbs:
        raise SystemExit("no database file found")
    db = load_db(dbs[0])
    rows, bad = [], 0
    for room in rooms_of(db):
        geom = room.get("geometry")
        if not geom:
            continue
        ok = bool(geom.get("gates", {}).get("all_pass"))
        if not ok:
            bad += 1
        eng = geom.get("engine", {})
        rows.append((room["id"], f"{eng.get('id')}/{eng.get('version')}",
                     geom.get("source", {}).get("kind"), geom.get("area_m2"),
                     len(geom.get("floor_polygon", [])), len(geom.get("obstacles", [])),
                     "PASS" if ok else "FAIL"))
    if not rows:
        print("  no room carries geometry yet — run: build --pano ... --depth ... --id ...")
        return 0
    print(f"  {'room':<24}{'engine':<22}{'source':<12}{'area':>8}{'vtx':>5}{'obs':>5}  gates")
    for r in rows:
        print(f"  {r[0]:<24}{r[1]:<22}{str(r[2]):<12}{r[3]:>8}{r[4]:>5}{r[5]:>5}  {r[6]}")
    print(f"\n  {len(rows)} engine-built rooms, {bad} failing.")
    return 0 if bad == 0 else 2


def cmd_list(args) -> int:
    print(banner())
    dbs = args.db or [p for p in DEFAULT_DBS if os.path.exists(os.path.join(ROOT, p))]
    dbs = [p if os.path.isabs(p) else os.path.join(ROOT, p) for p in dbs]
    db = load_db(dbs[0])
    built, legacy = [], []
    for room in rooms_of(db):
        (built if room.get("geometry") else legacy).append(room["id"])
    print(f"  engine-built ({len(built)}): {', '.join(built) or '-'}")
    print(f"  legacy bounds only ({len(legacy)}): {', '.join(legacy) or '-'}")
    print(f"\n  convert one:  python3 skills/panodrome_engine.py build "
          f"--pano public/assets/panoramas/<id>.jpg --depth <id>.npy --id <id>")
    return 0


# ----------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="panodrome_engine",
        description=f"{banner()} — 360 panorama -> metric walkable room")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="engine identity card").set_defaults(func=cmd_info)

    b = sub.add_parser("build", help="convert one panorama into a walkable room")
    b.add_argument("--pano", required=True, help="360 equirectangular image")
    b.add_argument("--id", required=True, help="room id in rooms_db.json")
    b.add_argument("--depth", help="metric ERP depth (.npy or 16-bit PNG)")
    b.add_argument("--depth-scale", type=float, default=None,
                   help="for 16-bit PNG depth: metres = pixel / scale")
    b.add_argument("--depth-cmd", help="shell command that writes a .npy "
                                       "({pano} and {out} are substituted)")
    b.add_argument("--plan", help="rect:WxD[:ceiling_h] or a plan .json")
    b.add_argument("--db", action="append", help="database path (repeatable)")
    b.add_argument("--create-room", action="store_true",
                   help="append a new room record if the id is not in the db")
    b.add_argument("--no-sync-walk", action="store_true",
                   help="only write geometry, leave the legacy walk block alone")
    b.add_argument("--force", action="store_true",
                   help="write even if gates fail (flagged all_pass=false)")
    b.set_defaults(func=cmd_build)

    v = sub.add_parser("verify", help="re-check every engine-built room")
    v.add_argument("--db", action="append")
    v.set_defaults(func=cmd_verify)

    lst = sub.add_parser("list", help="which rooms are engine-built")
    lst.add_argument("--db", action="append")
    lst.set_defaults(func=cmd_list)

    args = ap.parse_args(argv)
    write_engine_manifest()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
