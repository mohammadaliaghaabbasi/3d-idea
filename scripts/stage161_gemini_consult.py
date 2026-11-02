#!/usr/bin/env python3
"""Stage 1.6.1 — Gemini TIER-1 (gemini-3.6-flash) lead-architect consult.
Sends the broken Stage-1.6 screenshots + pipeline summary + the V2 relief-dome
design; asks for root-cause diagnosis + design critique + parameter sign-off.
One live T1 call (2 images). Result saved to docs/rd-artifacts/stage161/."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills"))
from ai_router import Router

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "rd-artifacts" / "stage161" / "gemini_consult.json"

IMGS = [
    ROOT / "docs/rd-artifacts/stage16/stage16_vlm_volume3d_viewA.jpg",   # old sofa cluster w/ extruded mesh
    ROOT / "docs/rd-artifacts/stage16/stage16_vlm_clean_viewB.jpg",     # old wall behind sofa (Telea zone)
]

PROMPT = """You are the LEAD 3D SPATIAL ARCHITECT for Panodrome, a three.js site that turns 360-degree equirect panoramas into walkable first-person interiors (metric rooms, real WASD/joystick walking, furniture colliders, doorway portals).

CONTEXT — STAGE 1.6 FAILED THE OWNER'S LIVE IPHONE AUDIT (catastrophic, production-pullback ordered):

Old pipeline (skill_360_to_walkable_3d.py): DAV2-small ONNX depth (2048x1024 disparity, inverted) -> guided-filter edge alignment -> multi-start measured-shell calibration (scale, cam_h, per-azimuth wall profile) -> furniture separation (depth < shell - 0.3m, morph clean-up, connected components) -> for each furniture piece: a grid mesh cut from the depth map with EDGE TEARING (quad-drop when depth spread > 14%) + RADIAL BACK-CAPS (0.22m) + JPEG pano texture -> compact GLB. The panorama itself got furniture ERASED + OpenCV TELEA inpainted over a 122px parallax guard band (dilate 12px + reveal band) to make the "shell" texture.

Owner's iPhone findings:
1) cabin: the furniture GLB exploded into giant spiky white/brown shards and jagged triangles radiating across the middle of the room.
2) anniversary_lounge: the green sofa / side table / coffee table had saw-tooth jagged spikes and accordion-like stretched edges sticking out of their sides (from the extrusion back-caps).
3) anniversary_lounge: the 122px Telea band left a huge blurry brown smudge on the wall behind the sofa, ruining the 4K photo.

The two attached screenshots are from the old build (view A: the sofa cluster with the extruded meshes; view B: the wall region that suffered the Telea inpainting).

V2 DESIGN (already in implementation — REVIEW IT):
- Rule A: the ORIGINAL crisp pano_4k.jpg is the ONLY texture (no inpainting, no shell swap, no cutouts). Per-fragment equirect shader (three.js) projects it from the capture point onto ANY geometry — pixel-exact at spawn.
- Rule B: a single WATERTIGHT GROUND-FLATTENED RADIAL RELIEF DOME replaces both the old shoebox room and the furniture cutouts. Offline bake (Python, per room): D = GaussianBlur(inverted DAV2 disparity, sigma=18px @ 2048) x calibrated scale -> per-direction radial relief field with:
  * floor snap: below-horizon rays whose depth is within ~3-16% of the analytic floor-plane distance (phi-dependent band) are blended/snapped to the EXACT y=0 plane (flat-floor law; final pass forces exact planar for steep rays phi < -50deg within 10cm of the floor);
  * ceiling snap to the calibrated ceiling plane (same ratio-band blend);
  * soft C1 clamp into the room envelope (softplus shoulder, k=1.2m, rmax = 1.25x box ray max, rmin spike guard ~1.7m at eye level);
  * outlier winsorisation (raw cache had negative-disparity speckles inverting to multi-km spikes);
  * encoded as a 512x256 u16 relief PNG (R=hi, G=lo byte; 23-90KB).
  Runtime (room.js): a 320x144-bin sphere grid around the capture point, each vertex displaced by the bilinearly-sampled relief radius; poles capped with tiny fans (floor cap exactly y=0). Result: ~46k verts, one draw call, no torn edges, no back-caps, no per-object meshes. Furniture is PAINTED on the photograph but sits at its TRUE radial depth (soft relief bulges), so walking gives genuine parallax.
- Walk envelope (owner spec): elastic radial boundary, base radius 1.1-1.35m from the capture point (per-room = wall_p10 - 0.35m, clamped 0.8-1.35), smooth spring damping from 78% of the radius, hard radial clamp at 100% with tangential slide; plus smooth cosine^2 "channels" toward each doorway ring (reach = ring_dist - 1.0m) and each obstacle collider (reach = dist - effR - 0.34m) so portals stay walk-in reachable and every collider is bumpable.
- Rule C: furniture collision stays REAL physics: existing calibrated 2D colliders (circle-vs-box / circle-vs-cylinder, sliding, bump events) upgraded with optional OBB yaw; plus a sleek GLASS FLOOR HALO (rounded-rect/circle outline + soft fill, proximity-faded, bump-flash) rendered on the floor around each obstacle. Optional clean Hunyuan3D-2 manifold proxies ONLY if a Gemini Vision manifold/spike check passes.

MEASURED BAKE RESULTS (all 10 rooms): floor deviation = 0.0mm exactly; saw-tooth zigzag metric (slope-reversal height) <= 0.29m everywhere; wall-band radius std 0.014-0.075m (measured rooms).

QUESTIONS (answer ALL, numbered, concise, engineering-grade):
1) Root-cause each of the three owner findings (cabin shards; sofa saw-tooth skirts; Telea smudge) in terms of the old pipeline's geometry/algorithm — what exactly produced spikes instead of surfaces?
2) Critique the V2 relief dome: name any REMAINING geometric hazards for a 1.1-1.35m walk radius (texture swimming at bulge silhouettes, vertical shear when camera eye 1.65m differs from capture height 0.75-1.05m, nadir/zenith caps, equirect seam, relief-vs-collider disagreement) and for each: is it acceptable at this radius, or give a concrete mitigation.
3) Are the parameters right? sigma=18px@2048 (3.2 deg), soft clamp k=1.2m, snap bands (0.72-0.86 steep / 0.84-0.94 mid / 0.92-0.97 shallow), envelope base = wall_p10 - 0.35m. If you would change any, say which and to what.
4) The cabin is small (walls ~1.2-1.5m from capture, capture height 0.75m, ceiling ~2.4m authored / 1.95m measured) — anything specific to watch so the QA screenshots (spawn + after walking 1.2m toward the bed) stay clean?
5) Final verdict: will this V2 deliver spike-free, smudge-free, genuinely-walkable rooms at QA >= 9/10? List your top-3 residual risks.
"""

def main():
    r = Router()
    out = r.generate(
        prompt=PROMPT,
        images=[str(p) for p in IMGS],
        tier=1,
        task="stage161_architect_consult",
        system="You are a senior 3D graphics engineer and spatial-AI architect. Be rigorous, concrete, and quantitative. No marketing language.",
        use_cache=True,
    )
    data = dict(out)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print("=== backend:", data.get("backend"), "model:", data.get("model"), "cache_hit:", data.get("cache_hit"))
    print("=== RESPONSE ===")
    print(data.get("text"))
    print("=== saved to", OUT)

if __name__ == "__main__":
    main()
