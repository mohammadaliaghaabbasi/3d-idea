#!/usr/bin/env python3
"""HF Hub survey: search Spaces & Models for pano->3DGS + viewers + layout.
Checks runtime status (running/paused) + hardware for remote-runnability."""
import json, os, urllib.request, urllib.parse, time

OUT = "/home/z/my-project/3d-idea/docs/rd-artifacts/survey"

def hf_api(url):
    req = urllib.request.Request(url, headers={"User-Agent": "panodrome-rd"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if i >= 2:
                return {"_error": str(e)}
            time.sleep(2)

SPACE_QUERIES = [
    "spag4d", "panosplat", "panosplatt3r", "mvsplat", "splatter 360",
    "sharp view synthesis", "wonderworld", "lgm", "unique3d", "flash3d",
    "panorama gaussian", "360 gaussian", "panorama to 3d", "gaussian splatting",
    "room layout panorama", "360 room layout", "dreamscene360", "pano2room",
    "triposr", "trellis",
]

def slim_space(s):
    return {
        "id": s.get("id") or s.get("repoId"),
        "likes": s.get("likes"),
        "updatedAt": (s.get("lastModified") or "")[:10],
        "sdk": s.get("sdk"),
        "tags": [t for t in (s.get("tags") or []) if not t.startswith("arxiv") and not t.startswith("license")][:8],
    }

def space_runtime(sid):
    d = hf_api(f"https://huggingface.co/api/spaces/{sid}")
    if d.get("_error"):
        return {"error": d["_error"]}
    rt = d.get("runtime") or {}
    return {
        "stage": rt.get("stage"),
        "hardware": (rt.get("hardware") or {}).get("requested") or rt.get("hardwareRequested"),
        "sdk": d.get("sdk"),
        "sleeping": rt.get("sleeping"),
    }

def main():
    results = {"queries": {}, "runtimes": {}}
    seen = {}
    for q in SPACE_QUERIES:
        url = "https://huggingface.co/api/spaces?" + urllib.parse.urlencode(
            {"search": q, "sort": "likes", "order": "desc", "limit": 12})
        res = hf_api(url)
        if isinstance(res, dict) and "_error" in res:
            print(f"[ERR] {q}: {res['_error']}")
            continue
        items = [slim_space(s) for s in res]
        results["queries"][q] = items
        print(f"[spaces] q='{q}' -> {len(items)}")
        for it in items[:7]:
            sid = it["id"]
            mark = "" 
            print(f"    {sid:55s} ♥{it['likes']}  sdk:{it['sdk']}  upd:{it['updatedAt']}")
            seen[sid] = it
        time.sleep(1.0)
    # runtime check for the most relevant candidates
    CANDIDATES = [
        s for s in seen if any(k in s.lower() for k in [
            "spag", "panosplat", "mvsplat", "wonderworld", "lgm", "unique3d",
            "sharp", "panorama", "splat", "360", "triposr", "trellis"])
    ]
    CANDIDATES = sorted(CANDIDATES, key=lambda s: -(seen[s]["likes"] or 0))[:28]
    for sid in CANDIDATES:
        results["runtimes"][sid] = space_runtime(sid)
        rt = results["runtimes"][sid]
        print(f"[runtime] {sid:58s} stage={rt.get('stage')} hw={rt.get('hardware')} sleep={rt.get('sleeping')}")
        time.sleep(0.8)
    # model search: SHARP weights mirrored on HF? + DAV2/pano layout models
    for q in ["sharp view synthesis", "panorama layout", "360 room layout estimation"]:
        url = "https://huggingface.co/api/models?" + urllib.parse.urlencode(
            {"search": q, "sort": "likes", "order": "desc", "limit": 8})
        res = hf_api(url)
        if isinstance(res, list):
            print(f"[models] q='{q}'")
            for m in res[:6]:
                print(f"    {m.get('id','?'):60s} ♥{m.get('likes')}  dl:{m.get('downloads')}")
    with open(os.path.join(OUT, "hf_spaces.json"), "w") as f:
        json.dump(results, f, indent=1, ensure_ascii=False)
    print("saved hf_spaces.json")

if __name__ == "__main__":
    main()
