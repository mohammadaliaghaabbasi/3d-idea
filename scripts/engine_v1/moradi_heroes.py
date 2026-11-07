#!/usr/bin/env python3
"""moradi_heroes.py — MORADI REAL-CONTENT TEST, Phase F hero composites.
H1  three-mode strips (pano|splat|both) at each scene's WORST 0.75 m state
H2  four-direction strip (worst scene: seam/mirror case) — all 4 dirs
H3  distance-ladder strips (bed1a worst dir, main3 worst dir, 0.2→1.3 m)
H4  cross-validation pairs (main3|main4, bed1a|bed1b at matched states)
H5  riskiest-room trio (kit1 px seam, main2 px mirrors, bed1a mx mirror+bed)
Output: download/panodrome-moradi/heroes/H*.jpg
"""
import json, os
import numpy as np
import cv2

STILLS = "/home/z/my-project/download/panodrome-moradi/stills"
HEROES = "/home/z/my-project/download/panodrome-moradi/heroes"; os.makedirs(HEROES, exist_ok=True)
ART = "/home/z/my-project/3d-idea/docs/rd-artifacts/engine-v1"

SCENES = ["moradi_main1", "moradi_main2", "moradi_main3", "moradi_main4",
          "moradi_kit1", "moradi_kit2", "moradi_bed1a", "moradi_bed1b",
          "moradi_bed2a", "moradi_bed3a"]
TITLES = {"moradi_main1": "Main_1 sitting", "moradi_main2": "Main_2 entry (mirrors@seam)",
          "moradi_main3": "Main_3 open living", "moradi_main4": "Main_4 open living B",
          "moradi_kit1": "Kitchen_1 (seam duplicate)", "moradi_kit2": "Kitchen_2 open plan",
          "moradi_bed1a": "Bedroom_1-1 (mirror@centre+bed)", "moradi_bed1b": "Bedroom_1-2 master B",
          "moradi_bed2a": "Bedroom_2-1 child sage", "moradi_bed3a": "Bedroom_3-1 pink/wardrobe"}
DISTS = ["02", "04", "06", "075", "10", "13"]

def load(p):
    img = cv2.imread(p); assert img is not None, p
    return img

def hstrip(imgs, gap=6, h=None):
    if h is None: h = min(im.shape[0] for im in imgs)
    imgs = [cv2.resize(im, (int(im.shape[1]*h/im.shape[0]), h)) for im in imgs]
    strips = []
    for i, im in enumerate(imgs):
        if i: strips.append(np.full((h, gap, 3), 255, np.uint8))
        strips.append(im)
    return np.hstack(strips)

def label_bar(text, w, h=34):
    bar = np.full((h, w, 3), 24, np.uint8)
    cv2.putText(bar, text, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 1, cv2.LINE_AA)
    return bar

def with_title(im, text):
    bar = label_bar(text, im.shape[1])
    return np.vstack([bar, im])

def main():
    met = json.load(open(f"{ART}/moradi_metrics.json"))["battery_075"]
    # H1 — three modes at each scene's worst state
    rows = []
    for sc in SCENES:
        if sc not in met: continue
        worst = min(met[sc]["per_dir"], key=lambda c: met[sc]["per_dir"][c]["psnr_db"])
        trio = []
        for mode in ("pano", "splat", "both"):
            p = f"{STILLS}/{sc}_{worst}_075_{mode}.jpg" if mode != "pano" else f"{STILLS}/{sc}_pano_{worst}.jpg"
            if os.path.exists(p): trio.append(load(p))
        if len(trio) == 3:
            s = with_title(hstrip(trio), f"{TITLES[sc]} — worst dir {worst} (travel) @0.75 m: pano | splat(magenta) | both")
            rows.append(s)
    if rows:
        h = 420
        rows = [cv2.resize(r, (int(r.shape[1]*h/r.shape[0]), h)) for r in rows]
        wmax = max(r.shape[1] for r in rows)
        canvas = np.full((h*len(rows)+6*(len(rows)-1), wmax, 3), 255, np.uint8)
        y = 0
        for r in rows:
            canvas[y:y+h, :r.shape[1]] = r; y += h+6
        cv2.imwrite(f"{HEROES}/H1_three_modes_worst_dir_all10.jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 88])
        print("H1 done", canvas.shape)

    # H2 — four directions at 0.75 for the seam/mirror scenes
    for sc, tag in (("moradi_main2", "H2a"), ("moradi_kit1", "H2b")):
        if sc not in met: continue
        imgs = []
        for code in ("px", "mx", "pz", "mz"):
            p = f"{STILLS}/{sc}_{code}_075_both.jpg"
            if os.path.exists(p):
                d = met[sc]["per_dir"][code]
                imgs.append(with_title(load(p), f"{code} travel/view {d['viewed_dir']}  PSNR {d['psnr_db']}dB  DE+{d['double_edge_excess_pct']}%"))
        if imgs:
            cv2.imwrite(f"{HEROES}/{tag}_four_dirs_075_{sc}.jpg", hstrip(imgs, h=520), [cv2.IMWRITE_JPEG_QUALITY, 88])
            print(tag, "done")

    # H3 — ladders
    for sc, code, tag in (("moradi_bed1a", "mx", "H3a"), ("moradi_main3", "pz", "H3b")):
        imgs = []
        for dt in DISTS:
            p = f"{STILLS}/{sc}_{code}_{dt}_both.jpg"
            if os.path.exists(p):
                m = json.load(open(f"{ART}/moradi_metrics.json"))["ladders"].get(sc, {}).get(f"{code}_{dt}")
                lab = f"{float(dt)/10 if len(dt)<=2 else float(dt)/100:.2f} m" + (f"  {m['psnr_db']}dB h{m['holes_pct']}%" if m else "")
                imgs.append(with_title(load(p), lab))
        if imgs:
            cv2.imwrite(f"{HEROES}/{tag}_ladder_{sc}_{code}.jpg", hstrip(imgs, h=560), [cv2.IMWRITE_JPEG_QUALITY, 88])
            print(tag, "done")

    # H4 — cross-validation pairs (worst states side by side)
    for a, b, tag, code in (("moradi_main3", "moradi_main4", "H4a", "pz"),
                            ("moradi_bed1a", "moradi_bed1b", "H4b", None)):
        imgs = []
        for sc in (a, b):
            if sc not in met: continue
            c = code or min(met[sc]["per_dir"], key=lambda x: met[sc]["per_dir"][x]["psnr_db"])
            p = f"{STILLS}/{sc}_{c}_075_both.jpg"
            if os.path.exists(p):
                imgs.append(with_title(load(p), f"{TITLES[sc]} — {c} @0.75 m  PSNR {met[sc]['per_dir'][c]['psnr_db']}dB"))
        if len(imgs) == 2:
            cv2.imwrite(f"{HEROES}/{tag}_crossval_{a}_vs_{b}.jpg", hstrip(imgs, h=520), [cv2.IMWRITE_JPEG_QUALITY, 88])
            print(tag, "done")

    # H5 — riskiest trio close-ups (crop centre band of the composite)
    imgs = []
    for sc, code, why in (("moradi_kit1", "px", "seam-duplicated dining table"),
                          ("moradi_main2", "px", "mirrors at seam + nadir stitch"),
                          ("moradi_bed1a", "mx", "mirror at centre + near bed")):
        if sc not in met: continue
        p = f"{STILLS}/{sc}_{code}_075_both.jpg"
        if os.path.exists(p):
            im = load(p); H, W = im.shape[:2]
            crop = im[int(H*0.22):int(H*0.78), :]
            d = met[sc]["per_dir"][code]
            imgs.append(with_title(crop, f"{TITLES[sc]} — {code} — {why} — PSNR {d['psnr_db']}dB DE+{d['double_edge_excess_pct']}%"))
    if imgs:
        cv2.imwrite(f"{HEROES}/H5_riskiest_trio_crops.jpg", np.vstack(imgs), [cv2.IMWRITE_JPEG_QUALITY, 90])
        print("H5 done")
    print("heroes ->", HEROES)

if __name__ == "__main__":
    main()
