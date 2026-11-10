# 16 — The engine: one command, one identity

> **فارسی:** همیشه و فقط یک موتور وجود دارد: `walkable-truth/1.0.0`. هر اتاقی که ساخته
> شده باشد، مُهر موتور را داخل `geometry.engine` دارد. برای تبدیل هر صفحهٔ ۳۶۰ که انتخاب
> کردی، فقط همین یک دستور را اجرا می‌کنی و اگر گیت‌ها رد شوند، اتاق اصلاً نوشته نمی‌شود.

This document answers exactly one question: **"which engine turned my 360 into a 3D
space?"** — and how to run it again on any page you choose.

Design rationale and measurements: `docs/15-walkable-truth-engine.md`.
Code: `skills/panodrome_engine.py` (engine), `skills/walkable_layout_fit.py` (geometry
core), `skills/walkable_layout_selftest.py` (proof against ground truth).

---

## 1. Identity

| | |
|---|---|
| engine id | `walkable-truth` |
| version | `1.0.0` |
| entry point | `skills/panodrome_engine.py` |
| stamp written into every room | `geometry.engine = {"id":"walkable-truth","version":"1.0.0"}` |
| manifest | `data/engine.json` (rewritten on every run) |
| runtime consumer | `public/js/collider.js` → `walk.polygon` + `walk.obstacles` |

Check it at any time — this is the authoritative answer, not a memory of one:

```bash
python3 skills/panodrome_engine.py info     # identity card: laws, sources, gates
python3 skills/panodrome_engine.py list     # which rooms were built by this engine
python3 skills/panodrome_engine.py verify   # re-run the gates on every built room
```

**Not** the engine, and never to be used again (owner order, `MEMORY_STATE.json →
stage_gate.iron_rule`): relief dome, depth-cut extrusion, shoebox, plumb patches, FOV zoom.
Those built the room by *deforming the photograph*. This engine deforms nothing.

## 2. Convert a 360 page — three ways, all explicit

```bash
# A. measured depth (best): PaGeR-metric-depth / DepthMaster / DA-V2-Hypersim output
python3 skills/panodrome_engine.py build \
    --pano public/assets/panoramas/cabin.jpg \
    --depth depth/cabin.npy \
    --id cabin

# B. a model hooked up as a command (it must write a metric .npy)
python3 skills/panodrome_engine.py build \
    --pano public/assets/panoramas/new_page.jpg \
    --depth-cmd 'python3 tools/pager_infer.py {pano} {out}' \
    --id new_page --create-room

# C. declared plan, no depth model at all (rect, or a JSON polygon)
python3 skills/panodrome_engine.py build \
    --pano public/assets/panoramas/new_page.jpg \
    --plan rect:6.0x4.2:2.8 \
    --id new_page --create-room
```

`--plan room.json` takes the architect's real outline:

```json
{
  "floor_polygon": [[-3, -2.1], [3, -2.1], [3, 2.1], [-3, 2.1]],
  "ceiling_h": 2.8,
  "camera_height_m": 1.6,
  "obstacles": [{ "centre_xz": [1.6, 0.9], "extent_xz": [1.2, 0.6],
                  "yaw_deg": 0, "base_y": -1.6, "height": 0.75 }]
}
```

The engine never guesses which source it used: `geometry.source.kind` is
`measured` | `estimated` | `declared`, with the file/command recorded next to it.

**It will not invent a room from a photograph alone.** A 360 image contains no metric
information; a tool that pretends otherwise is the reason the earlier stages looked fake.
Source C exists precisely so the honest path is also the fast path.

## 3. What gets written

Into `data/rooms_db.json` and `public/data/rooms_db.json` (same file, kept in sync):

```jsonc
"geometry": {
  "schema": "panodrome.room_geometry/1",
  "engine":  { "id": "walkable-truth", "version": "1.0.0" },
  "source":  { "kind": "measured", "depth_file": "...", "pano": "...", "pano_sha256_16": "..." },
  "camera_height_m": 1.55,
  "floor_y": -1.55,
  "ceiling_h": 2.5,
  "floor_polygon": [[-1.7286, -2.3137], ...],   // metres, CCW, exact
  "walls":  [{ "orientation": "x", "line": -1.7501, "samples": 211 }, ...],
  "area_m2": 16.076,
  "obstacles": [{ "centre_xz": [...], "yaw_deg": 0.5, "extent_xz": [...],
                  "base_y": -1.4772, "top_y": -0.9945 }],
  "confidence": { "coverage": 0.499, "floor_flat_rms_m": 0.0044,
                  "wall_plumb_deg": 0.1, "manhattan_resid_m": 0.0078 },
  "gates": { "all_pass": true }
},
"walk": {                       // the runtime contract, derived, not hand-written
  "player_radius": 0.28,
  "polygon": [...],             // exact boundary → collider slides on real walls
  "bounds": { ... },            // AABB fallback for older builds
  "ceiling_h": 2.5, "floor_y": -1.55,
  "obstacles": [{ "type": "box", "x":..., "z":..., "hw":..., "hd":..., "rot":... }],
  "engine": "walkable-truth/1.0.0"
}
```

### Gates (a failing room is never written)

| gate | limit | meaning |
|---|---|---|
| `floor_flat_rms_m` | ≤ 0.02 | the floor really is a plane |
| `wall_plumb_deg` | ≤ 1.5 | walls really are vertical |
| `ceiling_h_m` | 2.2 – 6.0 | a room, not a tunnel or a stadium |
| `area_m2` | 3 – 1200 | sane footprint |
| `coverage` | ≥ 0.45 | enough pixels were classified to trust the result |
| `manhattan_resid_m` | ≤ 0.22 | the plan really is orthogonal within tolerance |

`--force` writes a failing room with `all_pass:false` for debugging. It must never be used
for a room that ships.

## 4. Runtime: what changed

`public/js/collider.js` now prefers `walk.polygon`:

- capsule (r = 0.28) vs **every boundary segment** → sliding contact that is exact for
  concave rooms and diagonals (the old axis-aligned box is kept only as a fallback for
  rooms that have no geometry yet);
- obstacles come from `walk.obstacles` in the existing box vocabulary, so the halos,
  furniture proxies and bump events keep working unchanged;
- `walk.ceiling_h` / `walk.floor_y` are available for the eye height and ceiling law.

## 5. Verification actually performed

```bash
# geometry, against analytic ground truth (0.6 % depth noise)
cd skills && python3 walkable_layout_selftest.py
#   A_rect_6x4.2_one_obstacle   area 0.11 %  boundary 1.2 / 4.7 cm  IoU 0.948
#   C_rect_rotated_12deg        area 0.14 %  boundary 1.1 / 3.7 cm
#   B_bay_room (concave)        area 0.75 %  boundary 14.7 / 98 cm (edge-on limit)
#   RESULT: ALL CASES GREEN

# engine end-to-end on a real panorama file + measured depth (temp db)
python3 skills/panodrome_engine.py build --pano public/assets/panoramas/cabin.jpg \
        --depth <depth.npy> --id cabin --db /tmp/db.json
#   gates ALL PASS → geometry + walk written

# collision, headless (node + a one-file stub for `three`)
#   capsule rests exactly one radius off the wall; concave slide holds;
#   20 000 random 2.5 m/s steps never leave the polygon.
```

## 6. Adding a new 360 page — the whole procedure

1. drop the equirectangular image in `public/assets/panoramas/<id>.jpg` (+ preview);
2. get metric depth for it (PaGeR/DepthMaster/DA-V2) **or** describe the room with
   `--plan`;
3. run one `build` command with `--id <id>`;
4. `verify` → all green → the page is now a walkable room with real walls and obstacles;
5. `list` to confirm the room is engine-built (and which version built it).

Nothing else in the project needs to know about the new page: the room list, portals, HUD
and collider all read the same database record.
