#!/usr/bin/env python3
"""v1_run_with_rss.py — run rd_pano_to_splat.py in-process, report peak RSS (PHASE 1)."""
import runpy, resource, time, sys

t0 = time.time()
runpy.run_path("/home/z/my-project/3d-idea/scripts/rd_pano_to_splat.py", run_name="__main__")
wall = time.time() - t0
peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(f"\n[wrapper] wall={wall:.2f}s  PEAK_RSS={peak_kb/1024:.1f} MB (ru_maxrss, whole process incl. ONNX session)")
