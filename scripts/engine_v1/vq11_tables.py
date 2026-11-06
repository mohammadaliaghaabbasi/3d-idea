#!/usr/bin/env python3
"""vq11_tables.py — VQ 1.1 results tables (CSV + XLSX) for owner review.
Sheets: 1) Layer attribution (V1.0 vs V1.1) 2) Distance matrix (V1.1, 6x4)
3) Mobile load/perf profiles 4) Recommendation summary.
Output: download/panodrome-vq11/VQ11_results.xlsx + results CSVs
"""
import json, os
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

REPO = "/home/z/my-project/3d-idea"
ART = f"{REPO}/docs/rd-artifacts/engine-v1"
DL = "/home/z/my-project/download/panodrome-vq11"
os.makedirs(DL, exist_ok=True)

met = json.load(open(f"{ART}/vq11_metrics.json"))
perf = json.load(open(f"{ART}/vq11_perf.json"))
gen = json.load(open(f"{ART}/vq11_gen.json"))

wb = openpyxl.Workbook()
HDR = Font(bold=True, color="FFFFFF")
FILL = PatternFill("solid", fgColor="1F6B4A")
OKF = PatternFill("solid", fgColor="E8F5E9")
BADF = PatternFill("solid", fgColor="FCE4EC")

def style_header(ws, row=1):
    for c in ws[row]:
        if c.value is not None:
            c.font = HDR; c.fill = FILL; c.alignment = Alignment(horizontal="center")

# ---------- Sheet 1: layer attribution ----------
ws = wb.active; ws.title = "1_Layer_Attribution"
ws.append(["PANODROME VQ 1.1 — Layer attribution (which layer caused dots / blur / ghosting?)"])
ws.append([])
hdr = ["State (cabin, back-look)", "Pano bleed-through %px>12RGB", "Bleed mean |ΔRGB|",
       "Dot-grid spectral peak", "Soft holes % (α<0.5)", "True holes % (magenta)",
       "Splat sharpness (LapVar)", "Pano sharpness (LapVar)", "Composite-vs-pano PSNR dB",
       "Splat-vs-pano PSNR dB"]
ws.append(hdr)
rows = [
    ("V1.0 SHIPPED — origin, composite", "v1/origin"),
    ("V1.0 SHIPPED — 0.75m, composite", "v1/off075"),
    ("V1.1 FIXED — origin, composite", "v11/origin"),
    ("V1.1 FIXED — 0.75m, composite", "v11/off075"),
]
for label, key in rows:
    m = met["exp1"][key]
    ws.append([label, m["bleed_pct_gt12"], m["bleed_mean"], m["dot_grid_peak"],
               m["soft_holes_pct"], m["holes_pct"], m["sharp"]["splat"], m["sharp"]["pano"],
               m["compos_psnr_vs_pano_db"], m["mismatch_psnr_splat_vs_pano_db"]])
ws.append([])
ws.append(["VERDICT: dots + ghosting = SPLAT layer coverage (V1.0 σ=0.7·footprint, α=0.95 → mean coverage 64.5%, p5 45%).",
           "blur = splat source resolution (1022×518 grid / stride 2 ≈ 8× softer than 4K pano).",
           "pano layer itself renders CORRECTLY (render-vs-ideal PSNR 33.9dB, sharpness ratio 1.03).",
           "V1.1 (σ×1.86, opacity 1.0): bleed 54.6%→0.0%, dot peak 21871→1371 (16×), holes 0%."])
style_header(ws, 3)
for col, w in zip("ABCDEFGHIJ", [42, 16, 14, 14, 13, 13, 13, 13, 15, 15]):
    ws.column_dimensions[col].width = w

# ---------- Sheet 2: distance matrix ----------
ws2 = wb.create_sheet("2_Distance_Matrix_V11")
ws2.append(["PANODROME VQ 1.1 — cabin distance benchmark (V1.1 build, 4 directions, back-look, 390×844@DPR1)"])
ws2.append([])
ws2.append(["dir", "dist_m", "true holes %", "soft holes %", "pano bleed %", "dot-grid peak",
            "splat-vs-pano PSNR dB (mismatch incl. real parallax)", "sharp retention % (both vs pano)",
            "double-edge excess %"])
for m in sorted(met["exp2"], key=lambda x: (x["dist_m"], x["dir"])):
    ws2.append([m["dir"], m["dist_m"], m["holes_pct"], m["soft_holes_pct"], m["bleed_pct_gt12"],
                m["dot_grid_peak"], m["mismatch_psnr_splat_vs_pano_db"],
                m["sharp"]["retention_pct"], m["double_edge_excess_pct"]])
style_header(ws2, 3)
ws2.append([])
p = met["per_dist_summary"]
ws2.append(["MEAN per distance"])
ws2.append(["dist_m", "holes %", "soft %", "bleed %", "dot peak", "mismatch PSNR dB (mean)", "worst-dir PSNR dB"])
for dist in ["0.2", "0.4", "0.6", "0.75", "1.0", "1.3"]:
    v = p[dist]
    ws2.append([float(dist), v["holes_pct"]["mean"], v["soft_holes_pct"]["mean"], v["bleed_pct_gt12"]["mean"],
                round(v["dot_grid_peak"]["mean"], 1), v["mismatch_psnr_db"]["mean"], v["mismatch_psnr_db"]["min"]])
style_header(ws2, ws2.max_row - 6)
for col, w in zip("ABCDEFGHI", [6, 8, 12, 12, 12, 12, 24, 20, 16]):
    ws2.column_dimensions[col].width = w

# ---------- Sheet 3: mobile perf ----------
ws3 = wb.create_sheet("3_Mobile_Perf")
ws3.append(["PANODROME VQ 1.1 — mobile load & perf (iPhone-13 emulation, cold cache; fps = SwiftShader-relative)"])
ws3.append([])
ws3.append(["profile", "page config", "SPZ ready (fetch+decode) ms", "first frame ms",
            "wall to interactive ms", "idle fps*", "walk fps*", "heap MB (Chromium only)"])
for r in perf["runs"]:
    if "error" in r: continue
    ws3.append([r["profile"], r["tag"].split("/")[1], r["spz_ready_ms"], r["first_frame_ms"],
                r.get("wall_ms"), r.get("idle_fps_swiftshader"), r.get("walk_fps_swiftshader"),
                r.get("heapMB_chromium")])
ws3.append([])
ws3.append(["* fps numbers are headless-SwiftShader-relative (software GL) — NOT iPhone-13 absolute.",
            "Real-device numbers: open the lab with ?autotest=1 on iPhone Safari (in-page battery, copyable JSON).",
            "HUD 6095 ms explanation: SPZ 1.09MB over ~1.5–1.6 Mbps mobile link ≈ 5.8–6.1 s transfer",
            "(fast3g 1.6Mbps profile measured: 6108 ms; owner's 6095 ms matches within 0.2%).",
            "Engine decode itself: 475–540 ms (localhost). The 338–934 ms earlier lab result was also localhost/desktop.",
            "=> difference is NETWORK TRANSFER at the owner's bandwidth, not engine regression."])
style_header(ws3, 3)
for col, w in zip("ABCDEFGH", [26, 16, 20, 14, 16, 10, 10, 16]):
    ws3.column_dimensions[col].width = w

# ---------- Sheet 4: recommendation ----------
ws4 = wb.create_sheet("4_Recommendation")
ws4.append(["PANODROME VQ 1.1 — distance recommendation & final verdict"])
ws4.append([])
rec = [
    ("Zone", "Range", "Quality evidence"),
    ("PRIME (full quality)", "0.2 – 0.6 m", "mismatch PSNR 17.8–21.8 dB mean; VLM: coherent interior, minimal artifacts; holes 0%"),
    ("ACCEPTED (tested default)", "0.75 m", "mismatch 16.9 dB mean (worst dir 13.6); VLM: borderline-coherent, blur-only; holes 0%; PHASE-6 owner-approved SAFE_R"),
    ("TRANSIT ONLY", "1.0 – 1.3 m", "mismatch 15.2–16.0 dB; VLM: significant smearing, corner holes at 1.0m, severe at 1.3m — pass-through, don't stand"),
    ("RECOMMENDED DEFAULT", "SAFE_R = 0.75 m", "same as PHASE 6; quality-validated now on V1.1 with 4 directions; 0.6 m if owner prefers crisper"),
    ("FINAL VERDICT", "YES — current engine can deliver natural, quality movement",
     "with the V1.1 splat regeneration (same pipeline, tuned coverage: σ×1.86, opacity 1.0, same 132,349 splats, same 1.09MB SPZ). Double-image eliminated (bleed 0%); dots eliminated (16× lower lattice peak); holes 0% at all tested distances; at rest the untouched 4K pano shows. Remaining limit: splat-layer sharpness while walking (~8× softer than 4K source; inherent to single-pano 1022×518 reconstruction at 132k splats) — acceptable as a transient per VLM, and invisible at rest. No change of reconstruction method required for the 0.75m experience; for SHARPER walking views the future lever is a higher-resolution depth grid (stride 1 at same budget needs ~2× compression) — a tuning matter, not a method change."),
]
for row in rec:
    ws4.append(list(row))
style_header(ws4, 3)
for col, w in zip("ABC", [24, 22, 120]):
    ws4.column_dimensions[col].width = w
ws4.column_dimensions["C"].alignment = Alignment(wrap_text=True)

wb.save(f"{DL}/VQ11_results.xlsx")
print("saved ->", f"{DL}/VQ11_results.xlsx")

# CSV copies
import csv
with open(f"{DL}/distance_matrix_v11.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["dir", "dist_m", "holes_pct", "soft_holes_pct", "bleed_pct", "dot_grid_peak",
                "mismatch_psnr_db", "sharp_retention_pct", "double_edge_excess_pct"])
    for m in sorted(met["exp2"], key=lambda x: (x["dist_m"], x["dir"])):
        w.writerow([m["dir"], m["dist_m"], m["holes_pct"], m["soft_holes_pct"], m["bleed_pct_gt12"],
                    m["dot_grid_peak"], m["mismatch_psnr_splat_vs_pano_db"],
                    m["sharp"]["retention_pct"], m["double_edge_excess_pct"]])
with open(f"{DL}/layer_attribution.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["state", "bleed_pct", "bleed_mean", "dot_grid_peak", "soft_holes_pct", "holes_pct",
                "splat_lapvar", "pano_lapvar", "composite_vs_pano_psnr_db", "splat_vs_pano_psnr_db"])
    for key, m in met["exp1"].items():
        w.writerow([key, m["bleed_pct_gt12"], m["bleed_mean"], m["dot_grid_peak"], m["soft_holes_pct"],
                    m["holes_pct"], m["sharp"]["splat"], m["sharp"]["pano"],
                    m["compos_psnr_vs_pano_db"], m["mismatch_psnr_splat_vs_pano_db"]])
print("saved -> CSVs")
