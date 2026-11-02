#!/usr/bin/env python3
"""Stage 1 door calibration — crop candidate doorway fractions from the 6
curated equirect panoramas at door-centre height, for z-ai vision verification.

Crop is centred at (fraction*W, (90-pitch)/180*H) with pitch=-6 deg.
Also samples the two-channel depth map at the same ray to report the true
door distance (used later for waypoint placement).
"""
import json, os
from PIL import Image

ROOT = "/home/z/my-project/3d-idea"
DB = json.load(open(f"{ROOT}/data/rooms_db.json"))
OUT = "/tmp/doorcheck"
os.makedirs(OUT, exist_ok=True)

CANDIDATES = {
    "anniversary_lounge": [0.02],
    "art_studio": [0.058, 0.307],
    "cabin": [0.355],
    "comfy_cafe": [0.418, 0.685],
    "ballroom": [0.335, 0.905],
    "quadrangle_sunny": [0.49, 0.975],
}
PITCH = -6.0
CROP_W, CROP_H = 420, 560


def depth_at(room, frac, pitch_deg):
    """Two-channel depth (R*256+G)/65535 * depth_max, 3x3 mean, metres."""
    img = Image.open(f"{ROOT}/public/{room['depth_map']}").convert("RGB")
    w, h = img.size
    px = Image.open(f"{ROOT}/public/{room['depth_map']}").convert("RGB").load()
    cx = ((frac % 1.0) * w) % w
    cy = min(max((90 - pitch_deg) / 180 * h, 0), h - 1)
    vals = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            x = int(cx + dx) % w
            y = min(max(int(cy + dy), 0), h - 1)
            r, g, _ = px[x, y]
            vals.append(((r * 256 + g) / 65535) * room["depth_max"])
    return sum(vals) / len(vals)


report = {}
for room in DB["rooms"]:
    rid = room["id"]
    if rid not in CANDIDATES:
        continue
    pano = Image.open(f"{ROOT}/public/{room['panorama']}")
    W, H = pano.size
    for i, frac in enumerate(CANDIDATES[rid]):
        cx = (frac % 1.0) * W
        cy = (90 - PITCH) / 180 * H
        box = (int(cx - CROP_W / 2), int(cy - CROP_H / 2),
               int(cx + CROP_W / 2), int(cy + CROP_H / 2))
        crop = pano.crop(box)
        # horizontal wrap for fractions near the seam
        if box[0] < 0:
            crop.paste(pano.crop((W + box[0], box[1], W, box[3])), (0, 0))
        if box[2] > W:
            crop.paste(pano.crop((0, box[1], box[2] - W, box[3])), (W - box[0], 0))
        name = f"{rid}_c{i}_f{frac}.jpg"
        crop.save(f"{OUT}/{name}", quality=88)
        d = depth_at(room, frac, PITCH)
        report[f"{rid} c{i} f={frac}"] = round(d, 2)
        print(f"{rid:22s} cand{i} f={frac:<6} doorDepth={d:6.2f}m  -> {OUT}/{name}")

json.dump(report, open(f"{OUT}/depth_report.json", "w"), indent=1)
print("\nW,H of pano:", W, H)
