#!/usr/bin/env python3
"""STAGE 1.5 — restore the 4 re-curated rooms' panorama assets.

Re-downloads (pruned during the Stage-1 reset):
  photo_studio_loft_hall  (PolyHaven CC0, tonemapped 4K jpg)
  castle_zavelstein_cellar(PolyHaven CC0)
  school_hall             (PolyHaven CC0)
  leipzig_festsaal        (Wikimedia Commons, CC BY-SA 4.0, 4096-wide render)

Normalises every pano to 4096x2048 q88 and builds the 1024x512 preview,
matching the Stage-1 asset conventions exactly.
"""
import json, os, urllib.parse, urllib.request
from PIL import Image

ROOT = "/home/z/my-project/3d-idea"
PANO = f"{ROOT}/public/assets/panoramas"
PREV = f"{ROOT}/public/assets/preview"
UA = {"User-Agent": "PanodromeStage15/1.0 (asset restore; contact: repo owner)"}
TARGET_W = 4096

POLYHAVEN = ["photo_studio_loft_hall", "castle_zavelstein_cellar", "school_hall"]
LEIPZIG_TITLE = "File:Leipzig-Altes-Rathaus-1OG-zw-Festsaal-und-Ratsstube-IMG_6628-8x5B-360x180G-PanoS-04-03-2025.jpg"


def get(url, timeout=300):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def http_json(url):
    return json.loads(get(url, 60))


def normalise(raw_bytes, rid):
    tmp = f"{PANO}/.{rid}_src.jpg"
    with open(tmp, "wb") as f:
        f.write(raw_bytes)
    pano_path = f"{PANO}/{rid}.jpg"
    with Image.open(tmp) as im:
        im = im.convert("RGB")
        if im.size != (TARGET_W, TARGET_W // 2):
            im = im.resize((TARGET_W, TARGET_W // 2), Image.LANCZOS)
        im.save(pano_path, quality=88, optimize=True)
        im.resize((1024, 512), Image.LANCZOS).save(f"{PREV}/{rid}.jpg", quality=82, optimize=True)
    os.remove(tmp)
    with Image.open(pano_path) as im:
        assert im.size == (4096, 2048), (rid, im.size)
    print(f"  {rid}: pano {os.path.getsize(pano_path)/1e6:.2f}MB 4096x2048 + preview")


for rid in POLYHAVEN:
    print(f"=== {rid} (PolyHaven) ===")
    files = http_json(f"https://api.polyhaven.com/files/{rid}")
    tm = (files.get("tonemapped") or {}).get("4k") or (files.get("tonemapped") or {})
    url = tm.get("url") if isinstance(tm, dict) else None
    if not url:
        # fall back: any 4k jpg in tonemapped
        tm_all = files.get("tonemapped") or {}
        for k, v in tm_all.items():
            if isinstance(v, dict) and v.get("url") and v.get("format") == "jpg":
                url = v["url"]
                break
    assert url, f"no tonemapped jpg for {rid}"
    if ".jpg" not in url.split("?")[0]:
        url += ("&" if "?" in url else "?") + "format=jpg"
    print("  source:", url)
    normalise(get(url), rid)

print("=== leipzig_festsaal (Wikimedia Commons) ===")
q = urllib.parse.urlencode({
    "action": "query", "format": "json", "titles": LEIPZIG_TITLE,
    "prop": "imageinfo", "iiprop": "url|size", "iiurlwidth": str(TARGET_W),
})
d = http_json("https://commons.wikimedia.org/w/api.php?" + q)
page = next(iter(d["query"]["pages"].values()))
ii = page["imageinfo"][0]
url = ii.get("thumburl") or ii["url"]
print("  source:", url)
normalise(get(url), "leipzig_festsaal")

print("done.")
