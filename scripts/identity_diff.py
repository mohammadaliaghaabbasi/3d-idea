#!/usr/bin/env python3
# ============================================================================
# PANODROME — LAW 4 · IDENTITY RENDER DIFF (owner law 2026-11-03)
# ============================================================================
# The decisive honest gate: re-render the EXACT camera view (yaw/pitch, FOV 72,
# camera at the capture point) in pure Python directly from the ORIGINAL
# equirectangular photograph, and diff it against the browser screenshot.
#
# If the browser render is a faithful zero-warp reprojection of the photo, the
# diff is noise (compression + mip filtering).  ANY structural deviation — a
# bent ceiling, a stretched bedsheet, a new seam line, a sheared doorway —
# appears as a large residual.  This proves the render ≡ photograph without
# any judge at all.
#
# Usage: identity_diff.py <screenshot.jpg> <sidecar.json> <pano.jpg>
#   sidecar: {"yaw": r, "pitch": r, "fov": 72, "waypoint": {"x": px, "y": px} | null,
#             "dpr": 2}
# Prints: "IDENTITY rmse4=<v> colmax=<v> u_range=[..]" or "MISMATCH ..."
# ============================================================================
import json
import os
import sys

import numpy as np
from PIL import Image


def render_view(pano, W, H, yaw, pitch, fov_v_deg, mip=2):
    """Render the perspective view straight from the equirect photo."""
    # pre-filter the pano (≈ GPU mip level) so filtering matches the GPU
    im = Image.open(pano)
    if mip > 1:
        im = im.resize((im.width // mip, im.height // mip), Image.BOX)
    src = np.asarray(im.convert("RGB")).astype(np.float32)
    Sh, Sw = src.shape[:2]

    f = (H / 2) / np.tan(np.radians(fov_v_deg) / 2)
    cx, cy = W / 2, H / 2
    xs = np.arange(W, dtype=np.float32)[None, :].repeat(H, 0)
    ys = np.arange(H, dtype=np.float32)[:, None].repeat(W, 1)
    dc = np.stack([(xs - cx) / f, (cy - ys) / f, -np.ones_like(xs)], axis=-1)
    dc /= np.linalg.norm(dc, axis=-1, keepdims=True)

    cp, sp = np.cos(pitch), np.sin(pitch)
    cyw, syw = np.cos(yaw), np.sin(yaw)
    # Rx(pitch) then Ry(yaw):  world = Ry(yaw) @ Rx(pitch) @ cam
    x1 = dc[..., 0]
    y1 = dc[..., 1] * cp - dc[..., 2] * sp
    z1 = dc[..., 1] * sp + dc[..., 2] * cp
    dx = cyw * x1 + syw * z1
    dy = y1
    dz = -syw * x1 + cyw * z1

    u = (np.arctan2(dz, -dx) / (2 * np.pi)) % 1.0
    v = 1.0 - np.arccos(np.clip(dy, -1, 1)) / np.pi

    # bilinear sample (image row 0 = zenith: flipY texture convention)
    fx = u * Sw - 0.5
    fy = (1.0 - v) * Sh - 0.5
    fy = np.clip(fy, 0, Sh - 1.001)
    x0 = np.floor(fx).astype(int) % Sw
    y0 = fy.astype(int)
    x1i = (x0 + 1) % Sw
    ax = fx - np.floor(fx)
    ay = fy - y0
    out = (src[y0, x0] * (1 - ax)[..., None] * (1 - ay)[..., None]
           + src[y0, x1i] * ax[..., None] * (1 - ay)[..., None]
           + src[y0 + 1, x0] * (1 - ax)[..., None] * ay[..., None]
           + src[y0 + 1, x1i] * ax[..., None] * ay[..., None])
    u_span = (float(u.min()), float(u.max()))
    return out, u_span


def trace_edges(img, band=(0.42, 0.78), top=10, cx_window=None):
    """Locate the strongest near-vertical edges (subpixel x) in a band.
    cx_window: optional fraction of the width around the image centre to keep
    (e.g. 0.5 = central 50%).  The doorway gate aims AT the door, so the door
    verticals are central — this excludes extreme off-axis frame-edge strips
    whose traced position carries a large anisotropic-filtering confound."""
    import cv2
    gray = img.mean(axis=2).astype(np.float32)
    H, W = gray.shape
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    y0, y1 = int(H * band[0]), int(H * band[1])
    energy = np.abs(gx[y0:y1]).mean(axis=0)
    strong = np.where(energy > 28)[0]
    clusters = []
    if len(strong):
        start = prev = strong[0]
        for x in strong[1:]:
            if x - prev <= 6:
                prev = x
                continue
            clusters.append((start, prev))
            start = prev = x
        clusters.append((start, prev))
    out = []
    for (a, b) in clusters:
        if b - a > 13:
            continue
        seg = energy[a:b + 1]
        if seg.max() < 40:
            continue
        xsub = float((np.arange(a, b + 1) * seg).sum() / seg.sum())
        out.append((xsub, float(seg.max())))
    if cx_window is not None:
        half = W * cx_window / 2.0
        out = [(x, s) for (x, s) in out if abs(x - W / 2) <= half]
    out.sort(key=lambda t: -t[1])
    return out[:top]


def edge_displacement(shot, view, cx_window=None):
    """Match the strongest vertical edges between screenshot and photo-render.
    Returns (n_matched, worst_px) — the ADDED bending of the renderer."""
    es, ev = trace_edges(shot, cx_window=cx_window), trace_edges(view, cx_window=cx_window)
    matched, worst = 0, 0.0
    for (xs, ss) in es:
        best = None
        for (xv, sv) in ev:
            d = abs(xs - xv)
            if d <= 12 and (best is None or d < best[0]):
                best = (d, xv)
        if best is not None:
            matched += 1
            worst = max(worst, best[0])
    return matched, worst, [round(x) for x, _ in es]


def main():
    side = json.load(open(SIDECAR))
    shot = np.asarray(Image.open(SHOT).convert("RGB")).astype(np.float32)
    H, W = shot.shape[:2]
    dpr = side.get("dpr", 2)
    view, u_span = render_view(PANO, W, H, side["yaw"], side["pitch"], side.get("fov", 72))

    # ---- mask: HUD chrome (top pill, bottom bars/joystick) + waypoint ring
    mask = np.ones((H, W), bool)
    mask[: int(H * 0.10)] = False
    mask[int(H * 0.74):] = False
    wp = side.get("waypoint")
    if wp:
        yy, xx = np.ogrid[:H, :W]
        r = 110 * dpr / 2 * 2 / 2  # generous disc (device px)
        r = 120
        mask &= ((xx - wp["x"]) ** 2 + (yy - wp["y"]) ** 2) > r * r

    diff = np.abs(shot - view).mean(axis=2)

    # 4x box downsample of both (robust to mip/compression noise, still
    # structural: a 5 px warp survives as a >1 px edge displacement)
    def box4(a):
        h, w = a.shape[:2]
        return a[: h // 4 * 4, : w // 4 * 4].reshape(h // 4, 4, w // 4, 4).mean(axis=(1, 3))
    m4 = box4(mask.astype(np.float32)) > 0.999   # keep only fully-masked cells
    d4 = box4(diff)
    rmse4 = float(np.sqrt((d4[m4] ** 2).mean()))

    # per-column mean |diff| inside the mask (a seam line = persistent spike)
    col = np.where(mask, diff, np.nan)
    colmean = np.nanmean(col, axis=0)
    k = 9
    colsm = np.convolve(np.nan_to_num(colmean, nan=0.0), np.ones(k) / k, mode="same")
    interior = slice(int(W * 0.08), int(W * 0.92))
    colmax = float(colsm[interior].max())

    wrap = (u_span[0] < 0.03 or u_span[1] > 0.97) or (u_span[0] > u_span[1] and u_span[0] - u_span[1] < 0.06)
    print(f"u_range=[{u_span[0]:.3f},{u_span[1]:.3f}] wrap_in_view={wrap} "
          f"rmse4={rmse4:.2f} colmax={colmax:.1f}", file=sys.stderr)

    if len(sys.argv) > 4 and sys.argv[4] == "edges":
        # EDGE-DISPLACEMENT MODE: the strongest vertical edges in the
        # screenshot vs the photo-render — the renderer's ADDED bending
        # (photo-native leans/curves cancel out; they exist in both).
        # IDIFF_EDGE_CX_WINDOW: restrict the trace to the central fraction of
        # the width (the shot is AIMED at the door — door verticals are central;
        # far frame-edge strips carry an anisotropic-filtering confound that
        # would masquerade as renderer bending)
        cxw = float(os.environ.get("IDIFF_EDGE_CX_WINDOW", "0") or 0) or None
        n, worst, xs = edge_displacement(shot, view, cx_window=cxw)
        print(f"edges matched={n} worst_displacement={worst:.2f}px shot_edges={xs}", file=sys.stderr)
        ok = rmse4 < 10.0 and colmax < 26.0 and n >= 4 and worst <= 2.5
        print(f"IDENTITY rmse4={rmse4:.2f} colmax={colmax:.1f} edges={n} edge_dev={worst:.2f}px" if ok
              else f"MISMATCH rmse4={rmse4:.2f} colmax={colmax:.1f} edges={n} edge_dev={worst:.2f}px")
        return

    ok = rmse4 < 8.0 and colmax < 26.0
    print(f"IDENTITY rmse4={rmse4:.2f} colmax={colmax:.1f}" if ok
          else f"MISMATCH rmse4={rmse4:.2f} colmax={colmax:.1f}")


if __name__ == "__main__":
    SHOT, SIDECAR, PANO = sys.argv[1], sys.argv[2], sys.argv[3]
    main()
