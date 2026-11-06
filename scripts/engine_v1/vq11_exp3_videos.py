#!/usr/bin/env python3
"""vq11_exp3_videos.py — VQ 1.1 motion videos (agent-browser, DPR1 = true CSS px).
Per distance: walk out & back (look back), mode=both, auto crossfade (the real
shipped behaviour). Plus V1.0-vs-V1.1 comparison at 0.75 m and a 4-direction
tour at the recommended distance. 30 fps recording.
"""
import json, math, os, subprocess, sys, time

BASE = "http://localhost:8137/labs/engine-v1/vq11.html"
OUT = "/home/z/my-project/download/panodrome-vq11/videos"; os.makedirs(OUT, exist_ok=True)

def ab(*args, timeout=240):
    r = subprocess.run(["agent-browser", *args], capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()

def wait_ready():
    for _ in range(60):
        try:
            n = int(ab("eval", "window.__vq ? window.__vq.stats().splats : 0").strip().strip('"'))
            if n and n > 0:
                # Spark sort warm-up: wait until first splat frame has content
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

def video(gen, waypoints, path, mps=0.9, look=None, post=2.5):
    url = f"{BASE}?scene=cabin&gen={gen}&mode=both&ui=0&offset=0&dir=%2Bx&look=back&blend=auto"
    ab("open", url)
    pct = wait_ready()
    if look:
        ab("eval", f"window.__vq.setLook({look[0]}, {look[1]})")
    time.sleep(0.8)
    ab("record", "start", path)
    ab("eval", f"window.__vq.runWalkPath({json.dumps(waypoints)}, {mps})")
    dist = sum(math.hypot(waypoints[i][0]-waypoints[i-1][0], waypoints[i][1]-waypoints[i-1][1])
               for i in range(1, len(waypoints)))
    time.sleep(dist / mps + post)
    ab("record", "stop")
    return path, pct

def main():
    ab("close", "--all")
    ab("set", "viewport", "390", "844", "1")
    log = []
    # per-distance walk videos (V1.1), look back (-x = toward capture point)
    for d in (0.2, 0.4, 0.6, 0.75, 1.0, 1.3):
        p, pct = video("v11", [[0,0],[d,0],[0,0]], f"{OUT}/v11_walk_{str(d).replace('.','')}.mp4")
        log.append({"video": p, "gen": "v11", "dist_m": d, "ready_content_pct": pct})
        print("video", p, "content%", pct, flush=True)
    # V1.0 comparison at 0.75 m
    p, pct = video("v1", [[0,0],[0.75,0],[0,0]], f"{OUT}/v1_walk_075.mp4")
    log.append({"video": p, "gen": "v1", "dist_m": 0.75, "ready_content_pct": pct})
    print("video", p, "content%", pct, flush=True)
    # 4-direction tour at 0.75 m (V1.1): out+back in each direction
    p, pct = video("v11", [[0,0],[0.75,0],[0,0],[0,0.75],[0,0],[0,-0.75],[0,0],[0.75,0],[0,0],[-0.75,0],[0,0]],
                   f"{OUT}/v11_tour_075.mp4")
    log.append({"video": p, "gen": "v11", "dist_m": 0.75, "tour": True, "ready_content_pct": pct})
    print("video", p, "content%", pct, flush=True)
    json.dump(log, open("/tmp/vq11/videos/index.json", "w"), indent=1)
    print(json.dumps(log, indent=1))

if __name__ == "__main__":
    main()
