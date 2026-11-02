#!/usr/bin/env python3
"""STAGE 1.5 CURATION — the true-walk 10-room DB.

Rooms (curated walking narrative):
  1 anniversary_lounge   living_room  classic  PolyHaven      door f=0.020 (stage-1 VLM YES)
  2 art_studio           studio       modern   PolyHaven      door f=0.058 (stage-1 VLM YES)
  3 cabin                bedroom      cozy     PolyHaven      door f=0.355 (stage-1 VLM YES)
  4 comfy_cafe           cafe         cozy     PolyHaven      door f=0.685 (stage-1 VLM YES)
  5 large_corridor       corridor     classic  PolyHaven      door f=0.105 (VLM YES 2026-11-02 "dark wooden open double doorway")
  6 castle_zavelstein_cellar cellar   historic PolyHaven      door f=0.110 (VLM YES 2026-11-02)
  7 ballroom             hall         classic  PolyHaven      door f=0.335 (stage-1 VLM YES)
  8 school_hall          auditorium   historic PolyHaven      door f=0.594 (VLM YES 2026-11-02)
  9 leipzig_festsaal     banquet_hall classic  Heritage 360   door f=0.780 (VLM YES 2026-11-02 "arched wooden double doors")
 10 quadrangle_sunny     courtyard    open_air PolyHaven      door f=0.490 (stage-1 VLM YES)

Geometry law (room.js renders this):
  · room box = width x depth footprint centred at WORLD ORIGIN x/z, floor y=0,
    ceiling y=height; the pano capture point = room.camera (inside the box,
    usually (0, 1.6, 0); large_corridor stands at z=-1.5).
  · doorway ring = ray from capture point along the VLM-verified horizontal
    fraction, intersected with the box wall, pulled back 0.35 m, at y=1.3
    (door-centre height). Fully analytic — no depth map needed.

Walk data (collider.js):
  · room_bounds: box inset 0.6 m from every wall (camera never nearer than
    0.6 m to a wall — no clipping, no pixel-stretch).
  · obstacle_colliders: authored from the 2026-11-02 VLM obstacle strips
    (/tmp/s15check) cross-checked with the 3203ae2 VLM hotspot positions.
    box: {x, z, hw, hd}   cylinder: {x, z, r}   + EN/FA labels.

Writes data/rooms_db.json and public/data/rooms_db.json IDENTICALLY (md5).
"""
import hashlib, json, math, subprocess

ROOT = "/home/z/my-project/3d-idea"
WALL_BUFFER = 0.6
PLAYER_R = 0.30          # collider.js player radius (info only)
DOOR_Y = 1.3             # door-centre height
PULLBACK = 0.35          # ring floats this far in front of the wall
EYE = 1.6                # pano capture height (room.camera.y)

ORDER = [
    "anniversary_lounge", "art_studio", "cabin", "comfy_cafe", "large_corridor",
    "castle_zavelstein_cellar", "ballroom", "school_hall", "leipzig_festsaal",
    "quadrangle_sunny",
]
DOOR_FRAC = {
    "anniversary_lounge": 0.020, "art_studio": 0.058, "cabin": 0.355,
    "comfy_cafe": 0.685, "large_corridor": 0.105, "castle_zavelstein_cellar": 0.110,
    "ballroom": 0.335, "school_hall": 0.594, "leipzig_festsaal": 0.780,
    "quadrangle_sunny": 0.490,
}
STYLE_FAMILY = {
    "anniversary_lounge": "classic", "art_studio": "modern", "cabin": "cozy",
    "comfy_cafe": "cozy", "large_corridor": "classic", "castle_zavelstein_cellar": "historic",
    "ballroom": "classic", "school_hall": "historic", "leipzig_festsaal": "classic",
    "quadrangle_sunny": "open_air",
}
TYPE_GROUP = {
    "anniversary_lounge": "residential", "art_studio": "residential", "cabin": "residential",
    "comfy_cafe": "hospitality", "ballroom": "hospitality", "leipzig_festsaal": "hospitality",
    "large_corridor": "heritage", "castle_zavelstein_cellar": "heritage", "school_hall": "heritage",
    "quadrangle_sunny": "outdoor",
}

# obstacle colliders — VLM strips 2026-11-02 x 3203ae2 VLM hotspots (see header)
def L(en, fa):
    return {"en": en, "fa": fa}

OBSTACLES = {
    "anniversary_lounge": [
        {"type": "box", "x": -1.95, "z": -1.30, "hw": 0.32, "hd": 1.00, "label": L("Sofa", "مبل راحتی")},
        {"type": "cylinder", "x": -1.25, "z": -1.30, "r": 0.50, "label": L("Coffee Table", "میز عسلی")},
        {"type": "cylinder", "x": -1.10, "z": -2.35, "r": 0.55, "label": L("Armchair", "صندلی راحتی")},
        {"type": "box", "x": 0.90, "z": 2.75, "hw": 0.85, "hd": 0.30, "label": L("Sideboard", "بوفه چوبی")},
    ],
    "art_studio": [
        {"type": "cylinder", "x": -1.80, "z": 1.30, "r": 0.65, "label": L("Work Table", "میز کار")},
        {"type": "box", "x": -0.40, "z": 3.10, "hw": 0.65, "hd": 0.50, "label": L("Studio Stairs", "پله‌های استودیو")},
        {"type": "box", "x": 1.70, "z": 0.60, "hw": 0.85, "hd": 0.60, "label": L("Paint Table", "میز نقاشی")},
        {"type": "cylinder", "x": 1.90, "z": -1.90, "r": 0.60, "label": L("Table", "میز")},
        {"type": "cylinder", "x": 0.50, "z": -3.00, "r": 0.50, "label": L("Easel", "چوب‌قاب نقاشی")},
    ],
    "cabin": [
        {"type": "box", "x": 0.0, "z": -1.55, "hw": 1.25, "hd": 0.70, "label": L("Bed", "تخت‌خواب")},
        {"type": "box", "x": 0.0, "z": 2.00, "hw": 0.75, "hd": 0.38, "label": L("Desk", "میز کار")},
        {"type": "box", "x": 1.25, "z": 1.75, "hw": 0.40, "hd": 0.42, "label": L("Cabinet", "کمد")},
        {"type": "cylinder", "x": 1.35, "z": 0.35, "r": 0.50, "label": L("Chair", "صندلی")},
    ],
    "comfy_cafe": [
        {"type": "cylinder", "x": -2.00, "z": 0.00, "r": 0.55, "label": L("Café Table", "میز کافه")},
        {"type": "box", "x": -1.40, "z": 2.60, "hw": 0.75, "hd": 0.45, "label": L("Sofa", "مبل")},
        {"type": "box", "x": 0.90, "z": 3.00, "hw": 0.90, "hd": 0.45, "label": L("Sofa Bench", "نیمکت")},
        {"type": "cylinder", "x": 1.90, "z": 1.90, "r": 0.55, "label": L("Café Table", "میز کافه")},
        {"type": "cylinder", "x": 2.10, "z": 0.40, "r": 0.50, "label": L("Café Table", "میز کافه")},
        {"type": "box", "x": -0.80, "z": -3.00, "hw": 0.85, "hd": 0.45, "label": L("Sofa Bench", "نیمکت")},
    ],
    "large_corridor": [
        {"type": "box", "x": 1.45, "z": 4.90, "hw": 0.45, "hd": 0.45, "label": L("Ceramic Stove", "بخاری سفالی")},
        {"type": "box", "x": -1.45, "z": 0.70, "hw": 0.45, "hd": 0.45, "label": L("Tiled Stove", "بخاری کاشی‌کاری")},
    ],
    "castle_zavelstein_cellar": [],   # empty vaulted cellar — walls only (honest)
    "ballroom": [
        {"type": "box", "x": -3.60, "z": 2.30, "hw": 0.85, "hd": 1.10, "label": L("Grand Piano", "پیانو گرند")},
    ],
    "school_hall": [
        {"type": "box", "x": 0.0, "z": -6.80, "hw": 4.50, "hd": 1.60, "label": L("Stage", "سکوی مدرسه")},
        {"type": "box", "x": 0.0, "z": -4.30, "hw": 3.40, "hd": 0.55, "label": L("Chair Rows", "ردیف صندلی‌ها")},
        {"type": "box", "x": 0.0, "z": -2.90, "hw": 3.40, "hd": 0.55, "label": L("Chair Rows", "ردیف صندلی‌ها")},
        {"type": "box", "x": -3.80, "z": -1.60, "hw": 0.80, "hd": 1.05, "label": L("Piano", "پیانو")},
    ],
    "leipzig_festsaal": [
        {"type": "box", "x": 4.70, "z": 0.30, "hw": 0.32, "hd": 0.95, "label": L("Stone Fireplace", "شومینه سنگی")},
        {"type": "cylinder", "x": 3.70, "z": -2.70, "r": 0.45, "label": L("Statue", "مجسمه")},
    ],
    "quadrangle_sunny": [
        {"type": "box", "x": 0.0, "z": 11.20, "hw": 3.20, "hd": 0.55, "label": L("Manicured Hedge", "دیوار سبز")},
        {"type": "cylinder", "x": -11.00, "z": 2.50, "r": 0.80, "label": L("Tree", "درخت")},
        {"type": "cylinder", "x": -11.10, "z": -3.50, "r": 0.80, "label": L("Tree", "درخت")},
    ],
}


def hdir(frac):
    phi = 2 * math.pi * frac
    return (-math.cos(phi), math.sin(phi))


def wall_dist(cx, cz, dx, dz, hw, hd):
    """Distance from (cx,cz) along (dx,dz) to the box x∈[-hw,hw], z∈[-hd,hd]."""
    t = float("inf")
    if dx < -1e-9:
        t = min(t, (cx + hw) / -dx)
    if dx > 1e-9:
        t = min(t, (hw - cx) / dx)
    if dz < -1e-9:
        t = min(t, (cz + hd) / -dz)
    if dz > 1e-9:
        t = min(t, (hd - cz) / dz)
    return t


def solve_door(room, frac):
    w, h, d = room["room_shape"]["width"], room["room_shape"]["height"], room["room_shape"]["depth"]
    hw, hd = w / 2.0, d / 2.0
    c = room["camera"]
    dx, dz = hdir(frac)
    dist = wall_dist(c["x"], c["z"], dx, dz, hw, hd)
    pitch = -math.degrees(math.atan((c["y"] - DOOR_Y) / dist))
    pull = dist - PULLBACK
    pos = [round(c["x"] + dx * pull, 3), DOOR_Y, round(c["z"] + dz * pull, 3)]
    return {
        "id": f"{room['id']}_door",
        "origin": "vlm_verified_doorway",
        "fraction": frac,
        "pitch": round(pitch, 2),
        "distance": round(dist, 2),
        "position": pos,
    }


def walk_data(room):
    w, d = room["room_shape"]["width"], room["room_shape"]["depth"]
    hw, hd = w / 2.0 - WALL_BUFFER, d / 2.0 - WALL_BUFFER
    return {
        "player_radius": PLAYER_R,
        "bounds": {
            "minX": round(-hw, 3), "maxX": round(hw, 3),
            "minZ": round(-hd, 3), "maxZ": round(hd, 3),
        },
        "obstacles": OBSTACLES[room["id"]],
    }


# --------------------------------------------------------------- sources
cur = json.load(open(f"{ROOT}/data/rooms_db.json"))
by_id = {r["id"]: r for r in cur["rooms"]}

old = json.loads(subprocess.run(
    ["git", "show", "3203ae2:data/rooms_db.json"], cwd=ROOT,
    capture_output=True, text=True, check=True).stdout)
old_by_id = {r["id"]: r for r in old["rooms"]}

rooms = []
for rid in ORDER:
    src = by_id.get(rid) or old_by_id[rid]
    r = json.loads(json.dumps(src))   # deep copy
    r["room_type"] = src["room_type"]
    r["style_family"] = STYLE_FAMILY[rid]
    r["type_group"] = TYPE_GROUP[rid]
    r["style_tags"] = src.get("style_tags") or []
    r["camera"] = src["camera"]
    r["initial_view"] = src.get("initial_view") or {"facing": 0.5}
    r["portals"] = [solve_door(r, DOOR_FRAC[rid])]
    r["walk"] = walk_data(r)
    # drop phase-2.5+ features & offline-only fields (recoverable at 3203ae2)
    for k in ("hotspots", "hotspots_backend", "hotspots_generated_at", "commerce",
              "depth_map", "depth_encoding", "depth_backend", "depth_max"):
        r.pop(k, None)
    for p in r["portals"]:
        for k in ("normal", "width", "height", "label", "sponsored"):
            p.pop(k, None)
    rooms.append(r)

db = {
    "schema": "panodrome/rooms-db@2",
    "project": "Panodrome",
    "generated_at": "2026-11-02T00:00:00",
    "stage": "stage1.5_true_first_person_walk",
    "content_source": "PolyHaven CC0 (9) + Wikimedia Commons CC BY-SA 4.0 (1) — 10 curated design spaces, VLM-verified doorways, true room-box geometry with walk colliders",
    "geometry_law": ("room box = width x depth centred at world origin x/z, floor y=0, ceiling y=height; "
                     "pano capture point = room.camera; equirect projected per-fragment from the capture point; "
                     "walls/floor stay perfectly flat — zero vertex displacement, forever"),
    "rooms": rooms,
}

out = json.dumps(db, indent=2, ensure_ascii=False) + "\n"
open(f"{ROOT}/data/rooms_db.json", "w").write(out)
open(f"{ROOT}/public/data/rooms_db.json", "w").write(out)

a = hashlib.md5(open(f"{ROOT}/data/rooms_db.json", "rb").read()).hexdigest()
b = hashlib.md5(open(f"{ROOT}/public/data/rooms_db.json", "rb").read()).hexdigest()
print("DB md5 sync:", "OK" if a == b else "MISMATCH")
print(f"{len(rooms)} rooms:")
for r in rooms:
    p, w = r["portals"][0], r["walk"]
    ob = len(w["obstacles"])
    print(f"  {r['id']:24s} {r['room_shape']['width']:>4}x{r['room_shape']['depth']:<4} "
          f"bounds x[{w['bounds']['minX']},{w['bounds']['maxX']}] z[{w['bounds']['minZ']},{w['bounds']['maxZ']}] "
          f"obstacles={ob} door f={p['fraction']:<6} dist={p['distance']:>5} pos={p['position']}")

# sanity: every ring reachable (min distance from bounds to ring < 1.1 m)
print("\nwalk-in reachability (ring must be within 1.05m of the walkable rect):")
for r in rooms:
    p = r["portals"][0]["position"]
    bnd = r["walk"]["bounds"]
    dx = max(bnd["minX"] - p[0], 0, p[0] - bnd["maxX"])
    dz = max(bnd["minZ"] - p[2], 0, p[2] - bnd["maxZ"])
    dist = math.hypot(dx, dz)
    flag = "OK " if dist < 1.05 else "!! "
    print(f"  {flag}{r['id']:24s} gap={dist:.2f} m")
