# Verification log — 2026-11-12

Every claim in `README.md` / `measurements.json` traces to one of these runs.
Commands are copy-pasteable from the repo root.

## 1. Photographic bake

```
$ cd skills && python3 make_demo_splat.py
PANODROME WALKABLE ENGINE  v1.0.0  [walkable-truth/1.0.0]
  panorama    public/assets/panoramas/demo_splat.jpg (synthetic test pattern)
  splat       524288 gaussians, 35.65 MB
  depth map   public/data/demo_splat_depth.bin (288 KB for hole-fill)
  geometry    25.175 m2 · 4 vertices · 2 obstacles · gates PASS
  walk budget 5% -> 1.5 m · 15% -> 1.79 m
```

## 2. SPZ + LOD

```
$ python3 skills/spz_lod.py --ply public/assets/splats/demo_splat.ply
  lod0  stride  1   524,288 splats    4.21 MB  (8.03 B/splat)  px/splat 1.0
  lod1  stride  2   262,144 splats    2.14 MB  (8.16 B/splat)  px/splat 2.0
  lod2  stride  4   131,072 splats    1.08 MB  (8.27 B/splat)  px/splat 4.0
  lod3  stride  8    65,536 splats    0.55 MB  (8.38 B/splat)  px/splat 8.0
  round-trip  {'checked': 52429, 'pos_err_mm_max': 0.1221,
               'opacity_err_max': 0.0004, 'color_err_8bit_max': 1,
               'scale_rel_err_max_pct': 3.174}
  verdict     GREEN
```

## 3. Live origin (GitHub Pages)

```
$ for f in js/spz.js assets/splats/demo_splat_lod0.spz … lod3.spz; do
    curl -s -o /dev/null -w '%{http_code} %{size_download}B' "$BASE/$f?cb=$RANDOM"; done
js/spz.js                              200 4705B
assets/splats/demo_splat_lod0.spz      200 4209356B
assets/splats/demo_splat_lod1.spz      200 2139613B
assets/splats/demo_splat_lod2.spz      200 1083756B
assets/splats/demo_splat_lod3.spz      200 549271B
lods in manifest: 4
```

## 4. Runtime in the cloud browser

```js
// https://…/panodrome/engine-lab.html?lod=3
window.__lodInfo()
→ { level: 3, points: 65536, container: "spz/2", bytes: 549271 }
// ?lod=1
→ { level: 1, points: 262144, container: "spz/2", bytes: 2139613 }
// HUD line: "splats 65,536 · lod 3 · 8 px/splat · spz/2 0.55 MB · invented 0%"
```

## 5. Defect found and fixed during verification

GitHub Pages served the previous `data/engine_lab.json` after the SPZ deploy, so
the new page paired with the old manifest and loaded the PLY asset (HUD showed
`lod 0 · ply`). Fix: `engine-lab.html` fetches `data/engine_lab.json?v=2`
(commit `e76c20b`). Re-verified after the fix: `spz/2` at every tier.

## 6. Not verified (and why)

- **lod0 rendering in the browser.** Sandbox GL is SwiftShader: 0.3 fps at
  524,288 splats, `Page.captureScreenshot` times out at 15 s. The file itself is
  verified by the round-trip decoder (0.12 mm). Owner-side check needed.
- **Frame rate on real hardware.** Only the sandbox ratio (lod3 1.4 fps vs
  lod0 0.3 fps) was observed, which is a software-rasterisation artefact.
- **moradi page sharpness.** The policy change (`SAFE_R` gate) is deployed and
  the live `vq11.js` contains it (HTTP 200, patched block at lines 221-231), but
  the 520k-splat page also cannot be screenshotted under SwiftShader.
