#!/usr/bin/env python3
# ============================================================================
# PANODROME — TRUE-3D LIBRARY (Stage 2.1 "TRUE-WALK EVERYWHERE", owner order
# 2026-11-03).  Shared machinery for skills/build_all_3d_rooms.py:
#   · SEAMLESS procedural PBR palette textures (one tile ~ 1.9 m) exported
#     once to public/assets/true3d/mats/<key>.jpg  — the .glb files carry
#     GEOMETRY ONLY; materials are named "x_<paletteKey>#<kind>" and the
#     runtime (public/js/materials.js) assembles real MeshStandardMaterials
#     from the shared palette.  One palette download, 11 rooms, instant
#     tap-to-switch materials.
#   · parametric mesh builders (box / cylinder / torus / barrel vault / arch)
#     with METRIC UV tiling baked into the geometry.
#   · furniture kit (sofa, bed, chair, table, piano, easel, chandelier,
#     stove, plant, tree, fireplace …) — all real 3D multi-part meshes.
# ============================================================================
import json
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import trimesh

RNG = np.random.default_rng(20261104)
TEX_SZ = 512            # palette texture size (one tile ~ 1.9 m)


# ============================================================ seamless textures
def _jpg(img, name, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, name + ".jpg")
    img.save(p, quality=82)
    return p


def _noise_periodic(img, amp):
    """Tiling noise: blend a shifted copy so the wrap stays continuous."""
    a = np.asarray(img).astype(np.int16)
    h, w = a.shape[:2]
    n = RNG.integers(-amp, amp + 1, a.shape[:2])
    # cross-fade the noise at the tile borders (16 px) -> periodic
    k = 16
    ramp = np.linspace(0, 1, k).reshape(-1, 1)
    n[:k] = (n[:k] * ramp + n[-k:] * (1 - ramp)).astype(np.int16)
    n[:, :k] = (n[:, :k] * ramp.T + n[:, -k:] * (1 - ramp.T)).astype(np.int16)
    for c in range(3):
        a[:, :, c] = np.clip(a[:, :, c] + n, 0, 255)
    return Image.fromarray(a.astype(np.uint8))


def tex_oak(sz=TEX_SZ, planks=6, base=(176, 128, 84), gap=(64, 44, 28)):
    """Vertical oak planks, seamless top/bottom (forced plank breaks at y=0)."""
    pw = sz // planks
    a = np.zeros((sz, sz, 3), np.uint8)
    for p in range(planks):
        tone = int(RNG.integers(-14, 14))
        b = np.clip(np.array(base) + tone, 0, 255)
        col = np.tile(b, (sz, pw, 1)).astype(np.float32)
        yy = np.arange(sz).reshape(-1, 1)
        col += (np.sin(yy / 3.1 + RNG.uniform(0, 6.28)) * 5).reshape(sz, 1, 1)
        col += (np.linspace(-1, 1, pw).reshape(1, -1, 1) * 6)
        ky = int(RNG.integers(90, sz - 90))
        col -= np.exp(-((np.arange(sz) - ky) / 26.0) ** 2).reshape(-1, 1, 1) * 16
        a[:, p * pw:(p + 1) * pw] = np.clip(col, 0, 255).astype(np.uint8)
    img = Image.fromarray(a)
    d = ImageDraw.Draw(img)
    for p in range(planks):
        d.line([(p * pw, 0), (p * pw, sz)], fill=gap, width=3)      # plank seams (wrap OK)
    for p in range(planks):                                          # forced end-breaks incl. y=0
        d.line([(p * pw, 0), ((p + 1) * pw, 0)], fill=gap, width=2)
        for _ in range(2):
            y = int(RNG.integers(70, sz - 70))
            d.line([(p * pw, y), ((p + 1) * pw, y)], fill=gap, width=2)
    return _noise_periodic(img, 5)


def tex_herringbone(sz=TEX_SZ):
    """Herringbone oak parquet — 45° chevrons, period = full tile."""
    img = Image.new("RGB", (sz, sz), (150, 108, 66))
    d = ImageDraw.Draw(img)
    L = sz / 4.0                     # plank length in px (4 planks per tile)
    Wd = L / 4.0                     # plank width
    # draw 45° planks in both directions; pattern repeats each sz/2
    def plank(cx, cy, ang, tone):
        ca, sa = np.cos(ang), np.sin(ang)
        pts = []
        for (ux, uy) in ((-L / 2, -Wd / 2), (L / 2, -Wd / 2), (L / 2, Wd / 2), (-L / 2, Wd / 2)):
            pts.append((cx + ux * ca - uy * sa, cy + ux * sa + uy * ca))
        d.polygon(pts, fill=tone)
        d.line(pts + [pts[0]], fill=(96, 66, 40), width=2)
    tone_a = (176, 128, 82)
    tone_b = (166, 118, 74)
    step = L
    for gy in range(-2, int(sz / step) + 3):
        for gx in range(-2, int(sz / step) + 3):
            cx = gx * step + (gy % 2) * step / 2
            cy = gy * step / 2
            plank(cx, cy, np.pi / 4, tone_a if (gx + gy) % 2 == 0 else tone_b)
            plank(cx + step / 2, cy + step / 2, -np.pi / 4, tone_b if (gx + gy) % 2 == 0 else tone_a)
    img = img.filter(ImageFilter.GaussianBlur(0.4))
    return _noise_periodic(img, 5)


def tex_marble(sz=TEX_SZ, base=(236, 232, 224), vein=(168, 148, 96), wavy=True):
    """White marble with gold veins — periodic sin curves (tile-safe)."""
    a = np.tile(np.array(base, np.uint8), (sz, sz, 1))
    img = Image.fromarray(a)
    d = ImageDraw.Draw(img)
    for v in range(7):
        y0 = int(RNG.integers(0, sz))
        pts = [(x, (y0 + 22 * np.sin(2 * np.pi * (x / sz) * (1 + v % 3) + v * 1.7)) % sz)
               for x in range(0, sz + 1, 6)]
        tone = tuple(np.clip(np.array(vein) + int(RNG.integers(-24, 18)), 0, 255))
        d.line(pts, fill=tone, width=int(RNG.integers(2, 5)))
    for _ in range(140):              # faint secondary threads
        x, y = RNG.integers(0, sz, 2)
        d.line([(x, y), (x + int(RNG.integers(-30, 30)), y + int(RNG.integers(-14, 14)))],
               fill=tuple(np.clip(np.array(vein) + 26, 0, 255)), width=1)
    img = img.filter(ImageFilter.GaussianBlur(0.7))
    return _noise_periodic(img, 3)


def tex_travertine(sz=TEX_SZ):
    a = np.tile(np.array((214, 199, 178), np.uint8), (sz, sz, 1))
    img = Image.fromarray(a)
    d = ImageDraw.Draw(img)
    for v in range(9):
        y0 = int(RNG.integers(10, sz - 10))
        pts = [(x, y0 + int(9 * np.sin(2 * np.pi * x / sz * (1 + v) + v * 1.7))) for x in range(0, sz + 1, 8)]
        d.line(pts, fill=(196 + int(RNG.integers(-14, 8)), 180 + int(RNG.integers(-14, 8)), 158), width=int(RNG.integers(2, 5)))
    for _ in range(240):
        x, y = RNG.integers(0, sz, 2)
        r = int(RNG.integers(1, 3))
        d.ellipse([x, y, x + r, y + r], fill=(168, 152, 132))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    return _noise_periodic(img, 5)


def tex_microcement(sz=TEX_SZ):
    a = np.tile(np.array((188, 186, 182), np.uint8), (sz, sz, 1))
    img = Image.fromarray(a)
    img = img.filter(ImageFilter.GaussianBlur(6))
    blotch = Image.new("L", (sz, sz), 128)
    db = ImageDraw.Draw(blotch)
    for _ in range(22):
        x, y = RNG.integers(0, sz, 2)
        r = int(RNG.integers(40, 150))
        db.ellipse([x - r, y - r, x + r, y + r], fill=int(RNG.integers(112, 146)))
    blotch = blotch.filter(ImageFilter.GaussianBlur(30))
    b = np.asarray(blotch).astype(np.int16) - 128
    # mirror-blend the blotch so it wraps
    b = (b + np.roll(b, sz // 2, axis=0)[:, ::-1]) // 2
    arr = np.asarray(img).astype(np.int16) + (b.reshape(sz, sz, 1) * 12 // 128)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    return _noise_periodic(img, 4)


def tex_brick(sz=TEX_SZ, base=(156, 92, 70), mortar=(176, 168, 156), rows=8):
    img = Image.new("RGB", (sz, sz), mortar)
    d = ImageDraw.Draw(img)
    rh = sz / rows
    bw = sz / 4.0
    for r in range(rows):
        off = (r % 2) * bw / 2
        for b in range(-1, 5):
            x0 = b * bw + off + 3
            tone = np.clip(np.array(base) + int(RNG.integers(-16, 16)), 0, 255)
            d.rectangle([x0, r * rh + 3, x0 + bw - 6, (r + 1) * rh - 3], fill=tuple(tone))
    img = img.filter(ImageFilter.GaussianBlur(0.5))
    return _noise_periodic(img, 6)


def tex_stonefloor(sz=TEX_SZ):
    """Large flagstone tiles with grout — 2x2 slabs per tile."""
    img = Image.new("RGB", (sz, sz), (150, 146, 138))
    d = ImageDraw.Draw(img)
    half = sz // 2
    for (x0, y0) in ((0, 0), (half, 0), (0, half), (half, half)):
        tone = int(RNG.integers(-12, 12))
        c = np.clip(np.array((158, 153, 142)) + tone, 0, 255)
        d.rectangle([x0 + 4, y0 + 4, x0 + half - 4, y0 + half - 4], fill=tuple(c))
        for _ in range(26):
            x, y = RNG.integers(x0 + 8, x0 + half - 8, 2)
            r = int(RNG.integers(1, 4))
            d.point((x, y), fill=tuple(np.clip(c - 18, 0, 255)))
            d.ellipse([x, y, x + r, y + r], outline=tuple(np.clip(c - 26, 0, 255)))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    return _noise_periodic(img, 5)


def tex_tiles_stove(sz=TEX_SZ):
    """White ceramic stove tiles with blue cornflower motifs (Kachelofen)."""
    img = Image.new("RGB", (sz, sz), (238, 234, 226))
    d = ImageDraw.Draw(img)
    n = 8
    t = sz / n
    for r in range(n):
        for c in range(n):
            d.rectangle([c * t + 2, r * t + 2, (c + 1) * t - 2, (r + 1) * t - 2], fill=(232, 228, 218))
            if (r * c) % 3 == 0:
                cx, cy = (c + 0.5) * t, (r + 0.5) * t
                for k in range(5):
                    a0 = k * 2 * np.pi / 5
                    px, py = cx + 0.26 * t * np.cos(a0), cy + 0.26 * t * np.sin(a0)
                    d.ellipse([px - 3, py - 3, px + 3, py + 3], fill=(66, 96, 148))
                d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(90, 122, 172))
    return _noise_periodic(img, 3)


def tex_terrazzo(sz=TEX_SZ):
    """Terrazzo granite — cream base, marble chips."""
    img = Image.new("RGB", (sz, sz), (226, 220, 210))
    d = ImageDraw.Draw(img)
    chips = ((238, 234, 228), (196, 188, 176), (150, 146, 140), (128, 118, 108), (168, 120, 92))
    for _ in range(420):
        x, y = RNG.integers(0, sz, 2)
        r = int(RNG.integers(2, 7))
        d.ellipse([x, y, x + r, y + r], fill=chips[int(RNG.integers(0, len(chips)))])
    img = img.filter(ImageFilter.GaussianBlur(0.4))
    return _noise_periodic(img, 3)


def tex_velvet(sz=TEX_SZ, base=(44, 84, 56)):
    """Green tufted velvet — diamond stitching."""
    a = np.tile(np.array(base, np.uint8), (sz, sz, 1))
    img = Image.fromarray(a)
    d = ImageDraw.Draw(img)
    n = 8
    t = sz / n
    for r in range(n):
        for c in range(n):
            cx, cy = (c + 0.5) * t, (r + 0.5) * t
            d.ellipse([cx - t * 0.33, cy - t * 0.33, cx + t * 0.33, cy + t * 0.33],
                      fill=tuple(np.clip(np.array(base) + 16, 0, 255)))
    # diamond seams
    for r in range(-1, n + 1):
        for c in range(-1, n + 1):
            x0, y0 = c * t, r * t
            d.line([(x0, y0), (x0 + t, y0 + t)], fill=tuple(np.clip(np.array(base) - 26, 0, 255)), width=3)
            d.line([(x0 + t, y0), (x0, y0 + t)], fill=tuple(np.clip(np.array(base) - 26, 0, 255)), width=3)
    img = img.filter(ImageFilter.GaussianBlur(0.7))
    return _noise_periodic(img, 4)


def tex_boucle(sz=TEX_SZ, base=(225, 217, 202)):
    a = np.tile(np.array(base, np.uint8), (sz, sz, 1))
    img = Image.fromarray(a)
    d = ImageDraw.Draw(img)
    for _ in range(5200):
        x, y = RNG.integers(0, sz, 2)
        r = int(RNG.integers(1, 3))
        tone = int(RNG.integers(-16, 16))
        c = tuple(np.clip(np.array(base) + tone, 0, 255))
        d.ellipse([x, y, x + r, y + r], fill=c)
    img = img.filter(ImageFilter.GaussianBlur(0.5))
    return _noise_periodic(img, 4)


def tex_duvet(sz=TEX_SZ):
    """White quilted duvet — soft square quilting."""
    img = Image.new("RGB", (sz, sz), (240, 238, 232))
    d = ImageDraw.Draw(img)
    n = 6
    t = sz / n
    for r in range(n):
        for c in range(n):
            d.rectangle([c * t + 4, r * t + 4, (c + 1) * t - 4, (r + 1) * t - 4], fill=(236, 233, 226))
            d.ellipse([(c + 0.28) * t, (r + 0.28) * t, (c + 0.72) * t, (r + 0.72) * t], fill=(243, 241, 236))
            d.line([(c + 0.08) * t, (r + 0.08) * t, (c + 0.92) * t, (r + 0.92) * t], fill=(224, 220, 212), width=2)
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    return _noise_periodic(img, 3)


def tex_fabric_ochre(sz=TEX_SZ):
    a = np.tile(np.array((188, 148, 96), np.uint8), (sz, sz, 1))
    img = Image.fromarray(a)
    d = ImageDraw.Draw(img)
    for i in range(0, sz, 8):
        d.line([(i, 0), (i, sz)], fill=(176, 136, 86), width=2)
        d.line([(0, i), (sz, i)], fill=(196, 156, 104), width=2)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    return _noise_periodic(img, 6)


def tex_curtain(sz=TEX_SZ):
    """Linen curtain folds — vertical soft stripes (wrap by sin)."""
    a = np.zeros((sz, sz, 3), np.uint8)
    for x in range(sz):
        s = np.sin(2 * np.pi * x / (sz / 6.0))
        v = 226 + int(s * 14)
        a[x, :, :] = (v, v - 6, v - 16)
    img = Image.fromarray(a)
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    return _noise_periodic(img, 3)


def tex_rug_villa(sz=TEX_SZ):
    img = Image.new("RGB", (sz, sz), (208, 198, 184))
    d = ImageDraw.Draw(img)
    m = 60
    d.rectangle([m, m, sz - m, sz - m], outline=(178, 165, 148), width=10)
    d.rectangle([m + 26, m + 26, sz - m - 26, sz - m - 26], outline=(186, 172, 152), width=4)
    return _noise_periodic(img, 7)


def tex_rug_classic(sz=TEX_SZ):
    """Ornate medallion rug (anniversary lounge)."""
    img = Image.new("RGB", (sz, sz), (122, 44, 38))
    d = ImageDraw.Draw(img)
    d.rectangle([14, 14, sz - 14, sz - 14], outline=(198, 164, 92), width=8)
    d.rectangle([30, 30, sz - 30, sz - 30], outline=(232, 214, 168), width=3)
    cx = cy = sz // 2
    for r in (sz // 5, sz // 6, sz // 9):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(226, 196, 128), width=5)
    d.ellipse([cx - sz // 14, cy - sz // 14, cx + sz // 14, cy + sz // 14], fill=(198, 164, 92))
    for k in range(12):
        a0 = k * 2 * np.pi / 12
        x, y = cx + sz * 0.31 * np.cos(a0), cy + sz * 0.31 * np.sin(a0)
        d.ellipse([x - 8, y - 8, x + 8, y + 8], fill=(226, 196, 128))
    d.rectangle([40, 40, sz - 40, 66], fill=(142, 58, 48))
    d.rectangle([40, sz - 66, sz - 40, sz - 40], fill=(142, 58, 48))
    return _noise_periodic(img, 6)


def tex_grass(sz=TEX_SZ):
    a = np.tile(np.array((96, 128, 66), np.uint8), (sz, sz, 1))
    img = Image.fromarray(a)
    d = ImageDraw.Draw(img)
    for _ in range(3800):
        x, y = RNG.integers(0, sz, 2)
        tone = int(RNG.integers(-26, 26))
        c = tuple(np.clip(np.array((104, 138, 70)) + tone, 0, 255))
        d.line([(x, y), (x + int(RNG.integers(-2, 3)), y - int(RNG.integers(2, 6)))], fill=c)
    img = img.filter(ImageFilter.GaussianBlur(0.4))
    return _noise_periodic(img, 6)


def tex_gravel(sz=TEX_SZ):
    img = Image.new("RGB", (sz, sz), (172, 166, 156))
    d = ImageDraw.Draw(img)
    for _ in range(2600):
        x, y = RNG.integers(0, sz, 2)
        r = int(RNG.integers(1, 4))
        tone = int(RNG.integers(-22, 22))
        c = tuple(np.clip(np.array((178, 172, 162)) + tone, 0, 255))
        d.ellipse([x, y, x + r, y + r], fill=c)
    img = img.filter(ImageFilter.GaussianBlur(0.4))
    return _noise_periodic(img, 5)


def tex_hedge(sz=TEX_SZ):
    a = np.tile(np.array((58, 92, 46), np.uint8), (sz, sz, 1))
    img = Image.fromarray(a)
    d = ImageDraw.Draw(img)
    for _ in range(4200):
        x, y = RNG.integers(0, sz, 2)
        r = int(RNG.integers(2, 6))
        tone = int(RNG.integers(-22, 26))
        c = tuple(np.clip(np.array((70, 108, 54)) + tone, 0, 255))
        d.ellipse([x, y, x + r, y + r], fill=c)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    return _noise_periodic(img, 5)


def tex_foliage(sz=TEX_SZ):
    img = Image.new("RGB", (sz, sz), (52, 88, 42))
    d = ImageDraw.Draw(img)
    for _ in range(700):
        x, y = RNG.integers(0, sz, 2)
        r = int(RNG.integers(6, 22))
        tone = int(RNG.integers(-20, 30))
        c = tuple(np.clip(np.array((66, 106, 50)) + tone, 0, 255))
        d.ellipse([x, y, x + r, y + r], fill=c)
    img = img.filter(ImageFilter.GaussianBlur(1.0))
    return _noise_periodic(img, 6)


def tex_art_field(sz=640):
    img = Image.new("RGB", (sz, int(sz * 1.28)), (222, 202, 164))
    d = ImageDraw.Draw(img)
    W, H = img.size
    d.rectangle([int(W * 0.12), int(H * 0.10), int(W * 0.88), int(H * 0.50)], fill=(122, 58, 44))
    d.rectangle([int(W * 0.12), int(H * 0.56), int(W * 0.88), int(H * 0.88)], fill=(84, 70, 58))
    d.rectangle([int(W * 0.46), int(H * 0.10), int(W * 0.52), int(H * 0.88)], fill=(238, 228, 206))
    return img


def tex_art_line(sz=640):
    img = Image.new("RGB", (sz, int(sz * 1.28)), (236, 233, 226))
    d = ImageDraw.Draw(img)
    W, H = img.size
    for i, r in enumerate((int(W * 0.30), int(W * 0.42), int(W * 0.54))):
        box = [W // 2 - r, int(H * 0.16), W // 2 + r, int(H * 0.16) + 2 * r]
        d.arc(box, start=200 + i * 12, end=340 - i * 10, fill=(52, 48, 44), width=8 - i)
    d.ellipse([int(W * 0.62), int(H * 0.66), int(W * 0.62) + int(W * 0.2), int(H * 0.66) + int(W * 0.2)], fill=(176, 141, 84))
    d.line([(int(W * 0.18), int(H * 0.84)), (int(W * 0.58), int(H * 0.84))], fill=(52, 48, 44), width=6)
    return img


def tex_art_landscape(sz=640):
    """Impressionist forest light (art studio easel + cabin wall)."""
    W, H = sz, int(sz * 0.72)
    img = Image.new("RGB", (W, H), (214, 206, 180))
    d = ImageDraw.Draw(img)
    d.rectangle([0, int(H * 0.62), W, H], fill=(96, 116, 74))
    for i in range(9):
        x = int(i * W / 9 + RNG.integers(-12, 12))
        wdt = int(RNG.integers(14, 30))
        d.rectangle([x, int(H * 0.16), x + wdt, int(H * 0.66)], fill=(66 + i * 3, 52 + i * 2, 40))
    for k in range(6):
        x0, y0 = RNG.integers(0, W, 2)
        d.ellipse([x0, y0, x0 + 60, y0 + 44], fill=(238, 226, 178))
    img = img.filter(ImageFilter.GaussianBlur(1.6))
    return img


def tex_art_classic1(sz=480):
    """Gilded classical portrait block."""
    W, H = sz, int(sz * 1.25)
    img = Image.new("RGB", (W, H), (44, 36, 48))
    d = ImageDraw.Draw(img)
    d.ellipse([W * 0.28, H * 0.16, W * 0.72, H * 0.42], fill=(198, 160, 128))      # face
    d.rectangle([W * 0.22, H * 0.42, W * 0.78, H * 0.78], fill=(72, 58, 66))      # coat
    d.rectangle([W * 0.34, H * 0.34, W * 0.42, H * 0.46], fill=(30, 24, 28))
    d.rectangle([W * 0.58, H * 0.34, W * 0.66, H * 0.46], fill=(30, 24, 28))
    d.ellipse([W * 0.40, H * 0.24, W * 0.46, H * 0.30], fill=(24, 18, 22))
    d.ellipse([W * 0.54, H * 0.24, W * 0.60, H * 0.30], fill=(24, 18, 22))
    d.rectangle([W * 0.44, H * 0.30, W * 0.56, H * 0.33], fill=(120, 84, 70))
    return img


def tex_art_classic2(sz=480):
    """Classical landscape with ruin + sky."""
    W, H = sz, int(sz * 0.74)
    img = Image.new("RGB", (W, H), (206, 200, 178))
    d = ImageDraw.Draw(img)
    d.rectangle([0, int(H * 0.58), W, H], fill=(104, 116, 84))
    d.rectangle([int(W * 0.58), int(H * 0.30), int(W * 0.70), int(H * 0.60)], fill=(150, 140, 120))   # ruin
    d.rectangle([int(W * 0.60), int(H * 0.24), int(W * 0.63), int(H * 0.60)], fill=(150, 140, 120))
    d.ellipse([int(W * 0.12), int(H * 0.10), int(W * 0.34), int(H * 0.26)], fill=(232, 224, 196))     # cloud
    d.ellipse([int(W * 0.70), int(H * 0.08), int(W * 0.92), int(H * 0.22)], fill=(238, 230, 202))
    return img


def tex_plaster(sz=TEX_SZ, base=(233, 229, 221)):
    a = np.tile(np.array(base, np.uint8), (sz, sz, 1))
    img = Image.fromarray(a)
    blotch = Image.new("L", (sz, sz), 128)
    db = ImageDraw.Draw(blotch)
    for _ in range(26):
        x, y = RNG.integers(0, sz, 2)
        r = int(RNG.integers(30, 120))
        db.ellipse([x - r, y - r, x + r, y + r], fill=int(RNG.integers(112, 144)))
    blotch = blotch.filter(ImageFilter.GaussianBlur(26))
    b = np.asarray(blotch).astype(np.int16) - 128
    b = (b + np.roll(b, sz // 2, axis=0)[:, ::-1]) // 2      # periodic wrap
    arr = np.asarray(img).astype(np.int16) + (b.reshape(sz, sz, 1) * 14 // 128)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    return _noise_periodic(img, 4)


# palette definition — key → (texture fn | None, rough, metal, alpha, emissive)
PALETTE_DEF = {
    # floors / woods
    "oak":           (lambda: tex_oak(), 0.42, 0.0, None, None),
    "herringbone":   (lambda: tex_herringbone(), 0.4, 0.0, None, None),
    "parquet_dark":  (lambda: tex_oak(base=(120, 78, 48), gap=(52, 34, 22)), 0.4, 0.0, None, None),
    "timber":        (lambda: tex_oak(base=(128, 92, 60), planks=7, gap=(46, 32, 20)), 0.62, 0.0, None, None),
    "walnut":        (lambda: tex_oak(base=(102, 70, 44), planks=5, gap=(44, 30, 18)), 0.5, 0.0, None, None),
    # stones
    "calacatta":     (lambda: tex_marble(base=(238, 234, 226), vein=(176, 148, 84)), 0.28, 0.0, None, None),
    "marble_black":  (lambda: tex_marble(base=(28, 28, 30), vein=(140, 136, 128), ), 0.22, 0.05, None, None),
    "travertine":    (lambda: tex_travertine(), 0.55, 0.0, None, None),
    "microcement":   (lambda: tex_microcement(), 0.72, 0.0, None, None),
    "stonefloor":    (lambda: tex_stonefloor(), 0.66, 0.0, None, None),
    "terrazzo":      (lambda: tex_terrazzo(), 0.34, 0.0, None, None),
    "brick":         (lambda: tex_brick(), 0.85, 0.0, None, None),
    "tiles_stove":   (lambda: tex_tiles_stove(), 0.25, 0.0, None, None),
    # plasters / paint
    "plaster":       (lambda: tex_plaster(), 0.92, 0.0, None, None),
    "plaster_warm":  (lambda: tex_plaster(base=(236, 226, 208)), 0.92, 0.0, None, None),
    "cream_gold":    (lambda: tex_plaster(base=(238, 228, 200)), 0.55, 0.15, None, None),
    # fabrics
    "velvet_green":  (lambda: tex_velvet(), 0.95, 0.0, None, None),
    "boucle":        (lambda: tex_boucle(), 0.96, 0.0, None, None),
    "boucleL":       (lambda: tex_boucle(base=(233, 226, 212)), 0.96, 0.0, None, None),
    "duvet":         (lambda: tex_duvet(), 0.96, 0.0, None, None),
    "fabric_ochre":  (lambda: tex_fabric_ochre(), 0.94, 0.0, None, None),
    "curtain":       (lambda: tex_curtain(), 0.9, 0.0, None, None),
    # rugs / nature
    "rug_villa":     (lambda: tex_rug_villa(), 0.98, 0.0, None, None),
    "rug_classic":   (lambda: tex_rug_classic(), 0.98, 0.0, None, None),
    "grass":         (lambda: tex_grass(), 0.95, 0.0, None, None),
    "gravel":        (lambda: tex_gravel(), 0.9, 0.0, None, None),
    "hedge":         (lambda: tex_hedge(), 0.98, 0.0, None, None),
    "foliage":       (lambda: tex_foliage(), 0.95, 0.0, None, None),
    # art
    "art_field":     (lambda: tex_art_field(), 0.9, 0.0, None, None),
    "art_line":      (lambda: tex_art_line(), 0.9, 0.0, None, None),
    "art_landscape": (lambda: tex_art_landscape(), 0.9, 0.0, None, None),
    "art_classic1":  (lambda: tex_art_classic1(), 0.9, 0.0, None, None),
    "art_classic2":  (lambda: tex_art_classic2(), 0.9, 0.0, None, None),
    # colour-only
    "white_paint":   (None, 0.6, 0.0, None, None),
    "brass":         (None, 0.28, 0.95, None, None),
    "black_gloss":   (None, 0.18, 0.4, None, None),
    "iron_dark":     (None, 0.42, 0.8, None, None),
    "mirror":        (None, 0.05, 1.0, None, None),
    "glass":         (None, 0.06, 0.1, 0.16, None),
    "lamp_glow":     (None, 0.5, 0.0, None, (1.0, 0.82, 0.55)),
}
PALETTE_COLORS = {
    "white_paint": (0.93, 0.91, 0.88),
    "brass": (0.78, 0.60, 0.38),
    "black_gloss": (0.05, 0.05, 0.06),
    "iron_dark": (0.16, 0.16, 0.17),
    "mirror": (0.82, 0.86, 0.9),
    "glass": (0.78, 0.86, 0.92),
    "lamp_glow": (1.0, 0.98, 0.9),
}


PALETTE_NAMES = {
    "oak":           ("Light Oak", "بلوط روشن"),
    "herringbone":   ("Herringbone Oak", "پارکت جناغی بلوط"),
    "parquet_dark":  ("Walnut Parquet", "پارکت گردویی"),
    "timber":        ("Cabin Timber", "چوب کابین"),
    "walnut":        ("Walnut Wood", "چوب گردویی"),
    "calacatta":     ("Calacatta Gold Marble", "مرمر سفید رگه‌طلایی (کالاکاتا)"),
    "marble_black":  ("Black Marble", "مرمر مشکی"),
    "travertine":    ("Travertine", "سنگ تراورتن"),
    "microcement":   ("Microcement", "بتن اکسپوز (میکروسمنت)"),
    "stonefloor":    ("Old Flagstone", "سنگ کف قدیمی"),
    "terrazzo":      ("Terrazzo Granite", "ترازو گرانیت"),
    "brick":         ("Old Brick", "آجر کهنه"),
    "tiles_stove":   ("Ceramic Stove Tiles", "کاشی سفالی اجاق"),
    "plaster":       ("Plaster", "گچ"),
    "plaster_warm":  ("Warm Cream Plaster", "گچ کرم گرم"),
    "cream_gold":    ("Cream & Gold Molding", "کرم‌طلایی کلاسیک"),
    "velvet_green":  ("Green Velvet", "مخمل سبز"),
    "boucle":        ("Cream Bouclé", "بوفهٔ کرم"),
    "boucleL":       ("Light Bouclé", "بوفهٔ روشن"),
    "duvet":         ("White Duvet", "پتوی سفید"),
    "fabric_ochre":  ("Ochre Weave", "پارچهٔ اخرایی"),
    "curtain":       ("Linen Curtain", "پردهٔ کتانی"),
    "rug_villa":     ("Minimal Rug", "فرش مینیمال"),
    "rug_classic":   ("Classic Medallion Rug", "فرش کلاسیک مدالیون"),
    "grass":         ("Lawn", "چمن"),
    "gravel":        ("Gravel", "شن آهاری"),
    "hedge":         ("Hedge", "بوتهٔ چمنی"),
    "foliage":       ("Foliage", "برگ سبز"),
    "art_field":     ("Colour-field Painting", "نقاشی زمینهٔ رنگی"),
    "art_line":      ("Line Study", "طرح خطی"),
    "art_landscape": ("Forest Light", "نور جنگل"),
    "art_classic1":  ("Classical Portrait", "پرترهٔ کلاسیک"),
    "art_classic2":  ("Classical Landscape", "منظرهٔ کلاسیک"),
    "white_paint":   ("White Paint", "رنگ سفید"),
    "brass":         ("Brass", "برنج"),
    "black_gloss":   ("Black Gloss", "مشکی براق"),
    "iron_dark":     ("Dark Iron", "آهن تیره"),
    "mirror":        ("Mirror", "آینه"),
    "glass":         ("Glass", "شیشه"),
    "lamp_glow":     ("Warm Glow", "نور گرم"),
}


def export_palette(out_dir):
    """Write mats/*.jpg + palette.json manifest for the runtime."""
    manifest = {}
    for key, (fn, rough, metal, alpha, emissive) in PALETTE_DEF.items():
        entry = {"rough": rough, "metal": metal}
        nm = PALETTE_NAMES.get(key)
        if nm:
            entry["name"] = {"en": nm[0], "fa": nm[1]}
        if fn is not None:
            path = _jpg(fn(), key, out_dir)
            entry["map"] = "mats/" + key + ".jpg"
        else:
            entry["color"] = list(PALETTE_COLORS.get(key, (0.8, 0.8, 0.8)))
        if alpha is not None:
            entry["alpha"] = alpha
        if emissive is not None:
            entry["emissive"] = list(emissive)
            entry["emissiveIntensity"] = 1.35
        manifest[key] = entry
    mpath = os.path.join(out_dir, "palette.json")
    with open(mpath, "w") as f:
        json.dump(manifest, f, indent=1)
    return manifest


# ============================================================ geometry builders
def mat(key, kind=""):
    """Palette-bound trimesh material — the runtime resolves it by NAME."""
    from trimesh.visual.material import PBRMaterial
    name = "x_" + key + ("#" + kind if kind else "")
    try:
        return PBRMaterial(name=name, metallicFactor=0.0, roughnessFactor=0.8)
    except TypeError:
        return PBRMaterial(name=name)


def textured_box(extents, m, uv=(1.0, 1.0), center=(0, 0, 0)):
    ex, ey, ez = extents
    cx, cy, cz = center
    hx, hy, hz = ex / 2, ey / 2, ez / 2
    faces = [
        ((0, 0, 1), [(-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)], (ex, ey)),
        ((0, 0, -1), [(hx, -hy, -hz), (-hx, -hy, -hz), (-hx, hy, -hz), (hx, hy, -hz)], (ex, ey)),
        ((1, 0, 0), [(hx, -hy, hz), (hx, -hy, -hz), (hx, hy, -hz), (hx, hy, hz)], (ez, ey)),
        ((-1, 0, 0), [(-hx, -hy, -hz), (-hx, -hy, hz), (-hx, hy, hz), (-hx, hy, -hz)], (ez, ey)),
        ((0, 1, 0), [(-hx, hy, hz), (hx, hy, hz), (hx, hy, -hz), (-hx, hy, -hz)], (ex, ez)),
        ((0, -1, 0), [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz), (-hx, -hy, hz)], (ex, ez)),
    ]
    verts, uvs, fidx = [], [], []
    vi = 0
    for _, corners, (ue, ve) in faces:
        for c in corners:
            verts.append((c[0] + cx, c[1] + cy, c[2] + cz))
        ur, vr = uv
        uvs += [(0, 0), (ur, 0), (ur, vr), (0, vr)]
        fidx += [(vi, vi + 1, vi + 2), (vi, vi + 2, vi + 3)]
        vi += 4
    m2 = trimesh.Trimesh(vertices=np.array(verts, float), faces=np.array(fidx), process=False)
    m2.visual = trimesh.visual.TextureVisuals(uv=np.array(uvs, float), material=m)
    return m2


def _box_uv(scale=1.9):
    """Metric UV helper: one palette tile per ~1.9 m."""
    return scale / 1.9


def mbox(extents, key, center=(0, 0, 0), kind="furn", tile=True, name_hint=""):
    """Metric-tiled palette box."""
    ex, ey, ez = extents
    ur = max(ex, ez) / 1.9 if tile else 1.0
    vr = ey / 1.9 if tile else 1.0
    return textured_box(extents, mat(key, kind), uv=(ur, vr), center=center)


def textured_cylinder(radius, height, m, uv=(1.0, 1.0), center=(0, 0, 0), sections=28, r2=None, caps=True):
    r2 = radius if r2 is None else r2
    cx, cy, cz = center
    ang = np.linspace(0, 2 * np.pi, sections + 1)
    verts, uvs, fidx = [], [], []
    ur, vr = uv
    for t in ang:
        f = t / (2 * np.pi)
        verts.append((cx + np.cos(t) * radius, cy, cz + np.sin(t) * radius))
        uvs.append((f * ur, 0))
        verts.append((cx + np.cos(t) * r2, cy + height, cz + np.sin(t) * r2))
        uvs.append((f * ur, vr))
    for i in range(sections):
        a, b = 2 * i, 2 * i + 1
        c, d = 2 * (i + 1), 2 * (i + 1) + 1
        fidx += [(a, c, b), (b, c, d)]
    if caps:
        ci_b = len(verts)
        verts.append((cx, cy, cz)); uvs.append((0.5, 0.5))
        ci_t = len(verts)
        verts.append((cx, cy + height, cz)); uvs.append((0.5, 0.5))
        for i in range(sections):
            a, b = 2 * i, 2 * (i + 1)
            fidx += [(ci_b, a, b)]
            fidx += [(ci_t, 2 * i + 1, 2 * (i + 1) + 1)]
    m2 = trimesh.Trimesh(vertices=np.array(verts, float), faces=np.array(fidx, int), process=False)
    if not m2.is_winding_consistent:
        m2.invert()
    m2.visual = trimesh.visual.TextureVisuals(uv=np.array(uvs, float), material=m)
    return m2


def mcyl(radius, height, key, center=(0, 0, 0), kind="furn", r2=None, caps=True, sections=24, tile=True):
    ur = (2 * np.pi * max(radius, r2 if r2 else 0)) / 1.9 if tile else 1.0
    vr = height / 1.9 if tile else 1.0
    return textured_cylinder(radius, height, mat(key, kind), uv=(ur, vr), center=center,
                             sections=sections, r2=r2, caps=caps)


def torus(R, r, m, uv=(8, 2), center=(0, 0, 0), maj=48, mino=16, axis="z"):
    ang_m = np.linspace(0, 2 * np.pi, maj + 1)
    ang_n = np.linspace(0, 2 * np.pi, mino + 1)
    verts, uvs, fidx = [], [], []
    ur, vr = uv
    for i, a in enumerate(ang_m):
        ca, sa = np.cos(a), np.sin(a)
        for j, b in enumerate(ang_n):
            cb, sb = np.cos(b), np.sin(b)
            x = (R + r * cb) * ca
            y = r * sb
            z = (R + r * cb) * sa
            verts.append((x, y, z))
            uvs.append((i / maj * ur, j / mino * vr))
    for i in range(maj):
        for j in range(mino):
            a = i * (mino + 1) + j
            b = a + (mino + 1)
            fidx += [(a, b, a + 1), (a + 1, b, b + 1)]
    m2 = trimesh.Trimesh(vertices=np.array(verts, float), faces=np.array(fidx, int), process=False)
    if axis == "x":
        m2.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    m2.apply_translation(center)
    m2.visual = trimesh.visual.TextureVisuals(uv=np.array(uvs, float), material=m)
    return m2


def mtorus(R, r, key, center=(0, 0, 0), kind="furn", axis="z"):
    return torus(R, r, mat(key, kind), center=center, axis=axis)


def barrel_vault(radius, length, key, kind="ceiling", center=(0, 0, 0), sections=26, z_slices=14):
    """Horizontal half-cylinder vault (crown along z), open at the bottom."""
    cx, cy, cz = center
    angs = np.linspace(0, np.pi, sections + 1)          # 0..π (above y=cy)
    zs = np.linspace(-length / 2, length / 2, z_slices + 1)
    verts, uvs, fidx = [], [], []
    for i, a in enumerate(angs):
        x = np.cos(a) * radius
        y = np.sin(a) * radius
        for j, z in enumerate(zs):
            verts.append((cx + x, cy + y, cz + z))
            uvs.append((i / sections * (np.pi * radius / 1.9), j / z_slices * (length / 1.9)))
    for i in range(sections):
        for j in range(z_slices):
            a = i * (z_slices + 1) + j
            b = a + (z_slices + 1)
            fidx += [(a, a + 1, b), (a + 1, b + 1, b)]
    m2 = trimesh.Trimesh(vertices=np.array(verts, float), faces=np.array(fidx, int), process=False)
    if not m2.is_winding_consistent:
        m2.invert()
    m2.visual = trimesh.visual.TextureVisuals(uv=np.array(uvs, float), material=mat(key, kind))
    return m2


def rotate_y(mesh, angle, around=(0, 0)):
    mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, [0, 1, 0], around))
    return mesh


def translate(mesh, dx, dy, dz):
    mesh.apply_translation((dx, dy, dz))
    return mesh


# ============================================================ furniture kit
def add_box(scene, extents, key, center, node_name, kind="furn", tile=True):
    scene.add_geometry(mbox(extents, key, center=center, kind=kind, tile=tile), node_name=node_name)


def add_cyl(scene, r, h, key, center, node_name, kind="furn", r2=None, sections=24, tile=True):
    scene.add_geometry(mcyl(r, h, key, center=center, kind=kind, r2=r2, sections=sections, tile=tile),
                       node_name=node_name)


def f_sofa(scene, x, z, yaw, length=1.9, depth=0.85, key="boucle", cushion="boucleL", kind="furn", name="sofa", back_h=0.62):
    """3-seat sofa centred at (x, z), facing +local-x, rotated by yaw."""
    g = lambda n: _mk_group(n)
    parts = []
    base = mbox((depth, 0.30, length), key, center=(0, 0.24, 0), kind=kind)
    back = mbox((0.22, back_h, length), key, center=(-depth / 2 + 0.11, 0.24 + back_h / 2, 0), kind=kind)
    parts += [base, back]
    for dz in (-length / 2 + 0.10, length / 2 - 0.10):
        parts.append(mbox((depth, 0.24, 0.18), key, center=(0, 0.47, dz), kind=kind))
    nseat = max(1, int(length / 0.85))
    for i in range(nseat):
        z0 = -length / 2 + 0.12 + (i + 0.5) * (length - 0.24) / nseat
        parts.append(mbox((depth - 0.14, 0.13, (length - 0.3) / nseat - 0.05), cushion, center=(0.02, 0.45, z0), kind=kind))
        parts.append(mbox((0.15, 0.34, (length - 0.3) / nseat - 0.09), cushion, center=(-depth / 2 + 0.19, 0.63, z0), kind=kind))
    for dx, dz in ((-depth / 2 + 0.12, -length / 2 + 0.12), (depth / 2 - 0.12, -length / 2 + 0.12),
                   (-depth / 2 + 0.12, length / 2 - 0.12), (depth / 2 - 0.12, length / 2 - 0.12)):
        parts.append(mcyl(0.028, 0.10, "walnut", center=(dx, 0.05, dz), kind=kind, tile=False))
    grp = trimesh.scene.Scene()
    for i, p in enumerate(parts):
        grp.add_geometry(p, node_name=f"{name}_p{i}", geom_name=f"{name}_g{i}")
    return _place_group(grp, x, z, yaw)


def _mk_group(n):
    return trimesh.scene.Scene()


def _place_group(group_scene, x, z, yaw):
    """Pack a sub-scene into a transform-able object.

    trimesh.Scene nodes carry their own transforms; easiest robust approach:
    merge the parts into ONE mesh list with a shared group transform applied
    via a parent concatenation in the recipe.  We instead return the list of
    (mesh, local_name) and let the recipe add + transform each part.
    """
    raise NotImplementedError("use f_* builders returning part lists")


def parts_sofa(x, z, yaw, length=1.9, depth=0.85, key="boucle", cushion="boucleL", kind="furn", name="sofa", back_h=0.62):
    """Return [(mesh, node_name)] for a sofa, positioned and rotated."""
    out = []
    base = mbox((depth, 0.30, length), key, center=(0, 0.24, 0), kind=kind)
    back = mbox((0.22, back_h, length), key, center=(-depth / 2 + 0.11, 0.24 + back_h / 2, 0), kind=kind)
    out += [(base, f"{name}_base"), (back, f"{name}_back")]
    for i, dz in enumerate((-length / 2 + 0.10, length / 2 - 0.10)):
        out.append((mbox((depth, 0.24, 0.18), key, center=(0, 0.47, dz), kind=kind), f"{name}_arm{i}"))
    nseat = max(1, int(length / 0.85))
    for i in range(nseat):
        z0 = -length / 2 + 0.12 + (i + 0.5) * (length - 0.24) / nseat
        out.append((mbox((depth - 0.14, 0.13, (length - 0.3) / nseat - 0.05), cushion, center=(0.02, 0.45, z0), kind=kind), f"{name}_seat{i}"))
        out.append((mbox((0.15, 0.34, (length - 0.3) / nseat - 0.09), cushion, center=(-depth / 2 + 0.19, 0.63, z0), kind=kind), f"{name}_bcush{i}"))
    for i, (dx, dz) in enumerate(((-depth / 2 + 0.12, -length / 2 + 0.12), (depth / 2 - 0.12, -length / 2 + 0.12),
                                  (-depth / 2 + 0.12, length / 2 - 0.12), (depth / 2 - 0.12, length / 2 - 0.12))):
        out.append((mcyl(0.028, 0.10, "walnut", center=(dx, 0.05, dz), kind=kind, tile=False), f"{name}_leg{i}"))
    return _pose(out, x, z, yaw)


def parts_armchair(x, z, yaw, key="velvet_green", kind="furn", name="armchair"):
    out = []
    out.append((mbox((0.72, 0.26, 0.70), key, center=(0, 0.22, 0), kind=kind), f"{name}_base"))
    out.append((mbox((0.18, 0.52, 0.70), key, center=(-0.27, 0.50, 0), kind=kind), f"{name}_back"))
    for dz in (-0.26, 0.26):
        out.append((mbox((0.72, 0.20, 0.14), key, center=(0, 0.42, dz), kind=kind), f"{name}_arm{dz>0}"))
    out.append((mbox((0.52, 0.12, 0.50), key, center=(0.03, 0.40, 0), kind=kind), f"{name}_seat"))
    for dx, dz in ((-0.26, -0.24), (0.26, -0.24), (-0.26, 0.24), (0.26, 0.24)):
        out.append((mcyl(0.025, 0.09, "walnut", center=(dx, 0.045, dz), kind=kind, tile=False), f"{name}_leg"))
    return _pose(out, x, z, yaw)


def parts_bed_single(x, z, yaw, size=(1.0, 2.0), wood="timber", duvet="duvet", kind="furn", name="bed"):
    """Single/double bed: frame + mattress + duvet + 2 pillows."""
    W, L = size
    out = []
    out.append((mbox((W, 0.22, L), wood, center=(0, 0.19, 0), kind=kind), f"{name}_frame"))
    out.append((mbox((W - 0.06, 0.16, L - 0.06), "white_paint", center=(0, 0.38, 0), kind=kind, tile=False), f"{name}_mattress"))
    out.append((mbox((W - 0.10, 0.10, L * 0.62), duvet, center=(0, 0.48, L * 0.16), kind=kind), f"{name}_duvet"))
    for dz in (-L / 2 + 0.22, -L / 2 + 0.52):
        out.append((mbox((W - 0.22, 0.11, 0.34), "white_paint", center=(0, 0.50, dz), kind=kind, tile=False), f"{name}_pillow"))
    out.append((mbox((W, 0.65, 0.07), wood, center=(0, 0.42, -L / 2), kind=kind), f"{name}_headboard"))
    for dx, dz in ((-W / 2 + 0.06, -L / 2 + 0.06), (W / 2 - 0.06, -L / 2 + 0.06),
                   (-W / 2 + 0.06, L / 2 - 0.06), (W / 2 - 0.06, L / 2 - 0.06)):
        out.append((mbox((0.07, 0.08, 0.07), wood, center=(dx, 0.04, dz), kind=kind, tile=False), f"{name}_leg"))
    return _pose(out, x, z, yaw)


def parts_bunk_bed(x, z, yaw, size=(0.95, 2.05), wood="timber", duvet="duvet", kind="furn", name="bunk"):
    """Two-stack bunk bed along local z (head to -z)."""
    W, L = size
    out = []
    for lvl, y0 in enumerate((0.32, 1.18)):
        out.append((mbox((W, 0.16, L), wood, center=(0, y0, 0), kind=kind), f"{name}_slat{lvl}"))
        out.append((mbox((W - 0.04, 0.14, L - 0.04), "white_paint", center=(0, y0 + 0.13, 0), kind=kind, tile=False), f"{name}_mat{lvl}"))
        out.append((mbox((W - 0.08, 0.09, L * 0.6), duvet, center=(0, y0 + 0.22, L * 0.15), kind=kind), f"{name}_duv{lvl}"))
        out.append((mbox((W - 0.24, 0.10, 0.32), "white_paint", center=(0, y0 + 0.23, -L / 2 + 0.22), kind=kind, tile=False), f"{name}_pil{lvl}"))
    for dz in (-L / 2, 0, L / 2):
        for dx in (-W / 2, W / 2):
            out.append((mbox((0.07, 1.55, 0.07), wood, center=(dx, 0.78, dz), kind=kind, tile=False), f"{name}_post"))
    out.append((mbox((0.05, 0.28, 0.05), wood, center=(W / 2, 1.55, -L / 2 + 0.3), kind=kind, tile=False), f"{name}_rail"))
    return _pose(out, x, z, yaw)


def parts_table_round(x, z, r=0.42, h=0.46, key="walnut", kind="furn", name="table"):
    out = [
        (mcyl(r, 0.045, key, center=(0, h - 0.02, 0), kind=kind), f"{name}_top"),
        (mcyl(0.05, h - 0.05, key, center=(0, (h - 0.05) / 2, 0), kind=kind, tile=False), f"{name}_ped"),
        (mcyl(0.16, 0.025, key, center=(0, 0.012, 0), kind=kind, tile=False), f"{name}_foot"),
    ]
    return _pose(out, x, z, 0)


def parts_cafe_table(x, z, r=0.55, h=0.74, key="walnut", kind="furn", name="cafe_table"):
    out = [
        (mcyl(r, 0.04, key, center=(0, h - 0.02, 0), kind=kind), f"{name}_top"),
        (mcyl(0.04, h - 0.04, "iron_dark", center=(0, (h - 0.04) / 2, 0), kind=kind, tile=False), f"{name}_pole"),
        (mcyl(0.22, 0.03, "iron_dark", center=(0, 0.015, 0), kind=kind, tile=False), f"{name}_base"),
    ]
    return _pose(out, x, z, 0)


def parts_chair(x, z, yaw, key="walnut", seat="fabric_ochre", kind="furn", name="chair"):
    out = [
        (mbox((0.42, 0.04, 0.42), key, center=(0, 0.45, 0), kind=kind, tile=False), f"{name}_seat"),
        (mbox((0.42, 0.50, 0.045), key, center=(0, 0.70, -0.19), kind=kind, tile=False), f"{name}_back"),
        (mbox((0.40, 0.05, 0.40), seat, center=(0, 0.475, 0), kind=kind, tile=False), f"{name}_cushion"),
    ]
    for dx, dz in ((-0.17, -0.17), (0.17, -0.17), (-0.17, 0.17), (0.17, 0.17)):
        out.append((mcyl(0.02, 0.45, key, center=(dx, 0.225, dz), kind=kind, tile=False), f"{name}_leg"))
    return _pose(out, x, z, yaw)


def parts_piano_grand(x, z, yaw, kind="furn", name="piano"):
    """Stylised black grand piano (body + open lid + 3 legs + bench)."""
    out = []
    out.append((mbox((1.55, 0.30, 2.05), "black_gloss", center=(0, 0.62, 0), kind=kind, tile=False), f"{name}_body"))
    out.append((mbox((1.5, 0.05, 1.2), "black_gloss", center=(0.22, 0.92, -0.35), kind=kind, tile=False), f"{name}_lid"))
    out.append((mbox((0.9, 0.045, 0.34), "black_gloss", center=(-0.28, 0.80, 0.65), kind=kind, tile=False), f"{name}_keys"))
    for dx, dz in ((-0.6, -0.8), (0.6, -0.8), (-0.6, 0.85), (0.6, 0.85)):
        out.append((mcyl(0.05, 0.47, "black_gloss", center=(dx, 0.235, dz), kind=kind, tile=False), f"{name}_leg"))
    out.append((mbox((0.42, 0.07, 1.45), "walnut", center=(2.3, 0.90, 0.1), kind=kind, tile=False), f"{name}_bench"))
    return _pose(out, x, z, yaw)


def parts_easel(x, z, yaw, art_key="art_landscape", kind="furn", name="easel"):
    """Tripod easel + canvas with a painting."""
    out = []
    for dx, dz in ((-0.26, 0.0), (0.26, 0.0), (0.0, -0.30)):
        out.append((mbox((0.045, 1.62, 0.045), "walnut", center=(dx * 0.75, 0.81, dz + 0.15), kind=kind, tile=False), f"{name}_leg"))
    out.append((mbox((0.62, 0.05, 0.05), "walnut", center=(0, 0.62, 0.02), kind=kind, tile=False), f"{name}_tray"))
    out.append((mbox((0.62, 0.04, 0.04), "walnut", center=(0, 1.18, 0.02), kind=kind, tile=False), f"{name}_top"))
    out.append((mbox((0.66, 0.82, 0.03), art_key, center=(0, 1.05, 0.045), kind=kind, tile=False), f"{name}_canvas"))
    return _pose(out, x, z, yaw)


def parts_chandelier(scene_parts, x, y, z, drop=0.5, r=0.34, name="chandelier", kind="furn"):
    """Brass ring chandelier + 6 candle glasses, hanging at ceiling y."""
    out = []
    out.append((mcyl(0.012, drop, "brass", center=(x, y - drop / 2, z), kind=kind, tile=False), f"{name}_cord"))
    out.append((mtorus(r, 0.02, "brass", center=(x, y - drop, z), axis="x"), f"{name}_ring"))
    for k in range(6):
        a0 = k * 2 * np.pi / 6
        px, pz = x + r * np.cos(a0), z + r * np.sin(a0)
        out.append((mcyl(0.035, 0.09, "lamp_glow", center=(px, y - drop + 0.06, pz), kind=kind, tile=False), f"{name}_candle{k}"))
        out.append((mcyl(0.012, 0.16, "brass", center=(px, y - drop + 0.14, pz), kind=kind, tile=False), f"{name}_drop{k}"))
    scene_parts.extend(out)


def parts_pendant(x, y, z, name="pendant", kind="furn", r=0.16):
    out = [
        (mcyl(0.012, y - 0.42, "iron_dark", center=(x, (y + 0.42) / 2 + 0.21 - 0.21, z), kind=kind, tile=False), f"{name}_cord"),
        (mcyl(r, 0.20, "lamp_glow", center=(x, y - 0.42, z), kind=kind, r2=r * 0.7, tile=False), f"{name}_shade"),
    ]
    # cord: from ceiling y down to shade top (y-0.42)
    out[0] = (mcyl(0.012, 0.42, "iron_dark", center=(x, y - 0.21, z), kind=kind, tile=False), f"{name}_cord")
    return out


def parts_plant(x, z, s=1.0, kind="furn", name="plant"):
    out = [
        (mcyl(0.16 * s, 0.30 * s, "terracotta" if False else "walnut", center=(x, 0.15 * s, z), kind=kind, r2=0.20 * s, tile=False), f"{name}_pot"),
        (mcyl(0.12 * s, 0.06, "foliage", center=(x, 0.33 * s, z), kind=kind, tile=False), f"{name}_soil"),
    ]
    for k in range(7):
        a0 = RNG.uniform(0, 6.28)
        rr = 0.05 + 0.32 * s * RNG.uniform(0.3, 1)
        h0 = 0.42 * s
        out.append((mcyl(0.16 * s * RNG.uniform(0.6, 1.1), 0.55 * s * RNG.uniform(0.7, 1.2), "foliage",
                         center=(x + rr * np.cos(a0), h0 + 0.22 * s, z + rr * np.sin(a0)), kind=kind, r2=0.05 * s, sections=10, tile=False), f"{name}_leaf{k}"))
    return out


def parts_tree(x, z, h=3.6, r=0.14, kind="furn", name="tree"):
    out = [
        (mcyl(r, h * 0.55, "timber", center=(x, h * 0.55 / 2, z), kind=kind, r2=r * 0.7, tile=False), f"{name}_trunk"),
    ]
    for k in range(5):
        dx, dz = RNG.uniform(-0.9, 0.9, 2)
        rr = RNG.uniform(0.9, 1.5)
        out.append((mcyl(rr, rr * 0.8, "foliage", center=(x + dx, h * 0.62 + RNG.uniform(0, 1.2), z + dz), kind=kind, sections=14, tile=False), f"{name}_crown{k}"))
    return out


def parts_fireplace(x, z, yaw, kind="furn", name="fireplace"):
    """Stone fireplace against a wall behind it (local -x)."""
    out = [
        (mbox((0.36, 1.30, 1.90), "stonefloor", center=(0, 0.65, 0), kind=kind), f"{name}_body"),
        (mbox((0.44, 0.12, 2.10), "stonefloor", center=(0.04, 1.36, 0), kind=kind), f"{name}_mantel"),
        (mbox((0.10, 0.85, 0.80), "black_gloss", center=(0.14, 0.55, 0), kind=kind, tile=False), f"{name}_opening"),
        (mbox((0.16, 0.30, 0.55), "lamp_glow", center=(0.10, 0.30, 0), kind=kind, tile=False), f"{name}_fire"),
    ]
    return _pose(out, x, z, yaw)


def parts_stove(x, z, yaw, kind="furn", name="stove"):
    """Tiled ceramic stove (Kachelofen) — box body + dome + door."""
    out = [
        (mbox((0.62, 1.15, 0.62), "tiles_stove", center=(0, 0.72, 0), kind=kind), f"{name}_body"),
        (mbox((0.70, 0.10, 0.70), "tiles_stove", center=(0, 1.34, 0), kind=kind), f"{name}_cap"),
        (mcyl(0.06, 0.9, "iron_dark", center=(0, 1.85, 0), kind=kind, tile=False), f"{name}_flue"),
        (mbox((0.05, 0.26, 0.20), "iron_dark", center=(0.32, 0.42, 0), kind=kind, tile=False), f"{name}_door"),
    ]
    return _pose(out, x, z, yaw)


def _pose(parts, x, z, yaw):
    """Apply yaw rotation about origin then translate to (x, 0, z)."""
    R = trimesh.transformations.rotation_matrix(yaw, [0, 1, 0])
    T = np.eye(4); T[:3, 3] = (x, 0.0, z)
    M = T @ R
    out = []
    for mesh, name in parts:
        mesh.apply_transform(M)
        out.append((mesh, name))
    return out


def add_parts(scene, parts, prefix=""):
    for mesh, name in parts:
        scene.add_geometry(mesh, node_name=prefix + name)
