#!/usr/bin/env python3
"""moradi_video.py — MORADI REAL-CONTENT TEST motion evidence.
Two stop-motion walk videos (agent-browser DPR1, 30 fps, mode=both auto-blend
= shipped behaviour):
  1) moradi_main3 +x 0->1.3->0 m   (predicted best case, open living)
  2) moradi_bed1a -x 0->1.3->0 m   (predicted worst quadrant family: mirror+bed)
Server on 8137 (separate from the battery's 8141).
Output: download/panodrome-moradi/videos/
"""
import functools, json, math, os, subprocess, sys, threading, time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

REPO = "/home/z/my-project/3d-idea"
PORT = 8137
BASE = f"http://localhost:{PORT}/labs/engine-v1/vq11.html"
OUT = "/home/z/my-project/download/panodrome-moradi/videos"; os.makedirs(OUT, exist_ok=True)

def serve():
    os.chdir(f"{REPO}/public")
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), functools.partial(SimpleHTTPRequestHandler))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

def ab(*args, timeout=300):
    r = subprocess.run(["agent-browser", *args], capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()

def wait_ready():
    for _ in range(80):
        try:
            n = int(ab("eval", "window.__vq ? window.__vq.stats().splats : 0").strip().strip('"'))
            if n and n > 0:
                ab("eval", "window.__vq.state({mode:'splat',dir:'+x',offset:0,look:'back',bg:'magenta'})")
                time.sleep(6)
                pct = ab("eval", """(() => {
                  const c = document.querySelector('canvas');
                  const t = document.createElement('canvas'); t.width = 100; t.height = 200;
                  const x = t.getContext('2d');
                  x.drawImage(c, 0, 0, c.width, c.height, 0, 0, 100, 200);
                  const d = x.getImageData(0,0,100,200).data;
                  let mag = 0;
                  for (let i=0;i<d.length;i+=4){const r=d[i],g=d[i+1],b=d[i+2]; if(r>200&&b>200&&g<120) mag++;}
                  return (100 - 100*mag/(d.length/4)).toFixed(1);
                })()""").strip().strip('"')
                ab("eval", "window.__vq.state({mode:'both',dir:'+x',offset:0,look:'back',bg:'black'})")
                return float(pct)
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("never ready")

def video(scene, waypoints, path, mps=0.9, post=2.5):
    url = f"{BASE}?scene={scene}&gen=v11&mode=both&ui=0&offset=0&dir=%2Bx&look=back&blend=auto"
    ab("open", url)
    pct = wait_ready()
    time.sleep(0.8)
    ab("record", "start", path)
    ab("eval", f"window.__vq.runWalkPath({json.dumps(waypoints)}, {mps})")
    dist = sum(math.hypot(waypoints[i][0]-waypoints[i-1][0], waypoints[i][1]-waypoints[i-1][1])
               for i in range(1, len(waypoints)))
    time.sleep(dist/mps + post)
    ab("record", "stop")
    time.sleep(1.5)
    return path, pct

def main():
    serve()
    log = []
    for scene, wp, name in (("moradi_main3", [[0,0],[1.3,0],[0,0]], "moradi_main3_walk_px_0to13to0"),
                            ("moradi_bed1a", [[0,0],[-1.3,0],[0,0]], "moradi_bed1a_walk_mx_0to13to0")):
        p, pct = video(scene, wp, f"{OUT}/{name}.webm")
        log.append({"video": p, "scene": scene, "ready_content_pct": pct})
        print("video", p, "content%", pct, flush=True)
    json.dump(log, open(f"{OUT}/index.json", "w"), indent=1)
    print(json.dumps(log, indent=1))
    ab("close")

if __name__ == "__main__":
    main()
