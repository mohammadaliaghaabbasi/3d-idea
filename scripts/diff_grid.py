#!/usr/bin/env python3
"""Spatial diff grid using identity_diff.py's OWN reprojection (authoritative
convention) — splits the residual into a 4x4 grid to reveal the signature."""
import sys, json, importlib.util
import numpy as np
from PIL import Image

spec = importlib.util.spec_from_file_location("idiff", "/home/z/my-project/3d-idea/scripts/identity_diff.py")
idiff = importlib.util.module_from_spec(spec)
sys.modules["idiff"] = idiff
# identity_diff runs main() only under __main__ guard? check: it uses if __name__ == '__main__'
spec.loader.exec_module(idiff)

shot_path, sidecar_path, pano_path = sys.argv[1], sys.argv[2], sys.argv[3]
side = json.load(open(sidecar_path))
shot = np.asarray(Image.open(shot_path).convert("RGB")).astype(np.float32)
pano = np.asarray(Image.open(pano_path).convert("RGB")).astype(np.float32)
H, W = shot.shape[:2]

view, u_span = idiff.render_view(pano_path, W, H, side["yaw"], side["pitch"], side.get("fov", 72))

diff = np.abs(shot - view).mean(axis=2)
print(f"shot {W}x{H}, global mean|diff|={diff.mean():.2f}, max={diff.max():.0f}")
gh, gw = 4, 4
print("4x4 grid mean|diff| (rows top->bottom):")
for i in range(gh):
    print("  " + " ".join(f"{diff[i*H//gh:(i+1)*H//gh, j*W//gw:(j+1)*W//gw].mean():6.1f}" for j in range(gw)))
cols = diff.mean(axis=0); rows = diff.mean(axis=1)
print("col quartiles:", " ".join(f"{cols[int(k*W/4):int((k+1)*W/4)].mean():.1f}" for k in range(4)))
print("row quartiles:", " ".join(f"{rows[int(k*H/4):int((k+1)*H/4)].mean():.1f}" for k in range(4)))
# horizontal shift test: which dx minimizes the diff (misalignment signature)
best = (None, 1e9)
for dx in range(-24, 25, 4):
    xs = slice(max(0, dx), W + min(0, dx))       # view columns
    ss = slice(max(0, -dx), W + min(0, -dx))    # shot columns
    m = np.abs(shot[:, ss] - view[:, xs]).mean()
    if m < best[1]:
        best = (dx, m)
print(f"best horizontal shift: dx={best[0]} → mean|diff|={best[1]:.2f} (0 = aligned)")
