#!/usr/bin/env python3
"""
================================================================================
 PANODROME — FOOTPRINT BENCH  (does the rd-loop winner survive the real bake?)
================================================================================

    python3 skills/footprint_bench.py
    python3 skills/footprint_bench.py --footprints 1.15,0.9,0.75,0.6

`skills/rd_loop.py` searches an IDEALISED cloud: it samples the analytic room
directly, one splat per pinhole pixel, with a scale of its own choosing. That says
what footprint is best in principle. This asks whether the same answer survives
the REAL path — `bake_from_arrays` (ERP sampling, measured normals, quantised PLY,
an opacity term) and the SPZ container — so the win is not an artefact of the
idealised sampler.

Ground truth, and why it is the pano and not the analytic room
--------------------------------------------------------------
At the CAPTURE pose the source panorama IS the truth: a correct cloud rendered
from where it was captured must give that picture back. The sharpest picture the
pipeline can possibly produce at 320x180 is the pano resampled through the same
pinhole (one ERP sample per ray) — that is the reference, and it is an upper bound
by construction, never an inflated one.

The analytic room is NOT used as the headline reference. Its geometry matches the
depth map exactly (measured: depth ratio 1.000 over 57,600 rays), but its surface
classification is per-point while the pano's is per-ERP-pixel, so the two disagree
in a thin band at every ceiling/floor/wall junction. That is edge aliasing, not a
difference in sharpness, and scoring against it would bury the effect under a
~10 dB constant. It is still reported as `analytic_psnr` for the record.

After moving, no ground truth exists (there is no second capture), so only
geometry is reported there — and geometry is exactly what a footprint changes:

  holes %   pixels with no splat at all. A hole is not blur, and it is the price
            paid for sharpness, so it is always quoted next to it.
  edge      mean |grad| of luminance at the capture pose: up = sharper.

    python3 skills/footprint_bench.py
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from walkable_layout_selftest import render_depth                 # noqa: E402
from make_demo_splat import BOXES, CAM_H, CEIL, H, POLY, W, synth_colour  # noqa: E402
from bake_splat import bake_from_arrays                           # noqa: E402
import spz_lod                                                    # noqa: E402
import rd_loop as RD                                              # noqa: E402

POSES = [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (1.0, 0.0, 0.0), (1.5, 0.0, 0.0)]
OUT = os.path.join(ROOT, "docs", "agent-work", "2026-11-12-rd-loop",
                   "footprint_bench.json")


def edge_energy(img: np.ndarray) -> float:
    lum = img @ np.array([0.2126, 0.7152, 0.0722])
    return float(0.5 * (np.abs(np.diff(lum, axis=1)).mean()
                        + np.abs(np.diff(lum, axis=0)).mean()))


def pano_reference(rgb: np.ndarray) -> np.ndarray:
    """Best pinhole view derivable from the ERP at the capture pose."""
    dirs, _fx, _fy = RD.camera_dirs(POSES[0])
    th = np.arccos(np.clip(dirs[:, 1], -1.0, 1.0))
    ph = np.arctan2(dirs[:, 0], dirs[:, 2])
    r = np.clip((th / math.pi * H).astype(np.int64), 0, H - 1)
    c = np.clip(((ph + math.pi) / (2.0 * math.pi) * W).astype(np.int64), 0, W - 1)
    return rgb[r, c].reshape(RD.RH, RD.RW, 3)


def score(points, colours, radii, pano_ref, analytic_ref, tag: str) -> dict:
    rows = {}
    for pos in POSES:
        accC, accW = RD.render_splats(points, colours, radii, pos, sigma=1.0)
        img = RD.composite(accC, accW)
        row = {"holes_pct": round(float(np.mean(accW <= 1e-6)) * 100.0, 3)}
        if pos == POSES[0]:
            row["psnr"] = round(RD.psnr(img, pano_ref), 3)
            row["analytic_psnr"] = round(RD.psnr(img, analytic_ref), 3)
            row["edge_energy"] = round(edge_energy(img), 5)
        rows[f"{pos[0]:.1f}m"] = row
    print(f"  {tag:<24} PSNR@0 {rows['0.0m']['psnr']:6.2f} dB · "
          f"edge {rows['0.0m']['edge_energy']:.5f} · holes " +
          " ".join(f"{k}:{v['holes_pct']:.2f}%" for k, v in rows.items()))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="bake the demo room at several footprints and score them")
    ap.add_argument("--footprints", default="1.15,0.75",
                    help="comma-separated splat footprints in photo-pixel units")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)

    depth = render_depth(H, W, POLY, -CAM_H, CEIL, BOXES)
    rgb = synth_colour(depth)
    pano_ref = pano_reference(rgb.astype(np.float64) / 255.0)
    analytic_ref = RD.reference(POSES[0])
    apex = RD.psnr(pano_ref, analytic_ref)
    print(f"demo room {W}x{H} · {int(np.isfinite(depth).sum())} valid px · "
          f"pano-derived vs analytic reference {apex:.2f} dB (edge aliasing)")

    report = {"room": {"w": W, "h": H},
              "reference": {"pano_psnr_at_capture": round(RD.psnr(pano_ref, pano_ref), 3),
                            "pano_vs_analytic_db": round(apex, 3)},
              "render": {"w": RD.RW, "h": RD.RH},
              "poses": [p[0] for p in POSES], "footprints": {}}

    fps = [float(x) for x in args.footprints.split(",")]
    for fp in fps:
        ply = f"/tmp/fpb_{fp:.2f}.ply"
        info = bake_from_arrays(rgb, depth, ply, max_splats=W * H, footprint=fp)
        g = spz_lod.read_ply(ply)
        pts = np.stack([g["x"], g["y"], g["z"]], axis=1)
        col = np.clip(0.5 + spz_lod.SH_C0 *
                      np.stack([g["f_dc_0"], g["f_dc_1"], g["f_dc_2"]], axis=1), 0.0, 1.0)
        rad = np.exp(g["scale_0"])
        ply_rows = score(pts, col, rad, pano_ref, analytic_ref, f"ply {fp}")

        stem = f"fp{fp:.2f}".replace(".", "")
        os.makedirs("/tmp/fp_spz", exist_ok=True)
        levels = spz_lod.build_levels(ply, "/tmp/fp_spz", [1, 2, 4, 8], stem)
        z = spz_lod.read_spz(f"/tmp/fp_spz/{stem}_lod0.spz")
        zc = np.clip(0.5 + spz_lod.SH_C0 * z["f_dc"], 0.0, 1.0)
        spz_rows = score(z["pos"], zc, z["scale"][:, 0], pano_ref, analytic_ref,
                         f"spz lod0 {fp}")

        report["footprints"][f"{fp}"] = {
            "splats": info["splats"], "ply_mb": info["file_mb"],
            "px_per_splat": info["photo_px_per_splat"],
            "median_splat_mm": round(float(np.median(rad)) * 1000.0, 2),
            "ply_render": ply_rows, "spz_lod0_render": spz_rows,
            "lod_bytes": [l["bytes"] for l in levels["levels"]],
            "spz_roundtrip": levels["levels"][0]["roundtrip"],
        }

    base, new = fps[0], fps[-1]
    a, b = report["footprints"][f"{base}"], report["footprints"][f"{new}"]
    report["delta"] = {
        "footprints": [base, new],
        "psnr_at_capture_db": round(b["ply_render"]["0.0m"]["psnr"]
                                    - a["ply_render"]["0.0m"]["psnr"], 3),
        "edge_gain": round(b["ply_render"]["0.0m"]["edge_energy"]
                           - a["ply_render"]["0.0m"]["edge_energy"], 5),
        "holes_at_1.5m_pp": round(b["ply_render"]["1.5m"]["holes_pct"]
                                  - a["ply_render"]["1.5m"]["holes_pct"], 3),
        "container_cost_db": round(b["spz_lod0_render"]["0.0m"]["psnr"]
                                   - b["ply_render"]["0.0m"]["psnr"], 3),
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=1)
    print(f"\nDELTA {new} vs {base}: "
          f"{report['delta']['psnr_at_capture_db']:+.2f} dB at capture · "
          f"edge {report['delta']['edge_gain']:+.5f} · "
          f"holes@1.5m {report['delta']['holes_at_1.5m_pp']:+.3f} pp")
    print(f"container (SPZ lod0 vs PLY, same cloud): "
          f"{report['delta']['container_cost_db']:+.2f} dB")
    print(f"  -> {os.path.relpath(args.out, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
