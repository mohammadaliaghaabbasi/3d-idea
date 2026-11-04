#!/usr/bin/env python3
"""Remote live test #2: correct SHARP mirror + TRELLIS.2 image_to_3d generation."""
import json, os, time, traceback

OUT = "/home/z/my-project/3d-idea/docs/rd-artifacts/survey"
IMG = "/home/z/my-project/3d-idea/docs/rd-artifacts/zerowarp/qa_cabin_bed.jpg"

def collect_files(r, files):
    if isinstance(r, str):
        if any(r.lower().endswith(x) for x in (".ply", ".spz", ".splat", ".mp4", ".gif", ".png", ".jpg", ".webp", ".glb", ".ksplat")):
            files.append(r)
    elif isinstance(r, (list, tuple)):
        for x in r: collect_files(x, files)
    elif isinstance(r, dict):
        for x in r.values(): collect_files(x, files)

def timed(fn, budget):
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn)
        return fut.result(timeout=budget)

def test_sharp():
    out = {"target": "gagndeep/Apple-Sharp-Image-to-3D-View-Synthesis (ZeroGPU)", "error": None}
    try:
        from gradio_client import Client
        client = timed(lambda: Client("gagndeep/Apple-Sharp-Image-to-3D-View-Synthesis"), 120)
        api = client.view_api(return_format="dict")
        eps = list((api.get("named_endpoints") or {}).keys())
        out["endpoints"] = eps
        out["params"] = {k: [p.get("parameter_name") for p in (v.get("parameters") or [])]
                         for k, v in (api.get("named_endpoints") or {}).items()}
        print("SHARP endpoints:", json.dumps(out.get("params"), default=str)[:600])
        t0 = time.time()
        result = timed(lambda: client.predict(image_path=IMG, trajectory_type="rotate_forward", output_long_side="0", num_frames=30, fps=30, render_video=False, api_name="/run_sharp"), 420)
        out["wall_s"] = round(time.time() - t0, 1)
        files = []
        collect_files(result, files)
        out["files"] = files
        out["raw"] = str(result)[:300]
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        out["trace"] = traceback.format_exc()[-300:]
    return out

def test_trellis():
    out = {"target": "microsoft/TRELLIS.2 image_to_3d (ZeroGPU)", "error": None}
    try:
        from gradio_client import Client
        client = timed(lambda: Client("microsoft/TRELLIS.2"), 120)
        t0 = time.time()
        result = timed(lambda: client.predict(
            image=IMG, seed=0, resolution="1024", api_name="/image_to_3d"), 420)
        out["wall_s"] = round(time.time() - t0, 1)
        files = []
        collect_files(result, files)
        out["files"] = files
        out["raw"] = str(result)[:200]
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    return out

def main():
    results = {"sharp": test_sharp(), "trellis2": test_trellis()}
    print(json.dumps(results, indent=1, default=str)[:2000])
    with open(os.path.join(OUT, "space_probes2.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)
    print("saved space_probes2.json")

if __name__ == "__main__":
    main()
