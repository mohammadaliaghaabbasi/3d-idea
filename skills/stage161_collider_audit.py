#!/usr/bin/env python3
"""Stage 1.6.2 — GHOST COLLIDER AUDIT (owner order).

The stage-1.6 depth pipeline auto-carved physics colliders from DAV2 noise —
wall/floor points mistaken for furniture (owner: "players get stuck on
invisible obstacles").  This audit:

  1. separates AUTHORED colliders (stage-15 VLM-verified; owner's keep list)
     from AUTO depth-pipeline ones (via git history 5848cb0),
  2. applies deterministic ghost rules to AUTO colliders:
       - label "Door" (structure, not furniture)        -> REMOVE
       - wall-buried (far edge > 0.9 m beyond the wall) -> REMOVE
       - outside the walk bounds + 0.6 m (unreachable)  -> REMOVE
  3. vision-verifies every surviving AUTO collider against a PERSPECTIVE
     CROP of the panorama at its azimuth (composite per room, z-ai floor —
     free; TIER-1 routing, quota-cap aware): "is there floor-standing
     furniture here?"  No visual evidence -> GHOST -> REMOVE,
  4. rewrites walk.obstacles with provenance tags + md5-syncs the DB,
  5. reports the door-corridor status of every survivor.

AUTHORED colliders are NEVER removed (stage-15 VLM strips + owner's explicit
keep list: Grand Piano, cabin bed, anniversary sofa/table, ...).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))
from ai_router import Router

DB = ROOT / "data" / "rooms_db.json"
DB_PUBLIC = ROOT / "public" / "data" / "rooms_db.json"
REPORT = ROOT / "docs" / "rd-artifacts" / "stage162_collider_audit.json"
PRE_STAGE16 = "5848cb0"      # last commit before the stage-1.6 collider merge

WALL_BURIED_M = 0.9          # far edge beyond the wall radius -> ghost
CORRIDOR_HALF = 0.45         # m — capture->door corridor half-width check
COMPAT = {  # label -> acceptable vision names (fuzzy containment)
    "sofa": ["sofa", "couch", "settee", "bench", "loveseat", "armchair", "chair", "seat"],
    "table": ["table", "desk", "coffee table", "side table", "dining"],
    "bed": ["bed", "bunk", "mattress", "loft"],
    "cabinet": ["cabinet", "shelf", "shelves", "dresser", "cupboard", "wardrobe", "sideboard", "console", "counter", "bar"],
    "furniture": ["sofa", "couch", "table", "desk", "cabinet", "shelf", "dresser", "chair", "bed", "counter", "bar", "piano", "stool"],
    "piano": ["piano"],
    "radiator": ["radiator", "heater", "radiator cover", "fireplace"],
    "plant": ["plant", "potted", "tree", "palm"],
    "stove": ["stove", "heater", "fireplace", "radiator"],
    "door": [],
}


def log(*a):
    print(*a, flush=True)


def authored_map() -> dict:
    old = subprocess.run(["git", "show", f"{PRE_STAGE16}:public/data/rooms_db.json"],
                         capture_output=True, text=True, check=True).stdout
    db_old = json.loads(old)
    out = {}
    for r in db_old["rooms"]:
        out[r["id"]] = [(round(float(o["x"]), 2), round(float(o["z"]), 2)) for o in r["walk"].get("obstacles", [])]
    return out


def relief_wall_at(room: dict) -> dict:
    """Eye-level wall radius per pano-azimuth from the baked relief field."""
    rel = room["walk"]["relief"]
    img = np.asarray(Image.open(ROOT / "public" / rel["url"])).astype(np.float64)
    q = img[..., 0] * 256 + img[..., 1]
    F = rel["rmin"] + q / 65535 * (rel["rmax"] - rel["rmin"])
    return F[F.shape[0] // 2, :]      # (512,) eye-level radius per azimuth bin


def persp_crop(pano: np.ndarray, theta0: float, pitch0: float,
               w=360, h=260, fov_h=np.radians(72)) -> Image.Image:
    """Perspective crop from the equirect pano (spherical pinhole)."""
    Hp, Wp = pano.shape[:2]
    aspect = h / w
    fov_v = fov_h * aspect
    xs = (np.arange(w) / (w - 1) - 0.5) * fov_h
    ys = (0.5 - np.arange(h) / (h - 1)) * fov_v
    th = theta0 + xs[None, :].repeat(h, 0)                    # (h, w)
    ph = pitch0 + ys[:, None].repeat(w, 1)
    u = ((th / (2 * np.pi)) % 1)
    v = 0.5 - ph / np.pi
    px = np.clip(u * Wp, 0, Wp - 1).astype(np.float32)
    py = np.clip(v * Hp, 0, Hp - 1).astype(np.float32)
    x0 = np.floor(px).astype(np.int32); x1 = np.minimum(x0 + 1, Wp - 1)
    y0 = np.floor(py).astype(np.int32); y1 = np.minimum(y0 + 1, Hp - 1)
    fx = (px - x0)[..., None]; fy = (py - y0)[..., None]
    out = (pano[y0, x0] * (1 - fx) * (1 - fy) + pano[y0, x1] * fx * (1 - fy) +
           pano[y1, x0] * (1 - fx) * fy + pano[y1, x1] * fx * fy)
    return Image.fromarray(out.astype(np.uint8))


def build_composite(room, autos, panos) -> Path:
    """Grid of labeled perspective crops, one per AUTO collider."""
    panels = []
    for i, o in enumerate(autos):
        dx, dz = o["x"] - room["camera"]["x"], o["z"] - room["camera"]["z"]
        theta = float(np.arctan2(dz, -dx))          # pano azimuth
        crop = persp_crop(panos[room["id"]], theta, np.radians(-8))
        d = ImageDraw.Draw(crop)
        d.rectangle([0, 0, 68, 30], fill=(0, 0, 0))
        d.text((6, 7), f"[{i}]", fill=(255, 255, 0))
        panels.append(crop)
    cols = min(3, len(panels))
    rows = (len(panels) + cols - 1) // cols
    W, H = panels[0].size
    comp = Image.new("RGB", (cols * W + (cols - 1) * 8, rows * H + (rows - 1) * 8), (24, 24, 24))
    for k, c in enumerate(panels):
        comp.paste(c, ((k % cols) * (W + 8), (k // cols) * (H + 8)))
    out = Path("/tmp") / f"audit_{room['id']}.jpg"
    comp.save(out, quality=88)
    return out


def vision_audit(room, autos, panos) -> list:
    """Returns list of dicts {idx, seen_names, dist} from the composite."""
    comp = build_composite(room, autos, panos)
    labels = ", ".join(f"[{i}] {o['label']['en']} @{np.hypot(o['x']-room['camera']['x'], o['z']-room['camera']['z']):.1f}m"
                       for i, o in enumerate(autos))
    prompt = (f"Panodrome furniture verification. These are {len(autos)} perspective views from a 360° panorama "
              f"of a room, one per claimed furniture piece: {labels}.\n"
              "For EACH numbered panel [i], look at the scene 0.5-6 metres away and answer in STRICT JSON:\n"
              '[{"i": 0, "furniture": "name of the floor-standing furniture you actually see, or NONE", "dist_m": 2.5}, ...]\n'
              "Rules: 'furniture' must be a real object standing on the floor (sofa/table/bed/piano/cabinet/plant/heater...). "
              "If the panel mainly shows a wall, floor, door frame, ceiling or window with no floor-standing object, use NONE. "
              "dist_m = your distance estimate in metres. JSON only.")
    r = Router()
    out = r.generate(prompt=prompt, images=[str(comp)], tier=1,
                     task=f"stage162_collider_audit_{room['id']}", json_mode=True)
    try:
        t = out.get("text") or ""
        return json.loads(t[t.find("["):t.rfind("]") + 1])
    except Exception:
        return []


def main():
    db = json.loads(DB.read_text(encoding="utf-8"))
    auth = authored_map()
    panos = {r["id"]: np.asarray(Image.open(ROOT / "public" / r["panorama"]).convert("RGB"))
             for r in db["rooms"] if any(True for _ in [1])}  # lazy below
    report = {"generated": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
              "rooms": [], "removed": [], "kept_auto": []}

    for room in db["rooms"]:
        rid = room["id"]
        obs = room["walk"].get("obstacles", []) or []
        if not obs:
            continue
        walls = relief_wall_at(room)
        auth_pos = auth.get(rid, [])
        b = room["walk"]["bounds"]
        c = room["camera"]
        p = room["portals"][0]["position"]
        dxr, dzr = p[0] - c["x"], p[2] - c["z"]
        L2 = dxr * dxr + dzr * dzr

        autos, authored = [], []
        for o in obs:
            if any(abs(o["x"] - ax) < 0.03 and abs(o["z"] - az) < 0.03 for ax, az in auth_pos):
                o["source"] = "authored"
                authored.append(o)
            else:
                o["source"] = "auto"
                autos.append(o)

        removals = []
        # ---- deterministic ghost rules on AUTO colliders ----
        survivors = []
        for i, o in enumerate(autos):
            dx, dz = o["x"] - c["x"], o["z"] - c["z"]
            dist = float(np.hypot(dx, dz))
            effR = (o.get("r") or 0) or max(o.get("hw", 0), o.get("hd", 0))
            theta = float(np.arctan2(dz, -dx))
            wall = float(walls[int(((theta / (2 * np.pi)) % 1) * len(walls))])
            buried = (dist + effR) - wall
            if o["label"]["en"].strip().lower() in ("door", "door frame", "doorway"):
                removals.append({"idx": i, "label": o["label"]["en"], "rule": "label=Door (structure)"})
            elif buried > WALL_BURIED_M:
                removals.append({"idx": i, "label": o["label"]["en"], "rule": f"wall-buried {buried:.2f}m"})
            elif not (b["minX"] - 0.6 <= o["x"] <= b["maxX"] + 0.6 and b["minZ"] - 0.6 <= o["z"] <= b["maxZ"] + 0.6):
                removals.append({"idx": i, "label": o["label"]["en"], "rule": "outside walk bounds"})
            else:
                survivors.append(o)

        # ---- vision audit on survivors ----
        vision = vision_audit(room, survivors, panos) if survivors else []
        vmap = {}
        for v in vision:
            try:
                vmap[int(v.get("i"))] = v
            except Exception:
                pass
        final_autos = []
        for i, o in enumerate(survivors):
            v = vmap.get(i, {})
            seen = str(v.get("furniture", "")).strip()
            seen_l = seen.lower()
            dist = v.get("dist_m")
            names = COMPAT.get(o["label"]["en"].strip().lower(), COMPAT["furniture"])
            visual_match = seen != "" and seen.upper() != "NONE" and any(
                n in seen_l or seen_l in n for n in names)
            if visual_match:
                o["verified"] = "vision-2026-11-02"
                final_autos.append(o)
                report["kept_auto"].append({"room": rid, "label": o["label"]["en"],
                                            "seen": seen, "dist_m": dist})
            else:
                # ambiguous distance but clearly visible furniture of another
                # kind still counts (labels came from depth, not vision)
                if seen and seen.upper() != "NONE" and seen_l not in ("wall", "floor", "door", "doorway", "window", "ceiling"):
                    o["verified"] = "vision-2026-11-02"
                    final_autos.append(o)
                    report["kept_auto"].append({"room": rid, "label": o["label"]["en"],
                                                "seen": seen, "dist_m": dist, "note": "label-adjusted"})
                else:
                    removals.append({"idx": i, "label": o["label"]["en"],
                                     "rule": f"no visual evidence (vision saw: '{seen or 'no answer'}')"})

        # ---- door corridor status of the final set ----
        corridor = []
        for o in authored + final_autos:
            dx, dz = o["x"] - c["x"], o["z"] - c["z"]
            t = max(0.0, min(1.0, (dx * dxr + dz * dzr) / max(L2, 1e-9)))
            seg = float(np.hypot(dx - t * dxr, dz - t * dzr))
            effR = (o.get("r") or 0) or max(o.get("hw", 0), o.get("hd", 0))
            if seg < effR + CORRIDOR_HALF and 0.05 < t < 0.98:
                corridor.append({"label": o["label"]["en"], "source": o.get("source"), "seg_m": round(seg, 2)})

        new_obs = authored + final_autos
        room["walk"]["obstacles"] = new_obs
        for rm in removals:
            report["removed"].append({"room": rid, **rm})
        report["rooms"].append({
            "id": rid, "authored": len(authored), "auto_before": len(autos),
            "removed": removals, "auto_kept": len(final_autos),
            "door_corridor": corridor,
        })
        log(f"[{rid}] authored={len(authored)} auto={len(autos)} -> kept {len(final_autos)}, "
            f"removed {len(removals)}: {[r0['label'] + ' (' + r0['rule'] + ')' for r0 in removals]}")
        if corridor:
            log(f"    door corridor (real furniture, slide-around): {corridor}")

    txt = json.dumps(db, ensure_ascii=False, indent=2) + "\n"
    DB.write_text(txt, encoding="utf-8")
    DB_PUBLIC.write_text(txt, encoding="utf-8")
    import hashlib
    assert hashlib.md5(DB.read_bytes()).hexdigest() == hashlib.md5(DB_PUBLIC.read_bytes()).hexdigest()
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log(f"DB rewritten + md5-synced; report -> {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
