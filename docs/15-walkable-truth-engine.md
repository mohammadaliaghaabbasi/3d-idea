# 15 — The Walkable Truth Engine

> **فارسی در یک پاراگراف:** این سند راه‌حل هستهٔ پانودروم است: چطور از یک پانورامای ۳۶۰ درجه
> (یا عکس تخت) یک فضای *واقعاً* قابل قدم‌زدن بسازیم که کاربر حس کند در اتاق است و به اشیا
> برخورد کند. اصل کار: **عکس و هندسه را از هم جدا می‌کنیم.** عکس روی یک کرهٔ دست‌نخورده
> می‌ماند (هیچ ورتیسی جابه‌جا نمی‌شود)، و یک *مدل هندسی متریک* جداگانه از روی عمق متریک
> ساخته می‌شود که مرجع برخورد و پارالاکس است. خروجی: پلان اتاق + ارتفاع کف/سقف + جعبه‌های
> مانع، همه بر حسب متر، با گیت‌های عددی. پیاده‌سازی و اثبات عددی: `skills/walkable_layout_fit.py`
> و `skills/walkable_layout_selftest.py` (خطای مرز ۱.۲ سانتی‌متر روی اتاق ۲۵ متری).

Status: **v1 implemented and measured** (2026-11-10). Geometry core + analytic ground-truth
harness. Not yet wired to a real panorama or to the runtime.

---

## 1. The problem, stated honestly

The user's judgement on the previous build was precise: *"camera zooming, not walking"*.
That is the whole difficulty in one sentence. A 360 photograph is a record of **light
directions** from one point. Walking changes the **viewpoint**, and the photograph simply
has no information about that. Any system that fakes it by pushing pixels around
(depth-warp, relief dome, shoebox, plumb patches) produces bent straight lines and a
rubbery room — which is why those stages (1 – 1.6.2c) are now banned
(`MEMORY_STATE.json → stage_gate.iron_rule`).

So the constraint that killed the old approach is actually the design brief for the new one:

> **A photograph is an appearance. Walking needs geometry. Stop trying to store geometry
> inside the photograph.**

Two layers, two jobs, never mixed:

| Layer | Source | Job | Must never |
|---|---|---|---|
| **Appearance (photo shell)** | the original ERP panorama | what the eye sees at the capture point | be deformed to fake depth |
| **Geometry (metric proxy)** | **metric** depth → planes, polygons, boxes | where the walls/floor/objects *are*, in metres | claim detail it cannot measure |

The shell stays on a pristine `SphereGeometry`; the proxy is an independent, editable,
inspectable set of numbers. Collision reads the proxy, never the shell.

## 2. What makes it feel like walking

Four things, in order of importance. Miss any one and the illusion collapses:

1. **Translation, not zoom.** The camera moves in metres across a floor plane. FOV stays
   locked (68 desktop / 72 true-3D / 75 touch), forever.
2. **Contact.** A capsule of radius ≈ 0.28 m, height ≈ 1.7 m, sliding along exact
   vertical planes. Never stops dead, never passes through. Feet stay at floor level;
   steps above a 0.15 m threshold are blockers, below are steppable.
3. **Consistency.** The distance where the wall *looks* is where the collider *stops*.
   This is the number the whole pipeline exists to protect: a 20 cm mismatch between
   photo and collider is instantly felt as "fake".
4. **Parallax only where it is real.** Near objects rendered as true 3D occlude the shell
   correctly; distant walls are the photograph. The transition is hidden by depth
   blending, not by bending the photo.

## 3. Input paths

### 3.1 A 360 equirectangular panorama (primary)

One capture, full coverage, metric scale recoverable. This is the production path and what
v1 implements: `fit_layout(depth) → layout`.

### 3.2 Several flat photos of one room (multi-view)

Same geometry stage; the depth comes from multi-view instead of a single-image prior, and
the shell is stitched from the photos (or a splat). Strictly better geometrically, more work
for the uploader. Phase 2 of the product.

### 3.3 A single flat photo (the Pinterest case)

This is where honesty matters. One perspective photo contains **no information** about what
is behind the camera, and any system that shows you a full room has *invented* it. So the
product offers two explicitly labelled modes:

- **Documentary (default, honest):** only what was photographed. Metric point map from a
  single-image model (MoGe-2/3 style: points + FOV) → the visible frustum becomes a
  walkable wedge; unseen edges are a soft boundary ("photo ends here"), not fake walls.
  The user can walk a couple of metres inside the photographed volume and *nothing* is
  fabricated.
- **Generative (opt-in, labelled):** outpaint to a full panorama, then run the same 3.1
  path. This is a *designed* room, not a record — 2026 has several credible recipes
  (panorama synthesis → 3DGS lifting, e.g. One2Scene, "A Recipe for 3D Worlds",
  Image2World). It must carry a visible "AI-completed" badge, because Panodrome's promise
  is architectural truth, and attribution/licence culture is part of the brand.

Never silently promote mode 3.3 to 3.1.

## 4. The pipeline (bake time, offline)

Everything here runs in `skills/`, once per asset, and the browser only reads the result.
The browser must never run a depth model: it is slow, it is not deterministic across
devices, and it would make the collider depend on GPU state.

```
panorama.jpg
   │
   ├─(A) METRIC DEPTH + NORMALS ................ one forward pass
   │      PaGeR-metric-depth (DA3-giant backbone, 6-face cubemap, metres,
   │      normals, sky mask)  ·  fallback: DepthMaster / DA-V2-Hypersim + scale solve
   │
   ├─(B) CLEAN ................................ 3×3 median, invalid stays invalid
   │
   ├─(C) GRAVITY .............................. floor slab normal (histogram mode)
   │      tripod tilt corrected; verticals forced plumb (house law)
   │
   ├─(D) ROOM PLAN ............................ v1 = implemented
   │      1. vertical surfaces = |n·Y| < 0.25 between floor and ceiling
   │      2. radial profile per 0.5° azimuth: 92nd percentile of vertical radii
   │         (outermost vertical surface = the wall; furniture is always inside)
   │      3. Manhattan wall lines: split boundary into runs of constant
   │         orientation, median constant coordinate per run, merge within 18 cm
   │      4. polygon = intersections of consecutive wall lines (exactly orthogonal)
   │      5. per-edge refinement: refit each edge on its own wall pixels
   │         (rescues faces seen at grazing angles), re-intersect
   │
   ├─(E) HEIGHTS ............................... floor plane + ceiling plane (mode)
   │
   ├─(F) CONTENT .............................. everything not floor/ceiling/wall
   │      XZ clustering at 10 cm → oriented boxes (min-area box, snapped to the
   │      room frame ±12%), vertical extent from the 2–98% height quantiles,
   │      height < 15 cm discarded (threshold, not obstacle)
   │
   └─(G) GATES ................................ any failure = do not ship
```

Measured on analytic ground truth (`skills/walkable_layout_selftest.py`, 512×1024, 0.6%
depth noise):

| Case | Area error | Wall-foot error (mean / max) | Obstacle IoU |
|---|---|---|---|
| 6.0 × 4.2 m room + sofa box | 0.11% | **1.2 cm / 4.7 cm** | 0.948 |
| Same room, rotated 12° | 0.14% | **1.1 cm / 3.7 cm** | — |
| 8-wall room with a 0.9 m notch | 0.75% | 14.7 cm / 98 cm (see §9) | 0.897 |

Those numbers are the point of the whole document: a 1 cm wall-foot error is below what a
person can feel while walking.

## 5. Scale: the failure mode that ruins everything else

Monocular geometry is often right in *shape* and wrong in *size*. A room modelled at 80%
scale feels like a dollhouse; at 120% it feels like a cathedral. So scale is never taken on
faith:

- primary: a **metric** depth head (PaGeR produces metres directly), not SI-depth × guess;
- cross-checks: camera height ∈ [1.35, 1.85] m (tripod/handheld prior), ceiling ∈ [2.2, 6] m,
  door width ∈ [0.70, 1.05] m when a doorway is detected, floor-plan area ∈ [3, 1200] m²;
- if two priors disagree by more than 12%, the asset is flagged `scale_unverified` and the
  UI shows the measurement rather than hiding it. Architects forgive a labelled estimate;
  they never forgive a silent lie.

## 6. Runtime: collision that feels solid

The proxy is deliberately primitive, because primitives are exact:

```
Player: capsule r=0.28, h=1.70, eye 1.62, step-up 0.15
Static : floor polygon (convex decomposition) + wall half-spaces + OBB list
Move   : desired = input · speed · dt
         resolve: 1) depenetrate vs polygon edges  2) depenetrate vs OBBs
                  3) project velocity onto the contact plane (slide), keep tangential
Gate   : no reachable point may lie inside an OBB; no segment may cross a wall
```

Deliberately **not** used: mesh raycasts against the panorama sphere (that is what produced
"the camera is inside a picture"), and dynamic physics engines (a walk in a room needs no
gravity simulation, only a stable capsule).

Existing code already implements the OBB + sliding part (`public/js/collider.js`); what v1
adds is the *exact* floor-polygon boundary, which is the half that was missing.

## 7. Rendering the two layers together

```
photo shell  : SphereGeometry(500,128,96), MeshBasicMaterial, NEVER displaced
true-3D      : near-field meshes (furniture, door frames, columns) with PBR
blend        : per-object distance + depth-aware fade; the shell wins beyond ~4 m
order        : 3D meshes render in front of the shell (correct occlusion), so walking
               past a table hides the photo behind it — real parallax, zero warping
```

That is why the villa (`modern_3d_villa.glb`) already feels solid while the panoramas do
not: the villa *is* geometry. The engine's job is to give every panorama the same geometric
authority — first as colliders and occluders, and only later (and optionally) as visuals.

## 8. Data contract (rooms_db v2)

```jsonc
{
  "id": "cabin",
  "shell":  { "panorama": "assets/panoramas/cabin.jpg", "fov": 72 },
  "geometry": {
    "schema": "panodrome.room_geometry/1",
    "camera_height_m": 1.60,
    "floor_y": -1.60,
    "ceiling_h": 2.80,
    "floor_polygon": [[x, z], ...],          // metres, CCW, orthogonal
    "walls":  [{ "orientation": "x|z", "line": 2.10 }],
    "obstacles": [{ "centre_xz": [x, z], "yaw_deg": 0,
                    "extent_xz": [w, d], "base_y": -1.60, "top_y": -0.85 }],
    "confidence": { "coverage": 0.54, "floor_flat_rms_m": 0.001,
                    "wall_plumb_deg": 0.2, "manhattan_resid_m": 0.01 },
    "gates": { "...": true, "all_pass": true }
  }
}
```

Bake rule: **an asset whose `gates.all_pass` is false does not appear in the room list.**
A missing room is a QA ticket; a wrong room is a broken product.

## 9. Known limitations (measured, not guessed)

1. **Faces seen edge-on.** A surface within a few degrees of the viewing direction has very
   few pixels; the profile blends it with its neighbour (the notch in case B: 14.7 cm mean).
   Mitigation: per-edge plane refinement (already in), then a second panorama, then a
   30-second manual corner nudge in a layout editor. Do not pretend.
2. **Concave rooms beyond visibility.** From one point you cannot see the far arm of a deep
   L. The engine reconstructs what is visible; the rest must come from another capture.
   (This is also why the "L-shaped loft" test was replaced by a bay: the L test was
   geometrically invalid, not merely hard.)
3. **Mirrors and glass.** Metric depth is confidently wrong through them. Detect
   (reflection symmetry + sky mask), mark `non_walkable_surface`, and never collide.
4. **Thin structures** (railings, chair legs, plants) fall below the 250-point / 0.04 m²
   threshold. They are ignored by the collider, which is the forgiving choice.
5. **Furniture taller than the profile quantile** can absorb a wall bin; the second pass
   (distance-selected wall pixels) recovers most of it.

## 10. Milestones

| # | Deliverable | State |
|---|---|---|
| M0 | Geometry core + analytic ground-truth harness (this doc) | **done** |
| M1 | Real panorama bake: PaGeR/DA-V2 depth → `rooms_db.geometry` for the 10 existing rooms, gates enforced | next |
| M2 | Runtime consumption: `collider.js` reads `floor_polygon` + OBB list; walk test at 20 waypoints per room | |
| M3 | True-3D overlay for near objects (extruded OBBs → textured boxes first, meshes later) | |
| M4 | Flat-photo path: documentary wedge (MoGe), then labelled generative mode | |
| M5 | Multi-view / LiDAR / SketchUp ingest | |

M1 is where the product stops being a demo: the same 10 rooms get a metric, collidable
skeleton that matches their photographs.

## 11. Prior art used

- **PaGeR** — unified panoramic geometry from a single ERP (metric depth, normals, sky),
  built on Depth Anything 3: <https://github.com/prs-eth/PaGeR> ·
  <https://arxiv.org/abs/2605.26368>
- **DepthMaster** — unified metric depth for perspective *and* panoramic input:
  <https://arxiv.org/abs/2606.12368>
- **MoGe-2/3** — metric point maps + camera FOV from one image (the flat-photo path):
  <https://github.com/microsoft/MoGe>
- **Depth Anything V2 (metric, Hypersim)** — indoor metric fallback:
  <https://github.com/DepthAnything/Depth-Anything-V2>
- **HorizonNet / LayoutNet / NadirFloorNet** — panorama layout estimation lineage, for the
  floor-plan step: NadirFloorNet (CVPRW 2025) shows single-panorama metric floorplans.
- **Image2World** (MIT, 2026) — reference for "splat you can see + collision mesh you can
  bump into": <https://github.com/TingdeLiu/Image2world>
- **One2Scene** (ICLR 2026) — geometric scaffold before novel-view generation, for the
  generative single-photo mode: <https://arxiv.org/pdf/2602.19766>

## 12. Non-goals

- Photoreal *free* flying around a fabricated room. Panodrome is a walk through real space.
- Replacing the photograph with a generated one without labelling it.
- Any surface deformation of the source image, ever.
