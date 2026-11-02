#!/usr/bin/env python3
"""Extract a perspective view (virtual camera) from the anniversary_lounge pano.
Used to crop furniture for remote image-to-3D tests (Hunyuan3D-2 / splatter_image)."""
import numpy as np, cv2, sys, os

PANO = "/home/z/my-project/3d-idea/public/assets/panoramas/anniversary_lounge.jpg"
OUT = "/tmp/rd/out"
os.makedirs(OUT, exist_ok=True)

def pano_to_perspective(pano_bgr, yaw_deg, pitch_deg, fov_deg=65, out_w=640, out_h=512):
    """Render a virtual perspective camera looking at (yaw, pitch) into the equirect pano.
    Rolls the pano so the view center sits mid-image -> no BORDER_WRAP needed."""
    H, W = pano_bgr.shape[:2]
    shift = int(((yaw_deg / 360.0) % 1.0) * W)
    rolled = np.roll(pano_bgr, W // 2 - shift, axis=1)
    H, W = rolled.shape[:2]
    yaw_deg = 0.0
    f = (out_w / 2) / np.tan(np.radians(fov_deg) / 2)
    cx, cy = out_w / 2, out_h / 2
    xs, ys = np.meshgrid(np.arange(out_w), np.arange(out_h))
    xnd = -(xs - cx) / f         # camera right = -x when looking along +z (world)
    ynd = -(ys - cy) / f          # +y down in image, +y up in camera
    zc = np.ones_like(xnd)
    # camera frame -> world: yaw around Y, pitch around X
    yaw, pitch = np.radians(yaw_deg), np.radians(pitch_deg)
    Rz = np.array([[np.cos(-yaw), 0, np.sin(-yaw)],
                   [0, 1, 0],
                   [-np.sin(-yaw), 0, np.cos(-yaw)]])
    Rx = np.array([[1, 0, 0],
                   [0, np.cos(pitch), -np.sin(pitch)],
                   [0, np.sin(pitch), np.cos(pitch)]])
    R = Rz @ Rx
    dirs = np.stack([xnd, ynd, zc], axis=-1).reshape(-1, 3) @ R.T
    x, y, z = dirs[:, 0], dirs[:, 1], dirs[:, 2]
    theta = np.arctan2(z, x)                  # azimuth
    phi = np.arcsin(np.clip(y / np.linalg.norm(dirs, axis=1), -1, 1))
    u = ((((theta + np.pi / 2) / (2 * np.pi)) % 1.0) * W).reshape(out_h, out_w)
    v = ((0.5 - phi / np.pi) * H).reshape(out_h, out_w)
    return cv2.remap(rolled, u.astype(np.float32), v.astype(np.float32), cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REFLECT)

if __name__ == "__main__":
    pano = cv2.imread(PANO)
    # sofa at fraction 0.01 of width = yaw ~ 0.01*360 = 3.6 deg; take a wider view around it
    views = {
        "sofa_left": (0.01 * 360, -6, 70),      # left sofa (near)
        "coffee_table": (0.79 * 360, -8, 70),   # coffee table
        "sofa_right": (0.85 * 360, -6, 70),     # right sofa
    }
    for name, (yaw, pitch, fov) in views.items():
        img = pano_to_perspective(pano, yaw, pitch, fov, 768, 640)
        p = os.path.join(OUT, f"persp_{name}.jpg")
        cv2.imwrite(p, img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        print("saved", p, img.shape)
