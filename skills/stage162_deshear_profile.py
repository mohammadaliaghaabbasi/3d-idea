#!/usr/bin/env python3
"""PANODROME — STAGE 1.6.2c · STITCH DE-SHEAR PROFILE (per-row LUT).

Final defect of the plumb-line mission, root-caused 2026-11-03:

  * The relief dome is provably plumb at the door band (field trace:
    W_eff(phi) = const over the whole jamb height; E2E plumbP50 < 5 cm).
  * The residual jamb S-curve (3-5 screen px, three independent vision
    judges + numeric edge trace) is the STITCHER SHEAR BAKED INTO THE
    ORIGINAL PANO: in a true equirect every vertical 3D line maps to a
    CONSTANT-u column, but the ballroom's jambs wander up to ~7 px with
    a smooth S + per-row wander (stitcher seam crossing the door band;
    left and right jambs bow with OPPOSITE curvature).
  * Rule A forbids editing the pano file. The fix is a SAMPLING-TIME
    re-projection: measure each sheared jamb edge row by row in the
    source, store the measured shape as a per-row LUT (64 V-bins), and
    shift the shader's sample-u by the measured offset so every sheared
    source column lands back on its true plumb fragment column. The
    on-disk texture is NEVER modified.

Profile stored in rooms_db:

    room.walk.relief.stitch = {
      "r0": 0.26, "r1": 0.66,          # V band (door architecture rows)
      "bins": 64,
      "edges": [                        # up to 3 measured edges
        {"u": <U fraction>, "half": <U>, "blend": <U>,
         "cov": .., "linear_px": .., "quad_px": .., "maxdev_px": ..,
         "lut": [64 offsets in U fraction, mean-removed]}
      ]
    }

Runtime: public/js/room.js FRAG de-shears with u' = u + lut(v)*win(u).
Idempotent; md5-syncs the DB; writes docs/rd-artifacts/stage162_deshear_report.json.
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
REPORT = ROOT / "docs" / "rd-artifacts" / "stage162_deshear_report.json"

R0, R1 = 0.26, 0.66          # V band where doorway architecture lives
LUT_BINS = 64                # per-row offset bins over the band
EDGE_HALF_DEG = 6.0          # full correction window around each edge
EDGE_BLEND_DEG = 5.0         # feather beyond the window
MIN_COV = 0.50               # traced rows / band rows
MIN_MAXDEV_PX = 2.5          # store an edge only beyond this wander
MAX_MAXDEV_PX = 14.0         # render-residual bound: the faithful reprojection
                             # proves source shear is ~7-8 px; >14 px means the
                             # tracker drifted onto REAL CURVED CONTENT (log
                             # grooves, Victorian scrollwork) which must NOT
                             # be straightened (Rule A spirit)
MAX_LINEAR_PX = 12.0         # render shows jamb lean <= ~1 px screen: a larger
                             # linear means a diagonal/leaning real edge
EDGE_BAND_DEG = 10.0         # corrections only within +-10 deg of the door
JAMB_DUS = (-66, -40, 40, 80)  # known door-edge columns rel. to door centre
AUTO_CANDS = 8               # extra auto-detected energy columns
# Whitelist: only rooms with a JUDGE-CONFIRMED rendered jamb defect get a
# stored profile.  art_studio/leipzig surveyed edges are below measurement
# confidence (their QA gates all pass) -- correcting them risks bending
# real content with an unstable LUT.
DESHEAR_ROOMS = {"ballroom"}


def log(*a):
    print(*a, flush=True)


def trace_edge(gx: np.ndarray, Hp: int, Wp: int, u_seed: int, rows: np.ndarray,
               thresh: float = 80.0, jump: float = 5.0):
    """Seeded bidirectional edge trace (survey method, wider window).
    Returns u(y) with NaNs where the edge is lost."""
    us = np.full(len(rows), np.nan)
    seed_col = np.abs(gx[rows, u_seed])
    r_seed = int(np.argmax(seed_col))
    if seed_col[r_seed] < min(60.0, thresh):
        return us
    us[r_seed] = float(u_seed)
    for direction in (-1, 1):
        r = r_seed
        u_prev = float(u_seed)
        b_run = 0.0
        while True:
            r += direction
            if r < 0 or r >= len(rows):
                break
            pred = u_prev + 0.6 * b_run
            lo = max(0, int(round(pred)) - 10)
            hi = min(Wp, int(round(pred)) + 11)
            col = np.abs(gx[rows[r], lo:hi])
            if col.max() < thresh:
                break
            top = np.argsort(col)[-3:]
            w = col[top]
            uc = lo + float(np.average(top, weights=w))
            step = uc - u_prev
            if abs(step) > jump:           # a true stitcher edge never jumps
                break
            b_run = 0.6 * b_run + 0.4 * step
            b_run = float(np.clip(b_run, -0.015, 0.015))
            u_prev = uc
            us[r] = uc
    return us


def clean_trace(us: np.ndarray, rows: np.ndarray):
    """Median + Gaussian smooth the traced edge; measure its shape.
    Returns dict or None."""
    ok = ~np.isnan(us)
    if ok.sum() < 12:
        return None
    # longest contiguous segment (kills lost-then-regained jumps)
    idx = np.where(ok)[0]
    splits = np.where(np.diff(idx) > 1)[0]
    segs = np.split(idx, splits + 1)
    seg = max(segs, key=len)
    if len(seg) < 12:
        return None
    rr = rows[seg]
    uu = us[seg]
    # median filter the raw trace (kills 1-2 px tracker jitter)
    k = 9
    pad = np.pad(uu, k // 2, mode="edge")
    uu_m = np.array([np.median(pad[i:i + k]) for i in range(len(uu))])
    # gaussian smooth (the stitcher warp field is smooth; this keeps only that)
    sig = 3.0
    xs = np.arange(-3 * sig, 3 * sig + 1)
    ker = np.exp(-0.5 * (xs / sig) ** 2)
    ker /= ker.sum()
    pad = np.pad(uu_m, len(ker) // 2, mode="edge")
    uu_s = np.convolve(pad, ker, mode="valid")
    cov = len(seg) / len(rows)
    # shape metrics on the smoothed trace
    A = np.stack([np.ones_like(rr, dtype=float), rr - rr.mean(),
                  (rr - rr.mean()) ** 2], axis=1)
    try:
        coef, *_ = np.linalg.lstsq(A, uu_s, rcond=None)
    except Exception:
        return None
    a, b, cq = coef
    span = rr[-1] - rr[0]
    linear_px = float(b * span)
    quad_px = float(cq * span * span)
    resid = float(np.std(uu_s - A @ coef))
    dev = uu_s - np.mean(uu_s)
    maxdev = float(np.max(np.abs(dev)))
    if (cov < MIN_COV or abs(linear_px) > MAX_LINEAR_PX
            or maxdev < MIN_MAXDEV_PX or maxdev > MAX_MAXDEV_PX):
        return None
    return {"rows": rr, "u_smooth": uu_s, "cov": cov, "linear_px": linear_px,
            "quad_px": quad_px, "maxdev_px": maxdev, "resid_px": resid,
            "u_mean": float(np.mean(uu_s))}


def survey_room(room: dict) -> dict:
    pano = np.asarray(Image.open(ROOT / "public" / room["panorama"]).convert("L")).astype(np.float32)
    Hp, Wp = pano.shape
    c = room["camera"]
    p = room["portals"][0]["position"]
    th_door = float(np.arctan2(p[2] - c["z"], -(p[0] - c["x"])))
    col0 = int(((th_door / (2 * np.pi)) % 1) * Wp)
    gx = cv2.Sobel(pano, cv2.CV_32F, 1, 0, ksize=3)
    rows = np.arange(int(R0 * Hp), int(R1 * Hp))

    # candidate columns: known jamb offsets (scaled to this pano width) +
    # top auto energy columns inside ±12 deg of the door azimuth
    cands = [col0 + int(round(du * Wp / 4096.0)) for du in JAMB_DUS]
    energy = np.abs(gx[rows[0]:rows[-1], :]).sum(axis=0)
    half_px = int(12.0 / 360.0 * Wp)
    win = energy[col0 - half_px: col0 + half_px]
    n_auto = 0
    for i in np.argsort(win)[::-1]:
        u = col0 - half_px + i
        if win[i] < 0.25 * win.max():
            break
        if all(abs(u - x) >= 30 for x in cands):
            cands.append(u)
            n_auto += 1
        if n_auto >= AUTO_CANDS:
            break

    fits = []
    band_u = 10.0 / 360.0
    u0_frac = ((th_door / (2 * np.pi)) % 1)
    for u in cands:
        u = int(np.clip(u, 25, Wp - 25))
        du = abs(u / Wp - u0_frac)
        du = min(du, 1.0 - du)
        if du > band_u:
            continue                      # outside the door architecture band
        tr = trace_edge(gx, Hp, Wp, u, rows)
        fit = clean_trace(tr, rows)
        du_known = {abs(int(round(d * Wp / 4096))) for d in JAMB_DUS}
        if fit is None and int(abs(u - col0)) in du_known:
            # the two KNOWN jambs get one relaxed retry (lower contrast,
            # smaller jump budget) -- they are the owner's named targets
            tr = trace_edge(gx, Hp, Wp, u, rows, thresh=60.0, jump=6.0)
            fit = clean_trace(tr, rows)
        if fit is None:
            continue
        fit["u_seed"] = u
        fit["u_px"] = fit["u_mean"]          # representative column (px)
        fits.append(fit)
    # dedup edges closer than 30 px, keep the higher maxdev
    fits.sort(key=lambda f: -f["maxdev_px"])
    keep = []
    for f in fits:
        if all(abs(f["u_px"] - g["u_px"]) >= 30 for g in keep):
            keep.append(f)
        if len(keep) >= 3:
            break

    edges = []
    for f in keep:
        # resample the smoothed trace to the LUT grid over [R0, R1]
        grid = np.linspace(R0 * Hp, R1 * Hp, LUT_BINS + 1)
        rr, uu = f["rows"].astype(float), f["u_smooth"]
        order = np.argsort(rr)
        rr, uu = rr[order], uu[order]
        centres = 0.5 * (grid[:-1] + grid[1:])
        lut_px = np.interp(centres, rr, uu, left=uu[0], right=uu[-1])
        lut_u = (lut_px - f["u_mean"]) / Wp   # U-fraction offsets, mean-removed
        # quartic fit (portable GLSL: no dynamic array indexing) + residual
        x = (centres - 0.5 * (R0 + R1) * Hp) / (0.5 * (R1 - R0) * Hp)
        co4 = np.polyfit(x, lut_u, 4)
        resid4 = float(np.max(np.abs(lut_u - np.polyval(co4, x)))) * Wp
        lut_poly = [round(float(c), 9) for c in co4[::-1]]  # ascending powers
        edges.append({
            "u": round(float(f["u_px"] / Wp), 6),
            "half": round(EDGE_HALF_DEG / 360.0, 6),
            "blend": round(EDGE_BLEND_DEG / 360.0, 6),
            "cov": round(float(f["cov"]), 3),
            "linear_px": round(f["linear_px"], 2),
            "quad_px": round(f["quad_px"], 2),
            "maxdev_px": round(f["maxdev_px"], 2),
            "resid_px": round(f["resid_px"], 2),
            "poly_resid_px": round(resid4, 2),
            "poly": lut_poly,
            "lut": [round(float(v), 6) for v in lut_u],
        })

    applied = bool(edges)
    prof = None
    if applied:
        prof = {"r0": R0, "r1": R1, "bins": LUT_BINS, "edges": edges}
        room["walk"]["relief"]["stitch"] = prof
    else:
        room["walk"]["relief"].pop("stitch", None)
    return {"id": room["id"], "applied": applied, "edges": edges,
            "profile": prof}


def main():
    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    results = []
    for room in db["rooms"]:
        log(f"[deshear] {room['id']} ...")
        try:
            r = survey_room(room)
        except Exception as e:
            r = {"id": room["id"], "applied": False, "error": str(e)}
            if "portals" in room and room["portals"]:
                room["walk"]["relief"].pop("stitch", None)
        if room["id"] not in DESHEAR_ROOMS and r.get("applied"):
            r["applied"] = False
            r["profile"] = None
            room["walk"]["relief"].pop("stitch", None)
            log("    (surveyed but NOT applied: room not in whitelist)")
        results.append(r)
        if r.get("applied"):
            for e in r["edges"]:
                log(f"    edge u={e['u']:.4f} maxdev={e['maxdev_px']}px "
                    f"linear={e['linear_px']}px quad={e['quad_px']}px cov={e['cov']} "
                    f"lut|r|max={max(abs(v) for v in e['lut'])*4096:.1f}px")
        else:
            log("    no significant shear")

    txt = json.dumps(db, ensure_ascii=False, indent=2) + "\n"
    DB_PATH.write_text(txt, encoding="utf-8")
    DB_PUBLIC.write_text(txt, encoding="utf-8")
    a = hashlib.md5(DB_PATH.read_bytes()).hexdigest()
    b = hashlib.md5(DB_PUBLIC.read_bytes()).hexdigest()
    assert a == b, "DB md5 sync FAILED"
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "law": "Stage 1.6.2c stitch de-shear LUT: vertical 3D lines map to "
               "constant-u columns in a true equirect; the stitcher sheared "
               "the ballroom jambs (up to ~7 px S + wander, opposite curvature "
               "left/right). Measured per-row and re-projected at SAMPLING "
               "time (Rule A: the original pano file is NEVER modified).",
        "results": results,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"[deshear] DB saved + md5-synced; report -> {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
