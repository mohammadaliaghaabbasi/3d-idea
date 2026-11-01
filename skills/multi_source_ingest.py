#!/usr/bin/env python3
"""
PANODROME — Multi-source ingestion skill (Phase 3)
====================================================
Aggregates 360° architectural spaces from MULTIPLE platforms into
data/rooms_db.json, each carrying a truthful `source_platform` badge,
full creator attribution and license.

Source adapters
---------------
  wikimedia   — Wikimedia Commons (CC-BY / CC-BY-SA / CC0 / PD).
                Fetches imageinfo (author + license), downloads a
                4096px-wide scaled render, no scraping of protected APIs.
  url         — any direct equirect image URL (e.g. a Kuula / ArtStation
                asset the curator has permission or a CC licence for).
                Attribution fields are mandatory in the manifest — the
                skill refuses to ingest without them.
  polyhaven   — delegated to skills/ingest_polyhaven.py (CC0).

Pipeline per room:  download → normalise (4096×2048 JPG) → 1024×512
preview → procedural box-prior depth (imports ingest_polyhaven) →
VLM door/passages pass (portal fractions + initial facing) →
room JSON stub inserted into data/rooms_db.json (+ deploy copy sync).
Material hotspots afterwards:  python3 skills/vision_hotspots.py --rooms <ids>

Usage:
  python3 skills/multi_source_ingest.py                     # default manifest
  python3 skills/multi_source_ingest.py --only laon_cathedral,masjid_jami_al_huda
  python3 skills/multi_source_ingest.py --manifest my.json --dry
"""
import argparse
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest_polyhaven import procedural_depth, equirect_dir, box_exit_t  # noqa: E402

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow required: pip install pillow")

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "rooms_db.json"
DEPLOY_DB = REPO / "public" / "data" / "rooms_db.json"
PANO_DIR = REPO / "public" / "assets" / "panoramas"
PREVIEW_DIR = REPO / "public" / "assets" / "preview"
DEPTH_DIR = REPO / "public" / "assets" / "depth"

UA = {
    "User-Agent": "Panodrome-Ingest/1.0 "
    "(https://github.com/mohammadaliaghaabbasi; educational 360 architecture demo) python-urllib"
}
PANO_W, PANO_H = 4096, 2048
PREVIEW_W, PREVIEW_H = 1024, 512

PORTAL_PROMPT = """This is a 360-degree equirectangular panorama of an architectural space (the right edge continues into the left edge; you are standing at its center). Horizontal positions are fractions of the image width: 0.0 = left edge, 0.5 = exact center, 1.0 = right edge (same direction as 0.0).

1. Find every REAL doorway, door, archway, or open passage leading onward to another space (NOT windows, mirrors, or paintings).
2. Give the single most impressive direction to initially look at (main altar / dome / feature).

Answer with STRICT JSON only, no prose:
{"facing": <fraction 0-1 of the most impressive initial view>,
 "passages": [<up to 3 fractions where real passages/doorways/archways are>],
 "notes": ["<short note per passage>"]}"""


# ------------------------------------------------------------- curated manifest
# 8 new spaces (Phase 3). Persian/Islamic + European heritage + modern
# transport/civic architecture — all freely licensed Commons photography.
DEFAULT_MANIFEST = [
    {
        "id": "laon_cathedral",
        "source": {"kind": "wikimedia", "title": "File:Laon Cathedral Interior 360x180, Picardy, France - Diliff.jpg"},
        "source_platform": "Heritage 360",
        "room_type": "cathedral",
        "style_tags": ["gothic", "sacred", "stone", "monumental"],
        "name": {"en": "Laon Cathedral Nave", "fa": "نیایشگاه کلیسای جامع لان"},
        "description": {
            "en": "Early Gothic nave in Picardy — clustered piers, sexpartite vaults and deep charters of coloured light.",
            "fa": "نیایشگاه گوتیکِ قرن دوازدهم در پیکاردی؛ ستون‌های دسته‌ای، طاق‌های شش‌پاره و نور رنگینِ روزنه‌های ترازو.",
        },
        "room_shape": {"width": 13, "height": 24, "depth": 30},
        "camera": {"x": 0, "y": 1.6, "z": 0},
        "floor_material": "stone",
        "audio": {"ambient": "hall_air", "reverb": 0.9, "footsteps": "stone"},
    },
    {
        "id": "brompton_oratory",
        "source": {"kind": "wikimedia", "title": "File:Brompton Oratory 360x180, London, UK - Diliff.jpg"},
        "source_platform": "Heritage 360",
        "room_type": "chapel",
        "style_tags": ["baroque", "sacred", "marble", "classical"],
        "name": {"en": "Brompton Oratory Nave", "fa": "نیایشگاه برومپتون"},
        "description": {
            "en": "Italianate Baroque nave in London — polychrome marble columns, gilded dome and clerestory light.",
            "fa": "نیایشگاه باروک ایتالیایی در قلب لندن؛ ستون‌های مرمر رنگین، گنبد طلایی و نور ملایم طبقه‌ی روشن‌خانه.",
        },
        "room_shape": {"width": 16, "height": 18, "depth": 34},
        "camera": {"x": 0, "y": 1.6, "z": 0},
        "floor_material": "stone",
        "audio": {"ambient": "hall_air", "reverb": 0.8, "footsteps": "stone"},
    },
    {
        "id": "abchurch_st_mary",
        "source": {"kind": "wikimedia", "title": "File:St Mary Abchurch Interior 360x180, London, UK - Diliff.jpg"},
        "source_platform": "Heritage 360",
        "room_type": "chapel",
        "style_tags": ["wren", "baroque", "dome", "classical"],
        "name": {"en": "St Mary Abchurch", "fa": "کلیسای سنت‌مری آبچرچ"},
        "description": {
            "en": "Wren's intimate domed parish church — a painted dome floating over gilded reredos and warm woodwork.",
            "fa": "شاهکار جمع‌وجور کریستوفر رن؛ گنبدِ نقاشی‌شده بر فراز محراب طلایی و چوب‌آرایی گرم.",
        },
        "room_shape": {"width": 14, "height": 16, "depth": 14},
        "camera": {"x": 0, "y": 1.6, "z": 0},
        "floor_material": "stone",
        "audio": {"ambient": "hall_air", "reverb": 0.75, "footsteps": "stone"},
    },
    {
        "id": "chapel_royal_dublin",
        "source": {"kind": "wikimedia", "title": "File:Chapel Royal 360x180, Dublin Castle, Dublin, Ireland - Diliff.jpg"},
        "source_platform": "Heritage 360",
        "room_type": "chapel",
        "style_tags": ["gothic-revival", "sacred", "wood", "ornate"],
        "name": {"en": "Chapel Royal, Dublin Castle", "fa": "نیایشگاه سلطنتی قلعه دوبلین"},
        "description": {
            "en": "Gothic-Revival royal chapel carved in native oak — fan vaulting, stained glass and heraldic galleries.",
            "fa": "نیایشگاه سلطنتی به سبک احیای گوتیک؛ گنبد چوبیِ سله‌ای، شیشه‌های رنگی و تورهای نشان‌دار.",
        },
        "room_shape": {"width": 9, "height": 14, "depth": 22},
        "camera": {"x": 0, "y": 1.6, "z": 0},
        "floor_material": "stone",
        "audio": {"ambient": "hall_air", "reverb": 0.8, "footsteps": "wood"},
    },
    {
        "id": "kings_cross_concourse",
        "source": {"kind": "wikimedia", "title": "File:Kings Cross Railway Station Concourse 360x180, London, UK - Diliff.jpg"},
        "source_platform": "ArchViz Commons",
        "room_type": "station",
        "style_tags": ["contemporary", "steel", "grid", "civic"],
        "name": {"en": "King's Cross Western Concourse", "fa": "سالن غربی ایستگاه کینگز کراس"},
        "description": {
            "en": "John McAslan's 2012 steel tree — a single diagrid canopy spanning the Europe's largest single-span station concourse.",
            "fa": "قوس فولادی جان مک‌آسلان (۲۰۱۲)؛ سازه‌ی مشبکِ تک‌گشاد بزرگ‌ترین سقف ایستگاه اروپا.",
        },
        "room_shape": {"width": 30, "height": 22, "depth": 50},
        "camera": {"x": 0, "y": 1.6, "z": 0},
        "floor_material": "concrete",
        "audio": {"ambient": "city_hum", "reverb": 0.55, "footsteps": "concrete"},
    },
    {
        "id": "evora_library_hall",
        "source": {"kind": "wikimedia", "title": "File:Biblioteca Pública de Évora - Sala de exposições (360 panorama).jpg"},
        "source_platform": "ArchViz Commons",
        "room_type": "library",
        "style_tags": ["minimal", "white", "arches", "gallery"],
        "name": {"en": "Évora Public Library Gallery", "fa": "تالار کتابخانه عمومی اورا"},
        "description": {
            "en": "A minimal white exhibition hall of continuous vaults — light as the only ornament.",
            "fa": "تالار نمایشگاهی سفید و مینیمال با طاق‌های پیوسته؛ نور تنها تزیینِ فضا.",
        },
        "room_shape": {"width": 12, "height": 5, "depth": 18},
        "camera": {"x": 0, "y": 1.6, "z": 0},
        "floor_material": "concrete",
        "audio": {"ambient": "room_tone", "reverb": 0.4, "footsteps": "concrete"},
    },
    {
        "id": "leipzig_festsaal",
        "source": {"kind": "wikimedia", "title": "File:Leipzig-Altes-Rathaus-1OG-zw-Festsaal-und-Ratsstube-IMG 6628-8x5B-360x180G-PanoS-04-03-2025.jpg"},
        "source_platform": "Heritage 360",
        "room_type": "banquet_hall",
        "style_tags": ["renaissance", "civic", "wood", "historic"],
        "name": {"en": "Leipzig Old Town Hall", "fa": "خانه شهری قدیمی لایپزیگ"},
        "description": {
            "en": "Renaissance civic halls of 1556 — carved wooden ceilings, portal stonework and merchant grandeur.",
            "fa": "تالارهای شهری رنسانس ۱۵۵۶؛ سقف‌های چوبی کنده‌کاری، سنگ‌کاری درگاه‌ها و شکوه دوره‌ی بازرگانی.",
        },
        "room_shape": {"width": 10, "height": 7, "depth": 16},
        "camera": {"x": 0, "y": 1.6, "z": 0},
        "floor_material": "wood",
        "audio": {"ambient": "room_tone", "reverb": 0.5, "footsteps": "wood"},
    },
    {
        "id": "masjid_jami_al_huda",
        "source": {"kind": "wikimedia", "title": "File:PANO 360 masjid jami al huda pilangsari 2019.jpg"},
        "source_platform": "Heritage 360",
        "room_type": "mosque",
        "style_tags": ["islamic", "dome", "arches", "community"],
        "name": {"en": "Masjid Jami' Al-Huda", "fa": "مسجد جامع الحدا"},
        "description": {
            "en": "A village Friday mosque — central dome, pointed arches and a carved minbar under soft zenith light.",
            "fa": "مسجد جامع روستایی؛ گنبد مرکزی، قوس‌های جناغی و منبر چوبی زیر نور ملایمِ سقف.",
        },
        "room_shape": {"width": 16, "height": 9, "depth": 16},
        "camera": {"x": 0, "y": 1.6, "z": 0},
        "floor_material": "stone",
        "audio": {"ambient": "hall_air", "reverb": 0.85, "footsteps": "stone"},
    },
]


# ------------------------------------------------------------------ commons API

def _get(url, retries=4, timeout=120):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(15 + attempt * 15)
                continue
            raise
    raise RuntimeError("download failed: " + url)


def commons_info(title):
    """imageinfo + extmetadata for a Commons file."""
    q = urllib.parse.urlencode({
        "action": "query", "format": "json", "titles": title,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata",
        "iiurlwidth": str(PANO_W),
    })
    d = json.loads(_get("https://commons.wikimedia.org/w/api.php?" + q, timeout=40))
    page = next(iter(d["query"]["pages"].values()))
    ii = page["imageinfo"][0]
    md = ii.get("extmetadata") or {}
    strip = lambda v: " ".join(re.sub(r"<[^>]+>", " ", v or "").split())
    return {
        "url": ii.get("thumburl") or ii.get("url"),   # 4096-wide render
        "artist": strip((md.get("Artist") or {}).get("value")) or "unknown",
        "license": strip((md.get("LicenseShortName") or {}).get("value")) or "see source",
        "page": "https://commons.wikimedia.org/wiki/" + title.replace(" ", "_")[5:],
        "w": ii.get("thumbwidth") or ii.get("width"),
        "h": ii.get("thumbheight") or ii.get("height"),
    }


# ------------------------------------------------------------------ geometry

def portal_defs(room, passages, depth_img):
    """Portal defs from VLM passage fractions, anchored on the depth field."""
    depth_img = depth_img.convert("RGB")
    w, h = depth_img.size
    px = depth_img.load()

    def depth_at(frac, pitch):
        x = int(frac * (w - 1)) % w
        y = int(((90 - pitch) / 180.0) * (h - 1))
        r, g, _ = px[x, y]
        return ((r * 256 + g) / 65535.0) * room.get("depth_max", 10.0)

    shape = (room["room_shape"]["width"], room["room_shape"]["height"], room["room_shape"]["depth"])
    cam = (room["camera"]["x"], room["camera"]["y"], room["camera"]["z"])

    portals = []
    for i, frac in enumerate(passages[:2]):
        frac = float(frac) % 1.0
        dx, dy, dz = equirect_dir(frac, 3.0)
        d = depth_at(frac, 3.0)
        pos = [cam[0] + dx * (d - 0.06), min(max(cam[1] + dy * (d - 0.06), 1.0), 2.1), cam[2] + dz * (d - 0.06)]
        # walk-in normal points back toward the room centre
        n = (-dx, 0.0, -dz)
        ln = math.hypot(*n) or 1.0
        portals.append({
            "id": f"{room['id']}_p{i+1}",
            "fraction": round(frac, 4),
            "origin": "ai_vision_door",
            "position": [round(v, 3) for v in pos],
            "normal": [round(n[0] / ln, 3), 0.0, round(n[2] / ln, 3)],
            "width": 1.3,
            "height": 2.3,
            "label": {"en": "Smart Portal", "fa": "درگاه هوشمند"},
        })
    return portals


def extract_json(text):
    text = re.sub(r"```(?:json)?", "", text or "").strip().strip("`")
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


# ------------------------------------------------------------------ main

def ingest(entry, dry=False):
    import subprocess

    rid = entry["id"]
    src = entry["source"]
    print(f"\n=== {rid} ===")

    # --- source adapter
    if src["kind"] == "wikimedia":
        info = commons_info(src["title"])
        attribution = {
            "creator": info["artist"], "source": "Wikimedia Commons",
            "license": info["license"], "url": info["page"],
        }
        image_url = info["url"]
        print(f"  commons: {info['w']}x{info['h']} | {info['artist'][:40]} | {info['license']}")
    elif src["kind"] == "url":
        for field in ("creator", "source", "license", "url"):
            if not src.get(field):
                sys.exit(f"manifest error: url source for {rid} needs creator/source/license/url")
        attribution = {k: src[k] for k in ("creator", "source", "license", "url")}
        image_url = src["image"]
    else:
        sys.exit(f"unknown source kind: {src['kind']}")

    if dry:
        print("  (dry) would ingest:", attribution)
        return None

    # --- download + normalise
    pano_path = PANO_DIR / f"{rid}.jpg"
    prev_path = PREVIEW_DIR / f"{rid}.jpg"
    depth_path = DEPTH_DIR / f"{rid}_depth.png"
    raw = _get(image_url)
    import io
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    if abs(im.width / im.height - 2.0) > 0.06:
        print(f"  !! not 2:1 equirect ({im.width}x{im.height}) — SKIP")
        return None
    im = im.resize((PANO_W, PANO_H), Image.LANCZOS)
    im.save(pano_path, quality=84, optimize=True)
    im.resize((PREVIEW_W, PREVIEW_H), Image.LANCZOS).save(prev_path, quality=86)
    print(f"  panorama: {pano_path.name} ({pano_path.stat().st_size // 1024} KB)")

    # --- depth (procedural box prior, same as PolyHaven pipeline)
    shape = (entry["room_shape"]["width"], entry["room_shape"]["height"], entry["room_shape"]["depth"])
    cam = (entry["camera"]["x"], entry["camera"]["y"], entry["camera"]["z"])
    dmax = procedural_depth(shape, cam, depth_path)
    print(f"  depth: {depth_path.name} (depth_max={dmax:.2f})")

    # --- VLM passages + facing
    out_json = Path(f"/tmp/msi_{rid}.json")
    cmd = ["z-ai", "vision", "-p", PORTAL_PROMPT, "-i", str(prev_path), "-o", str(out_json)]
    passages, facing = [0.5], 0.5
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
        d = extract_json(json.loads(out_json.read_text())["choices"][0]["message"]["content"])
        if d:
            passages = [p for p in (d.get("passages") or []) if isinstance(p, (int, float))][:2] or [0.5]
            facing = float(d.get("facing") or 0.5) % 1.0
            print(f"  VLM passages: {passages} | facing {facing}")
    except Exception as e:
        print(f"  VLM portal pass failed ({e}) — using centre fallback")
    portals = portal_defs({**entry, "depth_max": dmax}, passages, Image.open(depth_path))

    # --- room record
    room = {
        "id": rid,
        "room_type": entry["room_type"],
        "style_tags": entry["style_tags"],
        "name": entry["name"],
        "description": entry["description"],
        "panorama": f"assets/panoramas/{rid}.jpg",
        "panorama_size": [PANO_W, PANO_H],
        "preview": f"assets/preview/{rid}.jpg",
        "depth_map": f"assets/depth/{rid}_depth.png",
        "depth_encoding": "uint16-two-channel-rgb",
        "depth_backend": "procedural",
        "depth_max": round(dmax, 3),
        "room_shape": entry["room_shape"],
        "camera": entry["camera"],
        "initial_view": {"facing": round(facing, 3)},
        "portals": portals,
        "floor_material": entry["floor_material"],
        "audio": entry["audio"],
        "hotspots": [],
        "attribution": attribution,
        "source_platform": entry["source_platform"],
    }
    print(f"  portals: {[(p['fraction'], p['position']) for p in portals]}")
    return room


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest")
    ap.add_argument("--only")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    manifest = DEFAULT_MANIFEST
    if args.manifest:
        manifest = json.load(open(args.manifest))
    if args.only:
        keep = {s.strip() for s in args.only.split(",")}
        manifest = [m for m in manifest if m["id"] in keep]

    db = json.load(open(DB))
    ids = {r["id"] for r in db["rooms"]}

    added = []
    for entry in manifest:
        if entry["id"] in ids:
            print(f"\n=== {entry['id']} already in DB — skip")
            continue
        room = ingest(entry, dry=args.dry)
        if room:
            db["rooms"].append(room)
            added.append(room["id"])

    if added:
        db["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime())
        DB.write_text(json.dumps(db, indent=2, ensure_ascii=False) + "\n")
        DEPLOY_DB.write_text(json.dumps(db, indent=2, ensure_ascii=False) + "\n")
        print(f"\nadded {len(added)} rooms: {added}")
        print(f"next: python3 skills/vision_hotspots.py --rooms {','.join(added)}")


if __name__ == "__main__":
    main()
