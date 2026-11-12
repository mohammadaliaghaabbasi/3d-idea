#!/usr/bin/env python3
"""
================================================================================
 PANODROME — SPZ + LOD  (make a photographic-density cloud servable)
================================================================================

A photographic bake (one gaussian per pano pixel) is 68 bytes/splat as PLY:
8.4 M splats for a 4K panorama = 570 MB. That is not servable. SPZ is the
Niantic container the whole splat world converged on: 24-bit fixed-point
positions, 8-bit log scales, 8-bit alpha, 8-bit colours — ~19 bytes/splat
before gzip, ~10x smaller than the PLY equivalent.

    python3 skills/spz_lod.py --ply public/assets/splats/demo_splat.ply \
        --levels 1,2,4,8 --out-dir public/assets/splats

  ->  demo_splat_lod0.spz  (stride 1, every splat)
      demo_splat_lod1.spz  (stride 2)
      demo_splat_lod2.spz  (stride 4)
      demo_splat_lod3.spz  (stride 8)

and a `spz_lod.json` manifest with counts, byte sizes and px-per-splat for
every level, so the viewer (and the honesty lane) can pick a tier instead of
guessing.

Format written: **SPZ version 2** (gzip stream). Version 4 is ZSTD + smallest-
three rotation packing; v2 gzip is the read-only-compatible one that every
loader in the wild (including Spark) still accepts.

    bytes  0.. 3   magic  0x5053474e  ("NGSP")
    bytes  4.. 7   version (2)
    bytes  8..11   numPoints
    bytes 12       shDegree (0 — DC colour only, which is all a bake has)
    bytes 13       fractionalBits (12 -> 0.24 mm at room scale)
    bytes 14       flags (0)
    bytes 15       reserved (0)

    then, per point, in stream order:
      positions  int24 x3   (value * 2^fractionalBits)
      alphas     uint8      (opacity * 255)
      colors     uint8 x3   (f_dc: (byte/255 - 0.5) / 0.15)
      scales     uint8 x3   (log: exp(byte/16 - 10))
      rotations  int8  x3   (q.xyz: byte/127.5 - 1; w = sqrt(1 - |xyz|^2))
================================================================================
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

MAGIC = 0x5053474E          # "NGSP" in file order
VERSION = 2
FRACTIONAL_BITS = 12        # 1/4096 m = 0.24 mm, range +-2048 m
SH_C0 = 0.28209479177387814


# --------------------------------------------------------------------- PLY in

def read_ply(path: str) -> dict[str, np.ndarray]:
    with open(path, "rb") as fh:
        raw = fh.read()
    marker = b"end_header\n"
    cut = raw.index(marker)
    header = raw[:cut].decode("ascii", "replace")
    body = raw[cut + len(marker):]
    count = int((header.split("element vertex ")[1]).split()[0])
    props = [l.split()[-1] for l in header.splitlines() if l.startswith("property float ")]
    data = np.frombuffer(body, dtype="<f4", count=count * len(props)).reshape(count, len(props))
    return {p: data[:, i].astype(np.float64) for i, p in enumerate(props)}


# ------------------------------------------------------------------- SPZ out

def _enc_positions(p: np.ndarray, frac_bits: int) -> bytes:
    q = np.round(p * (1 << frac_bits)).astype(np.int64)
    q = np.clip(q, -(1 << 23), (1 << 23) - 1)
    # 24-bit little endian, three bytes per axis, signed
    b = np.empty((q.shape[0], 3, 3), dtype=np.uint8)
    u = (q & 0xFFFFFF).astype(np.uint32)
    b[..., 0] = (u & 0xFF)
    b[..., 1] = ((u >> 8) & 0xFF)
    b[..., 2] = ((u >> 16) & 0xFF)
    return b.tobytes()


def _enc_alpha(alpha01: np.ndarray) -> bytes:
    return np.clip(np.round(alpha01 * 255.0), 0, 255).astype(np.uint8).tobytes()


def _enc_color(f_dc: np.ndarray) -> bytes:
    v = np.clip((f_dc * 0.15 + 0.5) * 255.0, 0, 255)
    return np.round(v).astype(np.uint8).tobytes()


def _enc_scale(scale_m: np.ndarray) -> bytes:
    v = np.clip((np.log(np.maximum(scale_m, 1e-6)) + 10.0) * 16.0, 0, 255)
    return np.round(v).astype(np.uint8).tobytes()


def _enc_rotation(q_wxyz: np.ndarray) -> bytes:
    q = q_wxyz / np.maximum(np.linalg.norm(q_wxyz, axis=1, keepdims=True), 1e-12)
    # q and -q are the same rotation; keep w >= 0 so w is recoverable from xyz
    flip = q[:, 0] < 0
    q[flip] *= -1.0
    xyz = np.clip(q[:, 1:4], -1.0, 1.0)
    v = np.round((xyz + 1.0) * 127.5).astype(np.int32) - 128
    return np.clip(v, -127, 127).astype(np.int8).tobytes()


def write_spz(path: str, g: dict[str, np.ndarray], frac_bits: int = FRACTIONAL_BITS) -> dict:
    n = len(g["x"])
    hdr = struct.pack("<IIIBBBB", MAGIC, VERSION, n, 0, frac_bits, 0, 0)
    pos = np.stack([g["x"], g["y"], g["z"]], axis=1)
    payload = b"".join([
        hdr,
        _enc_positions(pos, frac_bits),
        _enc_alpha(1.0 / (1.0 + np.exp(-g["opacity"]))),
        _enc_color(np.stack([g["f_dc_0"], g["f_dc_1"], g["f_dc_2"]], axis=1)),
        _enc_scale(np.stack([np.exp(g["scale_0"]), np.exp(g["scale_1"]),
                             np.exp(g["scale_2"])], axis=1)),
        _enc_rotation(np.stack([g["rot_0"], g["rot_1"], g["rot_2"], g["rot_3"]], axis=1)),
    ])
    with open(path, "wb") as fh:
        fh.write(gzip.compress(payload, 9))
    return {"points": n, "bytes": os.path.getsize(path),
            "bytes_per_splat": round(os.path.getsize(path) / n, 2)}


# ------------------------------------------------------------------ verify in

def read_spz(path: str) -> dict[str, np.ndarray]:
    """Decode what we just wrote (independent code path = a real round-trip)."""
    with open(path, "rb") as fh:
        buf = gzip.decompress(fh.read())
    magic, version, n, sh, frac, flags, _ = struct.unpack_from("<IIIBBBB", buf, 0)
    assert magic == MAGIC, "bad magic"
    off = 16
    pos_bytes = np.frombuffer(buf, dtype=np.uint8, count=n * 9, offset=off).reshape(n, 9)
    off += n * 9
    p = np.empty((n, 3), dtype=np.float64)
    for i in range(3):
        u = (pos_bytes[:, i * 3].astype(np.int64)
             | (pos_bytes[:, i * 3 + 1].astype(np.int64) << 8)
             | (pos_bytes[:, i * 3 + 2].astype(np.int64) << 16))
        u = np.where(u >= (1 << 23), u - (1 << 24), u)      # sign extend
        p[:, i] = u / (1 << frac)
    alpha = np.frombuffer(buf, dtype=np.uint8, count=n, offset=off) / 255.0
    off += n
    col = np.frombuffer(buf, dtype=np.uint8, count=n * 3, offset=off).reshape(n, 3) / 255.0
    f_dc = (col - 0.5) / 0.15
    off += n * 3
    sb = np.frombuffer(buf, dtype=np.uint8, count=n * 3, offset=off).reshape(n, 3)
    scale = np.exp(sb / 16.0 - 10.0)
    off += n * 3
    rb = np.frombuffer(buf, dtype=np.int8, count=n * 3, offset=off).reshape(n, 3)
    xyz = (rb.astype(np.float64) + 128.0) / 127.5 - 1.0
    w = np.sqrt(np.maximum(0.0, 1.0 - (xyz ** 2).sum(axis=1)))
    return {"pos": p, "alpha": alpha, "f_dc": f_dc, "scale": scale,
            "quat": np.concatenate([w[:, None], xyz], axis=1)}


def verify(a: dict[str, np.ndarray], spz_path: str, sample: int = 50000) -> dict:
    """Compare the SPZ against the EXACT arrays it was written from."""
    b = read_spz(spz_path)
    n = min(len(a["x"]), len(b["pos"]))
    step = max(1, n // sample)
    sl = slice(0, n, step)
    pos_err = np.abs(np.stack([a["x"][sl], a["y"][sl], a["z"][sl]], axis=1) - b["pos"][sl])
    op_a = 1.0 / (1.0 + np.exp(-a["opacity"][sl]))
    col_a = 0.5 + SH_C0 * np.stack([a["f_dc_0"][sl], a["f_dc_1"][sl], a["f_dc_2"][sl]], axis=1)
    col_b = 0.5 + SH_C0 * b["f_dc"][sl]
    sc_a = np.stack([np.exp(a["scale_0"][sl]), np.exp(a["scale_1"][sl]),
                     np.exp(a["scale_2"][sl])], axis=1)
    return {
        "checked": int(len(range(0, n, step))),
        "pos_err_mm_max": round(float(pos_err.max()) * 1000.0, 4),
        "opacity_err_max": round(float(np.abs(op_a - b["alpha"][sl]).max()), 4),
        "color_err_8bit_max": int(round(float(np.abs(col_a - col_b).max()) * 255)),
        "scale_rel_err_max_pct": round(float((np.abs(sc_a - b["scale"][sl]) / sc_a).max()) * 100, 3),
    }


# ---------------------------------------------------------------------- LOD

def build_levels(ply_path: str, out_dir: str, strides: list[int], stem: str) -> dict:
    g = read_ply(ply_path)
    total = len(g["x"])
    levels = []
    for li, stride in enumerate(strides):
        sub = {k: v[::stride] for k, v in g.items()}
        out = os.path.join(out_dir, f"{stem}_lod{li}.spz")
        info = write_spz(out, sub)
        info.update({
            "level": li,
            "stride": stride,
            "file": os.path.relpath(out, os.path.join(ROOT, "public")),
            "px_per_splat": round(float(stride), 2),
        })
        if li == len(strides) - 1 or li == 0:
            info["roundtrip"] = verify(sub, out)
        levels.append(info)
        print(f"  lod{li}  stride {stride:>2}  {info['points']:>8,} splats  "
              f"{info['bytes'] / 1e6:6.2f} MB  ({info['bytes_per_splat']} B/splat)"
              f"  px/splat {info['px_per_splat']}")
    manifest = {
        "source_ply": os.path.relpath(ply_path, os.path.join(ROOT, "public")),
        "total_splats": total,
        "container": "spz/2 (gzip, 24-bit fixed positions, DC colour only)",
        "fractional_bits": FRACTIONAL_BITS,
        "levels": levels,
    }
    mpath = os.path.join(out_dir, f"{stem}_lods.json")
    with open(mpath, "w") as fh:
        json.dump(manifest, fh, indent=1)
    print(f"  manifest -> {os.path.relpath(mpath, ROOT)}")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="3DGS PLY -> SPZ container + LOD tiers")
    ap.add_argument("--ply", required=True)
    ap.add_argument("--levels", default="1,2,4,8",
                    help="comma-separated strides; level 0 is always stride 1")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "public", "assets", "splats"))
    ap.add_argument("--stem", default=None)
    args = ap.parse_args(argv)

    ply = args.ply if os.path.isabs(args.ply) else os.path.join(ROOT, args.ply)
    stem = args.stem or os.path.splitext(os.path.basename(ply))[0]
    strides = sorted({1} | {int(s) for s in args.levels.split(",") if s.strip()})

    print(f"== SPZ + LOD ==  {os.path.relpath(ply, ROOT)}")
    man = build_levels(ply, args.out_dir, strides, stem)
    rt = [l for l in man["levels"] if "roundtrip" in l]
    bad = [l["level"] for l in rt if l["roundtrip"]["pos_err_mm_max"] > 1.0]
    print(f"  round-trip  {rt[0]['roundtrip']}")
    print(f"  verdict     {'GREEN' if not bad else 'FAIL level(s) ' + str(bad)}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
