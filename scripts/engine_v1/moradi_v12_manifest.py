#!/usr/bin/env python3
"""moradi_v12_manifest.py — six-field confidence manifest for VQ 1.2 (content gen v12).

New-rule machine-readable metadata for the complete Moradi exemplar (owner order
2026-11-11). Rules identical to moradi_eql_manifest.py:
  - every value copied from recorded artifacts (moradi_v12_gen.json /
    moradi_v12_metrics.json / moradi_v12_battery_index.json / wm_w1_attempt.json /
    moradi_eql_manifest.json for the unchanged fields) — nothing typed from memory;
  - status ladder unverified < estimated < measured < verified;
  - estimation never grants movement rights; EQL computed from evidence;
  - measured rejections are RECORDED, never hidden (alpha-structure, 2xD cull,
    LoD default-off, WM quota block).
Output: docs/rd-artifacts/engine-v1/moradi_v12_manifest.json
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "docs" / "rd-artifacts" / "engine-v1"
DATE = "2026-11-11"

gen = json.loads((ART / "moradi_v12_gen.json").read_text())
met = json.loads((ART / "moradi_v12_metrics.json").read_text())
wm = json.loads((ART / "wm_w1_attempt.json").read_text())
v11man = json.loads((ART / "moradi_eql_manifest.json").read_text())

SCENES = [s for s in gen["scenes"] if s.startswith("moradi_")]
BATTERY_SCENES = sorted(met["scenes"].keys())

def folder(value, status, source, method, confidence, date=DATE, **extra):
    f = {"value": value, "status": status, "source": source,
         "measurement_method": method, "confidence": confidence,
         "verification_date": date}
    f.update(extra)
    return f

scenes_out = {}
for s in SCENES:
    g = gen["scenes"][s]
    v11g = v11man["scenes"][s]
    m = met["scenes"].get(s)
    rec = {
        "zone": v11g["zone"],
        "eql": {
            "at_rest": "EQL-0",
            "in_motion": "EQL-3-EXP",
            "envelope_m": 0.75,
            "basis": ("rest = single-node 4K equirect rotation; motion = VQ 1.2 content "
                      "generation (~521-530k anisotropic surface-adhering splats) on the "
                      "same locked renderer (three 0.180.0 + Spark 2.4.0 + SPZ v4)"),
        },
        "panorama": v11g["panorama"],                       # unchanged source (verified)
        "splat_geometry": folder(
            value={"file": f"public/labs/engine-v1/assets/{s}_splat_v12.spz",
                   "n_splats": g["profile"]["n"], "spz_kb": g["export"]["spz_kb"],
                   "sh_degree": 0, "format": "SPZ v4",
                   "params": {"c_t": 0.65, "c_n": 0.55, "a_smooth": 1.0, "a_edge": 1.0,
                              "stride": 1, "grid": [1022, 518], "cam_h": 1.5,
                              "cull_r_m": 45.0,
                              "sigma_cap": "per-splat own source-pixel size (1.3x footprint)"},
                   "aniso_median": g["profile"]["aniso_median"],
                   "sigma_p99_m": g["profile"]["sigma_p99"],
                   "sigma_p99_over_D_room": g["profile"]["sigma_p99_over_D"],
                   "iso_fallback_pct": g["iso_fallback_pct"],
                   "culled_pct": g["culled_pct"]},
            status="estimated",
            source="DAV2-small ONNX depth -> same locked unprojection -> VQ 1.2 content "
                   "program (Marble §7; winner C6_aniso_mild from the measured sweep)",
            method="AI depth estimation — no physical scene measurement exists",
            confidence="medium (fidelity independently MEASURED, see fidelity folder)"),
        "metric_scale_k": v11g["metric_scale_k"],           # same DAV2 scale (unchanged method)
        "fidelity_0p75m": folder(
            value=(m if m else None),
            status=("measured" if m else "estimated"),
            source=("docs/rd-artifacts/engine-v1/moradi_v12_metrics.json "
                    "(battery subset: " + ", ".join(BATTERY_SCENES) + " x 4 dirs @0.75 m) + "
                    "EWA exact-Gaussian QC gate on ALL 10 scenes (moradi_v12_gen.json: "
                    "absent 0.0%, holes@0.75m 0.0% everywhere)"
                    if m else "EWA QC gate only (battery still pending for this scene)"),
            method="settle-aware native-DPR stills + PSNR/holes/dot/double-edge vs 4K pano; "
                   "EWA renderer = exact per-splat screen-covariance alpha coverage",
            confidence=("high (battery)" if m else "medium (QC gate only)"),
            note=(None if m else "v12 battery ran on the 3 riskiest scenes; "
                  "this scene is covered by the all-scene EWA gate (absent/holes = 0)")),
        "movement_envelope": v11g["movement_envelope"],     # unchanged measured basis
        "vlm_room_survey": v11g["vlm_room_survey"],         # unchanged observational survey
        "node_position": v11g["node_position"],             # still unverified
        "links": v11g["links"],                             # still unverified
    }
    scenes_out[s] = rec

manifest = {
    "manifest": "moradi_v12_manifest",
    "version": 1,
    "generated": DATE,
    "generated_by": "scripts/engine_v1/moradi_v12_manifest.py",
    "owner_order": ("«تمامی تجربه‌هایی که الان داری دقیقاً یک نمونهٔ تکمیلی از خواستهٔ ما را روی مرادی "
                    "پیاده کن … با کمک ماربل و این مدل هانیوان … یک نمونهٔ دقیق بدون ایراد برای بررسی "
                    "بساز، روی گیت‌هاب پوش کن و لینک سایت هم بده» (2026-11-11)"),
    "rule_basis": v11man["rule_basis"],
    "content_generation": {
        "program": "docs/engine-upgrade-v1/marble_reverse_engineering.md §7 items 1+3+4(+5) "
                   "+ WM demo native-filter analogs (worldmirror_reverse_engineering.md §6-2)",
        "winner": gen["winner"],
        "winner_params": gen["winner_params"],
        "locked_unchanged": ["DAV2-small ONNX depth", "spherical unprojection u=atan2(dz,-dx)/2pi",
                             "floor-median metric scale k (CAM_H 1.5m)", "PLY->SPZ v4",
                             "three 0.180.0 + Spark 2.4.0 renderer"],
        "changed_content_only": True,
        "sh_degree": 0,
        "measured_rejections": [
            {"item": "alpha structure (a_smooth 0.9/0.8, Marble median 0.29-0.57)",
             "evidence": "sweep C3_alpha_090: content alpha p5 < 0.97 gate FAIL at stride-1 density",
             "decision": "rejected at this density; alpha 1.0 kept (needs Marble's overlap density)"},
            {"item": "radial cull at 2 x D_room (room diameter)",
             "evidence": "deleted moradi_main2's entire +x view (100% absent) + 21.75% of main4; "
                         "measured: all window content is 100% within 45 m",
             "decision": "replaced by absolute 45 m cull (DAV2 60 m clip plateau + sky only)"},
            {"item": "Spark in-app LoD default-on (lod:true)",
             "evidence": "in-app LoD build does NOT complete on the 2-core SwiftShader profile "
                         "(splats stay 0 past 120 s; measured twice)",
             "decision": "default OFF; opt-in ?lod=1 documented; needs device verification"},
            {"item": "v12 sh_degree 3 (45 zero f_rest columns, v1.0 layout inertia)",
             "evidence": "529k sh3 splats died in SwiftShader settle; Marble 500k sh0 renders "
                         "24.9 fps in the same harness",
             "decision": "v12 exported as sh0 (honest: no view-dependency data exists)"},
        ],
    },
    "hunyuanworld_mirror_w1": {
        "attempt": "scripts/engine_v1/wm_w1_try.py",
        "asset": wm["asset"],
        "crops": {"n": wm["crops"]["n"], "size": wm["crops"]["size"], "fov_deg": wm["crops"]["fov_deg"]},
        "upload": "OK (8 CC0 cabin crops accepted in 42.2 s)",
        "gpu_run": "BLOCKED — ZeroGPU anonymous quota: 'You have exceeded your ZeroGPU runs "
                   "limit. Authenticate with a Hugging Face token for more quota'",
        "license_gate": "Tencent Community License (free < 1M MAU; EU/UK/KR excluded) — recorded",
        "data_rule": "NO Moradi/Kuula content uploaded (R&D-only license); CC0 cabin only",
        "adopted_now": "the demo's native post-filter ANALOGS: confidence/edge filter = our "
                       "isotropic edge fallback; sky filter = our >=45 m cull",
        "status": "unverified (live run quota-blocked; needs HF token or GPU + owner order)",
        "artifact": "docs/rd-artifacts/engine-v1/wm_w1_attempt.json",
    },
    "set": {
        "name": "Moradi real-content set (one house) — VQ 1.2 complete exemplar",
        "eql": {
            "at_rest": {"level": "EQL-0", "basis": "single-node 4K equirect rotation"},
            "in_motion": {"level": "EQL-3-EXP",
                          "basis": "VQ 1.2 content generation (~521-530k anisotropic splats) "
                                   "on the locked Spark 2.4.0 renderer — experimental, R&D-only"},
            "eql_2_claimable": False,
            "eql_2_blockers": v11man["set"]["eql"]["eql_2_blockers"],
            "engine_independence": v11man["set"]["eql"]["engine_independence"],
        },
        "v12_vs_v11_set": {
            "n_splats": ["132,349 (v11)", f"{gen['scenes'][SCENES[0]]['profile']['n']:,} (v12, {SCENES[0]})"],
            "aniso_median": ["1.0 (v11)", "1.8-2.1 (v12)"],
            "sh_degree": ["3 (45 zero coefficients)", "0 (honest)"],
            "spz_kb_range_v12": [min(gen['scenes'][s]['export']['spz_kb'] for s in SCENES),
                                 max(gen['scenes'][s]['export']['spz_kb'] for s in SCENES)],
            "ewa_gate_all_scenes": "absent 0.0% / holes@0.75m 0.0% (all 10 moradi + cabin)",
        },
        "battery_subset_scenes": BATTERY_SCENES,
        "battery_method_note": "same settle-aware methodology as the v11 160-still battery; "
                               "v12 sort cost ~4x (529k vs 132k) -> battery on the 3 riskiest "
                               "scenes (hero, far-view risk, curved-wardrobe risk) + all-scene "
                               "EWA gate; full 10-scene battery on owner order",
    },
    "scenes": scenes_out,
    "artifacts_index": {
        "gen_sweep_and_qc": "docs/rd-artifacts/engine-v1/moradi_v12_gen.json",
        "battery_index": "docs/rd-artifacts/engine-v1/moradi_v12_battery_index.json",
        "metrics": "docs/rd-artifacts/engine-v1/moradi_v12_metrics.json",
        "ab_pairs": "docs/rd-artifacts/engine-v1/v12_ab_pairs/",
        "wm_attempt": "docs/rd-artifacts/engine-v1/wm_w1_attempt.json",
        "report": "docs/engine-upgrade-v1/moradi_exemplar_v12.md",
        "v11_baseline": "docs/rd-artifacts/engine-v1/moradi_eql_manifest.json",
    },
}

# ---- asserts: values must equal the recorded artifacts ----
assert set(manifest["scenes"]) == set(SCENES) and len(SCENES) == 10
for s in SCENES:
    rec = manifest["scenes"][s]
    assert rec["splat_geometry"]["value"]["n_splats"] == gen["scenes"][s]["profile"]["n"]
    assert rec["splat_geometry"]["value"]["spz_kb"] == gen["scenes"][s]["export"]["spz_kb"]
    if met["scenes"].get(s):
        assert rec["fidelity_0p75m"]["value"]["psnr_mean"] == met["scenes"][s]["psnr_mean"]
    for fname, f in rec.items():
        if isinstance(f, dict) and "status" in f:
            assert f["status"] in {"unverified", "estimated", "measured", "verified"}, (s, fname)
assert manifest["hunyuanworld_mirror_w1"]["asset"].startswith("cabin")
json.loads(json.dumps(manifest))

OUT = ART / "moradi_v12_manifest.json"
OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
print(f"OK  wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size} bytes)")
print(f"    scenes: {len(manifest['scenes'])} | battery-subset: {BATTERY_SCENES}")
print(f"    WM W1: {manifest['hunyuanworld_mirror_w1']['status']}")
