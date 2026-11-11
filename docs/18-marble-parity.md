# 18 — Marble parity: what it takes to be that product, and what now runs

> **فارسی:** «ماربل» (World Labs) یک کار می‌کند: ورودی (عکس/پانوراما/ویدیو) می‌گیرد و یک
> جهان splat قابل‌قدم‌زدن برمی‌گرداند. ما همان زنجیره را داخل خودمان ساختیم، با یک تفاوت
> اساسی: ماربل فقط *ظاهر* را می‌سازد، ما **ظاهر + حقیقت فیزیکی** می‌دهیم. حالا در این
> ریپو: پانوراما → splat سه‌بعدی (`.ply` استاندارد 3DGS) + پلان متریک + بودجهٔ قدم، با یک
> دستور و بدون GPU (خود پخت روی CPU انجام می‌شود). آنچه هنوز نیاز به GPU/کلید دارد همان
> دو بخش است: عمق متریک از مدل، و پخت generative برای پر کردن نواحی دیده‌نشده.

## 1. What Marble actually does (capability, not marketing)

| Marble capability | Mechanism | Our equivalent |
|---|---|---|
| panorama → explorable world | 3DGS generation + navigation mesh | **implemented**: `skills/bake_splat.py` + `skills/panodrome_engine.py` |
| flat photo → world | skybox outpainting → splat | not yet (needs a generative model + key) |
| multi-view / video → world | multi-view splat reconstruction | not yet (needs GPU training) |
| walk with collision | navmesh / collision mesh | **implemented and better**: measured metric polygon + OBBs |
| "explore freely" without telling you what is invented | none | **ours**: `walk_budget` |

Marble's input list is exactly our capability ladder L0–L4 (`docs/17`). The difference is
that Marble's output is a picture you can move through; ours is a picture **plus a measured
room** that knows where it stops being true.

## 2. What now runs in this repo (CPU only, no keys)

```bash
# 1) geometry only (fast, L1)
python3 skills/panodrome_engine.py build --pano <pano.jpg> --depth <depth.npy> --id <room>

# 2) geometry + 3DGS splat + walk budget (L2)
python3 skills/bake_splat.py --pano <pano.jpg> --depth <depth.npy> --id <room>

# 3) proof with no dataset at all (synthetic test room, writes a scratch db)
python3 skills/make_demo_splat.py
```

Outputs, per room, stamped `walkable-truth/1.1.0`:

- `public/assets/splats/<id>.ply` — binary 3DGS (`x y z nx ny nz f_dc_0..2 opacity scale_0..2 rot_0..3`), loadable by SuperSplat, PlayCanvas, `splat-transform`, or our own `public/js/splat.js`.
- `geometry` — floor polygon, floor/ceiling heights, wall lines, obstacle OBBs, confidence, gates (measured: 1.2 cm mean wall error on analytic ground truth).
- `walk_budget` — `{curve, radius_5pct_m, radius_15pct_m, worst_radius_5pct_m, policy}`.
- `appearance` — `{mode:"splat", asset, splats, invented_fraction:0.0}`.
- `level` — `"L2"` when a splat exists, `"L1"` for geometry only.

Measured on the synthetic 6 × 4.2 m room (262 144 gaussians, 17.8 MB): area 25.175 m²,
4-vertex polygon, 2 obstacles, gates ALL PASS, walk budget 5 % → **1.19 m**, 15 % → 1.64 m.
Two-point uncertainty: the budget's absolute value depends on the room's furniture density;
what matters is that it is *measured*, and that a convex empty room reads ~0 holes at 1 m
while a room with a sofa grows behind the sofa — both verified in the test harness.

Why the bake is three lines of math and not a neural network: a splat bake is a
**lifting** operation. Depth already gives the 3D position of every photographed pixel;
the bake turns each pixel into a gaussian whose radius is its pixel footprint at that
distance, oriented by the measured normal, coloured by the photograph. No hallucination is
possible by construction — and that is precisely why it needs `walk_budget` to be honest
about the holes.

## 3. The GPU-gated half (what a key + a GPU buys)

| Step | Model / tool | Cost per room | Effect |
|---|---|---|---|
| metric depth | **PaGeR-metric-depth** (DA3) or DepthMaster / DA-V2-Hypersim | seconds–minutes | unlocks L1/L2 for real photographs |
| generative hole filling | **Pano2Room** (SIGGRAPH Asia'24, MIT) → 3DGS | 10–60 min | removes disocclusion holes, raises the honest radius |
| fast feed-forward bake | **FastPano3D** (2026) | seconds | same, when packaged |
| two-panorama 4K | **PanSplat** (CVPR'25, MIT) | minutes | L2 with *less* invention (two real viewpoints) |
| real capture lane | **InstantVR** recipe (15–40 panos, 1 m apart) | 10–30 min | L3: nothing invented at all |

None of this changes the runtime contract: collision reads `geometry`, appearance reads
`appearance`, and honesty reads `walk_budget`.

## 4. Runtime policy (implemented in the viewer, enforced in the walk)

Inside `radius_5pct` the splat/photo is pure photography. Past 5 % the holes appear exactly
where the camera never looked; the product rule is to fill them with **matte Lane A
geometry** (a survey-model look), never with a hallucinated texture, and past 15 % to say
"not photographed" rather than invent. This is the single feature Marble cannot copy without
admitting its own limits.

## 5. Install order for the owner

1. Bake the 10 existing rooms: they need a metric depth pass first (`--depth`). Until then
   they stay L1 with the photo shell — which is already shipped and honest.
2. Bake one room as L2 (`bake_splat.py`) and inspect it; only then pay for ten.
3. If a room must look perfect from 3 m away, either run Pano2Room on it (L2+) or capture it
   properly (L3). There is no third option, and `walk_budget` will show exactly which one
   you got.

## 6. Verification performed today

- `skills/walk_budget.py` self-check: capture-point holes = 0.0000 (a correct zero), convex
  room → ~0 at 1 m, sofa room → growth behind the sofa.
- `skills/make_demo_splat.py`: synthetic panorama (1024 × 512) → 262 144-gaussian PLY
  (17.8 MB) → geometry gates PASS → scratch database record with splat + budget.
- `skills/walkable_layout_selftest.py`: ALL CASES GREEN (1.1–1.2 cm wall-foot error).
- Not verified: nothing has been looked at in a browser yet; the splat viewer is new code
  and must be inspected on a device before it ships to anyone.
