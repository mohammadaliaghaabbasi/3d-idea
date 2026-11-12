# Inventory — 2026-11-12-splat-parity

Diff range: `279dd32..e76c20b` (30 files, +2399 / −64).

## Added — code

| File | Role |
|---|---|
| `skills/spz_lod.py` | PLY → SPZ v2 encoder, 4-level LOD builder, independent decoder + round-trip verify, manifest writer |
| `public/js/spz.js` | Browser SPZ reader (DecompressionStream gzip); returns the EWA renderer's `{count,pos,col,covA,covB,alpha}` |
| `public/js/holefill.js` | ERP coverage mask from low-res depth; the photo keeps every direction it can still explain |
| `public/labs/engine-v1/*` | Vendored copy of the live moradi page (`vq11.html/js`, `moradi.html`, `app.js`, `index.html`) so it can be patched from the SSOT repo |
| `docs/19_reconstruction_parity.md` | The design + research verdict document (S0–S5 ladder) |
| `docs/agent-work/**` | This work log |

## Changed — code

| File | Change |
|---|---|
| `skills/bake_splat.py` | `--density` flag; writes `photo_px_per_splat` into `appearance` and prints the sharpness line |
| `skills/make_demo_splat.py` | Bakes at `W*H` (1 gaussian per pano pixel) instead of 400k |
| `public/js/splat.js` | `.spz` → `loadSpz()` dispatch; everything else unchanged |
| `public/engine-lab.html` | LOD tiers + `?lod=N` + device-based tier policy; `__lodInfo()` hook; HUD shows tier / px-per-splat / container bytes; versioned manifest fetch (`?v=2`) |
| `public/data/engine_lab.json` | Asset points at `demo_splat_lod0.spz`; `lods` array with counts, bytes and px-per-splat |
| `public/labs/engine-v1/vq11.js` | Blend policy: inside `SAFE_R` the photograph is authoritative and the splat is not drawn; `?hold`, `?holdramp`, `?fill=1` |
| `MEMORY_STATE.json` | SPZ + LOD decision recorded, next action updated |

## Added — data / artifacts

| Path | Size |
|---|---|
| `public/assets/splats/demo_splat.ply` (rewritten) | 35,652,000 B (was 17,826,208) |
| `public/assets/splats/demo_splat_lod0.spz` | 4,209,356 B |
| `public/assets/splats/demo_splat_lod1.spz` | 2,139,613 B |
| `public/assets/splats/demo_splat_lod2.spz` | 1,083,756 B |
| `public/assets/splats/demo_splat_lod3.spz` | 549,271 B |
| `public/assets/splats/demo_splat_lods.json` | manifest with round-trip block |
| `public/data/demo_splat_depth.bin` | 294,916 B (hole-fill depth sphere) |
| `artifacts/holefill-*.png`, `artifacts/spz-lod3-*.png`, `artifacts/live-engine-lab.png` | screenshots used as evidence in this log |

## Commits

| SHA | Subject |
|---|---|
| `8e25c11` | engine: hole-fill composite — the photo stays sharp, splats fill only the holes |
| `e610778` | lab: fix the panorama path and guard it |
| `11827a4` | labs/vq11: the photograph stays authoritative inside the measured walk budget |
| `b035d50` | splat: bake at photographic density and publish the sharpness number |
| `98dc63f` | splat: ship the SPZ container and four LOD tiers |
| `e76c20b` | lab: version the manifest fetch so a deploy can't pair a new page with an old config |

## Live deployment

`scripts/deploy_gh_pages.sh` (additive) pushed to `panodrome:main`:
- 32 files (engine-lab + hole-fill + lab assets), then 1 file (vq11 policy), then 9 files (SPZ + LOD), then 1 file (manifest versioning).
- No deletions; `labs/engine-v1/**` and `assets/panoramas/moradi_*` preserved.
