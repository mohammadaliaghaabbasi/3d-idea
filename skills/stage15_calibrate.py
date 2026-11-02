#!/usr/bin/env python3
"""STAGE 1.5 calibration — two VLM passes:

A) Door crops (420x560 at pitch -6deg) for the 4 restored rooms' candidate
   doorway fractions (from the 3203ae2 records) — same quality bar as Stage 1
   ('VERDICT: YES, OFFSET: none').
B) Obstacle strips (full 360deg width, pitch -30..+8deg) for ALL 10 rooms —
   the VLM returns furniture bearings (% across image) + distance estimates,
   which we combine with 3203ae2 VLM hotspot data to author obstacle_colliders.

Outputs crops to /tmp/s15check/ and prints a ready-to-run z-ai vision command
list. Run this, then run the emitted commands, then paste results into
stage15_curate.py's authoring tables.
"""
import os
from PIL import Image

ROOT = "/home/z/my-project/3d-idea"
PANO = f"{ROOT}/public/assets/panoramas"
OUT = "/tmp/s15check"
os.makedirs(OUT, exist_ok=True)

DOOR_CANDIDATES = {  # from 3203ae2 portals (ai_vision_door)
    "photo_studio_loft_hall": [0.025, 0.915],
    "castle_zavelstein_cellar": [0.11],
    "school_hall": [0.594, 0.461],
    "leipzig_festsaal": [0.316, 0.78],
}
ROOMS = [
    "anniversary_lounge", "art_studio", "cabin", "comfy_cafe", "ballroom",
    "quadrangle_sunny", "photo_studio_loft_hall", "castle_zavelstein_cellar",
    "school_hall", "leipzig_festsaal",
]

PITCH = -6.0
DW, DH = 420, 560

def crop_door(rid, frac):
    pano = Image.open(f"{PANO}/{rid}.jpg")
    W, H = pano.size
    cx = (frac % 1.0) * W
    cy = (90 - PITCH) / 180 * H
    box = (int(cx - DW / 2), int(cy - DH / 2), int(cx + DW / 2), int(cy + DH / 2))
    crop = pano.crop(box)
    if box[0] < 0:
        crop.paste(pano.crop((W + box[0], box[1], W, box[3])), (0, 0))
    if box[2] > W:
        crop.paste(pano.crop((0, box[1], box[2] - W, box[3])), (W - box[0], 0))
    name = f"door_{rid}_f{frac}.jpg"
    crop.save(f"{OUT}/{name}", quality=88)
    return name

def strip_obstacles(rid):
    """Full-width strip, pitch -30..+8 deg -> rows at v for -30..+8."""
    pano = Image.open(f"{PANO}/{rid}.jpg")
    W, H = pano.size
    y_top = int((90 - 8) / 180 * H)     # pitch +8
    y_bot = int((90 + 30) / 180 * H)    # pitch -30
    strip = pano.crop((0, y_top, W, y_bot)).resize((2048, int(2048 * (y_bot - y_top) / W)), Image.LANCZOS)
    name = f"strip_{rid}.jpg"
    strip.save(f"{OUT}/{name}", quality=86)
    return name

print("== A) door crops ==")
cmds = []
for rid, fracs in DOOR_CANDIDATES.items():
    for f in fracs:
        n = crop_door(rid, f)
        p = (f"Look at this crop from a 360 panoramic photo. Is a real DOORWAY "
             f"(door frame / open door / archway) centered horizontally in the crop, "
             f"with its centre near the vertical middle of the crop? "
             f"Answer STRICTLY: 'VERDICT: YES' or 'VERDICT: NO', then if YES add "
             f"'OFFSET: none' or 'OFFSET: left ~N%' / 'OFFSET: right ~N%' for how far "
             f"the door centre is off the crop centre, and name the door in 5 words.")
        cmds.append(f"z-ai vision -p '{p}' -i {OUT}/{n} -o /tmp/s15check/out_{n}.json ; echo == {rid} f={f}")

print("== B) obstacle strips ==")
for rid in ROOMS:
    n = strip_obstacles(rid)
    p = ("This is a full 360-degree horizontal strip (panoramic, left edge continues at right edge) "
         "from an indoor 360 photo, taken at eye height 1.6m. List every large solid object that a "
         "person walking on the floor would bump into (furniture, piano, stove, stage, tables, "
         "kitchen counter, big plant, wall fireplace, bed). For EACH object output ONE line: "
         "'PERCENT | METERS | NAME' where PERCENT is its horizontal centre position as a percentage "
         "across the strip (0=left edge, 100=right edge) and METERS is your best estimate of its "
         "distance from the camera. Only solid walk-blocking objects, not rugs or ceiling lamps. "
         "Max 6 objects, biggest first.")
    cmds.append(f"z-ai vision -p '{p}' -i {OUT}/{n} -o /tmp/s15check/out_{n}.json ; echo == {rid} strip")

with open(f"{OUT}/run_vlm.sh", "w") as f:
    f.write("#!/bin/bash\n" + "\n".join(cmds) + "\n")
os.chmod(f"{OUT}/run_vlm.sh", 1 << 6 | 1 << 7 | 1 << 8)
print(f"\nwrote {OUT}/run_vlm.sh with {len(cmds)} VLM commands")
