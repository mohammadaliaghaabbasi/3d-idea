#!/usr/bin/env python3
"""
PANODROME — Portal calibration pass (Phase 2.5)

Marks the CURRENT portal fractions of every room on its preview panorama
with numbered crosshair markers, asks the VLM to verify each marker sits
dead-center on a REAL door / archway / open passage, and collects corrected
fractions where it does not. Writes /tmp/portal_calib/<room>.json results.

Usage:
  python3 scripts/portal_calibrate.py            # mark + verify all rooms
  python3 scripts/portal_calibrate.py --rooms cabin,ballroom
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
OUT = Path("/tmp/portal_calib")
OUT.mkdir(exist_ok=True)

PROMPT = """This is a 360-degree equirectangular panorama of an architectural space (the right edge continues into the left edge; you are standing at its center). I have drawn numbered circular crosshair markers on the image at the horizontal positions of two "portal" waypoints.

For EACH numbered marker, decide:
1. Does the marker sit ON or VERY NEAR a real doorway, door, archway, or open passage leading to another space? (A window, mirror, painting, wall panel, or alcove does NOT count. An open archway or clearly open doorway leading onward DOES count.)
2. If it does not, find the nearest real doorway/archway/open passage in the image and report its horizontal fraction.

Horizontal fraction convention: 0.0 = left edge of the image, 0.5 = exact center, 1.0 = right edge (identical direction to 0.0). Measure carefully.

Answer with STRICT JSON only, no prose:
{"markers": [
  {"marker": 1, "on_passage": true/false, "what_is_there": "<5-10 word description>", "corrected_fraction": <number 0-1, only if on_passage is false — the fraction of the nearest REAL passage, else null>},
  {"marker": 2, ...}
],
"all_passages": [<fractions of EVERY real doorway/archway/open passage visible in the whole image, 0-1>]}"""


def mark(room):
    preview = REPO / "public" / room["preview"]
    im = Image.open(preview).convert("RGB")
    W, H = im.size
    draw = ImageDraw.Draw(im)
    portals = room.get("portals", [])
    for i, p in enumerate(portals):
        x = int((p["fraction"] % 1.0) * W)
        y = int(H * 0.52)  # door center ≈ slightly below horizon
        r = 26
        draw.ellipse([x - r, y - r, x + r, y + r], outline=(255, 210, 40), width=5)
        draw.line([x - r - 10, y, x + r + 10, y], fill=(255, 210, 40), width=3)
        draw.line([x, y - r - 10, x, y + r + 10], fill=(255, 210, 40), width=3)
        # label box
        draw.rectangle([x + r + 4, y - 16, x + r + 34, y + 14], fill=(10, 10, 10))
        draw.text((x + r + 8, y - 10), str(i + 1), fill=(255, 210, 40))
    path = OUT / f"{room['id']}_marked.jpg"
    im.save(path, quality=88)
    return path


def extract_json(text):
    text = text.replace("```json", " ").replace("```", " ")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def vlm_content(path):
    """Read a z-ai vision output file -> content string."""
    try:
        d = json.load(open(path))
        return d["choices"][0]["message"]["content"]
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rooms", default="")
    args = ap.parse_args()

    db = json.load(open(REPO / "data" / "rooms_db.json"))
    rooms = db["rooms"]
    if args.rooms:
        keep = set(args.rooms.split(","))
        rooms = [r for r in rooms if r["id"] in keep]

    results = {}
    for room in rooms:
        rid = room["id"]
        out_json = OUT / f"{rid}.json"
        if not out_json.exists():          # fresh VLM call only if missing
            marked = mark(room)
            cmd = ["z-ai", "vision", "-p", PROMPT, "-i", str(marked), "-o", str(out_json)]
            subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        raw = vlm_content(out_json)
        data = extract_json(raw) or {}
        results[rid] = {
            "current_fractions": [p["fraction"] for p in room.get("portals", [])],
            "vlm": data,
        }
        marks = data.get("markers", [])
        verdict = " | ".join(
            f"M{m.get('marker')}: on_passage={m.get('on_passage')} -> {m.get('what_is_there', '')}"
            + (f" corr={m.get('corrected_fraction')}" if not m.get("on_passage") else "")
            for m in marks
        ) or "PARSE FAIL"
        print(f"[{rid}] {verdict}")
        print(f"    all_passages: {data.get('all_passages')}")

    (OUT / "_summary.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print(f"\nsummary -> {OUT / '_summary.json'}")


if __name__ == "__main__":
    main()
