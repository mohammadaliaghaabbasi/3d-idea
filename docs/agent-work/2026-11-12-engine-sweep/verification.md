# Verification log — engine-sweep (2026-11-12)

## 0. Container discovery (why the first two runs failed)

```
$ curl …/labs/engine-v1/assets/moradi_main1_splat.spz          → HTTP 404
$ api.github.com/…/contents/labs/engine-v1/assets               → 26 files
    {scene}_splat_v11.spz  and  {scene}_splat_v12.spz           (no plain name)
```

Then the decoding failed as well:

```
$ python3 - <<'EOF'  (header dump)
bytes 5687476  head 4e47535004000000
magic=0x5053474e ver=4 n=529396 sh=0 frac=12 flags=0 res=5
expected v2 size: 10058540 actual: 5687476
```

i.e. these assets are **SPZ v4** ("NGSP" + ZSTD), not the v2/gzip the writer emits.
Resolved empirically:

```
zstd magic (28 b5 2f fd) at byte 112 of 5687476
stream-decompressed → 10,587,920 bytes = n * 20
   positions 9n · alphas n · colours 3n · scales 3n · rotations 4n
```

`skills/engine_sweep.py::_decode_v4` implements exactly that (frame located by
magic, because the header is followed by an extension block). `zstandard` was
installed into the workspace venv (`python3 -m pip install zstandard`).

## 1. Moradi (10 live scenes, both generations)

```
$ python3 skills/engine_sweep.py --group moradi --scenes moradi_main1,moradi_main2,moradi_kit1
  moradi_main1     529396 splats · 15.8 px/splat · coverage {'0.00m': 1.0, '0.25m': 0.9975,
                   '0.50m': 0.9861, '1.00m': 0.9544, '1.50m': 0.9294}
  moradi_main2     529396 splats · 15.8 px/splat · {… '1.50m': 0.9304}
  moradi_kit1      529396 splats · 15.8 px/splat · {… '1.50m': 0.9716}
```
(remaining seven scenes run in two batches, same command with `--scenes`)

Summary of the merged `results.json`:

```
moradi rows: 10
coverage @0.5m: min 0.9857  max 0.9933
coverage @1.5m: min 0.9031  max 0.9716  mean 0.9360
px/splat set: [15.8]         (pano 4096×2048 = 8,388,608 px / 529,396 splats)
splat counts: [529396]       (v11 generation: 132,349 → 63.4 px/splat)
```

## 2. Houses (10 curated rooms) — two movement regimes

```
$ python3 skills/engine_sweep.py --group houses
  anniversary_lounge  [4096, 2048] obstacles 7 · bounds · egress 0 · outside 0.0 mm · residual 0.0 mm
  art_studio          [4096, 2048] obstacles 5 · bounds · egress 0 · outside 0.0 mm · residual 0.0 mm
  cabin               [4096, 2048] obstacles 5 · bounds · egress 0 · outside 0.0 mm · residual 26.6179 mm
  comfy_cafe          [4096, 2048] obstacles 8 · bounds · egress 0 · outside 0.0 mm · residual 37.736 mm
  large_corridor      [4096, 2048] obstacles 2 · bounds · egress 0 · outside 0.0 mm · residual 0.0 mm
  castle_zavelstein_cellar [4096,2048] obstacles 0 · bounds · egress 0 · outside 0.0 mm · residual 0.0 mm
  ballroom            [4096, 2048] obstacles 1 · bounds · egress 0 · outside 0.0 mm · residual 0.0 mm
  school_hall         [4096, 2048] obstacles 3 · bounds · egress 0 · outside 0.0 mm · residual 0.0 mm
  leipzig_festsaal    [4096, 2048] obstacles 2 · bounds · egress 0 · outside 0.0 mm · residual 0.0 mm
  quadrangle_sunny    [4096, 2048] obstacles 3 · bounds · egress 0 · outside 0.0 mm · residual 0.0 mm
```

Adversarial regime (`step_max = 0.85 m`) in the same run:

```
anniversary_lounge 350 egress / 329.64 mm      art_studio 13 / 257.01 mm
comfy_cafe 164 / 490.54 mm                     leipzig_festsaal 10 / 49.42 mm
all others 0
```

## 3. Villa

```
$ python3 skills/engine_sweep.py --group villa
  villa: 5 colliders {'box': 4, 'cylinder': 1} · area 23.65 m2 · bounds · egress 0
         · outside 0.0 mm · residual 0.0 mm
  adversarial: egress 318 / 160.0 mm
```

## 4. Harness defect found and fixed (disclosed, not hidden)

First version of the sweep clamped to the axis-aligned box and pushed out of
obstacles with no second wall pass, and measured penetration **before** resolve.
It reported `escaped 350 · worst pen 834.5 mm` for anniversary_lounge — an
artifact of the harness, not the engine. Rewritten as `skills/collision_probe.py`
mirroring `public/js/collider.js` (`resolve()`: polygon segments with 2 passes, or
bounds clamp; then obstacles; metrics measured **after** resolution), and split
into the realistic (≤0.10 m) and adversarial (≤0.85 m) regimes.

## 5. Not verified

- Lane A geometry for the 10 real rooms: **blocked** — `data/depth/` contains only
  `demo_splat.npy`; without 360 depth the engine refuses to invent a polygon.
- Visual rendering of any page: software GL in this sandbox (0.3–1.4 fps at these
  splat counts); all sweep results are numeric and data-level.
