#!/usr/bin/env python3
"""moradi_tables.py — MORADI REAL-CONTENT TEST results workbook.
Sheets: 0) source selection (15 Kuula posts -> 10) 1) predictions vs measured
(guess-card scoring — the core sheet) 2) 0.75 m battery 10 scenes x 4 dirs
3) distance ladders 4) load/size per scene 5) verdict (FA).
Output: download/panodrome-moradi/MORADI_results.xlsx
"""
import json, os
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

REPO = "/home/z/my-project/3d-idea"
ART = f"{REPO}/docs/rd-artifacts/engine-v1"
DL = "/home/z/my-project/download/panodrome-moradi"; os.makedirs(DL, exist_ok=True)

survey = json.load(open(f"{ART}/moradi_survey.json"))
pred = json.load(open(f"{ART}/moradi_predictions.json"))
gen = json.load(open(f"{ART}/moradi_gen.json"))
met = json.load(open(f"{ART}/moradi_metrics.json"))
ver = json.load(open(f"{ART}/moradi_verify.json"))
idx = json.load(open(f"{ART}/moradi_stills_index.json"))

TITLES = {"moradi_main1": "Main_1 sitting", "moradi_main2": "Main_2 entry",
          "moradi_main3": "Main_3 open living", "moradi_main4": "Main_4 open living B",
          "moradi_kit1": "Kitchen_1", "moradi_kit2": "Kitchen_2",
          "moradi_bed1a": "Bedroom_1-1", "moradi_bed1b": "Bedroom_1-2",
          "moradi_bed2a": "Bedroom_2-1", "moradi_bed3a": "Bedroom_3-1"}
SCENES = list(TITLES)

wb = openpyxl.Workbook()
HDR = Font(bold=True, color="FFFFFF")
FILL = PatternFill("solid", fgColor="1F6B4A")
HITF = PatternFill("solid", fgColor="E8F5E9")
NEARF = PatternFill("solid", fgColor="FFF8E1")
MISSF = PatternFill("solid", fgColor="FCE4EC")

def style_header(ws, row=1):
    for c in ws[row]:
        if c.value is not None:
            c.font = HDR; c.fill = FILL; c.alignment = Alignment(horizontal="center", wrap_text=True)

# ---------- Sheet 0: selection ----------
ws = wb.active; ws.title = "0_Selection"
ws.append(["MORADI REAL-CONTENT TEST — Kuula profile Mojtaba87, moradi house (one apartment)"])
ws.append(["15 unique sources (Kitchen_2 duplicate removed by md5; C7360 excluded = different house)"])
ws.append([])
ws.append(["scene", "Kuula title", "post URL", "room (VLM)", "size", "min wall m",
           "blown windows u", "mirrors u", "glossy floor", "nadir", "SELECTED"])
sel_set = set(SCENES)
name2scene = {}
for sid, title in [("main1","Main_1_moradi"),("main2","Main_2_moradi"),("main3","Main_3_moradi"),
                   ("main4","Main_4_moradi"),("kit1","Kitchen_1_moradi"),("kit2","Kitchen_2_moradi"),
                   ("bed1a","Bedroom_1-1_moradi"),("bed1b","Bedroom_1-2_moradi"),
                   ("bed2a","Bedroom_2-1_moradi"),("bed3a","Bedroom_3-1_moradi"),
                   ("bed2b","Bedroom_2-2_moradi"),("bed3b","Bedroom_3-2_moradi"),
                   ("kit3a","Kitchen_3_moradi"),("kit3b","Kitchen_3-2_moradi"),("c7360","C7360")]:
    name2scene[title] = f"moradi_{sid}" if sid in sel_set else None
for k, v in survey.items():
    z = v["vlm"]
    wins = "; ".join(f"u={w['u']}{' BLOWN' if w.get('blown') else ''}" for w in z.get("windows", []))
    mgs = "; ".join(f"u={m['u']}" for m in z.get("mirrors_glass", [])) or "—"
    ws.append([name2scene.get(v["title"]) or "—", v["title"], v["kuula_post"],
               str(z.get("room", "?")), str(z.get("size_feel", "?")), z.get("dist_to_wall_min_m", "?"),
               wins or "—", mgs, str(z.get("glossy_floor")), str(z.get("nadir")),
               "YES" if name2scene.get(v["title"]) else "no"])
style_header(ws, 4)
ws.column_dimensions["C"].width = 34; ws.column_dimensions["D"].width = 26
ws.column_dimensions["G"].width = 30; ws.column_dimensions["H"].width = 22

# ---------- Sheet 1: predictions vs measured ----------
ws = wb.create_sheet("1_Guess_vs_Measured")
ws.append(["GUESS CARDS — locked BEFORE pipeline run (docs/rd-artifacts/engine-v1/moradi_predictions.json)"])
ws.append([])
ws.append(["scene", "metric / state", "predicted", "measured", "score"])
n = 0
for pid in pred["predictions"].keys():          # prediction keys are short ids (main1, ...)
    scene = f"moradi_{pid}"
    p = pred["predictions"].get(pid); r = ver["per_scene"].get(pid)
    if not p or not r or "error" in r: continue
    rows = [
        ("holes% max @0.75 (all dirs)", str(p["pred"]["holes_pct_075_all_dirs"]), str(r["bands"]["holes_all"]["meas"]), r["bands"]["holes_all"]["score"]),
        ("bleed% (V1.1 anchor)", str(p["pred"]["bleed_pct"]), str(r["bands"]["bleed"]["meas"]), r["bands"]["bleed"]["score"]),
        ("dot peak (lattice anchor)", str(p["pred"]["dot_peak"]), str(r["bands"]["dot_peak"]["meas"]), r["bands"]["dot_peak"]["score"]),
        ("sharp retention %", str(p["pred"]["sharp_retention_pct"]), str(r["bands"]["sharp_ret"]["meas"]), r["bands"]["sharp_ret"]["score"]),
    ]
    for code, s in r["per_state_psnr"].items():
        rows.append((f"PSNR dB @0.75 travel {code} (view {s['viewed']})", str(s["pred"]), str(s["meas"]), s["score"]))
    rows.append(("worst-state call", p["pred"]["worst_state"][:40],
                 f"actual: {r['worst_state']['actual_worst_code']}", r["worst_state"]["score"]))
    for row in rows:
        ws.append([TITLES[scene], *row])
        c = ws.cell(ws.max_row, 5)
        c.fill = {"HIT": HITF, "NEAR": NEARF, "MISS": MISSF}.get(row[3], PatternFill())
        n += 1
    ws.append([])
style_header(ws, 3)
ws.column_dimensions["A"].width = 24; ws.column_dimensions["B"].width = 40
ws.column_dimensions["C"].width = 18; ws.column_dimensions["D"].width = 14
ws.append([f"TOTAL: {ver['summary']['counts']} — accuracy {ver['summary']['accuracy_pct']}% HIT, "
           f"{ver['summary']['hit_plus_near_pct']}% HIT+NEAR (n={sum(ver['summary']['counts'].values())})"])
ws.append(["cross-validation: " + json.dumps(ver.get("cross_validation", {}), ensure_ascii=False)])

# ---------- Sheet 2: 0.75 battery ----------
ws = wb.create_sheet("2_Battery_075")
ws.append(["0.75 m (accepted SAFE_R) x 4 travel dirs x 3 modes — per-dir metrics (worst PSNR = scene risk)"])
ws.append([])
ws.append(["scene", "travel", "viewed", "holes %", "soft holes %", "bleed %", "dot peak",
           "sharp ret %", "PSNR dB", "double-edge + %"])
for scene in SCENES:
    if scene not in met["battery_075"]: continue
    for code in ("px", "mx", "pz", "mz"):
        d = met["battery_075"][scene]["per_dir"].get(code)
        if not d: continue
        ws.append([TITLES[scene], code, d["viewed_dir"], d["holes_pct"], d["soft_holes_pct"],
                   d["bleed_pct"], d["dot_peak"], d["sharp_ret_pct"], d["psnr_db"],
                   d["double_edge_excess_pct"]])
    ws.append([TITLES[scene] + " — SUMMARY", "", "",
               met["battery_075"][scene]["holes_max"], "",
               met["battery_075"][scene]["bleed_max"], "",
               met["battery_075"][scene]["sharp_ret_mean"],
               f"mean {met['battery_075'][scene]['psnr_mean']} worst {met['battery_075'][scene]['psnr_worst']}",
               met["battery_075"][scene]["de_excess_max"]])
    ws.append([])
style_header(ws, 3)

# ---------- Sheet 3: ladders ----------
ws = wb.create_sheet("3_Ladders")
ws.append(["distance ladders 0.2-1.3 m — predicted-worst dir + calm dir"])
ws.append([])
ws.append(["scene", "dir", "offset m", "holes %", "PSNR dB", "sharp ret %", "DE + %"])
for scene, lad in met.get("ladders", {}).items():
    for k, d in lad.items():
        code, dt = k.rsplit("_", 1)
        ws.append([TITLES.get(scene, scene), code, d["offset_m"], d["holes_pct"],
                   d["psnr_db"], d["sharp_ret_pct"], d["double_edge_excess_pct"]])
    ws.append([])
style_header(ws, 3)

# ---------- Sheet 4: load/size ----------
ws = wb.create_sheet("4_Load_Size")
ws.append(["real-content asset + harness load marks (SwiftShader-relative, DPR1) — SPZ ~1 MB like cabin"])
ws.append([])
ws.append(["scene", "SPZ KB", "pano KB", "n splats", "k metric", "far-clip % (blown windows)",
           "origin alpha p5", "spz ready ms", "first frame ms"])
for scene in SCENES:
    g = gen["scenes"].get(scene)
    st = (idx.get("scenes", {}).get(scene, {}) or {}).get("stats_end", {}) or {}
    marks = st.get("marks", {}) if isinstance(st, dict) else {}
    if not g: continue
    ws.append([TITLES[scene], g["spz_kb"], g["pano_kb"], g["n_splats"], g["k_metric_scale"],
               g["depth_clip_hi_pct"], g["origin_qc"]["alpha_p5"],
               marks.get("spz_ready_ms", st.get("spzReadyMs", "—")),
               marks.get("first_frame_ms", st.get("firstFrameMs", "—"))])
style_header(ws, 3)

# ---------- Sheet 5: verdict (FA) ----------
ws = wb.create_sheet("5_Verdict_FA")
ws.append(["MORADI REAL-CONTENT TEST — حکم نهایی (Persian)"])
ws.append([])
ws.append(["سؤال مالک: آیا موتور فعلی روی محتوای واقعیِ یک خانهٔ کامل، تجربهٔ حرکت طبیعی و باکیفیت می‌دهد؟"])
ws.append([])
vp = pred["house_level_predictions"]["final_question_answer_predicted"]
ws.append(["پیش‌بینی قفل‌شده (قبل از اجرا):", vp])
ws.append([])
ws.append(["نتایج کلیدی (پس از اندازه‌گیری):"])
for scene in SCENES:
    if scene not in met["battery_075"]: continue
    b = met["battery_075"][scene]
    ws.append([TITLES[scene], f"PSNR mean {b['psnr_mean']} / worst {b['psnr_worst']} dB",
               f"holes max {b['holes_max']}%", f"bleed max {b['bleed_max']}%",
               f"DE+ max {b['de_excess_max']}%"])
ws.append([])
ws.append(["دقت حدس‌ها:", json.dumps(ver["summary"], ensure_ascii=False)])
ws.append(["اعتبارسنجی متقاطع:", json.dumps(ver.get("cross_validation", {}), ensure_ascii=False)])

wb.save(f"{DL}/MORADI_results.xlsx")
print("saved ->", f"{DL}/MORADI_results.xlsx")
