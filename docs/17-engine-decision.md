# 17 — The Engine, settled: two outputs, three lanes, one law

> **فارسی در یک نگاه:** تصمیم من **مسیر سوم** است، ولی با یک تصحیح مهم: مسئلهٔ ما
> «عکس یا مدل» نیست، «دو خروجی» است. هر فضا دو چیز جدا لازم دارد: **ظاهر** (چه می‌بینی)
> و **حقیقت فیزیکی** (کجا دیوار است). ظاهر می‌تواند عکس باشد، splat باشد یا مش؛ حقیقت
> فیزیکی همیشه از هندسهٔ متریک می‌آید. هندسهٔ متریک ساخته شد (`walkable-truth/1.0.0`).
> حالا فقط باید لایهٔ ظاهر عوض‌پذیر شود و یک چیز تازه اضافه شود که هیچ‌کس ندارد:
> **بودجهٔ قدم** — دقیقاً کجا حقیقت تمام می‌شود و از آن به بعد تصویر ساختهٔ هوش مصنوعی است.

Status: decision document (supersedes the "which path" debate). Implementation ladder in §6.

---

## 1. The law that cannot be argued with

A single 360 panorama is one viewpoint. Walking changes the viewpoint. Therefore from one
panorama, **any** system that shows you the room from 2 m away is *inventing* whatever was
hidden behind the sofa, the column or the door frame. No algorithm escapes this — algorithms
only hide it well or badly.

The four past attempts are four ways of hiding it badly:

| Attempt | What it did | Why it broke | Root cause |
|---|---|---|---|
| Shoebox | photo on a box | the sofa is painted on the floor and drags with you | no geometry, no disocclusion handling |
| Inpainting cut-outs | mask furniture, Telea-fill | sawtooth edges, brown smears | 2D inpainting has no 3D context |
| Relief dome | displace the sphere by depth | door frames bend, sheets melt | **geometry stored inside the photo** |
| Python-built rooms | box/cylinder/cones | cartoon, interpenetrating objects | primitives cannot be a real café |

All four failed at the same place: they asked **one** thing (pixels) to carry **two** jobs
(appearance + geometry). The engine we built fixes that split. What it lacks is a good
*appearance* layer for near-field walking — a rendering problem, not a geometry problem.

## 2. The decision: three lanes, two outputs

```
   any input ──▶ LANE A — TRUTH (always built)
   (pano / flat /   metric depth → floor polygon, heights,
    multi-photo /   obstacles, confidence, gates, WALK BUDGET
    video / glb)                    │
                                    │
                 LANE B — APPEARANCE (swappable): B1 photo shell · B2 3DGS splat · B3 authored GLB
                                    │
                 LANE C — HONESTY (new): disocclusion map + policy + "invented" label
```

**The invariant:** collision and portals read **Lane A only** — never the photo, never the
splat. A splat is a picture you can walk into, not a surface you can trust. That is why the
villa (a real GLB) already feels solid and the panoramas never did.

**Why this is not simply "path 3":** path 3 said *replace* the cartoon meshes with splats —
that is only Lane B. It would still leave no exact walls, no walk budget, and no way to say
where the truth ends. Lane A exists and is measured to 1.2 cm; Lane C is what makes the
result trustworthy instead of merely pretty.

## 3. Capability ladder — what "any photo" honestly means

| Level | Input | Lane A (truth) | Lane B (look) | Honest walk radius | Compute / room |
|---|---|---|---|---|---|
| **L0** | one flat photo | depth → frustum wedge only | photo plane + proxy | 0.5–1.0 m inside the wedge | seconds |
| **L1** | one 360 pano | full polygon + OBBs (**built** ✅) | photo shell, zero-warp | 1.0–2.0 m from capture | ~4 s CPU |
| **L2** | one 360 pano + generative bake | same polygon, same depth | 3DGS splat (Pano2Room / FastPano3D) | 3–6 m, holes inpainted | 10–60 min GPU, or seconds feed-forward |
| **L3** | 15–40 photos / 1 m-spaced 360 video / LiDAR | mesh + navmesh from the same cloud | 3DGS trained on real views | whole room, nothing invented | 10–30 min GPU |
| **L4** | authored asset (ArchViz GLB) | from the asset itself | PBR / baked GLB | unlimited | 0 |

The ladder is the answer to "can I convert any page I choose?" — **yes, and the engine says
which level it reached** instead of pretending L1 is L3. One panorama cannot become L3; it
becomes L2 (pretty, partly invented) or stays L1 (real, limited). Stating that is the
product: it is the only honest position in a market of "AI turns any photo into a 3D world".

## 4. Lane C — walk budget (the differentiator)

For a translation **t** from the capture point, part of the view reveals what the camera
never saw. That fraction is measurable from the depth map alone, with no model: forward-splat
the ERP depth by **t** (8–16 directions × 4 distances), count pixels with no source sample.

```jsonc
"walk_budget": {
  "at_0.5m": 0.012, "at_1.0m": 0.048, "at_2.0m": 0.171, "at_3.0m": 0.384,
  "radius_5pct_m": 1.05,      // stay inside: ≤5% of the view is unknown
  "radius_15pct_m": 1.85,
  "policy": "soft"
}
```

Runtime policy:

1. inside `radius_5pct` → pure photograph, nothing invented;
2. 5 %–15 % → gaps filled by **Lane A geometry in a flat matte colour** (reads as a survey
   model), never a plausible hallucinated texture;
3. beyond 15 % → the room refuses, or the UI states "this area was not photographed".

No competitor does this because they sell the fantasy. Panodrome sells the measurement.

## 5. What each lane needs

**Lane A — exists.** `skills/panodrome_engine.py`: metric ERP depth → polygon + heights +
OBBs + gates. Measured 1.2 cm mean wall error, 0.95 furniture IoU, 14.7 cm in a concave
notch (documented limit).

**Lane B1 — exists.** Pristine sphere, zero-warp. Ships today for the 10 PolyHaven rooms and
is genuinely high quality *while the camera stays near the capture point* — which Lane C now
makes explicit instead of accidental.

**Lane B2 — new, off-the-shelf:**

- **Pano2Room** (SIGGRAPH Asia 2024, MIT) — pano → mesh completion → inpainting → 3DGS;
  MIT code + checkpoints, ~30 min on one GPU. <https://github.com/TrickyGo/Pano2Room>
- **FastPano3D** (2026) — feed-forward, "up to 156× faster than Pano2Room", seconds per pano;
  the target once packaged. <https://arxiv.org/abs/2606.30352>
- **PanSplat** (CVPR 2025, MIT) — two-panorama 4K synthesis; two shots of one room upgrade
  L1 → L2 with *less* invention. <https://github.com/chengzhag/PanSplat>
- No-code validation of the same recipe (pano → MoGe depth → mesh → video model fills
  disocclusions → SfM → 3DGS): <https://github.com/mickmumpitz/ComfyUI-SplatKit>

**Lane B3 — exists.** Real authored GLBs (the villa): the only assets with unlimited honest
walking.

**Lane C — to build.** ~200 lines of numpy on the depth map Lane A already loads, plus a
fade policy in `room.js` / `collider.js`.

## 6. Build order (every step has a number that can fail)

| # | Step | Gate | Why first |
|---|---|---|---|
| 1 | Walk budget for the 10 existing rooms | curve per room; `radius_5pct` in 0.8–2.5 m | cheapest; makes L1 honest today; no GPU |
| 2 | L2 bake on **one** room (cabin / art studio) | 1.5 m sideways view cleaner than B1, no floating shards, splat ≤ 30 MB | proves the look upgrade before paying for 10 |
| 3 | Splat viewer in the existing app (`.spz`/`.ply`) | ≥ 30 fps on the test iPhone; splat vs collider < 10 cm | the "photoreal walk" moment |
| 4 | Multi-photo / video lane (InstantVR recipe) | two real rooms end-to-end, collision from the same cloud | the only 100 %-real path |
| 5 | Agent-facing `convert` API + capability report | an agent converts an arbitrary upload with no human | literally the ask |

## 7. Engine contract v2

```jsonc
"geometry": { "schema": "panodrome.room_geometry/2",
              "engine": {"id":"walkable-truth","version":"2.0.0"}, ... },
"appearance": { "mode": "shell|splat|glb", "asset": "assets/splats/cabin.spz",
                "source": "panorama|generated|authored|captured",
                "invented_fraction": 0.18 },
"walk_budget": { "radius_5pct_m": 1.05, "policy": "soft", "curve": {} },
"level": "L2"
```

`level`, `appearance.source` and `invented_fraction` are the fields that separate Panodrome
from a "photo → 3D" toy: the site always knows — and always says — how much of what you see
was photographed.

## 8. On the "Mirror" site

Searches did not identify a single walkable-3D site called *Mirror* with public data; they
surface `Pano2Room`, `PanSplat`, `InstantVR`, Marble/Scenario "skybox to splat" and unrelated
"mirror" projects. Send the URL or repo name and it will be mapped onto this ladder — the
expectation is L1/L2 with heavy inpainting and no walk budget, i.e. exactly the gap this
design closes.

## 9. Prior art (checked 2026-11)

- **World Labs Marble / Scenario "Skybox to Splat"** — one pano → walkable splat; L2 is a
  product, not a demo. <https://worldlabs.ai/labs/showcase/teleport>
- **InstantVR** (2025) — 15–20 panos at 1 m spacing → 3DGS + density-based collision mesh;
  98 % of walk attempts correctly blocked. The L3 recipe.
  <https://www.preprints.org/manuscript/202512.2692>
- **3D Pano Inpainting** (IEEE VR 2024) — single pano → textured mesh + 6DoF.
  <https://jonathanventura.github.io/3d-pano-inpainting>
- **PanoFloor** (ISMAR 2025) — multi-room floorplans + stereoscopic view graph.
  <https://www.crs4.it/vic/data/papers/ismar2025-panofloor.pdf>
- **splat-transform** (PlayCanvas, MIT) — CLI with `--collision-mesh` and interior voxel
  fill/carve: ready-made Lane A fallback for splats.
  <https://github.com/playcanvas/splat-transform>
- **NadirFloorNet** (CVPRW 2025) — metric floorplan from registered panos.
  <https://openaccess.thecvf.com/content/CVPR2025W/USM3D/papers/Pintore_NadirFloorNet_reconstructing_multi-room_floorplans_from_a_small_set_of_registered_CVPRW_2025_paper.pdf>

## 10. Non-goals, restated

- No displacement of the source panorama, ever (B1 stays pristine).
- No procedural primitives pretending to be furniture.
- No unlabelled generative content inside a "real" room.
- No claim of L2/L3 for an input that cannot support it.
