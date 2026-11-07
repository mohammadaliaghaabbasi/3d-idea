#!/usr/bin/env python3
"""moradi_survey.py — MORADI REAL-CONTENT TEST, Phase A1.
VLM reads of the 15 unique Kuula equirect sources (4K, files.kuula.io
<uuid>/01-4096.jpg) from the moradi-house set of kuula.co/profile/Mojtaba87.
Extracts FACTS ONLY (no engine predictions — those are written by the analyst
in moradi_predictions.py BEFORE any pipeline run):
  room type, layout, size feel, camera pos, windows (count/position/exposure),
  mirrors & glass, glossy floors, thin-leg furniture, ceiling fixtures,
  nadir artifacts, doorways, clutter, house-consistency markers.
Position convention requested as horizontal fraction u of the equirect width
(u=0 left edge, 0.5 centre, 1 right edge) -> converted later to harness world
dirs via the engine's equirect mapping (u=0 -> -x, 0.25 -> +z, 0.5 -> +x,
0.75 -> -z).
Output: docs/rd-artifacts/engine-v1/moradi_survey.json
"""
import json, os, subprocess, sys
from PIL import Image

REPO = "/home/z/my-project/3d-idea"
SRC = "/tmp/moradi/src"
ART = f"{REPO}/docs/rd-artifacts/engine-v1"
SMALL = "/tmp/moradi/small"; os.makedirs(SMALL, exist_ok=True)

POSTS = [
    # (scene_id, kuula_title, post_id, uuid)
    ("c7360",   "C7360",             "LxFdY", "6adc-ea27-34f1-b162"),
    ("bed3b",   "Bedroom_3-2_moradi","L8JTd", "6ac7-3089-8264-a158"),
    ("bed3a",   "Bedroom_3-1_moradi","L8JTX", "6ac7-303f-86f5-0116"),
    ("bed2b",   "Bedroom_2-2_moradi","L8JTl", "6ac7-300b-0b05-7754"),
    ("bed2a",   "Bedroom_2-1_moradi","L8JMW", "6ac7-2fc8-0fb9-6182"),
    ("bed1b",   "Bedroom_1-2_moradi","L8JHt", "6ac7-2f39-e21f-8213"),
    ("bed1a",   "Bedroom_1-1_moradi","L8JDH", "6ac7-2eec-6895-f123"),
    ("kit3b",   "Kitchen_3-2_moradi","L8JDG", "6ac7-2ea3-d9e0-1165"),
    ("kit3a",   "Kitchen_3_moradi", "L8J1y", "6ac7-2e4c-c86f-4333"),
    ("kit2",    "Kitchen_2_moradi", "L8J1g", "6ac7-2e1a-39dd-3132"),
    ("kit1",    "Kitchen_1_moradi", "L8JZ6", "6ac7-2b6e-a589-4652"),
    ("main4",   "Main_4_moradi",    "L8JZT", "6ac7-2b40-658a-c193"),
    ("main3",   "Main_3_moradi",    "L8JZM", "6ac7-2b0e-5e23-f548"),
    ("main2",   "Main_2_moradi",    "L8JZc", "6ac7-2ad3-e3b2-f631"),
    ("main1",   "Main_1_moradi",    "L8JZk", "6ac7-2a2d-0365-c351"),
]  # Kitchen_2b excluded: byte-identical duplicate of Kitchen_2 (md5 match)

PROMPT = """You are looking at a 360 equirectangular photo of an interior. Answer as COMPACT JSON only (no markdown fence), with these exact keys:
{"room": "...", "layout": "...", "size_feel": "small|medium|large", "cam_pos": "centre|corner|against-wall|doorway",
"windows": [{"u": 0.0-1.0, "blown": true|false, "note": "..."}],
"mirrors_glass": [{"u": 0.0-1.0, "what": "..."}],
"glossy_floor": true|false, "rug_coverage": "none|partial|large",
"thin_legs": ["chair legs", ...], "ceiling": "plain|fixtures|cove",
"nadir": "clean|tripod|shadow|stitch", "doorways": [{"u": 0.0-1.0, "to": "..."}],
"clutter": "sparse|normal|dense", "house_markers": "materials/style in 5-10 words",
"dist_to_wall_min_m": 0.5, "notes": "anything that stresses depth estimation"}
Rules: 'u' is the horizontal position in the FLAT panorama: 0.0 = left edge, 0.5 = exact centre, 1.0 = right edge (wrap-around). "blown" = overexposed pure-white sky through the window. dist_to_wall_min_m = your estimate of the closest wall/large furniture distance from camera, metres. Be factual, terse, no speculation about 3D."""

def survey():
    out = {}
    for scene, title, pid, uuid in POSTS:
        big = f"{SRC}/{title}.jpg"
        small = f"{SMALL}/{scene}.jpg"
        if not os.path.exists(small):
            im = Image.open(big); im.thumbnail((2048, 1024))
            im.save(small, quality=88)
        r = subprocess.run(
            [sys.executable, "skills/ai_router.py", "--tier", "2", "--task",
             f"moradi-survey-{scene}", "--json-mode", "-p", PROMPT, "-i", small],
            cwd=REPO, capture_output=True, text=True, timeout=180)
        raw = r.stdout.strip()
        # router prints a status line first; JSON follows
        lines = [l for l in raw.splitlines() if l.strip().startswith("{")]
        parsed = None
        for l in lines:
            try:
                parsed = json.loads(l); break
            except Exception:
                continue
        if parsed is None:  # fallback: try full stdout as JSON
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"_raw": raw[:800], "_err": r.stderr[-300:]}
        out[scene] = {"title": title, "post_id": pid, "kuula_post": f"https://kuula.co/post/{pid}",
                      "files_uuid": uuid, "vlm": parsed}
        print(f"[survey] {scene} ({title}): "
              + ("OK" if "room" in parsed else f"PARSE-ISSUE {list(parsed)[:4]}"), flush=True)
    json.dump(out, open(f"{ART}/moradi_survey.json", "w"), ensure_ascii=False, indent=1)
    print("saved ->", f"{ART}/moradi_survey.json")

if __name__ == "__main__":
    survey()
