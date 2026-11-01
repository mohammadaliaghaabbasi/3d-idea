#!/usr/bin/env python3
"""
PANODROME — Phase 2 skill: AI X-Ray Material & Furniture Hotspots
==================================================================
Runs a VLM pass (GLM vision via the z-ai CLI) over the rooms in
data/rooms_db.json and detects 2–3 notable architectural elements
per room (floor material, feature wall, lighting fixture, signature
furniture, …) with:

  * spherical coordinates  — fraction (horizontal image fraction,
    wraps at the seam) + pitch (deg) + yaw (deg = fraction x 360,
    panorama azimuth, 0° at the image left edge)
  * bilingual copy          — title_en / title_fa / desc_en / desc_fa
  * material_category       — wood | stone | metal | glass | textile |
    ceramic | lighting | concrete | brick | plaster | vegetation | other

Each element's (fraction, pitch) is projected onto the room's depth
map to get a world-space pin position that floats slightly in front
of the real surface — exactly the convention the engine uses:

  dir(f, p) = (-cos(2πf)·sinθ, cosθ, sin(2πf)·sinθ),  θ = π/2 − p·π/180
  depth(f, p) = (R·256 + G)/65535 · depth_max        (two-channel PNG)
  pin = room.camera + dir · clamp(depth − 0.18, 0.55, depth_max)

Writes upgraded hotspots back into data/rooms_db.json (canonical)
and regenerates the deploy copy public/data/rooms_db.json.
Rooms whose VLM call fails keep their previous (curated) hotspots.

Usage:
  python3 skills/vision_hotspots.py                 # all 10 rooms
  python3 skills/vision_hotspots.py --rooms cabin,ballroom
  python3 skills/vision_hotspots.py --dry           # no DB write
"""
import argparse
import datetime
import json
import math
import re
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow required: pip install pillow")

REPO = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "data" / "rooms_db.json"
DEPLOY_DB = REPO / "public" / "data" / "rooms_db.json"

CATEGORIES = {
    "wood", "stone", "metal", "glass", "textile", "ceramic",
    "lighting", "concrete", "brick", "plaster", "vegetation", "other",
}

PROMPT = """This is a 360-degree equirectangular panorama of an architectural interior (the right edge continues into the left edge; you are standing at its center). Horizontal position can be expressed as a fraction of the image width: 0.0 = left edge, 0.5 = exact center, 1.0 = right edge (same direction as 0.0). Vertical position is a pitch in degrees: 0 = eye level / horizon, +90 = straight up (ceiling), -90 = straight down (floor).

Find 2 or 3 of the MOST notable architectural / interior-design elements visible in this room — for example the floor material, a feature wall, a lighting fixture, a signature furniture piece, a ceiling treatment, a staircase or a fireplace. Pick visually prominent, REAL elements (never things that are not in the photo). IMPORTANT: choose elements in DIFFERENT parts of the room — spread them across different horizontal fractions (directions), do NOT cluster them all in one spot. The pitch must point AT the element itself: ceiling elements and hanging fixtures have positive pitch, floor materials and rugs have negative pitch, wall and furniture elements are near 0.

Answer with STRICT JSON only, no prose at all:
{"elements": [
  {"fraction": <number 0.0-1.0>, "pitch": <number -90..90>,
   "title_en": "<= 6 words", "desc_en": "<1-2 sentences about the material, craft and design detail>",
   "title_fa": "<= 6 words, natural Persian>", "desc_fa": "<1-2 sentences, natural Persian>",
   "category": "<one of: wood, stone, metal, glass, textile, ceramic, lighting, concrete, brick, plaster, vegetation, other>"}
]}"""


# ------------------------------------------------------------------ helpers

def extract_json(text):
    """Best-effort JSON extraction from a VLM reply (mirrors parse_vision.py)."""
    text = re.sub(r"```(?:json)?", "", text).strip().strip("`")
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return None


def slug(s, maxlen=34):
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return (s[:maxlen].rstrip("_")) or "element"


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def norm_fraction(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v < 0 or v >= 1:
        v = v % 1.0
    return round(v, 4)


def norm_pitch(v):
    try:
        return round(clamp(float(v), -85, 85), 1)
    except (TypeError, ValueError):
        return None


def norm_text(v, fallback=""):
    if not isinstance(v, str):
        return fallback
    return " ".join(v.split()).strip()[:220] or fallback


def equirect_dir(frac, pitch_deg):
    phi = 2 * math.pi * frac
    theta = math.pi / 2 - math.radians(pitch_deg)
    st = math.sin(theta)
    return (-math.cos(phi) * st, math.cos(theta), math.sin(phi) * st)


def load_depth(path):
    return Image.open(path).convert("RGB")


def depth_at_meters(img, room, frac, pitch_deg):
    """3x3 mean of the two-channel depth around (fraction, pitch) — same
    pixel mapping as panorama.js sampleDepth(): x = u*(w-1), y = ((90-p)/180)*(h-1)."""
    w, h = img.size
    x = frac * (w - 1)
    y = ((90 - pitch_deg) / 180.0) * (h - 1)
    vals = []
    px = img.load()
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            xx = int(round(x)) + dx
            yy = int(round(clamp(y + dy, 0, h - 1)))
            xx %= w  # horizontal wrap at the seam
            r, g, _b = px[xx, yy]
            vals.append((r * 256 + g) / 65535.0)
    return (sum(vals) / len(vals)) * room.get("depth_max", 10.0)


def pin_position(room, img, frac, pitch_deg, pullback=0.18, min_r=0.55):
    dx, dy, dz = equirect_dir(frac, pitch_deg)
    d = depth_at_meters(img, room, frac, pitch_deg)
    r = clamp(d - pullback, min_r, room.get("depth_max", 10.0))
    c = room["camera"]
    return [round(c["x"] + dx * r, 3), round(c["y"] + dy * r, 3), round(c["z"] + dz * r, 3)]


def vlm_elements(room):
    """One z-ai vision call per room; returns parsed element dicts or None."""
    out = Path(f"/tmp/vlm_hs_{room['id']}.json")
    cmd = ["z-ai", "vision", "-p", PROMPT, "-i", str(REPO / "public" / room["preview"]),
           "-o", str(out)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
        raw = json.loads(out.read_text(encoding="utf-8"))
        content = raw["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"    VLM call failed: {e}")
        return None
    d = extract_json(content)
    if not d or not isinstance(d.get("elements"), list):
        print(f"    unparseable reply -> {str(content)[:110]!r}")
        return None
    return d["elements"]


# ------------------------------------------------------------------ main

def build_hotspots(room):
    img = load_depth(REPO / "public" / room["depth_map"])
    elems = vlm_elements(room)
    if not elems:
        return None

    hotspots, used = [], []
    for e in elems[:3]:
        frac = norm_fraction(e.get("fraction"))
        pitch = norm_pitch(e.get("pitch"))
        if frac is None or pitch is None:
            continue
        # dedupe near-duplicates (same element reported twice)
        if any(abs(frac - f) < 0.03 and abs(pitch - p) < 10 for f, p in used):
            continue
        used.append((frac, pitch))

        title_en = norm_text(e.get("title_en"), "Architectural detail")
        cat = str(e.get("category", "other")).strip().lower()
        if cat not in CATEGORIES:
            cat = "other"

        hotspots.append({
            "id": f"{room['id']}_{slug(title_en)}",
            "origin": "ai_vlm",
            "fraction": frac,
            "yaw": int(round(frac * 360)) % 360,   # panorama azimuth, deg
            "pitch": pitch,
            "position": pin_position(room, img, frac, pitch),
            "title": {"en": title_en, "fa": norm_text(e.get("title_fa"), title_en)},
            "desc": {
                "en": norm_text(e.get("desc_en"), "A notable material and design detail."),
                "fa": norm_text(e.get("desc_fa"), "جزئیات قابل‌توجه متریال و طراحی."),
            },
            "material_category": cat,
        })
        if len(hotspots) == 3:
            break

    return hotspots or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rooms", help="comma-separated room ids (default: all)")
    ap.add_argument("--dry", action="store_true", help="no DB write")
    args = ap.parse_args()

    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    only = set(args.rooms.split(",")) if args.rooms else None
    changed = 0

    for room in db["rooms"]:
        if only and room["id"] not in only:
            continue
        print(f"[VLM] {room['id']}")
        hs = build_hotspots(room)
        if hs:
            room["hotspots"] = hs
            room["hotspots_backend"] = "vlm"
            room["hotspots_generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
            room.pop("hotspots_curated", None)
            changed += 1
            for h in hs:
                print(f"    + {h['title']['en'][:44]:46s} yaw={h['yaw']:>3}° pitch={h['pitch']:>5}° cat={h['material_category']:9s} pos={h['position']}")
        else:
            print("    (kept existing curated hotspots)")

    if args.dry:
        print("\n--dry: nothing written")
        return
    if not changed:
        print("\nno rooms updated")
        return

    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    DEPLOY_DB.write_text(json.dumps(db, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {DB_PATH.relative_to(REPO)} + {DEPLOY_DB.relative_to(REPO)} ({changed} rooms)")


if __name__ == "__main__":
    main()
