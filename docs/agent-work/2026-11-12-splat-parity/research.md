# Research log — 2026-11-12

Owner supplied five references. Everything below was read on 2026-11-12 and is
reported as the source states it; nothing here is inferred silently.

## 1. `github.com/morluto/rea` — REA (Reverse Engineer Anything)

**Not a reconstruction project.** It is an MCP/CLI toolkit for inspecting native
binaries, JS/Electron apps, .NET assemblies, APK/IL2CPP metadata, GGUF model
headers, etc. Owner offered it as the *method* (reverse-engineer a site), not as
the technique. Nothing from it was applied in this session; noted so a future
session does not chase it as a pipeline reference.

## 2. `scenics.app/blog/turn-a-360-photo-into-a-3d-world` — Scenics Worlds

Facts stated by the product page:
- One 2:1 360 photo, ≥1024×512, preferably ≥2560×1280.
- Output is displayed **as a Gaussian splat**; movement is limited to a small
  area around the capture point.
- Explicit: *"The softness and changed fine details are part of the real
  output."* and *"This is a reconstruction, not a measurement."*
- Movement generosity is set by the enclosure question (room vs open view); glass
  is not reconstructed as a surface.
- Their cited basis is Kerbl et al. 2023 (3DGS), which itself requires
  multi-view capture — the single-photo case is model reconstruction, not capture.

**Extracted principle:** a single 360 photo does not carry the samples needed to
stay sharp off the capture point, and the honest product says so.

## 3. `github.com/ZiYang-xie/WorldGen` — the most concrete open pipeline

README + releases (2026):
- Two stages: panorama (FLUX.1-dev for text; any image for image mode) → 3D.
- Stage 2: **360 depth estimation** — was UniK3D, **replaced by DA-2** (2026-04-11).
- **RGBD → Gaussian splatting**, explicitly credited to **WonderWorld**.
- Optional **ml-sharp** (Apple), modified for 360 via **6-face cubemap** depth
  alignment (2026-04-12 "Improved Sharp") — i.e. pixel-scale gaussians per face.
- Background inpainting via LaMa / FLUX (`inpaint_bg`), OneFormer, LayerPano3D.
- Mesh mode available; README notes mesh "should give better results than splat"
  for structure.
- Requires GPU + gated weights (FLUX.1-dev licence acceptance).

**Extracted principle:** sharpness comes from *density + alignment* of gaussians
(ml-sharp per cubemap face), not from tuning a sparse cloud.

## 4. `home-design.ai/3d-showroom`

- Input: image / text / floor plan; models "Mini" (~60 s, 5 credits) and
  "Plus" (~300 s, 15 credits).
- Claim: AI detects depth, perspective and room relationships → 360 walkthrough.
- No technical detail published; output is a rendered 360 environment, not an
  inspectable splat file. Nothing reproducible to copy beyond "depth-aware
  reconstruction is expected to take seconds-to-minutes of GPU".

## 5. `astorie.ai/tools/image-to-3d-world` (+ `/models/3d/gaussian-splat`)

- Uses a vendor gaussian-splat generator from an image node (Nano Banana / Flux).
- States plainly: output is a *draft / spatial preview*, not pixel-identical, and
  "very large splat scenes can feel heavy on lower-spec machines".

## 6. Bonus reference found while searching (same runtime as ours)

`github.com/TingdeLiu/Image2world` — one photo → navigable world using
**Spark + three.js** (the stack our `labs/engine-v1` uses): splat with **four
LODs**, collision mesh, optional Marble key. Confirms LOD is standard practice
for dense splats.

## Synthesis — what all real implementations share

1. Monocular **360 depth** (UniK3D / DA-2 / in-house).
2. **RGBD → gaussians at pixel scale**, with inpainting for disocclusions.
3. **LOD tiers** because a pixel-scale cloud is heavy.
4. An honest label: reconstruction, not measurement.

## Format reference used for SPZ

`github.com/nianticlabs/spz` README + `load-spz.cc` + the community mapping doc
(`usd-3dgs-plugins/docs/reference/SPZ_MAPPING.md`):
- magic `0x5053474e`, version 2 or 3 = gzip, version 4 = ZSTD "NGSP".
- header: magic, version, numPoints, shDegree, fractionalBits, flags, reserved.
- positions = signed 24-bit fixed point, scale `2^-fractionalBits`.
- scale byte → `exp(b/16 - 10)`; alpha byte → `b/255`; colour byte →
  `(b/255 - 0.5)/0.15` applied to the DC coefficient.
- rotations v2 = first-three of the quaternion as signed 8-bit; v3+ = smallest
  three packed in 10 bits.
- stream order: positions, alphas, colors, scales, rotations, SH.
