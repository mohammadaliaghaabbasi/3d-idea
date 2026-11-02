#!/usr/bin/env python3
"""Remote HF Space tests v2: simplified + fixed param names.
Usage: rd_remote_spaces.py hunyuan|splatter"""
import time, os, sys, urllib.request

OUT = "/tmp/rd/out"
os.makedirs(OUT, exist_ok=True)
LOG = open(f"{OUT}/remote_log.txt", "a", buffering=1)
def log(*a):
    msg = " ".join(str(x) for x in a)
    print(msg, flush=True); LOG.write(msg + "\n")

from gradio_client import Client, handle_file

def test_hunyuan():
    t0 = time.time()
    log("=== Hunyuan3D-2 /shape_generation START ===")
    try:
        c = Client("tencent/Hunyuan3D-2", verbose=False)
        log(f"[{time.time()-t0:.0f}s] connected")
        job = c.submit(
            caption="green upholstered armchair",
            image=handle_file("/tmp/rd/out/persp_sofa_left.jpg"),
            steps=30, guidance_scale=5.0, seed=1234, octree_resolution=256,
            check_box_rembg=True, num_chunks=8000, randomize_seed=True,
            api_name="/shape_generation")
        log(f"[{time.time()-t0:.0f}s] job submitted; polling (max 11 min)...")
        import threading
        def watchdog():
            while True:
                time.sleep(30)
                try:
                    st = job.status()
                    log(f"[{time.time()-t0:.0f}s] status={st.code} queue={getattr(st,'rank',None)}")
                except Exception:
                    return
        threading.Thread(target=watchdog, daemon=True).start()
        res = job.result()
        log(f"[{time.time()-t0:.0f}s] RESULT in {time.time()-t0:.0f}s total")
        files = []
        def walk(r):
            if isinstance(r, (list, tuple)):
                for x in r: walk(x)
            elif hasattr(r, "url"): files.append(r.url)
            elif isinstance(r, str) and r.startswith("http"): files.append(r)
        walk(res)
        log(f"files: {files[:12]}")
        for i, u in enumerate(files):
            try:
                ext = os.path.splitext(u.split("?")[0])[1] or ".bin"
                p = f"{OUT}/hunyuan_out_{i}{ext}"
                urllib.request.urlretrieve(u, p)
                log(f"  downloaded {p} {os.path.getsize(p)} bytes")
            except Exception as e:
                log(f"  dl fail {str(e)[:120]}")
        with open(f"{OUT}/hunyuan_time.json", "w") as f:
            import json; json.dump({"total_s": round(time.time()-t0, 1)}, f)
    except Exception as e:
        log(f"Hunyuan3D-2 FAIL after {time.time()-t0:.0f}s: {type(e).__name__}: {str(e)[:300]}")

def test_splatter():
    t0 = time.time()
    log("=== splatter_image START ===")
    try:
        c = Client("szymanowiczs/splatter_image", verbose=False)
        api = c.view_api(return_format="dict")["named_endpoints"]
        log("endpoints/params:", {k: [p.get("parameter_name") for p in v.get("parameters", [])]
                                  for k, v in api.items() if k != "/check_input_image"})
        src = "/tmp/rd/out/persp_sofa_left.jpg"
        r0 = None
        try:
            r0 = c.predict(input_image=handle_file(src), api_name="/check_input_image")
            log(f"[{time.time()-t0:.0f}s] check_input OK")
        except Exception as e:
            log(f"check_input skip: {str(e)[:100]}")
        pre_url = None
        try:
            r1 = c.predict(input_image=handle_file(src), preprocess_background=True,
                           api_name="/preprocess")
            log(f"[{time.time()-t0:.0f}s] preprocess -> {str(r1)[:150]}")
            def grab_url(r):
                if isinstance(r, (list, tuple)):
                    for x in r:
                        u = grab_url(x)
                        if u: return u
                if hasattr(r, "url"): return r.url
                if isinstance(r, str) and r.startswith("http"): return r
                return None
            pre_url = grab_url(r1)
        except Exception as e:
            log(f"preprocess fail: {str(e)[:120]}")
        img = handle_file(pre_url) if pre_url else handle_file(src)
        r2 = c.predict(image=img, api_name="/reconstruct_and_export")
        log(f"[{time.time()-t0:.0f}s] reconstruct -> {str(r2)[:400]}")
        def grab_dl(r, tag):
            if isinstance(r, (list, tuple)):
                for x in r: grab_dl(x, tag)
            elif hasattr(r, "url"): grab_dl(r.url, tag)
            elif isinstance(r, str) and r.startswith("http"):
                try:
                    ext = os.path.splitext(r.split("?")[0])[1] or ".bin"
                    p = f"{OUT}/splatter_{tag}{ext}"
                    urllib.request.urlretrieve(r, p)
                    log(f"  downloaded {p} {os.path.getsize(p)} bytes")
                except Exception as e:
                    log(f"  dl fail {str(e)[:120]}")
        grab_dl(r2, "out")
        log(f"splatter DONE in {time.time()-t0:.0f}s")
    except Exception as e:
        log(f"splatter_image FAIL after {time.time()-t0:.0f}s: {type(e).__name__}: {str(e)[:300]}")

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("hunyuan", "both"): test_hunyuan()
    if which in ("splatter", "both"): test_splatter()
    log("DONE")
