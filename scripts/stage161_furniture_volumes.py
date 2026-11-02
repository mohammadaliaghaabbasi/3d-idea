#!/usr/bin/env python3
"""Stage 1.6.1 — Rule C: furniture bounding-volume verification pass.
TIER 1 (gemini-3.6-flash; auto-falls to the z-ai floor when the 15-call
quota cap is exhausted) verifies each room's calibrated colliders against
the panorama and returns volumes (cx, cz, w, d, h, yaw, label_en, label_fa).
MERGE POLICY (guarded): positions move at most 0.35 m; no deletions; labels
only when clearly wrong; h / yaw added as new metadata (used by the halo
rendering + future OBB colliders)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills"))
from ai_router import Router

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "rd-artifacts" / "stage161" / "furniture_volumes.json"

PROMPT = """You are verifying furniture collision volumes for a 360° equirect panorama room (Panodrome, three.js first-person walker). The image is an EQUIRECTANGULAR panorama: horizontal axis = azimuth 0..360° (u=0 faces -x, u=0.25 faces +z, u=0.5 faces +x, u=0.75 faces -z), vertical axis = elevation +90°(top)..-90°(bottom). The camera stands at the room origin (0,0) at height {cam_h} m. Room box: {w} m wide (x), {d} m deep (z), {h} m tall.

CURRENT CALIBRATED COLLIDERS (x, z in metres from the camera, world axes: +x east in the pano at u=0.5, +z at u=0.25):
{obstacles}

For EACH collider: (1) CONFIRM you can see that furniture piece in the panorama, (2) refine its position/size ONLY IF clearly wrong (max correction 0.35 m — these positions came from depth-map measurement + VLM strips and are already E2E-verified), (3) estimate its HEIGHT (m) and YAW (radians, 0 = axis-aligned to the room walls; estimate only for rotated pieces like sofas on diagonals), (4) keep the labels unless clearly wrong.

Return STRICT JSON only:
{{"room": "{rid}", "pieces": [{{"idx": 0, "seen": true, "cx": 1.01, "cz": -1.41, "w": 2.0, "d": 2.0, "h": 0.82, "yaw": 0.0, "label_en": "sofa", "label_fa": "مبل", "note": ""}}]}}
No prose outside the JSON."""


def run_room(room):
    obs = room["walk"]["obstacles"]
    obs_txt = json.dumps(
        [{"idx": i, "type": o["type"], "x": o["x"], "z": o["z"],
          **({"r": o["r"]} if o["type"] == "cylinder" else {"hw": o["hw"], "hd": o["hd"]}),
          "label_en": o["label"]["en"], "label_fa": o["label"]["fa"]}
         for i, o in enumerate(obs)], ensure_ascii=False, indent=1)
    prompt = PROMPT.format(
        rid=room["id"], cam_h=room["camera"]["y"],
        w=room["room_shape"]["width"], d=room["room_shape"]["depth"], h=room["room_shape"]["height"],
        obstacles=obs_txt)
    r = Router()
    out = r.generate(
        prompt=prompt,
        images=[str(ROOT / "public" / room["panorama"])],
        tier=1,
        task=f"stage161_furniture_{room['id']}",
        json_mode=True,
    )
    return dict(out)


def guarded_merge(room, pieces):
    """Apply guarded updates: h + yaw always; position/size only within
    0.35 m of the measured values; no deletions; labels only if sane."""
    changes = []
    obs = room["walk"]["obstacles"]
    for p in pieces or []:
        i = p.get("idx")
        if not isinstance(i, int) or i < 0 or i >= len(obs) or not p.get("seen", False):
            continue
        o = obs[i]
        if "h" in p and isinstance(p["h"], (int, float)) and 0.05 < p["h"] < 4.5:
            o["h"] = round(float(p["h"]), 2)
        if "yaw" in p and isinstance(p["yaw"], (int, float)) and abs(p["yaw"]) < 1.6:
            o["rot"] = round(float(p["yaw"]), 3)
        moved = False
        if all(isinstance(p.get(k), (int, float)) for k in ("cx", "cz")):
            if abs(p["cx"] - o["x"]) <= 0.35 and abs(p["cz"] - o["z"]) <= 0.35:
                if abs(p["cx"] - o["x"]) > 0.02 or abs(p["cz"] - o["z"]) > 0.02:
                    o["x"], o["z"] = round(float(p["cx"]), 2), round(float(p["cz"]), 2)
                    moved = True
        sized = False
        if o["type"] == "box" and all(isinstance(p.get(k), (int, float)) for k in ("w", "d")):
            hw, hd = p["w"] / 2, p["d"] / 2
            if abs(hw - o["hw"]) <= 0.35 and abs(hd - o["hd"]) <= 0.35 and hw > 0.05 and hd > 0.05:
                if abs(hw - o["hw"]) > 0.02 or abs(hd - o["hd"]) > 0.02:
                    o["hw"], o["hd"] = round(hw, 2), round(hd, 2)
                    sized = True
        if o["type"] == "cylinder" and isinstance(p.get("w"), (int, float)):
            r2 = p["w"] / 2
            if abs(r2 - o["r"]) <= 0.35 and r2 > 0.05 and abs(r2 - o["r"]) > 0.02:
                o["r"] = round(r2, 2)
                sized = True
        le = str(p.get("label_en", "")).strip()
        lf = str(p.get("label_fa", "")).strip()
        labeled = False
        if le and lf and le.lower() != o["label"]["en"].lower() and len(le) < 30:
            o["label"] = {"en": le, "fa": lf}
            labeled = True
        if moved or sized or labeled or "h" in o:
            changes.append({"idx": i, "label": o["label"]["en"], "moved": moved,
                            "sized": sized, "labeled": labeled, "h": o.get("h"),
                            "rot": o.get("rot", 0)})
    return changes


def main():
    db = json.loads((ROOT / "data" / "rooms_db.json").read_text(encoding="utf-8"))
    results = {}
    for rid in ("anniversary_lounge", "cabin"):
        room = next(r for r in db["rooms"] if r["id"] == rid)
        out = run_room(room)
        text = out.get("text") or ""
        try:
            j0, j1 = text.find("{"), text.rfind("}")
            pieces = json.loads(text[j0:j1 + 1]).get("pieces")
        except Exception:
            pieces = None
        changes = guarded_merge(room, pieces) if pieces else []
        results[rid] = {
            "backend": out.get("backend"), "model": out.get("model"),
            "cache_hit": out.get("cache_hit"),
            "pieces_returned": len(pieces) if pieces else 0,
            "guarded_changes": changes,
        }
        print(f"[{rid}] backend={out.get('backend')}:{out.get('model')} "
              f"pieces={len(pieces) if pieces else 0} changes={len(changes)}")
        for c in changes:
            print("   ", c)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    # persist the DB (both copies, md5-synced) if anything changed
    if any(r["guarded_changes"] for r in results.values()):
        import hashlib
        txt = json.dumps(db, ensure_ascii=False, indent=2) + "\n"
        (ROOT / "data" / "rooms_db.json").write_text(txt, encoding="utf-8")
        (ROOT / "public" / "data" / "rooms_db.json").write_text(txt, encoding="utf-8")
        a = hashlib.md5((ROOT / "data" / "rooms_db.json").read_bytes()).hexdigest()
        b = hashlib.md5((ROOT / "public" / "data" / "rooms_db.json").read_bytes()).hexdigest()
        assert a == b
        print("DB updated with guarded furniture volumes (md5-synced)")
    print("saved", OUT)


if __name__ == "__main__":
    main()
