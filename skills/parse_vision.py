#!/usr/bin/env python3
"""Parse raw VLM door-detection responses (/tmp/vlm_<room>.json) into
data/vision_overrides.json for skills/ingest_polyhaven.py --vision-file."""
import json
import re
import sys

ROOMS = ["anniversary_lounge", "photo_studio_loft_hall", "art_studio", "ballroom",
         "large_corridor", "comfy_cafe", "castle_zavelstein_cellar", "cabin",
         "quadrangle_sunny", "school_hall"]

def extract_json(text):
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

def clamp01(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v % 1.0 if v != 1.0 else 0.999

out = {}
for rid in ROOMS:
    try:
        raw = json.load(open(f"/tmp/vlm_{rid}.json"))
        content = raw["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"{rid}: NO RESPONSE ({e})")
        continue
    d = extract_json(content)
    if not d:
        print(f"{rid}: UNPARSEABLE -> {content[:120]!r}")
        continue
    facing = clamp01(d.get("facing", 0.5))
    doors = []
    for x in d.get("doors", []) or []:
        c = clamp01(x)
        if c is None:
            continue
        # dedupe doors that are basically the same opening
        if all(abs(c - e) > 0.08 and abs(abs(c - e) - 1.0) > 0.08 for e in doors):
            doors.append(round(c, 4))
        if len(doors) == 2:
            break
    notes = d.get("notes", [])
    out[rid] = {"facing": round(facing, 4) if facing is not None else 0.5, "doors": doors}
    print(f"{rid:28s} facing={out[rid]['facing']:<7} doors={doors}  notes={notes}")

path = "data/vision_overrides.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"\nwrote {path} ({len(out)} rooms)")
