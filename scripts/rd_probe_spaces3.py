#!/usr/bin/env python3
"""Remote live test #3: proper TRELLIS.2 session flow + alternate SHARP mirror."""
import json, os, time, traceback

OUT = "/home/z/my-project/3d-idea/docs/rd-artifacts/survey"
IMG = "/home/z/my-project/3d-idea/docs/rd-artifacts/zerowarp/qa_cabin_bed.jpg"

def collect_files(r, files):
    if isinstance(r, str) and any(r.lower().endswith(x) for x in
            (".ply", ".spz", ".splat", ".mp4", ".gif", ".png", ".jpg", ".webp", ".glb", ".ksplat")):
        files.append(r)
    elif isinstance(r, (list, tuple)):
        for x in r: collect_files(x, files)
    elif isinstance(r, dict):
        for x in r.values(): collect_files(x, files)

def timed(fn, budget):
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(fn).result(timeout=budget)

def test_trellis_session():
    out = {"target": "microsoft/TRELLIS.2 full session flow", "error": None}
    try:
        from gradio_client import Client, handle_file
        client = timed(lambda: Client("microsoft/TRELLIS.2"), 120)
        timed(lambda: client.predict(api_name="/start_session"), 60)
        pre = timed(lambda: client.predict(input=handle_file(IMG), api_name="/preprocess_image"), 180)
        img_prompt = pre if isinstance(pre, str) else (pre[0] if isinstance(pre, (list, tuple)) else str(pre))
        out["preprocess"] = str(img_prompt)[:120]
        t0 = time.time()
        result = timed(lambda: client.predict(image=handle_file(img_prompt), seed=0, resolution="1024", api_name="/image_to_3d"), 420)
        out["wall_s"] = round(time.time() - t0, 1)
        files = []
        collect_files(result, files)
        out["files"] = files
        out["raw"] = str(result)[:200]
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        out["trace"] = traceback.format_exc()[-300:]
    return out

def test_sharp_mirror():
    out = {"target": "inoculatemedia/Apple-Sharp-Image-to-3D-View-Synthesis", "error": None}
    try:
        from gradio_client import Client, handle_file
        client = timed(lambda: Client("inoculatemedia/Apple-Sharp-Image-to-3D-View-Synthesis"), 120)
        api = client.view_api(return_format="dict")
        eps = list((api.get("named_endpoints") or {}).keys())
        out["endpoints"] = eps
        ep = "/run_sharp" if "/run_sharp" in eps else eps[0]
        t0 = time.time()
        result = timed(lambda: client.predict(
            image_path=handle_file(IMG), trajectory_type="rotate_forward",
            output_long_side="0", num_frames=30, fps=30, render_video=True, api_name=ep), 420)
        out["wall_s"] = round(time.time() - t0, 1)
        files = []
        collect_files(result, files)
        out["files"] = files
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    return out

def main():
    results = {"trellis2_session": test_trellis_session(), "sharp_mirror": test_sharp_mirror()}
    print(json.dumps(results, indent=1, default=str)[:2500])
    with open(os.path.join(OUT, "space_probes3.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)
    print("saved space_probes3.json")

if __name__ == "__main__":
    main()
