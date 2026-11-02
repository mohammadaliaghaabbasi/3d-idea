#!/usr/bin/env python3
"""Depth-Anything-V2-small ONNX inference on an equirectangular panorama.
Measures wall-clock time and saves 16-bit raw depth + 8-bit visualization."""
import time, sys, os
import numpy as np
import cv2
import onnxruntime as ort

PANO = "/home/z/my-project/3d-idea/public/assets/panoramas/anniversary_lounge.jpg"
MODEL = "/tmp/rd/models/hf/onnx/model.onnx"
OUT_DIR = "/tmp/rd/out"
os.makedirs(OUT_DIR, exist_ok=True)

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

def to_multiple(x, m=14):
    return max(m, int(round(x / m)) * m)

def main():
    t0 = time.time()
    img = cv2.imread(PANO)  # BGR
    H, W = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0

    # full-ish resolution: 1/2 of 4096 -> 2044x1036 (multiple of 14), CPU-viable
    tw = to_multiple(W / 2)   # 2044
    th = to_multiple(H / 2)   # 1036
    resized = cv2.resize(rgb, (tw, th), interpolation=cv2.INTER_AREA)
    x = (resized - IMAGENET_MEAN) / IMAGENET_STD
    x = np.transpose(x, (2, 0, 1))[None].astype(np.float32)

    so = ort.SessionOptions()
    so.intra_op_num_threads = 2
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(MODEL, so, providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    print(f"[setup] session built in {time.time()-t0:.1f}s, input={in_name} {sess.get_inputs()[0].shape}, output={sess.get_outputs()[0].shape}")

    t1 = time.time()
    out = sess.run(None, {in_name: x})[0]
    dt = time.time() - t1
    print(f"[infer] ran in {dt:.2f}s on {tw}x{th} -> raw depth {out.shape} {out.dtype}")

    d = out[0].astype(np.float32)
    if d.shape != (th, tw):
        d = cv2.resize(d, (tw, th), interpolation=cv2.INTER_CUBIC)
    # upscale back to (W/2, H/2) for the prototype (half-res pano)
    HW, WW = H // 2, W // 2
    depth = cv2.resize(d, (WW, HW), interpolation=cv2.INTER_CUBIC).astype(np.float32)

    np.save(os.path.join(OUT_DIR, "depth_raw.npy"), depth)
    # 16-bit png: normalize to [0, 65535], near = large value
    d16 = ((depth - depth.min()) / (depth.max() - depth.min()) * 65535).astype(np.uint16)
    cv2.imwrite(os.path.join(OUT_DIR, "depth_16bit.png"), d16)
    # 8-bit vis: near = bright
    vis = ((depth - depth.min()) / (depth.max() - depth.min()) * 255).astype(np.uint8)
    vis = cv2.applyColorMap(255 - vis, cv2.COLORMAP_TURBO)  # near=red? invert so near=hot
    cv2.imwrite(os.path.join(OUT_DIR, "depth_vis.png"), vis)
    cv2.imwrite(os.path.join(OUT_DIR, "pano_half.jpg"), cv2.resize(img, (WW, HW)))
    print(f"[stats] depth min={depth.min():.3f} max={depth.max():.3f} mean={depth.mean():.3f} (relative units)")
    print(f"[total] {time.time()-t0:.1f}s | saved depth_raw.npy {depth.shape}")

if __name__ == "__main__":
    main()
