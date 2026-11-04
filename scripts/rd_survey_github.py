#!/usr/bin/env python3
"""
Panodrome R&D 2026-11-04 — Systematic GitHub API survey.
Category 1: feed-forward 360° / single-image -> 3DGS generators
Category 2: web viewers + .spz compressors
Category 3: 360° room-layout / floorplan estimators
Queries GitHub /search/repositories + direct repo GETs.
Token is read from .env (never printed). Results -> docs/rd-artifacts/survey/.
"""
import json, os, sys, time, urllib.request, urllib.parse, datetime

ROOT = "/home/z/my-project/3d-idea"
OUT = os.path.join(ROOT, "docs/rd-artifacts/survey")
os.makedirs(OUT, exist_ok=True)

def load_token():
    try:
        with open(os.path.join(ROOT, ".env")) as f:
            for line in f:
                if line.startswith("GITHUB_TOKEN="):
                    return line.strip().split("=", 1)[1]
    except FileNotFoundError:
        pass
    return os.environ.get("GITHUB_TOKEN", "")

TOKEN = load_token()

def gh_api(url, retries=2):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "panodrome-rd",
    })
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if i >= retries:
                return {"_error": str(e)}
            time.sleep(3 + i * 3)

def slim(r):
    """Slim a repo record to what the survey table needs."""
    if r is None or "_error" in r or "message" in r and "full_name" not in r:
        return r
    return {
        "full_name": r.get("full_name"),
        "url": r.get("html_url"),
        "stars": r.get("stargazers_count"),
        "updated": r.get("pushed_at"),
        "created": r.get("created_at"),
        "license": (r.get("license") or {}).get("spdx_id"),
        "lang": r.get("language"),
        "desc": (r.get("description") or "")[:200],
        "topics": r.get("topics", [])[:10],
        "archived": r.get("archived"),
    }

DIRECT_REPOS = {
    "cat1_feedforward_3dgs": [
        "apple/ml-sharp", "3DTopia/LGM", "open-mmlab/GS-LRM", "xxlong0/WonderWorld",
        "AiuniAI/Unique3D", "chenxwh?/Director3D".split("?")[0],  # placeholder fixed below
    ],
}

# --- fix the direct list properly ---
CAT1_DIRECT = [
    "apple/ml-sharp",            # SHARP (Apple)
    "3DTopia/LGM",                # Large Multi-View Gaussian model
    "open-mmlab/GS-LRM",          # GS-LRM
    "xxlong0/WonderWorld",        # WonderWorld
    "AiuniAI/Unique3D",           # Unique3D
    "Doubiiu/ToonCrafter",        # NOT needed — placeholder removed below
]
CAT1_DIRECT = [r for r in CAT1_DIRECT if "Doubiiu" not in r]
CAT1_DIRECT += [
    "donydchen/MVSplat360",       # MVSplat360 (CVPR 2025, same author family as MVSplat)
    "donydchen/MVSplat",          # MVSplat baseline for context
    "HengyiWang/DepthSplat",     # DepthSplat (CVPR 2025)
    "In3Dgame/Flash3D",           # Flash3D
    "LucasAlegre/?" if False else "imagine-imagine/Director3D",  # Director3D guess
    "JK-Lee88/LayerPano3D",       # LayerPano3D
    "arthurchen0512/Pano2Room",   # Pano2Room (failed locally before — context)
    "chingswy/DreamScene360",    # DreamScene360 guess? may 404
    "yuedong1?/None" if False else None,
]
CAT1_DIRECT = [r for r in CAT1_DIRECT if r and "?" not in r]

CAT2_DIRECT = [
    "sparkjsdev/spark",           # World Labs Spark viewer
    "mkkellogg/GaussianSplats3D", # Three.js splat viewer
    "playcanvas/supersplat",      # SuperSplat editor
    "nianticlabs/spz",            # .spz compression format lib
    "antimatter15/splat",         # reference WebGL splat viewer
    "playcanvas/engine",          # for context
    "pmndrs?" if False else "mkkellogg? " if False else "graphdeco-inria/gaussian-splatting",  # original 3DGS (context)
]
CAT2_DIRECT = [r for r in CAT2_DIRECT if "?" not in r and " " not in r]

CAT3_DIRECT = [
    "sunghoonho/HorizonNet",      # HorizonNet
    "chengsunh/led2-net",         # LED2-Net
    "cvlab-epfl/HoHoNet",         # HoHoNet
    "yocheng?" if False else None,  # AtlantaNet — search instead
    "JingwenJiaLong?/None" if False else None,
]
CAT3_DIRECT = [r for r in CAT3_DIRECT if r]

SEARCHES = [
    # Category 1 searches (feed-forward pano->3DGS, 2024-2026)
    ("cat1", "PanoSplat"),
    ("cat1", "Splatter-360"),
    ("cat1", "panorama gaussian splatting"),
    ("cat1", "360 gaussian splatting"),
    ("cat1", "panorama to 3D gaussian splatting created:>2024-06-01"),
    ("cat1", "equirectangular gaussian splatting"),
    ("cat1", "single image gaussian splatting feed-forward created:>2024-06-01"),
    ("cat1", "ODGS omni-directional gaussian splatting"),
    ("cat1", "pano room gaussian created:>2025-01-01"),
    # Category 3 searches
    ("cat3", "360 room layout estimation"),
    ("cat3", "panorama layout estimation"),
    ("cat3", "AtlantaNet"),
    ("cat3", "DOPNet"),
    ("cat3", "HoHoNet layout"),
    ("cat3", "panorama floorplan estimation created:>2023-06-01"),
    ("cat3", "equirectangular room layout onnx"),
    ("cat3", "Bi-Layout"),
    ("cat3", "horizon net layout panorama"),
]

def search_repos(q, per_page=12):
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode({
        "q": q, "sort": "stars", "order": "desc", "per_page": per_page})
    res = gh_api(url)
    if "items" not in res:
        return {"query": q, "_error": res.get("_error", res.get("message", "?"))}
    return {"query": q, "total": res.get("total_count"), "items": [slim(r) for r in res["items"]]}

def main():
    results = {"direct": {}, "search": [], "_meta": {
        "generated": datetime.datetime.now().isoformat(),
        "token_used": bool(TOKEN),
    }}
    cats = {"cat1_feedforward": CAT1_DIRECT, "cat2_viewers": CAT2_DIRECT, "cat3_layout": CAT3_DIRECT}
    for cat, repos in cats.items():
        results["direct"][cat] = {}
        for repo in repos:
            results["direct"][cat][repo] = slim(gh_api(f"https://api.github.com/repos/{repo}"))
            time.sleep(0.5)
    for cat, q in SEARCHES:
        res = search_repos(q)
        res["category"] = cat
        results["search"].append(res)
        time.sleep(2.5)  # authenticated search rate limit = 30/min
    with open(os.path.join(OUT, "github_repos.json"), "w") as f:
        json.dump(results, f, indent=1, ensure_ascii=False)
    # Print compact digest
    for cat, repos in results["direct"].items():
        print(f"\n### {cat}")
        for name, r in repos.items():
            if r and "full_name" in r:
                print(f"  {r['full_name']:45s} ⭐{r['stars']:>6}  push:{(r['updated'] or '')[:10]}  lic:{r['license']}  arch:{r['archived']}")
                print(f"      {r['desc'][:110]}")
            else:
                print(f"  {name:45s} -> {str(r)[:80]}")
    print("\n### searches")
    for s in results["search"]:
        if "items" not in s:
            print(f"  [ERR] {s['query'][:50]}: {s.get('_error')}")
            continue
        print(f"  [{s['category']}] q='{s['query'][:55]}' total={s['total']}")
        for it in s["items"][:6]:
            print(f"      {it['full_name']:48s} ⭐{it['stars']:>6} push:{(it['updated'] or '')[:10]} — {it['desc'][:80]}")

if __name__ == "__main__":
    main()
