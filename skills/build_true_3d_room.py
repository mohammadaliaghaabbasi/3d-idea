#!/usr/bin/env python3
# ============================================================================
# PANODROME — LAW 3: TRUE-3D ARCHITECTURAL ROOM BUILDER (owner law 2026-11-03)
# ============================================================================
# Builds modern_3d_villa.glb — a 100% REAL 3D architectural interior (NOT a
# projected photo!): real box walls with PBR wood/plaster/travertine
# procedural textures, real 3D furniture meshes (sofa, travertine coffee
# table, oak sideboard, floor lamp, sculpture plinth + bronze torus, art
# frames), recessed ceiling light trims, windows opening onto the runtime
# skybox, and an exit doorway.  Every object is a real mesh — multi-metre
# 6DoF walking can never warp anything.
#
# Outputs:
#   public/assets/true3d/modern_3d_villa.glb      — the glb scene
#   docs/rd-artifacts/true3d/villa_room.json      — exact rooms_db room record
#                                                    (walk bounds, EXACT Box3
#                                                    furniture colliders,
#                                                    light rig, portal)
#   docs/rd-artifacts/true3d/textures/*.png       — procedural PBR textures
#   public/assets/preview/modern_3d_villa.jpg     — preview placeholder
#                                                    (replaced by the real
#                                                    render in E2E)
# ============================================================================
import json
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import trimesh
from trimesh.visual.material import PBRMaterial

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEX_DIR = os.path.join(ROOT, "docs", "rd-artifacts", "true3d", "textures")
GLB_PATH = os.path.join(ROOT, "public", "assets", "true3d", "modern_3d_villa.glb")
DB_FRAG = os.path.join(ROOT, "docs", "rd-artifacts", "true3d", "villa_room.json")
PREVIEW = os.path.join(ROOT, "public", "assets", "preview", "modern_3d_villa.jpg")

RNG = np.random.default_rng(20261103)

# ---------------------------------------------------------------- villa spec
ROOM = dict(w=6.4, d=5.2, h=3.0)          # interior X / Z / Y extents
WALL_T = 0.15                              # wall thickness (outward)
WIN = dict(w=1.5, h=1.5, sill=0.85, zc=(-1.35, 1.35))   # west-wall windows
DOOR = dict(w=1.0, h=2.1, xc=1.8)         # north-wall exit door


# ================================================================ textures
def _noise(img, amp, blur=0):
    a = np.asarray(img).astype(np.int16)
    n = RNG.integers(-amp, amp + 1, a.shape[:2])
    if blur:
        n = np.asarray(Image.fromarray(n.astype(np.uint8)).filter(ImageFilter.GaussianBlur(blur))).astype(np.int16) - 128
        n = (n.astype(np.float32) / 128 * amp).astype(np.int16)
    for c in range(3):
        a[:, :, c] = np.clip(a[:, :, c] + n, 0, 255)
    return Image.fromarray(a.astype(np.uint8))


def tex_oak_planks(sz=1024, planks=8):
    """Vertical oak planks: per-plank tone, stretched grain, dark gaps."""
    pw = sz // planks
    a = np.zeros((sz, sz, 3), np.uint8)
    for p in range(planks):
        tone = 176 + int(RNG.integers(-16, 16))
        base = np.array([tone, int(tone * 0.72), int(tone * 0.47)])
        col = np.tile(base, (sz, pw, 1)).astype(np.float32)
        yy = np.arange(sz).reshape(-1, 1)
        grain = (np.sin(yy / 3.1 + RNG.uniform(0, 6.28) + np.linspace(0, 6, pw).reshape(1, -1) * 0.4) * 5)
        grain += (np.linspace(-1, 1, pw).reshape(1, -1) * 6)     # cathedral arc
        col += grain.reshape(sz, pw, 1)
        knot_y = RNG.integers(80, sz - 80)
        ky = np.exp(-((np.arange(sz) - knot_y) / 26.0) ** 2).reshape(-1, 1, 1)
        col -= ky * 16
        col = np.clip(col, 0, 255).astype(np.uint8)
        a[:, p * pw:(p + 1) * pw] = col
    img = Image.fromarray(a)
    d = ImageDraw.Draw(img)
    for p in range(planks):
        d.line([(p * pw, 0), (p * pw, sz)], fill=(64, 44, 28), width=3)
        # staggered plank ends
        for _ in range(2):
            y = int(RNG.integers(60, sz - 60))
            d.line([(p * pw, y), ((p + 1) * pw, y)], fill=(70, 50, 32), width=2)
    return _noise(img, 5)


def tex_plaster(sz=512):
    a = np.full((sz, sz, 3), 0, np.uint8)
    a[:, :, 0] = 233; a[:, :, 1] = 229; a[:, :, 2] = 221
    img = Image.fromarray(a)
    img = img.filter(ImageFilter.GaussianBlur(0))
    blotch = Image.new("L", (sz, sz), 128)
    db = ImageDraw.Draw(blotch)
    for _ in range(26):
        x, y = RNG.integers(0, sz, 2)
        r = int(RNG.integers(30, 120))
        db.ellipse([x - r, y - r, x + r, y + r], fill=int(RNG.integers(112, 144)))
    blotch = blotch.filter(ImageFilter.GaussianBlur(26))
    b = np.asarray(blotch).astype(np.int16) - 128
    arr = np.asarray(img).astype(np.int16) + (b.reshape(sz, sz, 1) * 14 // 128)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    return _noise(img, 4)


def tex_travertine(sz=512):
    a = np.full((sz, sz, 3), 0, np.uint8)
    a[:, :, 0] = 214; a[:, :, 1] = 199; a[:, :, 2] = 178
    img = Image.fromarray(a)
    d = ImageDraw.Draw(img)
    for v in range(9):                      # wavy horizontal veins
        y0 = int(RNG.integers(10, sz - 10))
        pts = [(x, y0 + int(9 * np.sin(x / 47.0 + v * 1.7))) for x in range(0, sz + 1, 8)]
        d.line(pts, fill=(196 + int(RNG.integers(-14, 8)), 180 + int(RNG.integers(-14, 8)), 158), width=int(RNG.integers(2, 5)))
    for _ in range(260):                    # pits
        x, y = RNG.integers(0, sz, 2)
        r = int(RNG.integers(1, 3))
        d.ellipse([x, y, x + r, y + r], fill=(168, 152, 132))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    return _noise(img, 5)


def tex_boucle(sz=512, base=(225, 217, 202)):
    a = np.tile(np.array(base, np.uint8), (sz, sz, 1))
    img = Image.fromarray(a)
    d = ImageDraw.Draw(img)
    for _ in range(5200):                   # knobby bouclé loops
        x, y = RNG.integers(0, sz, 2)
        r = int(RNG.integers(1, 3))
        tone = int(RNG.integers(-16, 16))
        c = tuple(np.clip(np.array(base) + tone, 0, 255))
        d.ellipse([x, y, x + r, y + r], fill=c)
    img = img.filter(ImageFilter.GaussianBlur(0.5))
    return _noise(img, 4)


def tex_rug(sz=1024):
    base = (208, 198, 184)
    a = np.tile(np.array(base, np.uint8), (sz, sz, 1))
    img = Image.fromarray(a)
    d = ImageDraw.Draw(img)
    m = 74
    d.rectangle([m, m, sz - m, sz - m], outline=(178, 165, 148), width=10)
    d.rectangle([m + 26, m + 26, sz - m - 26, sz - m - 26], outline=(186, 172, 152), width=4)
    return _noise(img, 7, blur=1)


def tex_art_field(sz=640):
    """Colour-field painting: ochre ground, deep oxide block, cream seam."""
    img = Image.new("RGB", (sz, int(sz * 1.28)), (222, 202, 164))
    d = ImageDraw.Draw(img)
    W, H = img.size
    d.rectangle([int(W * 0.12), int(H * 0.10), int(W * 0.88), int(H * 0.50)], fill=(122, 58, 44))
    d.rectangle([int(W * 0.12), int(H * 0.56), int(W * 0.88), int(H * 0.88)], fill=(84, 70, 58))
    d.rectangle([int(W * 0.46), int(H * 0.10), int(W * 0.52), int(H * 0.88)], fill=(238, 228, 206))
    return _noise(img, 4)


def tex_art_line(sz=640):
    """Minimal line study: chalk ground, charcoal arcs, brass disc."""
    img = Image.new("RGB", (sz, int(sz * 1.28)), (236, 233, 226))
    d = ImageDraw.Draw(img)
    W, H = img.size
    for i, r in enumerate((int(W * 0.30), int(W * 0.42), int(W * 0.54))):
        box = [W // 2 - r, int(H * 0.16), W // 2 + r, int(H * 0.16) + 2 * r]
        d.arc(box, start=200 + i * 12, end=340 - i * 10, fill=(52, 48, 44), width=8 - i)
    d.ellipse([int(W * 0.62), int(H * 0.66), int(W * 0.62) + int(W * 0.2), int(H * 0.66) + int(W * 0.2)], fill=(176, 141, 84))
    d.line([(int(W * 0.18), int(H * 0.84)), (int(W * 0.58), int(H * 0.84))], fill=(52, 48, 44), width=6)
    return _noise(img, 3)


def tex_oak_dark(sz=512):
    return _noise(tex_oak_planks(sz, planks=6), 4)


def save_tex(name, img):
    os.makedirs(TEX_DIR, exist_ok=True)
    p = os.path.join(TEX_DIR, name)
    img.save(p)
    return p


# ============================================================ geometry utils
def textured_box(extents, mat, uv=(1.0, 1.0), center=(0, 0, 0), tile_axes="auto"):
    """Box with per-face UVs (seam-split vertices), planar per face.

    uv: (u_repeat, v_repeat) applied along each face's dominant axes.
    """
    ex, ey, ez = extents
    cx, cy, cz = center
    hx, hy, hz = ex / 2, ey / 2, ez / 2
    faces = [
        # (+normal, 4 corners CCW seen from outside, (u_axis, v_axis) extents)
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
    m = trimesh.Trimesh(vertices=np.array(verts, float), faces=np.array(fidx), process=False)
    m.visual = trimesh.visual.TextureVisuals(uv=np.array(uvs, float), material=mat)
    return m


def textured_cylinder(radius, height, mat, uv=(1.0, 1.0), center=(0, 0, 0), sections=28, r2=None, caps=True):
    r2 = radius if r2 is None else r2
    cx, cy, cz = center
    ang = np.linspace(0, 2 * np.pi, sections + 1)
    verts, uvs, fidx = [], [], []
    ur, vr = uv
    for i, t in enumerate(ang):
        f = t / (2 * np.pi)
        r_top = r2 + (radius - r2) * 0.0  # bottom radius uses `radius`
        verts.append((cx + np.cos(t) * radius, cy, cz + np.sin(t) * radius))
        uvs.append((f * ur, 0))
        verts.append((cx + np.cos(t) * r2, cy + height, cz + np.sin(t) * r2))
        uvs.append((f * ur, vr))
    for i in range(sections):
        a, b = 2 * i, 2 * i + 1
        c, d = 2 * (i + 1), 2 * (i + 1) + 1
        fidx += [(a, c, b), (b, c, d)]     # outward winding (y-up, CCW from out)
    if caps:
        ci_b = len(verts)
        verts.append((cx, cy, cz)); uvs.append((0.5, 0.5))
        ci_t = len(verts)
        verts.append((cx, cy + height, cz)); uvs.append((0.5, 0.5))
        for i in range(sections):
            a, b = 2 * i, 2 * (i + 1)
            fidx += [(ci_b, a, b)]
            fidx += [(ci_t, 2 * i + 1, 2 * (i + 1) + 1)]
    m = trimesh.Trimesh(vertices=np.array(verts, float), faces=np.array(fidx, int), process=False)
    if not m.is_winding_consistent:
        m.invert()
    m.visual = trimesh.visual.TextureVisuals(uv=np.array(uvs, float), material=mat)
    return m


def torus(R, r, mat, uv=(8, 2), center=(0, 0, 0), maj=48, mino=16, axis="z"):
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
    m = trimesh.Trimesh(vertices=np.array(verts, float), faces=np.array(fidx, int), process=False)
    if axis == "x":
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    m.apply_translation(center)
    m.visual = trimesh.visual.TextureVisuals(uv=np.array(uvs, float), material=mat)
    return m


def pbr(name, tex=None, baseColorFactor=None, metallic=0.0, rough=0.8, emissive=None, alpha=None):
    kw = dict(name=name)
    if tex is not None:
        kw["baseColorTexture"] = tex
    if baseColorFactor is not None:
        kw["baseColorFactor"] = list(baseColorFactor)
    kw["metallicFactor"] = metallic
    kw["roughnessFactor"] = rough
    if emissive is not None:
        kw["emissiveFactor"] = list(emissive)
    if alpha is not None:
        kw["alphaMode"] = alpha
    try:
        return PBRMaterial(**kw)
    except TypeError:
        kw.pop("emissiveFactor", None)
        kw.pop("alphaMode", None)
        return PBRMaterial(**kw)


# ==================================================================== build
def build():
    os.makedirs(os.path.dirname(GLB_PATH), exist_ok=True)
    # ---- textures ----
    t_oak = save_tex("oak_planks.png", tex_oak_planks())
    t_plaster = save_tex("plaster.png", tex_plaster())
    t_trav = save_tex("travertine.png", tex_travertine())
    t_boucle = save_tex("boucle.png", tex_boucle())
    t_boucle_light = save_tex("boucle_light.png", tex_boucle(base=(233, 226, 212)))
    t_rug = save_tex("rug.png", tex_rug())
    t_art1 = save_tex("art_field.png", tex_art_field())
    t_art2 = save_tex("art_line.png", tex_art_line())
    t_oakdark = save_tex("oak_dark.png", tex_oak_dark())

    TEX = {n: Image.open(p) for n, p in [
        ("oak", t_oak), ("plaster", t_plaster), ("trav", t_trav),
        ("boucle", t_boucle), ("boucleL", t_boucle_light), ("rug", t_rug),
        ("art1", t_art1), ("art2", t_art2), ("oakdark", t_oakdark)]}

    # ---- materials ----
    m_floor = pbr("oak_floor", TEX["oak"], rough=0.42)
    m_wall = pbr("plaster_wall", TEX["plaster"], rough=0.92)
    m_ceil = pbr("plaster_ceiling", TEX["plaster"], rough=0.95)
    m_trav = pbr("travertine", TEX["trav"], rough=0.55)
    m_boucle = pbr("boucle_fabric", TEX["boucle"], rough=0.96)
    m_boucleL = pbr("boucle_fabric_light", TEX["boucleL"], rough=0.96)
    m_rug = pbr("wool_rug", TEX["rug"], rough=0.98)
    m_oaktrim = pbr("oak_trim", TEX["oakdark"], rough=0.5)
    m_metal_dark = pbr("alu_dark", baseColorFactor=(0.13, 0.13, 0.14, 1.0), metallic=0.85, rough=0.35)
    m_bronze = pbr("bronze", baseColorFactor=(0.72, 0.55, 0.36, 1.0), metallic=0.95, rough=0.28)
    m_art1 = pbr("art_field", TEX["art1"], rough=0.9)
    m_art2 = pbr("art_line", TEX["art2"], rough=0.9)
    m_glass = pbr("window_glass", baseColorFactor=(0.78, 0.86, 0.92, 0.16), rough=0.06, metallic=0.1, alpha="BLEND")
    m_spot = pbr("ceil_spot", baseColorFactor=(1.0, 1.0, 1.0, 1.0), rough=0.4, emissive=(1.0, 0.94, 0.82))
    m_shade = pbr("lamp_shade", baseColorFactor=(0.96, 0.92, 0.84, 1.0), rough=0.85, emissive=(0.42, 0.36, 0.26))

    W, D, H = ROOM["w"], ROOM["d"], ROOM["h"]
    hw, hd, T = W / 2, D / 2, WALL_T
    scene = trimesh.Scene()

    # ---------------- floor / ceiling ----------------
    scene.add_geometry(textured_box((W + 2 * T, 0.12, D + 2 * T), m_floor, uv=(4.4, 3.6), center=(0, -0.06, 0)), node_name="floor_oak")
    scene.add_geometry(textured_box((W + 2 * T, 0.12, D + 2 * T), m_ceil, uv=(4, 3), center=(0, H + 0.06, 0)), node_name="ceiling_plaster")

    # ---------------- walls (box segments around openings) ----------------
    def wall_seg(name, x0, x1, y0, y1, z0, z1):
        cx, cy, cz = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
        ex, ey, ez = x1 - x0, y1 - y0, z1 - z0
        # texture tile ≈ 1.9 m
        ur = max(ex, ez) / 1.9
        vr = ey / 1.9
        scene.add_geometry(textured_box((ex, ey, ez), m_wall, uv=(ur, vr), center=(cx, cy, cz)), node_name=name)

    # WEST wall (x = -hw): two windows z∈[zc±w/2], y∈[sill, sill+h]
    xw0, xw1 = -hw - T, -hw
    zw_lo, zw_hi = WIN["zc"][0] - WIN["w"] / 2, WIN["zc"][0] + WIN["w"] / 2
    zw2_lo, zw2_hi = WIN["zc"][1] - WIN["w"] / 2, WIN["zc"][1] + WIN["w"] / 2
    s_lo, s_hi = WIN["sill"], WIN["sill"] + WIN["h"]
    wall_seg("wall_w_a", xw0, xw1, 0, H, -hd, zw_lo)
    wall_seg("wall_w_pier", xw0, xw1, 0, H, zw_hi, zw2_lo)
    wall_seg("wall_w_b", xw0, xw1, 0, H, zw2_hi, hd)
    for i, (zl, zh) in enumerate(((zw_lo, zw_hi), (zw2_lo, zw2_hi))):
        wall_seg(f"wall_w_sill{i+1}", xw0, xw1, 0, s_lo, zl, zh)
        wall_seg(f"wall_w_head{i+1}", xw0, xw1, s_hi, H, zl, zh)
        # window frame (dark aluminium) + glass
        for (fx0, fx1, fy0, fy1, fz) in (
            (xw0 + 0.02, xw1 - 0.02, s_lo - 0.06, s_lo, (zl + zh) / 2),
            (xw0 + 0.02, xw1 - 0.02, s_hi, s_hi + 0.06, (zl + zh) / 2),
        ):
            scene.add_geometry(textured_box((fx1 - fx0, fy1 - fy0, zh - zl + 0.12), m_metal_dark,
                                            center=((fx0 + fx1) / 2, (fy0 + fy1) / 2, fz)), node_name=f"win{i+1}_frame_h")
        for fz in (zl - 0.03, zh + 0.03):
            scene.add_geometry(textured_box((0.09, WIN["h"] + 0.12, 0.06), m_metal_dark,
                                            center=(-hw - 0.06, (s_lo + s_hi) / 2, fz)), node_name=f"win{i+1}_frame_v")
        scene.add_geometry(textured_box((0.05, WIN["h"], 0.045), m_metal_dark,
                                        center=(-hw - 0.055, (s_lo + s_hi) / 2, (zl + zh) / 2)), node_name=f"win{i+1}_mullion")
        scene.add_geometry(textured_box((0.02, WIN["h"] - 0.08, WIN["w"] - 0.10), m_glass,
                                        center=(-hw - 0.05, (s_lo + s_hi) / 2, (zl + zh) / 2)), node_name=f"win{i+1}_glass")

    # EAST wall (x = +hw): solid
    wall_seg("wall_e", hw, hw + T, 0, H, -hd, hd)
    # SOUTH wall (z = +hd): solid
    wall_seg("wall_s", -hw, hw, 0, H, hd, hd + T)
    # NORTH wall (z = -hd): door opening x∈[door±w/2], y∈[0, door_h]
    zn0, zn1 = -hd - T, -hd
    dl, dr = DOOR["xc"] - DOOR["w"] / 2, DOOR["xc"] + DOOR["w"] / 2
    wall_seg("wall_n_a", -hw, dl, 0, H, zn0, zn1)
    wall_seg("wall_n_b", dr, hw, 0, H, zn0, zn1)
    wall_seg("wall_n_head", dl, dr, DOOR["h"], H, zn0, zn1)
    # oak door casing
    scene.add_geometry(textured_box((DOOR["w"] + 0.24, 0.10, 0.16), m_oaktrim,
                                    center=(DOOR["xc"], DOOR["h"] + 0.05, -hd - 0.02)), node_name="door_head_casing")
    for fx in (dl - 0.06, dr + 0.06):
        scene.add_geometry(textured_box((0.10, DOOR["h"] + 0.10, 0.16), m_oaktrim,
                                        center=(fx, (DOOR["h"] + 0.10) / 2, -hd - 0.02)), node_name="door_jamb_casing")

    # baseboards
    bb = 0.10
    for name, ex, ez, cx, cz in (
        ("bb_w", 0.03, D - 0.0, -hw + 0.015, 0),
        ("bb_e", 0.03, D, hw - 0.015, 0),
        ("bb_s", W, 0.03, 0, hd - 0.015),
        ("bb_n_a", dl + hw, 0.03, (-hw + dl) / 2, -hd + 0.015),
        ("bb_n_b", hw - dr, 0.03, (dr + hw) / 2, -hd + 0.015),
    ):
        scene.add_geometry(textured_box((ex, bb, ez), m_oaktrim, center=(cx, bb / 2, cz)), node_name=name)

    # ---------------- recessed ceiling light trims ----------------
    for i, (lx, lz) in enumerate(((1.5, 1.2), (-1.5, 1.2), (1.5, -1.2), (-1.5, -1.2))):
        scene.add_geometry(textured_cylinder(0.085, 0.025, m_metal_dark, center=(lx, H - 0.032, lz)),
                           node_name=f"spot_trim{i+1}")
        scene.add_geometry(textured_cylinder(0.062, 0.012, m_spot, center=(lx, H - 0.048, lz)),
                           node_name=f"spot_emitter{i+1}")

    # ---------------- furniture ----------------
    # rug
    scene.add_geometry(textured_box((3.4, 0.012, 2.4), m_rug, uv=(1, 1), center=(0.15, 0.006, 0.75)), node_name="rug")

    # sofa (facing +X toward the sideboard)
    sx, sz = -0.6, 0.6
    scene.add_geometry(textured_box((0.86, 0.32, 2.16), m_boucle, uv=(1.6, 1), center=(sx, 0.26, sz)), node_name="sofa_base")
    scene.add_geometry(textured_box((0.26, 0.58, 2.16), m_boucle, uv=(1.2, 1), center=(sx - 0.30, 0.62, sz)), node_name="sofa_back")
    for i, dz in enumerate((-1.14, 1.14)):
        scene.add_geometry(textured_box((0.86, 0.26, 0.24), m_boucle, center=(sx, 0.51, sz + dz)), node_name=f"sofa_arm{i+1}")
    for i, dz in enumerate((-0.55, 0.55)):
        scene.add_geometry(textured_box((0.74, 0.15, 1.02), m_boucleL, center=(sx + 0.04, 0.495, sz + dz)), node_name=f"sofa_seat{i+1}")
        scene.add_geometry(textured_box((0.17, 0.40, 0.98), m_boucleL, center=(sx - 0.26, 0.70, sz + dz)), node_name=f"sofa_backcushion{i+1}")
    for dx, dz in ((-0.36, -0.98), (0.36, -0.98), (-0.36, 0.98), (0.36, 0.98)):
        scene.add_geometry(textured_cylinder(0.028, 0.10, m_oaktrim, center=(sx + dx, 0.05, sz + dz)), node_name="sofa_leg")

    # travertine coffee table
    tx, tz = 0.75, 0.6
    scene.add_geometry(textured_box((1.15, 0.07, 0.55), m_trav, uv=(1.4, 0.8), center=(tx, 0.365, tz)), node_name="table_top")
    for i, dx in enumerate((-0.42, 0.42)):
        scene.add_geometry(textured_box((0.09, 0.33, 0.45), m_trav, center=(tx + dx, 0.165, tz)), node_name=f"table_leg{i+1}")

    # oak sideboard (east wall)
    bx, bz = hw - 0.24, -0.9
    scene.add_geometry(textured_box((0.44, 0.62, 1.8), m_oaktrim, uv=(1.6, 1), center=(bx, 0.35, bz)), node_name="sideboard_body")
    scene.add_geometry(textured_box((0.46, 0.035, 1.84), m_trav, center=(bx, 0.685, bz)), node_name="sideboard_top")
    for dz in (-0.62, 0.62):
        scene.add_geometry(textured_box((0.36, 0.5, 0.02), m_metal_dark, center=(bx - 0.05, 0.35, bz + dz)), node_name="sideboard_handle")

    # floor lamp
    lx, lz = 0.95, -1.3
    scene.add_geometry(textured_cylinder(0.16, 0.025, m_metal_dark, center=(lx, 0.012, lz)), node_name="lamp_base")
    scene.add_geometry(textured_cylinder(0.016, 1.42, m_metal_dark, center=(lx, 0.72, lz)), node_name="lamp_pole")
    scene.add_geometry(textured_cylinder(0.185, 0.27, m_shade, r2=0.135, center=(lx, 1.36, lz)), node_name="lamp_shade")

    # sculpture: travertine plinth + bronze torus
    px, pz = -2.35, -1.7
    scene.add_geometry(textured_box((0.42, 1.0, 0.42), m_trav, uv=(0.6, 1.4), center=(px, 0.5, pz)), node_name="plinth")
    scene.add_geometry(torus(0.155, 0.052, m_bronze, center=(px, 1.19, pz), axis="x"), node_name="torus_sculpture")

    # art frames
    def art_frame(name, w, h, cx, cy, cz, mat, face):
        d = 0.045
        t = 0.055
        if face == "x":       # on an x-plane wall (east)
            for (fx0, fy0, fy1) in ((cy - h / 2 - t, cy - h / 2, cy + h / 2),):
                pass
            scene.add_geometry(textured_box((d, h + 2 * t, w + 2 * t), m_oaktrim, center=(cx, cy, cz)), node_name=f"{name}_back")
            scene.add_geometry(textured_box((d + 0.02, h, w), mat, center=(cx - 0.01, cy, cz)), node_name=name)
        else:                 # on a z-plane wall (south)
            scene.add_geometry(textured_box((w + 2 * t, h + 2 * t, d), m_oaktrim, center=(cx, cy, cz)), node_name=f"{name}_back")
            scene.add_geometry(textured_box((w, h, d + 0.02), mat, center=(cx, cy, cz + 0.01)), node_name=name)

    art_frame("art_east", 0.95, 1.25, hw - 0.05, 1.78, -0.9, m_art1, "x")
    art_frame("art_s1", 0.62, 0.86, -1.5, 1.62, hd - 0.05, m_art2, "z")
    art_frame("art_s2", 0.62, 0.86, 0.9, 1.62, hd - 0.05, m_art1, "z")

    # ---------------------------------------------------------------- export
    glb = scene.export(file_type="glb")
    with open(GLB_PATH, "wb") as f:
        f.write(glb)
    n_mesh = len(scene.geometry)
    n_tris = sum(len(g.faces) for g in scene.geometry.values())

    # exact Box3 colliders (same numbers as the meshes — single source of truth)
    obstacles = [
        dict(type="box", x=sx, z=sz, hw=0.50, hd=1.32, h=0.92, rot=0.0, source="authored",
             label=dict(en="Sofa", fa="مبل")),
        dict(type="box", x=tx, z=tz, hw=0.62, hd=0.32, h=0.40, rot=0.0, source="authored",
             label=dict(en="Coffee Table", fa="میز عسلی")),
        dict(type="box", x=bx, z=bz, hw=0.26, hd=0.95, h=0.72, rot=0.0, source="authored",
             label=dict(en="Sideboard", fa="بوفه")),
        dict(type="cylinder", x=lx, z=lz, r=0.21, h=1.63, rot=0.0, source="authored",
             label=dict(en="Floor Lamp", fa="چراغ ایستاده")),
        dict(type="box", x=px, z=pz, hw=0.26, hd=0.26, h=1.28, rot=0.0, source="authored",
             label=dict(en="Sculpture Plinth", fa="پایهٔ مجسمه")),
    ]

    room = {
        "id": "modern_3d_villa",
        "room_type": "living_room",
        "style_tags": ["modern", "minimal", "bright"],
        "type": "true_3d",
        "badge": {
            "en": "🧊 True 3D space (LiDAR / 3D Mesh)",
            "fa": "🧊 فضای سه‌بعدی واقعی (LiDAR / 3D Mesh)",
        },
        "name": {"en": "Modern 3D Villa", "fa": "ویلای مدرن سه‌بعدی"},
        "description": {
            "en": "A real 3D modern villa living room — true geometry, PBR oak, plaster and travertine, full 6DoF walking with exact furniture collision.",
            "fa": "نشیمن واقعیِ یک ویلای مدرن — هندسهٔ سه‌بعدی حقیقی با متریال چوب، گچ و تراورتن؛ قدم‌زدن کامل شش‌درجه‌آزادی با برخورد دقیق با مبلمان.",
        },
        "glb": "assets/true3d/modern_3d_villa.glb",
        "preview": "assets/preview/modern_3d_villa.jpg",
        "room_shape": {"width": W, "height": H, "depth": D},
        "camera": {"x": 0.9, "y": 1.65, "z": 1.9},
        "initial_view": {"facing": 0.85},
        "portals": [{
            "id": "villa_exit_door",
            "origin": "authored_doorway",
            "position": [DOOR["xc"], 1.35, -hd + 0.32],
        }],
        "floor_material": "wood",
        "audio": {"ambient": "room_tone", "reverb": 0.32, "footsteps": "wood"},
        "attribution": {
            "creator": "Panodrome Studio",
            "source": "Built-in True-3D",
            "license": "CC0",
            "url": "https://mohammadaliaghaabbasi.github.io/panodrome/",
        },
        "source_platform": "built_in",
        "style_family": "modern",
        "type_group": "residential",
        "sky": {
            "zenith": "#7db3e8",
            "horizon": "#eef2f4",
            "sun": "#fff3dd",
            "sun_dir": [-0.62, 0.55, 0.22],
        },
        "walk": {
            "player_radius": 0.3,
            "bounds": {"minX": -hw + 0.45, "maxX": hw - 0.45, "minZ": -hd + 0.45, "maxZ": hd - 0.45},
            "obstacles": obstacles,
            "lights": [
                {"type": "sun", "pos": [-14, 18, 5], "intensity": 2.6, "color": "#fff1de"},
                {"type": "spot", "pos": [1.5, 2.72, 1.2], "intensity": 0.5, "color": "#ffe7c6", "distance": 8},
                {"type": "spot", "pos": [-1.5, 2.72, 1.2], "intensity": 0.5, "color": "#ffe7c6", "distance": 8},
                {"type": "spot", "pos": [1.5, 2.72, -1.2], "intensity": 0.5, "color": "#ffe7c6", "distance": 8},
                {"type": "spot", "pos": [-1.5, 2.72, -1.2], "intensity": 0.5, "color": "#ffe7c6", "distance": 8},
            ],
        },
    }
    os.makedirs(os.path.dirname(DB_FRAG), exist_ok=True)
    with open(DB_FRAG, "w") as f:
        json.dump(room, f, ensure_ascii=False, indent=1)

    # preview placeholder (real render substituted by E2E screenshot)
    os.makedirs(os.path.dirname(PREVIEW), exist_ok=True)
    make_preview_placeholder()

    print(f"GLB  → {GLB_PATH}  ({len(glb)/1024:.0f} KB, {n_mesh} meshes, {n_tris} tris)")
    print(f"DB   → {DB_FRAG}")
    print(f"PREV → {PREVIEW}")
    return n_mesh, n_tris


def make_preview_placeholder():
    W, H = 780, 1180
    img = Image.new("RGB", (W, H), (18, 24, 34))
    d = ImageDraw.Draw(img)
    for y in range(H):                      # warm vertical gradient
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(24 + 30 * t), int(30 + 26 * t), int(40 + 22 * t)))
    # minimal isometric room sketch
    cx, cy = W // 2, int(H * 0.44)
    d.polygon([(cx - 260, cy), (cx, cy - 150), (cx + 260, cy), (cx, cy + 150)], outline=(214, 226, 240), width=4)
    d.polygon([(cx - 260, cy), (cx - 260, cy + 300), (cx, cy + 450), (cx, cy + 150)], outline=(150, 176, 200), width=3)
    d.polygon([(cx + 260, cy), (cx + 260, cy + 300), (cx, cy + 450), (cx, cy + 150)], outline=(150, 176, 200), width=3)
    d.rectangle([cx - 90, cy + 160, cx + 40, cy + 300], outline=(196, 208, 220), width=3)
    img = img.filter(ImageFilter.GaussianBlur(0.4))
    img.save(PREVIEW, quality=88)


if __name__ == "__main__":
    build()
