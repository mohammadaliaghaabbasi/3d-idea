#!/usr/bin/env python3
"""moradi_verify.py — MORADI REAL-CONTENT TEST, Phase E.
Scores the LOCKED predictions (moradi_predictions.json, written before any
pipeline run) against the Phase D measurements (moradi_metrics.json).
Scoring:
  * band metrics (holes/bleed/dot/sharp/psnr): HIT if measured in [lo,hi],
    NEAR if within 25% band extension, MISS otherwise
  * worst_state: HIT if that state has the scene's min PSNR at 0.75 m
  * qualitative flags: mirror/seam/blown/near-field stress -> check the
    predicted state is among the scene's 2 weakest PSNR or has the max
    double-edge excess
  * cross-validation pairs: |mean PSNR delta| <= threshold (main3/4: 1.5 dB,
    kit1/2: 2 dB, bed1a/b: bands overlap >= 50%)
Output: docs/rd-artifacts/engine-v1/moradi_verify.json
"""
import json
import numpy as np

ART = "/home/z/my-project/3d-idea/docs/rd-artifacts/engine-v1"
pred = json.load(open(f"{ART}/moradi_predictions.json"))
meas = json.load(open(f"{ART}/moradi_metrics.json"))
P, M = pred["predictions"], meas["battery_075"]

def mkey(scene):  # prediction id (main1) -> metrics key (moradi_main1)
    return scene if scene.startswith("moradi_") else f"moradi_{scene}"

# map prediction state labels -> travel-dir codes
STATE_CODE = {"px": "px", "mx": "mx", "pz": "pz", "mz": "mz"}

def band_score(val, lo, hi):
    if lo <= val <= hi: return "HIT"
    w = (hi - lo) * 0.25
    if lo - w <= val <= hi + w: return "NEAR"
    return "MISS"

def parse_state_label(label):
    for c in ("px", "mx", "pz", "mz"):
        if label.startswith(c): return c
    return None

out = {"per_scene": {}, "summary": {}}
tot = {"HIT": 0, "NEAR": 0, "MISS": 0}
def tally(s):
    tot[s] = tot.get(s, 0) + 1

for scene, p in P.items():
    m = M.get(mkey(scene))
    if not m: out["per_scene"][scene] = {"error": "no measurements"}; continue
    r = {"bands": {}, "worst_state": None, "flags": {}, "notes": []}
    # global bands
    holes_all = max(d["holes_pct"] for d in m["per_dir"].values())
    for key, mk in (("holes_pct_075_all_dirs", holes_all),):
        lo, hi = p["pred"][key]
        r["bands"]["holes_all"] = {"pred": [lo, hi], "meas": holes_all,
                                   "score": band_score(holes_all, lo, hi)}
        tally(r["bands"]["holes_all"]["score"])
    lo, hi = p["pred"]["bleed_pct"]
    bleed_max = m["bleed_max"]
    r["bands"]["bleed"] = {"pred": [lo, hi], "meas": bleed_max,
                           "score": band_score(bleed_max, lo, hi)}
    tally(r["bands"]["bleed"]["score"])
    lo, hi = p["pred"]["dot_peak"]
    dp = max(d["dot_peak"] for d in m["per_dir"].values())
    r["bands"]["dot_peak"] = {"pred": [lo, hi], "meas": round(dp, 1),
                              "score": band_score(dp, lo, hi)}
    tally(r["bands"]["dot_peak"]["score"])
    lo, hi = p["pred"]["sharp_retention_pct"]
    sr_ = m["sharp_ret_mean"]
    r["bands"]["sharp_ret"] = {"pred": [lo, hi], "meas": sr_,
                               "score": band_score(sr_, lo, hi)}
    tally(r["bands"]["sharp_ret"]["score"])
    # per-state PSNR bands
    per_state = {}
    for label, band in p["pred"]["psnr_db_075_per_state"].items():
        code = parse_state_label(label)
        if code is None or code not in m["per_dir"]:
            continue
        got = m["per_dir"][code]["psnr_db"]
        sc = band_score(got, band[0], band[1])
        per_state[code] = {"pred": band, "meas": got, "score": sc,
                           "viewed": m["per_dir"][code]["viewed_dir"]}
        tally(sc)
    r["per_state_psnr"] = per_state
    # worst-state call
    wc = parse_state_label(p["pred"]["worst_state"].split(" ")[0])
    actual_worst = min(m["per_dir"], key=lambda c: m["per_dir"][c]["psnr_db"])
    r["worst_state"] = {"pred_code": wc, "actual_worst_code": actual_worst,
                        "score": "HIT" if wc == actual_worst else
                                 ("NEAR" if m["per_dir"][wc]["psnr_db"] <= m["psnr_worst"] + 0.8 else "MISS")}
    tally(r["worst_state"]["score"])
    # qualitative failure-family flags (checked vs 2 weakest states + max double-edge)
    weakest2 = sorted(m["per_dir"], key=lambda c: m["per_dir"][c]["psnr_db"])[:2]
    de_max_code = max(m["per_dir"], key=lambda c: m["per_dir"][c]["double_edge_excess_pct"])
    fam = pred["house_level_predictions"]["failure_families_expected"]
    for fam_name, states in fam.items():
        for st in states:
            parts = st.split(" ")
            if len(parts) < 2: continue          # scene-level families (e.g. glossy floor) — listed, not state-scored
            sc_scene, code = parts[0], parts[1]
            if mkey(sc_scene) != mkey(scene) or code not in m["per_dir"]: continue
            weak_hit = code in weakest2
            de_hit = bool(code == de_max_code and m["per_dir"][code]["double_edge_excess_pct"] >=
                      np.median([d["double_edge_excess_pct"] for d in m["per_dir"].values()]))
            r["flags"][f"{fam_name}:{code}"] = {"in_weakest2": weak_hit,
                                                "de_max": de_hit,
                                                "confirmed": bool(weak_hit or de_hit)}
    out["per_scene"][scene] = r

# cross-validation pairs
cv = {}
pairs = [("moradi_main3", "moradi_main4", 1.5), ("moradi_kit1", "moradi_kit2", 2.0),
         ("moradi_bed1a", "moradi_bed1b", None)]
for a, b, thr in pairs:
    if a in M and b in M:
        d_mean = abs(M[a]["psnr_mean"] - M[b]["psnr_mean"])
        if thr is not None:
            ok = d_mean <= thr
            cv[f"{a}|{b}"] = {"psnr_mean_delta_db": round(d_mean, 2), "threshold": thr, "ok": bool(ok)}
        else:  # band overlap >= 50%
            la, lb = [sorted(d["psnr_db"] for d in M[s]["per_dir"].values()) for s in (a, b)]
            ra = (min(la), max(la)); rb = (min(lb), max(lb))
            ov = max(0, min(ra[1], rb[1]) - max(ra[0], rb[0]))
            frac = ov / max(1e-9, min(ra[1]-ra[0], rb[1]-rb[0]))
            cv[f"{a}|{b}"] = {"range_a": [round(x,2) for x in ra], "range_b": [round(x,2) for x in rb],
                              "overlap_frac": round(frac, 2), "ok": bool(frac >= 0.5)}
        tally("HIT" if cv[f"{a}|{b}"]["ok"] else "MISS")
out["cross_validation"] = cv
out["summary"] = {"counts": tot,
                  "accuracy_pct": round(100*tot["HIT"]/max(1, sum(tot.values())), 1),
                  "hit_plus_near_pct": round(100*(tot["HIT"]+tot["NEAR"])/max(1, sum(tot.values())), 1)}
json.dump(out, open(f"{ART}/moradi_verify.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps(out["summary"], indent=1))
print("cross-validation:", json.dumps(cv, indent=1))
for s, r in out["per_scene"].items():
    if "error" in r: print(s, r["error"]); continue
    print(f"{s}: worst_state {r['worst_state']['score']} | bands:",
          {k: v["score"] for k, v in r["bands"].items()},
          "| states:", {k: v["score"] for k, v in r["per_state_psnr"].items()})
print("saved ->", f"{ART}/moradi_verify.json")
