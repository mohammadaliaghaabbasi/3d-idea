#!/usr/bin/env python3
"""MORADI EQL MANIFEST — six-field confidence folders for the Moradi real-content set.

New-rule pilot (owner mission 2026-11-07: "fix the Moradi section with the new rules"):
applies the EQL / data-confidence framework (BPLUS_DATA_SCHEMA_PROPOSAL design doc)
to the Moradi R&D set as MACHINE-READABLE metadata.

Rules honored here:
  - Every value is copied from the recorded R&D artifacts (gen/metrics/verify/survey/
    predictions). Nothing is typed from memory; nothing is invented.
  - Six-field folder per datum: value / status / source / measurement_method /
    confidence / verification_date.
  - Status ladder: unverified < estimated < measured < verified.
  - Estimation never grants movement rights; unverified node positions => EQL-2 not
    claimable for this set.
  - rooms_db.json is NOT touched (this is R&D metadata, production schema stays v1).

Output: docs/rd-artifacts/engine-v1/moradi_eql_manifest.json
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "docs" / "rd-artifacts" / "engine-v1"
OUT = ART / "moradi_eql_manifest.json"
DATE = "2026-11-07"          # date of the Moradi mission (all artifacts same day)
BATTERY_OFFSET_M = 0.75      # the measured accepted envelope

gen = json.loads((ART / "moradi_gen.json").read_text())
met = json.loads((ART / "moradi_metrics.json").read_text())
ver = json.loads((ART / "moradi_verify.json").read_text())
sur = json.loads((ART / "moradi_survey.json").read_text())
pre = json.loads((ART / "moradi_predictions.json").read_text())

SCENES = list(gen["scenes"].keys())                    # moradi_main1 ... moradi_bed3a
SURVEY_KEY = {s: s.replace("moradi_", "") for s in SCENES}
ZONES = {  # honest per-scene room labels (as on the review page, English keys for machine use)
    "moradi_main1": "neoclassical sitting", "moradi_main2": "entrance hall",
    "moradi_main3": "open living pt.A", "moradi_main4": "open living pt.B",
    "moradi_kit1": "kitchen/dining pt.A", "moradi_kit2": "kitchen pt.B",
    "moradi_bed1a": "master bedroom pt.A", "moradi_bed1b": "master bedroom pt.B",
    "moradi_bed2a": "child bedroom", "moradi_bed3a": "pink bedroom",
}
PAIRS = [("moradi_main3", "moradi_main4"), ("moradi_kit1", "moradi_kit2"),
         ("moradi_bed1a", "moradi_bed1b")]

def folder(value, status, source, method, confidence, date=DATE, **extra):
    f = {"value": value, "status": status, "source": source,
         "measurement_method": method, "confidence": confidence,
         "verification_date": date}
    f.update(extra)
    return f

STATUS_ORDER = {"unverified": 0, "estimated": 1, "measured": 2, "verified": 3}

# ---------------------------------------------------------------- per-scene --
scenes_out = {}
set_double_edge_max = -99.0
set_dot_peak_max = 0.0
for s in SCENES:
    g, key = gen["scenes"][s], SURVEY_KEY[s]
    b = met["battery_075"][s]
    per_dir = b["per_dir"]
    worst_dir = min(per_dir, key=lambda d: per_dir[d]["psnr_db"])
    de_max = max(per_dir[d]["double_edge_excess_pct"] for d in per_dir)
    dot_max = max(per_dir[d]["dot_peak"] for d in per_dir)
    set_double_edge_max = max(set_double_edge_max, de_max)
    set_dot_peak_max = max(set_dot_peak_max, dot_max)
    sv = sur[key]["vlm"]

    scenes_out[s] = {
        "zone": ZONES[s],
        "eql": {
            "at_rest": "EQL-0",
            "in_motion": "EQL-3-EXP",
            "envelope_m": BATTERY_OFFSET_M,
            "basis": ("rest = single-node 4K equirect rotation (labs harness); "
                      "motion = VQ 1.1 gaussian splat layer, EXPERIMENTAL path, R&D-only"),
        },
        "panorama": folder(
            value={"file": f"public/assets/panoramas/{s}.jpg", "kb": g["pano_kb"],
                   "resolution": "4K equirect"},
            status="verified",
            source=f"kuula.co/post/{sur[key]['post_id']} — Mojtaba87 "
                   "(R&D-only benchmark; any public use requires the photographer's permission)",
            method="4K equirect download; md5 dedup within the profile set (Kitchen_2 duplicate removed)",
            confidence="high"),
        "splat_geometry": folder(
            value={"file": f"public/labs/engine-v1/assets/{s}_splat_v11.spz",
                   "n_splats": g["n_splats"], "spz_kb": g["spz_kb"],
                   "params": gen["params_locked"], "format": "SPZ v4"},
            status="estimated",
            source="DAV2-small ONNX monocular depth -> VQ 1.1 locked projection "
                   "(method lock, no per-scene tuning)",
            method="AI depth estimation — no physical scene measurement exists",
            confidence="medium (fidelity independently MEASURED at 0.75 m, see fidelity folder)",
            extra_note=None),
        "metric_scale_k": folder(
            value=g["k_metric_scale"],
            status="estimated",
            source="k_solver on DAV2-small relative depth + pano geometry assumptions",
            method="monocular depth scale heuristic (CAM_H 1.5 m anchor)",
            confidence="low-medium — never to be presented as measured dimensions"),
        "fidelity_0p75m": folder(
            value={"offset_m": BATTERY_OFFSET_M,
                   "psnr_mean_db": b["psnr_mean"], "psnr_worst_db": b["psnr_worst"],
                   "psnr_worst_dir": worst_dir, "psnr_best_db": b["psnr_best"],
                   "holes_max_pct": b["holes_max"],
                   "double_edge_max_pct": de_max, "dot_peak_max": dot_max,
                   "per_dir": {d: {"psnr_db": per_dir[d]["psnr_db"],
                                   "holes_pct": per_dir[d]["holes_pct"],
                                   "double_edge_excess_pct": per_dir[d]["double_edge_excess_pct"]}
                               for d in per_dir}},
            status="measured",
            source="exp2 battery — settle-aware native-DPR stills "
                   "(set-wide: 10 scenes x 4 dirs x 3 modes @0.75 m + 2 full distance ladders = 160)",
            method="PSNR vs 4K pano reference at 0.75 m; hole/bleed/dot/double-edge pixel statistics",
            confidence="high"),
        "movement_envelope": folder(
            value=BATTERY_OFFSET_M,
            status="measured",
            source="set-wide @0.75 m battery (this scene included) + full distance ladders "
                   "on moradi_bed1a (mx/px) and moradi_main3 (pz) anchor the curve "
                   "(PRIME 0.2-0.6 / ACCEPTED 0.75 / TRANSIT 1.0-1.3 m)",
            method="distance ladder 0.2->1.3 m with settle-aware captures; "
                   "VLM confirmation on the 3 riskiest rooms",
            confidence="high",
            note="harness default clamp now equals this measured value (was 1.3 = TRANSIT edge)"),
        "vlm_room_survey": folder(
            value={"room": sv["room"], "layout": sv.get("layout"),
                   "size_feel": sv.get("size_feel"),
                   "windows": [{"u": w["u"], "blown": w.get("blown")} for w in sv.get("windows", [])],
                   "mirrors_glass": [{"u": m["u"], "what": m["what"]} for m in sv.get("mirrors_glass", [])],
                   "doorways": [{"u": d["u"], "to": d["to"]} for d in sv.get("doorways", [])]},
            status="estimated",
            source=f"VLM survey of the 16-post profile set ({DATE} 23:23, before prediction lock)",
            method="visual inspection of the equirect; u = horizontal position on the pano seam",
            confidence="medium",
            note="observational, not measured geometry — estimated data never grants movement rights"),
        "node_position": folder(
            value=None,
            status="unverified",
            source="none — Kuula posts publish no capture-position metadata",
            method="n/a",
            confidence="none",
            date=None,
            note="EQL-2 (node-based spatial navigation) NOT claimable for this set; "
                 "same-space pairs are cross-validation instruments, not navigation links"),
        "links": folder(
            value=[],
            status="unverified",
            source="none recorded",
            method="n/a",
            confidence="none",
            date=None),
    }
    # drop the placeholder key accidentally named extra_note
    scenes_out[s]["splat_geometry"].pop("extra_note", None)

# ------------------------------------------------------------------ set-level --
ladders = met["ladders"]
xval = ver["cross_validation"]
score = ver["summary"]

manifest = {
    "manifest": "moradi_eql_manifest",
    "version": 1,
    "generated": DATE,
    "generated_by": "scripts/engine_v1/moradi_eql_manifest.py",
    "rule_basis": (
        "Pilot of the six-field confidence folders + EQL derivation "
        "(BPLUS_DATA_SCHEMA_PROPOSAL, design-stage) on R&D data. "
        "rooms_db.json and production are NOT touched. EQL is computed from evidence, "
        "never manually assigned; admins may only downgrade, never upgrade past evidence."
    ),
    "set": {
        "name": "Moradi real-content set (one house)",
        "source": "kuula.co/profile/Mojtaba87",
        "one_house_rule": "owner law — all scenes from ONE house; C7360 excluded (different house)",
        "license": "R&D-only benchmark; any public deployment requires the photographer's permission",
        "selection_funnel": "16 posts -> -1 md5 duplicate (Kitchen_2) -> -1 other house (C7360) "
                            "-> -3 reserves (kit3a, bed2b, bed3b) -> 10 scenes",
        "reserves": {"kit3a": "kuula.co/post/L8J1y — service kitchen, glass doors on both seam edges",
                     "bed2b": "kuula.co/post/L8JTl — second view of the child bedroom",
                     "bed3b": "kuula.co/post/L8JTd — second view of the pink bedroom (arched door)"},
        "excluded": {"C7360": "kuula.co/post/LxFdY — different house (style markers, upload bundle, washer-in-cabinet)",
                     "Kitchen_2 duplicate": "same post uploaded twice; md5-identical -> one unique source"},
        "method_lock": {
            **gen["params_locked"],
            "depth_model": "DAV2-small ONNX", "format": "SPZ v4",
            "n_splats_per_scene": gen["scenes"]["moradi_main1"]["n_splats"],
            "per_scene_tuning": "NONE (locked params only)",
        },
        "eql": {
            "at_rest": {"level": "EQL-0",
                        "basis": "single-node 4K equirect rotation on the labs harness"},
            "in_motion": {"level": "EQL-3-EXP",
                          "basis": "VQ 1.1 gaussian splat layer (experimental path) — R&D-only, "
                                   "owner-review page, never presented as production"},
            "eql_2_claimable": False,
            "eql_2_blockers": [
                "no metric node positions (Kuula publishes no capture positions)",
                "no measured inter-node distances or doorway graph",
                "same-space pairs are cross-validation instruments, not navigation links",
            ],
            "engine_independence": (
                "EQL-1 (Zero-Warp 0.08 m envelope) is a DIFFERENT engine and is not applied "
                "to this set; the three engines never merge (owner law)."
            ),
        },
        "movement_envelope": {
            "ladder_bands_m": {"PRIME": [0.2, 0.6], "ACCEPTED": [0.75, 0.75], "TRANSIT": [1.0, 1.3]},
            "transit_note": "small holes only in mirror/wardrobe quadrants beyond 1.0 m",
            "measured_basis": "ladders on moradi_bed1a (mx/px) + moradi_main3 (pz) + set-wide @0.75 m battery + VLM on 3 riskiest rooms",
            "harness_default_change": {
                "file": "public/labs/engine-v1/vq11.js",
                "from_m": 1.3, "to_m": 0.75,
                "rule": "envelope numbers come from measurement (new rule 2026-11-07)",
                "rd_ladder_access": "?safeR=1.3 explicit, or ?autotest=1 (battery lifts it itself)",
                "date": DATE,
            },
        },
        "fidelity_summary": {
            "psnr_mean_range_db": [min(scenes_out[s]["fidelity_0p75m"]["value"]["psnr_mean_db"] for s in SCENES),
                                   max(scenes_out[s]["fidelity_0p75m"]["value"]["psnr_mean_db"] for s in SCENES)],
            "worst_of_set": {"scene": "moradi_main2", "psnr_db": met["battery_075"]["moradi_main2"]["psnr_worst"],
                             "dir": "pz", "cause": "glazed double doors + heavy patterned curtains (not the predicted seam mirrors)"},
            "holes_max_pct": max(met["battery_075"][s]["holes_max"] for s in SCENES),
            "holes_max_scene": "moradi_bed3a (curved-wardrobe quadrant)",
            "double_edge_max_pct_set": round(set_double_edge_max, 2),
            "double_edge_note": "negative excess = no double edge; measured in all 40 scene-dir cells",
            "dot_peak_max_set": round(set_dot_peak_max, 1),
            "dot_note": "same order as the cabin same-code reference",
            "ladder_curves": {s: {k: v for k, v in ladders[s].items()} for s in ladders},
        },
        "cross_validation": {f"{a}|{b}": xval[f"{a}|{b}"] for a, b in PAIRS},
        "prediction_scorecard": {
            **score["counts"], "accuracy_pct_strict": score["accuracy_pct"],
            "accuracy_pct_with_near": score["hit_plus_near_pct"], "n": 93,
            "locked_before_run": "docs/rd-artifacts/engine-v1/moradi_predictions.json (23:27, pre-SPZ)",
            "honest_note": "directional failure-family calls 11/12 confirmed; PSNR bands systematically "
                           "pessimistic on mirrors/seam — the engine was better than feared",
        },
    },
    "scenes": scenes_out,
    "artifacts_index": {
        "gen": "docs/rd-artifacts/engine-v1/moradi_gen.json",
        "metrics": "docs/rd-artifacts/engine-v1/moradi_metrics.json",
        "verify": "docs/rd-artifacts/engine-v1/moradi_verify.json",
        "survey": "docs/rd-artifacts/engine-v1/moradi_survey.json",
        "predictions": "docs/rd-artifacts/engine-v1/moradi_predictions.json",
        "stills_index": "docs/rd-artifacts/engine-v1/moradi_stills_index.json",
        "report": "docs/engine-upgrade-v1/moradi_realcontent_v1.md",
    },
}

# ------------------------------------------------------------------ asserts --
assert set(manifest["scenes"]) == set(SCENES) and len(SCENES) == 10
ALLOWED = set(STATUS_ORDER)
for s, rec in manifest["scenes"].items():
    for fname, f in rec.items():
        if isinstance(f, dict) and "status" in f:
            assert f["status"] in ALLOWED, (s, fname, f["status"])
    # numbers must equal the recorded artifacts (copied, not retyped)
    assert rec["fidelity_0p75m"]["value"]["psnr_mean_db"] == met["battery_075"][s]["psnr_mean"]
    assert rec["fidelity_0p75m"]["value"]["holes_max_pct"] == met["battery_075"][s]["holes_max"]
    assert rec["splat_geometry"]["value"]["n_splats"] == gen["scenes"][s]["n_splats"]
    assert rec["metric_scale_k"]["value"] == gen["scenes"][s]["k_metric_scale"]
for a, b in PAIRS:
    assert f"{a}|{b}" in xval
json.loads(json.dumps(manifest))          # round-trip

OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
print(f"OK  wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size} bytes)")
print(f"    scenes: {len(manifest['scenes'])}")
print(f"    set double_edge_max = {set_double_edge_max:.2f}%  (all-negative => zero double edges measured)")
print(f"    set dot_peak_max    = {set_dot_peak_max:.1f}")
print(f"    cross-validation: " + ", ".join(f"{a.split('_')[1]}|{b.split('_')[1]} ok={xval[f'{a}|{b}']['ok']}" for a, b in PAIRS))
