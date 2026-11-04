#!/usr/bin/env python3
"""Round 2: fix 404 repos via search + fetch READMEs of top candidates.
Extracts hardware/licensing/HF-space facts. Never prints the token."""
import json, os, time, urllib.request, urllib.parse, re

ROOT = "/home/z/my-project/3d-idea"
OUT = os.path.join(ROOT, "docs/rd-artifacts/survey")

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

def gh_api(url, raw=False, retries=2):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
        "User-Agent": "panodrome-rd",
    })
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace") if raw else json.load(r)
        except Exception as e:
            if i >= retries:
                return None if raw else {"_error": str(e)}
            time.sleep(3)

def search_one(q):
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": q, "sort": "stars", "order": "desc", "per_page": 6})
    res = gh_api(url)
    if "items" not in res:
        return []
    return [(i["full_name"], i["stargazers_count"], i["pushed_at"], (i["description"] or "")[:100],
             (i.get("license") or {}).get("spdx_id")) for i in res["items"]]

def slim_repo(full):
    r = gh_api(f"https://api.github.com/repos/{full}")
    if "full_name" not in r:
        return {"_error": r.get("_error")}
    return {"full_name": r["full_name"], "url": r["html_url"], "stars": r["stargazers_count"],
            "pushed_at": r["pushed_at"], "created_at": r["created_at"],
            "license": (r.get("license") or {}).get("spdx_id"), "lang": r.get("language"),
            "desc": (r.get("description") or "")[:250], "forks": r.get("forks_count"),
            "open_issues": r.get("open_issues_count")}

KEYWORDS = re.compile(r"(vram|gpu|cuda|a100|rtx|4090|3090|huggingface|hf|space|demo|onnx|cpu|"
                      r"macos|apple|metal|colab|gradio|requirements|install|pip install|conda|"
                      r"license|seconds|minutes|fps|mobile|webgl|webgpu|three\.js|ply|\.spz|splat|"
                      r"feed.?forward|fine.?tun|train)", re.I)

def readme_facts(full):
    raw = gh_api(f"https://api.github.com/repos/{full}/readme", raw=True)
    if raw is None:
        return {"_readme_error": "no readme"}
    lines = [l for l in raw.splitlines() if KEYWORDS.search(l)]
    return {"n_lines": len(raw.splitlines()), "key_lines": lines[:60]}

FIX_SEARCHES = [
    "GS-LRM large reconstruction model gaussian",
    "WonderWorld interactive 3D scene generation",
    "DepthSplat connected gaussian",
    "Flash3D feed-forward 3D",
    "Director3D",
    "LayerPano3D layered 360",
    "Pano2Room panorama gaussian",
    "HorizonNet horizon layout",
    "LED2-Net layout",
    "HoHoNet holistically",
    "PanoDreamer panorama",
    "ImmersiveGA immersive gaussian",
    "ZeroNVS zero-shot panorama",
]

CANDIDATE_READMES = [
    # cat1 panorama->3DGS
    "cedarconnor/SPAG4d", "zhichu99/PanoSplatt3R", "thucz/splatter360", "chengzhag/PanSplat",
    "nerficg-project/SPaGS", "LeoDarcy/360GS", "DECK6/ringsplat", "ShijieZhou-UCLA/DreamScene360",
    "jfirma1/ComfyUI-DreamScene360", "lukehollis/sphr",
    "apple-aiml-research/ml-sharp", "3DTopia/LGM", "AiuniAI/Unique3D", "donydchen/MVSplat360",
    # cat2 viewers
    "sparkjsdev/spark", "mkkellogg/GaussianSplats3D", "nianticlabs/spz", "playcanvas/supersplat",
    "antimatter15/splat",
    # cat3 layout
    "LIAGM/Bi_Layout", "zhijieshen-bjtu/DOPNet", "zhijieshen-bjtu/MV-DOPNet", "crs4/AtlantaNet",
    "Starrah/DMH-Net",
]

def main():
    out = {"fixed_searches": {}, "repos": {}, "readmes": {}}
    for q in FIX_SEARCHES:
        res = search_one(q)
        out["fixed_searches"][q] = res
        print(f"[search] {q}")
        for fn, st, pu, d, lic in res[:4]:
            print(f"    {fn:50s} ⭐{st:<6} {pu[:10]} lic={lic} — {d[:70]}")
        time.sleep(2.2)
    for full in CANDIDATE_READMES:
        out["repos"][full] = slim_repo(full)
        out["readmes"][full] = readme_facts(full)
        r = out["repos"][full]
        if "stars" in r:
            print(f"[repo] {full:45s} ⭐{r['stars']:<6} push:{(r['pushed_at'] or '')[:10]} lic:{r['license']}")
        else:
            print(f"[repo] {full:45s} ERR {str(r)[:60]}")
        time.sleep(0.8)
    with open(os.path.join(OUT, "github_round2.json"), "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print("saved github_round2.json")

if __name__ == "__main__":
    main()
