#!/usr/bin/env python3
"""Remote route live-probe: ZeroGPU Spaces via gradio_client (free, no local GPU).
Targets: community SHARP space, microsoft/TRELLIS.2, ashawkey/LGM.
Time-boxed: each call wrapped in try/except with a hard timeout."""
import json, os, time, traceback

OUT = "/home/z/my-project/3d-idea/docs/rd-artifacts/survey"
IMG = "/home/z/my-project/3d-idea/docs/rd-artifacts/zerowarp/qa_cabin_bed.jpg"

SPACES = [
    "gagandeep/Apple-Sharp-Image-to-3D-View-Synthesis",
    "microsoft/TRELLIS.2",
    "ashawkey/LGM",
]

def probe(sid):
    res = {"space": sid, "api": None, "error": None}
    t0 = time.time()
    try:
        from gradio_client import Client
        import concurrent.futures as cf
        with cf.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(Client, sid)
            client = fut.result(timeout=90)
        try:
            api = client.view_api(return_format="dict")
            res["api"] = {k: {
                "named_parameters": list((v.get("parameters") or {}).keys()) if isinstance(v, dict) else None,
                "returns": [str(r)[:80] for r in ((v.get("returns") or {}).get("parameter_names") or [])] if isinstance(v, dict) else None,
            } for k, v in (api.get("named_endpoints") or {}).items()}
        except Exception as e:
            res["api_error"] = str(e)[:200]
        res["connect_s"] = round(time.time() - t0, 1)
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    return res

def predict_sharp():
    """The key remote test: single perspective image -> 3DGS on free ZeroGPU."""
    out = {"target": "SHARP community space", "error": None, "outputs": []}
    try:
        from gradio_client import Client
        import concurrent.futures as cf
        with cf.ThreadPoolExecutor(max_workers=1) as ex:
            client = ex.submit(Client, "gagandeep/Apple-Sharp-Image-to-3D-View-Synthesis").result(timeout=90)
        api = client.view_api(return_format="dict")
        eps = list((api.get("named_endpoints") or {}).keys())
        out["endpoints"] = eps
        ep = "/predict" if "/predict" in eps else eps[0]
        with cf.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(client.predict, IMG, api_name=ep)
            result = fut.result(timeout=280)
        out["raw"] = str(result)[:400]
        files = []
        def walk(r):
            if isinstance(r, str):
                if any(r.endswith(x) for x in (".ply", ".spz", ".mp4", ".gif", ".png", ".jpg", ".webp", ".glb")):
                    files.append(r)
            elif isinstance(r, (list, tuple)):
                for x in r: walk(x)
            elif isinstance(r, dict):
                for x in r.values(): walk(x)
        walk(result)
        out["files"] = files
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        out["trace"] = traceback.format_exc()[-400:]
    return out

def main():
    results = {"probes": [], "sharp_predict": None}
    for sid in SPACES:
        r = probe(sid)
        print(json.dumps(r, indent=1, default=str)[:900])
        results["probes"].append(r)
    print("\n=== SHARP live prediction (ZeroGPU) ===")
    results["sharp_predict"] = predict_sharp()
    print(json.dumps(results["sharp_predict"], indent=1, default=str)[:1200])
    with open(os.path.join(OUT, "space_probes.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)
    print("saved space_probes.json")

if __name__ == "__main__":
    main()
