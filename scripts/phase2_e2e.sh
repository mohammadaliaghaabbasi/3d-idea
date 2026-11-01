#!/bin/bash
# PANODROME — Phase 2 E2E: AI X-Ray hotspots + Dream House moodboard
# enter -> xray toggle -> pin click card -> space peek -> save room -> drawer
# -> share url -> house tour from URL (?house=) -> FA RTL -> console errors
set -u
mkdir -p /tmp/render
cd /home/z/my-project/3d-idea/public
python3 -m http.server 8137 >/tmp/httpserver.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null' EXIT
sleep 1.5

agent-browser open http://localhost:8137
agent-browser storage local clear
agent-browser reload
agent-browser wait 2500
agent-browser eval "document.getElementById('btn-enter').click()"
agent-browser wait 4500
echo "room1: $(agent-browser eval "document.getElementById('room-name').textContent")"

echo "=== 1) X-Ray OFF by default ==="
agent-browser eval "'xray.active=' + window.__panodrome.xray.active + ' visiblePins=' + window.__panodrome.hotspotScreen().filter(h=>h.visible).length"

echo "=== 2) toggle X-Ray ON ==="
agent-browser eval "document.getElementById('btn-xray').click()"
agent-browser wait 1200
agent-browser eval "'xray.active=' + window.__panodrome.xray.active + ' visiblePins=' + window.__panodrome.hotspotScreen().filter(h=>h.visible).length + ' chipActive=' + document.getElementById('btn-xray').classList.contains('active')"
agent-browser screenshot /tmp/render/p2-1-xray-on.png

echo "=== 3) face a pin, then click it -> glass card ==="
agent-browser eval "
(() => {
  const P = window.__panodrome;
  const pin = P.xray.pins[0];
  const d = pin.sprite.position.clone().sub(P.camera.position);
  const c = P.controls;
  c.yaw = Math.atan2(-d.x, -d.z);
  c.pitch = Math.max(-0.5, Math.min(0.5, Math.atan2(d.y, Math.hypot(d.x, d.z))));
  return 'facing pin: ' + pin.def.title.en;
})()"
agent-browser wait 900
agent-browser eval "JSON.stringify(window.__panodrome.hotspotScreen())" --json > /tmp/hs.json 2>/dev/null
CLICK=$(python3 -c "
import json
env = json.load(open('/tmp/hs.json'))
arr = json.loads(env['data']['result'])
W, H = 1536, 960
vis = [h for h in arr if not h['behind'] and h['visible'] and 0 <= h['x'] <= W and 0 <= h['y'] <= H]
h = vis[0]
print(h['x'], h['y'], h['title'], h['cat'])")
echo "pin at: $CLICK"
set -- $CLICK; HX=$1; HY=$2
agent-browser eval "
(() => {
  const c = document.querySelector('#scene canvas');
  const ev = (t) => new PointerEvent(t, {bubbles:true, clientX:$HX, clientY:$HY, pointerId:9, isPrimary:true, pointerType:'mouse'});
  c.dispatchEvent(ev('pointerdown'));
  c.dispatchEvent(ev('pointerup'));
  return 'clicked';
})()"
agent-browser wait 600
agent-browser eval "'card open=' + document.getElementById('xray-card').classList.contains('open') + ' | title=' + document.getElementById('xray-title').textContent + ' | cat=' + document.getElementById('xray-cat-label').textContent"
agent-browser screenshot /tmp/render/p2-2-xray-card.png
agent-browser eval "document.getElementById('xray-close').click(); 'closed=' + !document.getElementById('xray-card').classList.contains('open')"

echo "=== 4) SPACE peek hold/release ==="
agent-browser eval "window.dispatchEvent(new KeyboardEvent('keydown', {code:'Space', key:' ', bubbles:true})); 'space down dispatched'"
agent-browser wait 700
agent-browser eval "'hold on: active=' + window.__panodrome.xray.active + ' hold=' + window.__panodrome.xray.holdActive + ' visPins=' + window.__panodrome.hotspotScreen().filter(h=>h.visible).length"
agent-browser eval "window.dispatchEvent(new KeyboardEvent('keyup', {code:'Space', key:' ', bubbles:true})); 'space up dispatched'"
agent-browser wait 600
agent-browser eval "'after release: visPins=' + window.__panodrome.hotspotScreen().filter(h=>h.visible).length"

echo "=== 5) save room (button) ==="
agent-browser eval "document.getElementById('btn-save').click()"
agent-browser wait 700
agent-browser eval "'saved=' + document.getElementById('btn-save').classList.contains('saved') + ' | label=' + document.getElementById('btn-save-label').textContent + ' | count=' + document.getElementById('house-count').textContent + ' | ids=' + JSON.stringify(window.__panodrome.moodboard.ids) + ' | toast=' + document.getElementById('toast').classList.contains('show')"

echo "=== 6) drawer open + share url ==="
agent-browser eval "document.getElementById('btn-house').click()"
agent-browser wait 700
agent-browser eval "'drawer=' + document.getElementById('house-drawer').classList.contains('open') + ' | items=' + document.querySelectorAll('.house-item').length + ' | share=' + window.__panodrome.moodboard.shareUrl()"
agent-browser screenshot /tmp/render/p2-3-drawer.png
agent-browser eval "document.getElementById('drawer-close').click(); 'drawer closed=' + !document.getElementById('house-drawer').classList.contains('open')"

echo "=== 7) house tour from URL (?house=cabin,ballroom,art_studio) ==="
agent-browser open "http://localhost:8137/?house=cabin,ballroom,art_studio"
agent-browser storage local clear
agent-browser reload
agent-browser wait 2500
agent-browser eval "document.getElementById('btn-enter').click()"
agent-browser wait 4500
agent-browser eval "'tour room=' + document.getElementById('room-name').textContent + ' | badge=' + document.getElementById('house-badge-text').textContent + ' | badgeHidden=' + document.getElementById('house-badge').classList.contains('hud-hidden') + ' | modeLocked=' + document.getElementById('mode-bar').classList.contains('tour-disabled')"
agent-browser eval "JSON.stringify(window.__panodrome.portalScreen().map(p=>({t:p.target,r:p.reason})))"
agent-browser eval "'db cabin idx=' + window.__panodrome.state.db.rooms.findIndex(r=>r.id==='cabin') + ' ballroom idx=' + window.__panodrome.state.db.rooms.findIndex(r=>r.id==='ballroom')"
agent-browser screenshot /tmp/render/p2-4-house-tour.png

echo "=== 8) walk through portal in tour (must stay inside chain) ==="
agent-browser eval "JSON.stringify(window.__panodrome.portalScreen())" --json > /tmp/p2.json 2>/dev/null
PCLICK=$(python3 -c "
import json
env = json.load(open('/tmp/p2.json'))
arr = json.loads(env['data']['result'])
vis = [p for p in arr if not p['behind']]
p = vis[0]
print(p['x'], p['y'], p['target'])")
echo "portal at: $PCLICK"
set -- $PCLICK; PX=$1; PY=$2; PT=$3
agent-browser eval "
(() => {
  const c = document.querySelector('#scene canvas');
  const ev = (t) => new PointerEvent(t, {bubbles:true, clientX:$PX, clientY:$PY, pointerId:9, isPrimary:true, pointerType:'mouse'});
  c.dispatchEvent(ev('pointerdown'));
  c.dispatchEvent(ev('pointerup'));
  return 'clicked';
})()"
sleep 5
agent-browser eval "'after tour transition: room=' + document.getElementById('room-name').textContent + ' | targets=' + JSON.stringify(window.__panodrome.portalScreen().map(p=>p.target))"

echo "=== 9) exit tour ==="
agent-browser eval "document.getElementById('house-badge-exit').click()"
agent-browser wait 800
agent-browser eval "'badge hidden=' + document.getElementById('house-badge').classList.contains('hud-hidden') + ' | modeLocked=' + document.getElementById('mode-bar').classList.contains('tour-disabled') + ' | targets=' + JSON.stringify(window.__panodrome.portalScreen().map(p=>p.target))"

echo "=== 10) FA RTL (drawer + save + xray card) ==="
agent-browser eval "document.getElementById('btn-lang').click()"
agent-browser wait 600
agent-browser eval "'dir=' + document.documentElement.dir + ' | saveBtn=' + document.getElementById('btn-save-label').textContent + ' | houseTitle=' + document.querySelector('#house-drawer h2').textContent"
agent-browser eval "document.getElementById('btn-xray').click()"
agent-browser wait 900
agent-browser eval "'pins fa: ' + JSON.stringify(window.__panodrome.hotspotScreen().slice(0,3).map(h=>h.title))"
agent-browser eval "window.__panodrome.xray.openCard(window.__panodrome.state.room.hotspots[0])"
agent-browser wait 400
agent-browser eval "'fa card: ' + document.getElementById('xray-title').textContent + ' | ' + document.getElementById('xray-cat-label').textContent + ' | ' + document.getElementById('xray-desc').textContent.slice(0,60)"
agent-browser screenshot /tmp/render/p2-5-fa-card.png

echo "=== errors / console ==="
agent-browser errors
agent-browser console 2>&1 | tail -8
echo PHASE2-E2E-DONE
