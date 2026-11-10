#!/usr/bin/env python3
"""Marble (worldlabs.ai) vs Panodrome VQ 1.1 — SPZ quantitative comparison.

Research artifact for docs/engine-upgrade-v1/marble_reverse_engineering.md
(owner order 2026-11-10: reverse-engineer Marble as a SYSTEM, answer 'what is
usable in our system', push to GitHub; NO engine/production changes).

READ-ONLY towards all existing project files: this script only WRITES
  docs/rd-artifacts/engine-v1/marble_spz_compare.json
Sources:
  Marble samples (public, from docs.worldlabs.ai/marble/export/specs):
    https://wlt-ai-cdn.art/example_exports/warm_traditional_kitchen_interior/
      warm_traditional_kitchen_interior_500k.spz
      warm_traditional_kitchen_interior_2m.spz
  Ours: public/labs/engine-v1/assets/*_splat_v11.spz (+ original gen cabin)

SPZ binary format implemented from the MIT-licensed reference decoder in
sparkjsdev/spark (rust/spark-lib/src/spz.rs @ v2.4.0):
  - v1..v3: whole file is gzip; inside: 16B header
      [0..4]='NGSP' LE, [4..8]=version u32, [8..12]=numSplats u32,
      [12]=shDegree, [13]=fractionalBits, [14]=flags, [15]=reserved
    then payload streams in order: centers(9B/splat i24/2^frac), alphas(1B),
    rgb(3B), scales(3B, exp(b/16-10)), quats(4B v3+), sh(int16)...
  - v4: raw 32B NGSP header at file start (same first 16 + [15]=numStreams,
    [16..20]=tocByteOffset), TOC of numStreams*[compressedSize u64][uncompressed
    u64], each stream ZSTD-compressed, order: centers, alphas, rgb, scales,
    quats, sh, extension, childCounts, childStarts.
  - flags bit 0x80 => alpha stored half-range: opacity = b/255 * 2.0
"""
import gzip
import json
import math
import os
import struct
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAB = os.path.join(REPO, "public/labs/engine-v1/assets")
OUT_JSON = os.path.join(REPO, "docs/rd-artifacts/engine-v1/marble_spz_compare.json")
MARBLE_DIR = "/tmp/marble_samples"
SPZ_MAGIC = 0x5053474E  # "NGSP" LE
SH_C0 = 0.28209479177387814


def _i24_le(b):
    v = b.astype(np.uint32)
    v = v | (v[:, :, 0:1] * 0)  # keep shape
    out = b[:, :, 0].astype(np.int32) | (b[:, :, 1].astype(np.int32) << 8) | (b[:, :, 2].astype(np.int32) << 16)
    # sign-extend 24-bit
    out = np.where(out & 0x800000, out - 0x1000000, out)
    return out


def parse_spz(path):
    raw = open(path, "rb").read()
    head4 = raw[:4]
    if head4[:2] == b"\x1f\x8b":
        data = gzip.decompress(raw)
        fmt = "gzip"
        hdr = data[:16]
        payload = data[16:]
    elif struct.unpack("<I", head4)[0] == SPZ_MAGIC:
        fmt = "ngsp-v4"
        hdr = raw[:32]
        version, num_splats = struct.unpack("<II", hdr[4:12])
        sh_degree, fractional_bits, flags, num_streams = hdr[12], hdr[13], hdr[14], hdr[15]
        toc_off = struct.unpack("<I", hdr[16:20])[0]
        streams = []
        cursor = toc_off + num_streams * 16
        for i in range(num_streams):
            e = toc_off + i * 16
            csize, usize = struct.unpack("<QQ", raw[e:e + 16])
            blob = raw[cursor:cursor + csize]
            cursor += csize
            if csize == 0:
                streams.append(b"")
                continue
            import zstandard
            dctx = zstandard.ZstdDecompressor()
            try:
                streams.append(dctx.decompress(blob, max_output_size=usize if usize else 1 << 30))
            except zstandard.ZstdError:
                dobj = dctx.decompressobj()
                streams.append(dobj.decompress(blob))
        order = ["centers", "alphas", "rgb", "scales", "quats", "sh", "extension", "childCounts", "childStarts"]
        named = {order[i]: s for i, s in enumerate(streams) if i < len(order)}
        centers_b = np.frombuffer(named["centers"], dtype=np.uint8).reshape(-1, 3, 3)
        alphas_b = np.frombuffer(named["alphas"], dtype=np.uint8)
        scales_b = np.frombuffer(named["scales"], dtype=np.uint8).reshape(-1, 3)
        assert len(centers_b) >= num_splats, f"centers {len(centers_b)} < {num_splats}"
        centers = _i24_le(centers_b[:num_splats]).astype(np.float32) / float(1 << fractional_bits)
        op_scale = 2.0 if (flags & 0x80) else 1.0
        alphas = alphas_b[:num_splats].astype(np.float32) / 255.0 * op_scale
        scales = np.exp(scales_b[:num_splats].astype(np.float32) / 16.0 - 10.0)
        return dict(version=version, num_splats=num_splats, sh_degree=sh_degree,
                    fractional_bits=fractional_bits, flags=flags, fmt=fmt,
                    centers=centers, alphas=alphas, scales=scales)
    else:
        raise ValueError(f"{path}: not gzip and not NGSP: {head4!r}")

    magic, version, num_splats = struct.unpack("<III", hdr[:12])
    assert magic == SPZ_MAGIC, f"{path}: bad inner magic"
    sh_degree, fractional_bits, flags = hdr[12], hdr[13], hdr[14]
    n = num_splats
    off = 0
    if version == 1:
        centers = np.frombuffer(payload[off:off + n * 6], dtype="<f2").reshape(-1, 3).astype(np.float32)
        off += n * 6
    else:
        cb = np.frombuffer(payload[off:off + n * 9], dtype=np.uint8).reshape(-1, 3, 3)
        centers = _i24_le(cb).astype(np.float32) / float(1 << fractional_bits)
        off += n * 9
    op_scale = 2.0 if (flags & 0x80) else 1.0
    alphas = np.frombuffer(payload[off:off + n], dtype=np.uint8).astype(np.float32) / 255.0 * op_scale
    off += n
    rgb_bytes = n * 3
    off += rgb_bytes  # skip rgb
    sb = np.frombuffer(payload[off:off + n * 3], dtype=np.uint8).reshape(-1, 3)
    scales = np.exp(sb.astype(np.float32) / 16.0 - 10.0)
    off += n * 3
    return dict(version=version, num_splats=num_splats, sh_degree=sh_degree,
                fractional_bits=fractional_bits, flags=flags, fmt=fmt,
                centers=centers, alphas=alphas, scales=scales)


def pct(x):
    return round(float(x) * 100, 2)


def stats(path, label):
    d = parse_spz(path)
    c, a, s = d["centers"], d["alphas"], d["scales"]
    n = d["num_splats"]
    mn, mx = c.min(axis=0), c.max(axis=0)
    ext = mx - mn
    diag = float(np.linalg.norm(ext))
    # geometric-mean per-splat scale (physical size proxy of each gaussian)
    with np.errstate(divide="ignore"):
        gs = np.exp(np.log(np.maximum(s, 1e-12)).mean(axis=1))
    aniso = s.max(axis=1) / np.maximum(s.min(axis=1), 1e-12)
    file_kb = os.path.getsize(path) / 1024.0
    r = dict(
        label=label, file=os.path.basename(path), format=d["fmt"], spz_version=d["version"],
        sh_degree=d["sh_degree"], fractional_bits=d["fractional_bits"], flags=d["flags"],
        file_kb=round(file_kb, 1), num_splats=n,
        bytes_per_splat=round(file_kb * 1024 / n, 2),
        bbox_extent=[round(float(v), 3) for v in ext], bbox_diag=round(diag, 3),
        scale_median=round(float(np.median(gs)), 5),
        scale_p75=round(float(np.percentile(gs, 75)), 5),
        scale_p90=round(float(np.percentile(gs, 90)), 5),
        scale_p99=round(float(np.percentile(gs, 99)), 5),
        scale_over_diag_median=round(float(np.median(gs)) / diag, 6),
        aniso_median=round(float(np.median(aniso)), 2),
        alpha_median=round(float(np.median(a)), 3),
        alpha_below_01_pct=pct((a < 0.1).mean()),
        alpha_above_09_pct=pct((a > 0.9).mean()),
        splats_per_diag=round(n / diag, 0),
    )
    return r


def main():
    files = []
    m500k = os.path.join(MARBLE_DIR, "warm_traditional_kitchen_interior_500k.spz")
    m2m = os.path.join(MARBLE_DIR, "warm_traditional_kitchen_interior_2m.spz")
    if os.path.exists(m500k):
        files.append((m500k, "MARBLE warm-traditional-kitchen 500k (SPAR-1 export sample)"))
    if os.path.exists(m2m):
        files.append((m2m, "MARBLE warm-traditional-kitchen 2M (SPAR-1 export sample)"))
    for s in ["moradi_main1_splat_v11", "moradi_bed1a_splat_v11", "moradi_kit1_splat_v11"]:
        p = os.path.join(LAB, f"{s}.spz")
        if os.path.exists(p):
            files.append((p, f"OURS {s.replace('_splat_v11','')} (VQ 1.1 DAV2-small unprojection)"))
    p = os.path.join(LAB, "cabin_splat_v11.spz")
    if os.path.exists(p):
        files.append((p, "OURS cabin gen-v11 (VQ 1.1)"))
    p = os.path.join(LAB, "cabin_splat.spz")
    if os.path.exists(p):
        files.append((p, "OURS cabin gen-v1 (VQ 1.0 reference)"))

    rows = []
    for p, label in files:
        try:
            r = stats(p, label)
        except Exception as e:
            r = dict(label=label, file=os.path.basename(p), error=str(e))
        rows.append(r)
        print(json.dumps(r, ensure_ascii=False))

    out = dict(
        test="marble_vs_panodrome_spz_compare",
        when=os.path.basename(__file__),
        date="2026-11-10",
        marble_source="https://docs.worldlabs.ai/marble/export/specs (public example exports)",
        marble_scene="warm_traditional_kitchen_interior (interior, comparable to our Moradi rooms)",
        parser="standalone python SPZ v1-v4 parser written from sparkjsdev/spark rust/spark-lib/src/spz.rs @2.4.0 (MIT)",
        note_units="Marble SPZ raw units are arbitrary (semantics_metadata.metric_scale_factor unknown for public samples); "
                   "scale_over_diag_median normalizes by scene diagonal for unit-free comparison. Ours are meters.",
        rows=rows,
    )
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\nwrote {OUT_JSON}")

    # markdown table for the doc
    cols = ["label", "num_splats", "file_kb", "scale_over_diag_median", "scale_p99",
            "alpha_below_01_pct", "aniso_median", "splats_per_diag", "sh_degree", "spz_version"]
    print("\n| " + " | ".join(cols) + " |")
    print("|" + "---|" * len(cols))
    for r in rows:
        print("| " + " | ".join(str(r.get(c, "?")) for c in cols) + " |")


if __name__ == "__main__":
    main()
