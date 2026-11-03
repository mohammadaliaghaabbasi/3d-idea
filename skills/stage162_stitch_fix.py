#!/usr/bin/env python3
"""Stage 1.6.2 — STITCH SHEAR SURVEY + SAMPLING PROFILE.

Final defect of the plumb-line mission: the door-jamb S-curve that survives
perfectly plumb geometry is IN THE STITCHED PANO ITSELF.  In a true
equirect projection every vertical 3D line maps to a CONSTANT-u column;
the ballroom's doorway jambs drift 18-27 px (1.6-2.4 deg) plus a ~5 px
quadratic bow across their height -- the stitcher sheared the door band.

This survey measures that shear per room (Sobel-traced vertical edges in
the door band, robust median linear+quadratic fit) and stores a SAMPLING
profile in rooms_db:

    room.walk.relief.stitch = {
      "u0": door azimuth (U units), "half": window half-width (U),
      "blend": window blend (U),
      "b": shear linear  (U units per V unit),
      "c": shear quad   (U units per V^2),
      "r0","r1": row-range of the measured band (V units)
    }

The RUNTIME FRAGMENT SHADER applies the inverse shear when sampling the
ORIGINAL pano (room.js): the on-disk texture is never modified (Rule A),
the rendered doorway de-shears to true plumb columns.

Idempotent; md5-syncs the DB; writes docs/rd-artifacts/stage162_stitch_report.json.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "rooms_db.json"
DB_PUBLIC = ROOT / "public" / "data" / "rooms_db.json"
REPORT = ROOT / "docs" / "rd-artifacts" / "stage162_stitch_report.json"

R0, R1 = 0.26, 0.66          # V band where doorway architecture lives
HALF_DEG, BLEND_DEG = 12.0, 10.0
MIN_TRACE_FRAC = 0.45        # of the band rows
MIN_MAXDEV_PX = 6.0          # apply correction only beyond this (0.5 deg)
EDGE_THRESH = 80.0          # Sobel |gx| minimum for an edge row


def log(*a):
    print(*a, flush=True)


def survey_room(room: dict) -> dict:
    pano = np.asarray(Image.open(ROOT / "public" / room["panorama"]).convert("L")).astype(np.float32)
    Hp, Wp = pano.shape
    c = room["camera"]
    p = room["portals"][0]["position"]
    th_door = float(np.arctan2(p[2] - c["z"], -(p[0] - c["x"])))
    u0 = ((th_door / (2 * np.pi)) % 1)
    col0 = int(u0 * Wp)
    half_px = int(HALF_DEG / 360 * Wp)

    gx = cv2.Sobel(pano, cv2.CV_32F, 1, 0, ksize=3)
    rows = np.arange(int(R0 * Hp), int(R1 * Hp))

    # candidate columns: strong summed vertical-edge energy near the door
    energy = np.abs(gx[rows[0]:rows[-1], :]).sum(axis=0)
    win = energy[col0 - half_px: col0 + half_px].copy()
    cands = []
    for i in np.argsort(win)[::-1]:
        u = col0 - half_px + i
        if win[i] < 0.20 * win.max():
            break
        if all(abs(u - x) >= 10 for x, _ in cands):
            cands.append((u, float(win[i])))
        if len(cands) >= 8:
            break

    vc = 0.5 * (R0 + R1) * Hp
    fits = []
    for u_start, en in cands:
        us = np.full(len(rows), np.nan)
        # seed at the row with the STRONGEST edge in this column (not the
        # band center -- the jamb/leaf edge often skips the center row)
        seed_col = np.abs(gx[rows, u_start])
        r_seed = int(np.argmax(seed_col))
        if seed_col[r_seed] < EDGE_THRESH:
            continue
        us[r_seed] = u_start
        b_pred = 0.0
        for direction in (-1, 1):
            r = r_seed
            u_prev = u_start
            b_run = 0.0
            while True:
                r += direction
                if r < 0 or r >= len(rows):
                    break
                pred = u_prev + b_pred
                lo, hi = int(round(pred)) - 15, int(round(pred)) + 16
                lo = max(0, lo); hi = min(Wp, hi)
                col = np.abs(gx[rows[r], lo:hi])
                if col.max() < EDGE_THRESH:
                    break
                k = int(np.argmax(col))
                top = np.argsort(col)[-3:]
                w = col[top]
                uc = lo + float(np.average(top, weights=w))
                b_run = 0.6 * b_run + 0.4 * (uc - u_prev)
                b_pred = np.clip(b_run, -0.30, 0.30)
                u_prev = uc
                us[r] = uc
        cov = np.mean(~np.isnan(us))
        if cov < MIN_TRACE_FRAC:
            continue
        rr = rows[~np.isnan(us)]
        uu = us[~np.isnan(us)]
        # fit u = a + b*(r-vc) + c*(r-vc)^2  (per-row px)
        A = np.stack([np.ones_like(rr, dtype=np.float64),
                      (rr - vc).astype(np.float64),
                      ((rr - vc) ** 2).astype(np.float64)], axis=1)
        try:
            coef, *_ = np.linalg.lstsq(A, uu, rcond=None)
        except Exception:
            continue
        resid = float(np.sqrt(np.mean((uu - A @ coef) ** 2)))
        if resid > 2.5:
            continue
        span = len(rows)
        a, b, cq = coef
        # max deviation from u=const over the band
        d = rr - vc
        maxdev = float(np.max(np.abs(b * d + cq * d * d)))
        fits.append({"u": float(a), "b_px": float(b), "c_px": float(cq),
                     "maxdev_px": maxdev, "cov": float(cov), "resid_px": resid})

    prof = {"u0": round(u0, 5), "half": round(HALF_DEG / 360.0, 5),
            "blend": round(BLEND_DEG / 360.0, 5), "r0": R0, "r1": R1}
    if fits:
        b_med = float(np.median([f["b_px"] for f in fits]))
        c_med = float(np.median([f["c_px"] for f in fits]))
        # recompute the correction's own max shift with the MEDIANS
        d = (np.arange(int(R0 * Hp), int(R1 * Hp)) - vc).astype(np.float64)
        maxdev = float(np.max(np.abs(b_med * d + c_med * d * d)))
        if maxdev >= MIN_MAXDEV_PX:
            # convert to U-per-V units:  du_px = b*drow + c*drow^2;
            # drow = (V-vcv)*Hp ; du_U = du_px / Wp
            Hpf = float(Hp)
            prof.update({
                "b": round(b_med * Hpf / Wp, 7),          # U per V
                "c": round(c_med * Hpf * Hpf / Wp, 9),    # U per V^2
                "maxdev_px": round(maxdev, 1),
            })
            return {"id": room["id"], "applied": True, "edges": fits,
                    "b_pxrow": round(b_med, 5), "c_pxrow2": float(f"{c_med:.3e}"),
                    "profile": prof}
    return {"id": room["id"], "applied": False, "edges": fits, "profile": None}


def main():
    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    results = []
    for room in db["rooms"]:
        log(f"[stitch] {room['id']} ...")
        try:
            r = survey_room(room)
        except Exception as e:
            r = {"id": room["id"], "applied": False, "error": str(e)}
        results.append(r)
        if r.get("applied"):
            room["walk"]["relief"]["stitch"] = r["profile"]
            log(f"    SHEAR b={r['b_pxrow']:.5f}px/row c={r['c_pxrow2']:.2e}px/row^2 "
                f"maxdev={r['profile']['maxdev_px']}px over {len(r['edges'])} edges -> profile stored")
        else:
            room["walk"]["relief"].pop("stitch", None)
            log(f"    no significant shear ({len(r.get('edges', []))} edges traced)")

    txt = json.dumps(db, ensure_ascii=False, indent=2) + "\n"
    DB_PATH.write_text(txt, encoding="utf-8")
    DB_PUBLIC.write_text(txt, encoding="utf-8")
    a = hashlib.md5(DB_PATH.read_bytes()).hexdigest()
    b = hashlib.md5(DB_PUBLIC.read_bytes()).hexdigest()
    assert a == b, "DB md5 sync FAILED"
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "law": "Stage 1.6.2 stitch-shear survey: vertical 3D lines must map to "
               "constant-u equirect columns; measured doorway shear (stitcher "
               "artifact) stored as a sampling-time de-shear profile (Rule A: "
               "the original pano file is NEVER modified)",
        "results": results,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"[stitch] DB saved + md5-synced; report -> {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
