#!/usr/bin/env python3
"""STAGE 1 CURATION — lock the Panodrome DB to 6 pure interior-architecture
spaces with exactly 1 VLM-verified doorway each.

Chosen doorways (all 'VERDICT: YES, OFFSET: none' from z-ai vision on 420x560
crops at pitch -6deg, see /tmp/doorcheck):
  anniversary_lounge  f=0.020  d=2.33m  wide archway into dining area
  art_studio          f=0.058  d=2.69m  light door w/ vertical window
  cabin               f=0.355  d=2.87m  wood door with hanging coats
  comfy_cafe          f=0.685  d=3.84m  large rectangular doorway, grey frame
  ballroom            f=0.335  d=8.18m  open white-framed doorway
  quadrangle_sunny    f=0.490  d=12.09m dark wooden doorway in red brick

Waypoint position = panoCam + dir(fraction, -6deg) * (dist - 0.35)
so the ring projects dead-centre on the real doorway at a truthful distance.
Strips: hotspots (+embedded commerce), extra portals. Keeps attribution,
audio profile (Stage 3 will use it), depth fields (offline tooling).

Writes data/rooms_db.json and public/data/rooms_db.json IDENTICALLY.
"""
import json, math, os, shutil

ROOT = "/home/z/my-project/3d-idea"
PITCH = -6.0

# curated order = the walking narrative of the collection
ORDER = ["anniversary_lounge", "art_studio", "cabin", "comfy_cafe", "ballroom", "quadrangle_sunny"]
DOOR_FRAC = {  # id -> VLM-verified doorway fraction
    "anniversary_lounge": 0.020,
    "art_studio": 0.058,
    "cabin": 0.355,
    "comfy_cafe": 0.685,
    "ballroom": 0.335,
    "quadrangle_sunny": 0.490,
}
DOOR_CENTRE_Y = 1.3   # world height of a door's centre line
PULLBACK = 0.35       # ring floats this far in front of the door plane


def dir_of(frac, pitch_deg):
    phi = 2 * math.pi * frac
    theta = math.radians(90 - pitch_deg)
    st, ct = math.sin(theta), math.cos(theta)
    return (-math.cos(phi) * st, ct, math.sin(phi) * st)


def depth_field(room):
    from PIL import Image
    img = Image.open(f"{ROOT}/public/{room['depth_map']}").convert("RGB")
    w, h = img.size
    px = img.load()
    return px, w, h, room["depth_max"]


def depth_at(px, w, h, dmax, frac, pitch_deg):
    cx = ((frac % 1.0) * w) % w
    cy = min(max((90 - pitch_deg) / 180 * h, 0), h - 1)
    vals = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            x = int(cx + dx) % w
            y = min(max(int(cy + dy), 0), h - 1)
            r, g, _ = px[x, y]
            vals.append(((r * 256 + g) / 65535) * dmax)
    return sum(vals) / len(vals)


def solve_door_pitch(room, frac):
    """Find the pitch whose ray lands at DOOR_CENTRE_Y on the door plane."""
    px, w, h, dmax = depth_field(room)
    cam_y = room["camera"]["y"]
    best = None
    for i in range(-80, 21):          # pitch -20deg .. +5deg in 0.25 steps
        p = i * 0.25
        d = depth_at(px, w, h, dmax, frac, p)
        if d <= 0.5:
            continue
        y_land = cam_y + math.tan(math.radians(p)) * d
        err = abs(y_land - DOOR_CENTRE_Y)
        if best is None or err < best[2]:
            best = (p, d, err)
    return best


db = json.load(open(f"{ROOT}/data/rooms_db.json"))
by_id = {r["id"]: r for r in db["rooms"]}

new_rooms = []
for rid in ORDER:
    r = json.loads(json.dumps(by_id[rid]))  # deep copy
    frac = DOOR_FRAC[rid]
    pitch, dist, err = solve_door_pitch(r, frac)
    d = dir_of(frac, pitch)
    pull = dist - PULLBACK
    cam = r["camera"]
    pos = [round(cam["x"] + d[0] * pull, 3),
           round(cam["y"] + d[1] * pull, 3),
           round(cam["z"] + d[2] * pull, 3)]
    r["portals"] = [{
        "id": f"{rid}_door",
        "origin": "vlm_verified_doorway",
        "fraction": frac,
        "pitch": round(pitch, 2),
        "distance": round(dist, 2),
        "position": pos,
    }]
    r.pop("hotspots", None)
    r.pop("hotspots_backend", None)
    r.pop("hotspots_generated_at", None)
    r.pop("commerce", None)
    new_rooms.append(r)

db["rooms"] = new_rooms
db["generated_at"] = "2026-11-02T00:00:00"
db["stage"] = "stage1_zero_distortion_core"
db["content_source"] = "PolyHaven CC0 — 6 curated pure interior-architecture spaces"
db.pop("routing_modes", None)

out = json.dumps(db, indent=2, ensure_ascii=False) + "\n"
open(f"{ROOT}/data/rooms_db.json", "w").write(out)
open(f"{ROOT}/public/data/rooms_db.json", "w").write(out)

# ---- delete assets of the 12 dropped rooms ----
removed = 0
for kind in ("panoramas", "preview", "depth"):
    folder = f"{ROOT}/public/assets/{kind}"
    for fn in sorted(os.listdir(folder)):
        stem = fn.rsplit("_depth", 1)[0].rsplit(".", 1)[0]
        if stem not in ORDER:
            os.remove(os.path.join(folder, fn))
            removed += 1
print(f"DB curated: {len(new_rooms)} rooms; assets removed: {removed} files")

# ---- verify ----
import hashlib
a = hashlib.md5(open(f"{ROOT}/data/rooms_db.json", "rb").read()).hexdigest()
b = hashlib.md5(open(f"{ROOT}/public/data/rooms_db.json", "rb").read()).hexdigest()
print("DB md5 sync:", "OK" if a == b else "MISMATCH")
for r in new_rooms:
    p = r["portals"][0]
    print(f"  {r['id']:20s} f={p['fraction']:<6} pitch={p['pitch']:>5} dist={p['distance']:>5} pos={p['position']}")
left = {k: len(os.listdir(f"{ROOT}/public/assets/{k}")) for k in ("panoramas", "preview", "depth")}
print("assets left:", left)
