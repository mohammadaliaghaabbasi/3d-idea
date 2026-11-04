#!/usr/bin/env python3
"""
v1_license_audit.py — PHASE 2: independent live license audit for every component
of the Panodrome CPU Splat Engine + Spark runtime. Fetches GitHub API + HF API,
saves raw evidence, prints a verdict table. Token read from .env (never printed).
"""
import json, os, sys, urllib.request, urllib.error

REPO = "/home/z/my-project/3d-idea"
OUT = f"{REPO}/docs/rd-artifacts/engine-v1/license_raw"
os.makedirs(OUT, exist_ok=True)

env = {}
for line in open(f"{REPO}/.env"):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1); env[k] = v
TOK = env.get("GITHUB_TOKEN", "")

def gh(path):
    req = urllib.request.Request(f"https://api.github.com{path}", headers={
        "Authorization": f"Bearer {TOK}", "Accept": "application/vnd.github+json",
        "User-Agent": "panodrome-license-audit"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def raw(url):
    req = urllib.request.Request(url, headers={"User-Agent": "panodrome-license-audit"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()

def hf_model(repo_id):
    req = urllib.request.Request(f"https://huggingface.co/api/models/{repo_id}",
                                 headers={"User-Agent": "panodrome-license-audit"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

repos = [
    # (id, github_fullname, role, claim)
    ("dav2",            "LiheYoung/Depth-Anything-V2",        "depth weights source repo", "Apache-2.0 (owner claim)"),
    ("spz",             "nianticlabs/spz",                    "PLY->SPZ compression (prod)", "MIT (owner claim)"),
    ("spark",           "sparkjsdev/spark",                  "web splat viewer (target runtime)", "MIT (owner claim)"),
    ("gs3d",            "mkkellogg/GaussianSplats3D",        "fallback viewer (three 0.160)", "MIT (owner claim)"),
    ("three",           "mrdoob/three.js",                    "webGL engine (prod 0.160 + lab 0.180)", "MIT (owner claim)"),
    ("onnxruntime",     "microsoft/onnxruntime",              "CPU inference runtime", "MIT"),
    ("spag4d",          "cedarconnor/SPAG4d",                  "architecture reference (idea only, code NOT copied)", "owner says now MIT — verify"),
    ("ringsplat",       "DECK6/ringsplat",                     "unverified by owner — verify repo+license", "MIT claimed by owner"),
    ("sharp",           "apple-aiml-research/ml-sharp",        "RESTRICTED candidate", "code: Apple Sample Code / weights: research-only"),
    ("unisharp",        "Insta360-Research-Team/UniSHARP",     "restricted candidate", "NOASSERTION"),
]
results = []
for rid, full, role, claim in repos:
    ev = {"id": rid, "repo": full, "role": role, "claim": claim}
    try:
        d = gh(f"/repos/{full}")
        lic = d.get("license") or {}
        ev.update({"spdx": lic.get("spdx_id"), "license_name": lic.get("name"),
                   "stars": d.get("stargazers_count"), "pushed_at": d.get("pushed_at"),
                   "archived": d.get("archived"), "default_branch": d.get("default_branch")})
        try:
            lraw = raw(f"https://raw.githubusercontent.com/{full}/{d['default_branch']}/LICENSE")
            ev["license_head"] = lraw.decode("utf-8", "replace")[:400]
        except Exception:
            ev["license_head"] = None
    except Exception as e:
        ev["error"] = str(e)
    results.append(ev)
    print(f"[{rid}] {full}: spdx={ev.get('spdx')} stars={ev.get('stars')} pushed={ev.get('pushed_at')}")

# search repos the owner could not verify
for q in ["DA360", "OmniRoam", "PaGeR panorama gaussian"]:
    try:
        s = gh(f"/search/repositories?q={urllib.parse.quote(q)}&sort=stars&per_page=5")
        print(f"\nSEARCH '{q}':")
        for it in s.get("items", [])[:5]:
            print(f"  - {it['full_name']} ({it['stargazers_count']}*) license={it.get('license') and it['license']['spdx_id']} pushed={it['pushed_at']} :: {(it.get('description') or '')[:80]}")
            results.append({"id": f"search:{q}", "repo": it["full_name"], "stars": it["stargazers_count"],
                            "spdx": (it.get("license") or {}).get("spdx_id") if it.get("license") else None,
                            "desc": (it.get("description") or "")[:120]})
    except Exception as e:
        print(f"search {q}: {e}")

# HF model license tags (ONNX weights actually used by the engine)
hf_models = ["onnx-community/depth-anything-v2-small", "depth-anything/Depth-Anything-V2-Small"]
for m in hf_models:
    try:
        d = hf_model(m)
        tags = d.get("tags", [])
        lic = [t for t in tags if t.startswith("license:")]
        print(f"\nHF {m}: license tags={lic}")
        results.append({"id": f"hf:{m}", "license_tag": lic, "downloads": d.get("downloads")})
    except Exception as e:
        print(f"HF {m}: {e}")
        results.append({"id": f"hf:{m}", "error": str(e)})

# SPAG4d README dependency/credits table (owner cited DA360+DAP as commercial-OK there)
try:
    readme = raw("https://raw.githubusercontent.com/cedarconnor/SPAG4d/main/README.md").decode("utf-8", "replace")
    open(f"{OUT}/spag4d_readme.md", "w").write(readme)
    keep = [l for l in readme.splitlines() if any(k in l for k in ("DA360", "DAP", "PaGeR", "SHARP", "OmniRoam", "icense"))][:40]
    print("\nSPAG4d README relevant lines:")
    for l in keep: print("  |", l[:160])
    results.append({"id": "spag4d_readme_lines", "lines": keep})
except Exception as e:
    print(f"spag4d readme: {e}")

import urllib.parse  # noqa (late import used above)
json.dump(results, open(f"{OUT}/license_audit_raw.json", "w"), indent=1, ensure_ascii=False)
print(f"\nraw evidence -> {OUT}/license_audit_raw.json")
