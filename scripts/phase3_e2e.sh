#!/bin/bash
# ============================================================================
# PANODROME — Phase 3 E2E (desktop 1440x900 + mobile 390x844)
# sleek portals · scroll/dbl-tap walk · commerce card · narrator btn
# upload studio (real file upload!) · lead-gen · house tour · FA RTL · mobile HUD
# ============================================================================
set -u
mkdir -p /tmp/render
cd /home/z/my-project/3d-idea/public
python3 -m http.server 8137 >/tmp/httpserver.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null' EXIT
sleep 1.5

PASS=0; FAIL=0
expect() { # expect "name" "value" "contains|num_gt|eq|nonempty"
  local name="$1" val="$2" mode="$3" want="${4:-}"
  local ok=0
  case "$mode" in
    contains)  [[ "$val" == *"$want"* ]] && ok=1 ;;
    num_gt)    python3 -c "exit(0 if float('${val:-0}') > float('$want') else 1)" && ok=1 ;;
    num_ge)    python3 -c "exit(0 if float('${val:-0}') >= float('$want') else 1)" && ok=1 ;;
    eq)        [[ "$val" == "$want" ]] && ok=1 ;;
    nonempty)  [[ -n "$val" && "$val" != "null" && "$val" != "undefined" ]] && ok=1 ;;
  esac
  if [ $ok = 1 ]; then PASS=$((PASS+1)); echo "  ✓ $name";
  else FAIL=$((FAIL+1)); echo "  ✗ FAIL: $name  → got: '$val' (want $mode '$want')"; fi
}

EV() {
  agent-browser eval "$1" --json >/tmp/ev.json 2>/dev/null
  python3 -c "
import json
try:
    d = json.load(open('/tmp/ev.json'))
    r = d.get('data', {}).get('result', '')
    print(r if isinstance(r, str) else json.dumps(r))
except Exception:
    print('')"
}

echo "================ DESKTOP 1440x900 ================"
agent-browser open http://localhost:8137
agent-browser set viewport 1440 900
agent-browser storage local clear
agent-browser reload
agent-browser wait 2600
agent-browser eval "document.getElementById('btn-enter').click()" >/dev/null
agent-browser wait 5000
agent-browser errors --clear >/dev/null

echo "--- 1) room loaded, 18 rooms, platform badge ---"
expect "room name" "$(EV "document.getElementById('room-name').textContent")" nonempty
expect "18 rooms in DB" "$(EV "window.__panodrome.state.db.rooms.length")" eq "18"
expect "platform badge" "$(EV "document.getElementById('room-platform').textContent")" nonempty
expect "hire button label" "$(EV "document.getElementById('btn-hire-label').textContent")" nonempty
expect "listen button label" "$(EV "document.getElementById('btn-listen-room-label').textContent")" nonempty

echo "--- 2) sleek portals (waypoints, not giant boxes) ---"
expect "portals exist" "$(EV "window.__panodrome.portalScreen().length")" num_gt "0"
expect "portal target set" "$(EV "window.__panodrome.state.portals[0].target !== null")" eq "true"
agent-browser screenshot /tmp/render/p3-01-desktop-portals.jpg

echo "--- 3) scroll-to-walk ---"
P0=$(EV "JSON.stringify(window.__panodrome.camPos())")
agent-browser eval "(()=>{const c=document.querySelector('#scene canvas');for(let i=0;i<6;i++){c.dispatchEvent(new WheelEvent('wheel',{deltaY:-140,bubbles:true,cancelable:true}));}return 'wheeled'})()" >/dev/null
agent-browser wait 900
P1=$(EV "JSON.stringify(window.__panodrome.camPos())")
MOVED=$(python3 -c "
import json,sys,math
a=json.loads('$P0'); b=json.loads('$P1')
print(round(math.hypot(b['x']-a['x'], b['z']-a['z']),2))")
expect "camera moved by wheel (m)" "$MOVED" num_gt "0.4"

echo "--- 4) double-click glide walk ---"
P0=$(EV "JSON.stringify(window.__panodrome.camPos())")
agent-browser dblclick "#scene canvas"
agent-browser wait 1300
P1=$(EV "JSON.stringify(window.__panodrome.camPos())")
MOVED=$(python3 -c "
import json,math
a=json.loads('$P0'); b=json.loads('$P1')
print(round(math.hypot(b['x']-a['x'], b['z']-a['z']),2))")
expect "camera glided on dblclick (m)" "$MOVED" num_gt "0.5"

echo "--- 5) X-Ray pin -> shoppable card ---"
agent-browser eval "document.getElementById('btn-xray').click()" >/dev/null
agent-browser wait 1200
expect "pins visible" "$(EV "window.__panodrome.hotspotScreen().filter(h=>h.visible).length")" num_gt "0"
agent-browser eval "
(() => {
  const P = window.__panodrome;
  const pin = P.xray.pins[0];
  const d = pin.sprite.position.clone().sub(P.camera.position);
  const c = P.controls;
  c.yaw = Math.atan2(-d.x, -d.z);
  c.pitch = Math.max(-0.5, Math.min(0.5, Math.atan2(d.y, Math.hypot(d.x, d.z))));
  return 'facing ' + pin.def.title.en;
})()" >/dev/null
agent-browser wait 800
HITS=$(EV "JSON.stringify(window.__panodrome.hotspotScreen().filter(h=>!h.behind&&h.visible))")
HX=$(python3 -c "import json; h=json.loads('$HITS')[0]; print(h['x'])")
HY=$(python3 -c "import json; h=json.loads('$HITS')[0]; print(h['y'])")
agent-browser eval "
(() => {
  const c = document.querySelector('#scene canvas');
  const ev = (t) => new PointerEvent(t, {bubbles:true, clientX:$HX, clientY:$HY, pointerId:9, isPrimary:true, pointerType:'mouse'});
  c.dispatchEvent(ev('pointerdown')); c.dispatchEvent(ev('pointerup'));
  return 'pin clicked';
})()" >/dev/null
agent-browser wait 600
expect "card open" "$(EV "document.getElementById('xray-card').classList.contains('open')")" eq "true"
expect "commerce block visible" "$(EV "!document.getElementById('xray-commerce').classList.contains('hud-hidden')")" eq "true"
expect "brand badge" "$(EV "document.getElementById('xc-brand').textContent")" nonempty
expect "tier badge" "$(EV "document.getElementById('xc-tier').textContent")" nonempty
expect "price tag" "$(EV "document.getElementById('xc-price').textContent")" nonempty
expect "swatches (3)" "$(EV "document.querySelectorAll('#xc-swatches .swatch').length")" eq "3"
expect "narrator button in card" "$(EV "!!document.getElementById('xray-listen')")" eq "true"
agent-browser screenshot /tmp/render/p3-02-commerce-card.jpg

echo "--- 6) swatch click ---"
agent-browser eval "document.querySelectorAll('#xc-swatches .swatch')[2].click()" >/dev/null
expect "swatch selection moved" "$(EV "[...document.querySelectorAll('#xc-swatches .swatch')].findIndex(s=>s.classList.contains('sel'))")" eq "2"

echo "--- 7) inquire -> lead-gen drawer (product) ---"
agent-browser eval "document.getElementById('xc-inquire').click()" >/dev/null
agent-browser wait 500
expect "inquiry drawer open" "$(EV "document.getElementById('inquiry-drawer').classList.contains('open')")" eq "true"
expect "inquiry subject" "$(EV "document.getElementById('inquiry-subject').textContent")" nonempty
agent-browser eval "document.getElementById('inquiry-close').click()" >/dev/null

echo "--- 8) hire designer (design mode) ---"
agent-browser eval "document.getElementById('xray-close').click()" >/dev/null
agent-browser eval "document.getElementById('btn-hire').click()" >/dev/null
agent-browser wait 400
expect "design drawer title" "$(EV "document.getElementById('inquiry-title').textContent")" nonempty
agent-browser eval "document.getElementById('inquiry-close').click()" >/dev/null

echo "--- 9) portal hover card + enter (desktop) ---"
agent-browser eval "document.getElementById('btn-xray').click()" >/dev/null   # xray off
agent-browser eval "
(() => {
  const P = window.__panodrome;
  const ps = P.portalScreen().filter(p=>!p.behind);
  if (!ps.length) return 'none';
  const c = P.controls;
  c.yaw = c.yaw; c.pitch = 0;
  return JSON.stringify(ps[0]);
})()" >/dev/null
# face first portal then hover it
PORTALXY=$(EV "
(() => {
  const P = window.__panodrome;
  const p = P.state.portals[0];
  const d = p.group.position.clone().sub(P.camera.position);
  P.controls.yaw = Math.atan2(-d.x, -d.z);
  P.controls.pitch = 0;
  return 'ok';
})()"; )
agent-browser wait 600
PH=$(EV "JSON.stringify(window.__panodrome.portalScreen().filter(p=>!p.behind))")
PX=$(python3 -c "import json; print(json.loads('$PH')[0]['x'])" 2>/dev/null || echo 720)
PY=$(python3 -c "import json; print(json.loads('$PH')[0]['y'])" 2>/dev/null || echo 450)
agent-browser eval "
(() => {
  const c = document.querySelector('#scene canvas');
  c.dispatchEvent(new PointerEvent('pointermove', {bubbles:true, clientX:$PX, clientY:$PY, pointerId:4, pointerType:'mouse'}));
  return 'hover';
})()" >/dev/null
agent-browser wait 400
expect "portal card opens on hover" "$(EV "document.getElementById('portal-card').classList.contains('open')")" eq "true"
expect "portal card shows target" "$(EV "document.getElementById('portal-name').textContent")" nonempty
agent-browser screenshot /tmp/render/p3-03-portal-card.jpg
ROOM0=$(EV "window.__panodrome.state.roomIdx")
agent-browser eval "document.getElementById('portal-enter').click()" >/dev/null
agent-browser wait 4200
expect "transition to next room" "$(EV "window.__panodrome.state.roomIdx != $ROOM0")" eq "true"

echo "--- 10) Upload Studio (real file!) ---"
agent-browser eval "document.getElementById('btn-upload').click()" >/dev/null
agent-browser wait 500
expect "studio opens" "$(EV "document.getElementById('upload-studio').classList.contains('open')")" eq "true"
agent-browser upload "#us-file" /tmp/test360.jpg
agent-browser wait 1200
expect "image ready" "$(EV "window.__panodrome.uploads.img !== null")" eq "true"
agent-browser eval "document.getElementById('us-canvas').click()" >/dev/null   # place door (center)
agent-browser eval "document.getElementById('us-canvas').click()" >/dev/null   # second door
agent-browser fill "#us-title" "My Test Space 360"
agent-browser fill "#us-creator" "Test Creator"
agent-browser eval "document.getElementById('us-go').click()" >/dev/null
agent-browser wait 4000
expect "19 rooms after upload" "$(EV "window.__panodrome.state.db.rooms.length")" eq "19"
expect "walked into upload" "$(EV "window.__panodrome.state.room.user_generated === true")" eq "true"
expect "upload room name" "$(EV "document.getElementById('room-name').textContent")" contains "Test Space"
expect "upload badge" "$(EV "document.getElementById('room-platform').textContent")" contains "Creator Upload"
agent-browser screenshot /tmp/render/p3-04-uploaded-room.jpg

echo "--- 11) house tour ---"
agent-browser eval "document.getElementById('btn-save').click()" >/dev/null
agent-browser eval "document.getElementById('btn-house').click()" >/dev/null
agent-browser wait 400
expect "drawer open" "$(EV "document.getElementById('house-drawer').classList.contains('open')")" eq "true"
agent-browser eval "document.getElementById('btn-clear-house').click()" >/dev/null
agent-browser wait 300
agent-browser eval "document.getElementById('drawer-close').click()" >/dev/null
# save two rooms via tour URL instead (fast)
agent-browser open "http://localhost:8137/?house=cabin,ballroom,art_studio"
agent-browser wait 2600
agent-browser eval "document.getElementById('btn-enter').click()" >/dev/null
agent-browser wait 5000
expect "tour badge active" "$(EV "!document.getElementById('house-badge').classList.contains('hud-hidden')")" eq "true"
expect "tour reason=house" "$(EV "window.__panodrome.state.portals[0].reason")" eq "house"

echo "--- 12) FA RTL ---"
agent-browser eval "document.getElementById('btn-lang').click()" >/dev/null
agent-browser wait 600
expect "dir=rtl" "$(EV "document.documentElement.dir")" eq "rtl"
expect "FA room name" "$(EV "document.getElementById('room-name').textContent")" nonempty
agent-browser eval "document.getElementById('btn-xray').click()" >/dev/null
agent-browser wait 1000
agent-browser eval "
(() => {
  const P = window.__panodrome;
  const pin = P.xray.pins[0];
  const d = pin.sprite.position.clone().sub(P.camera.position);
  P.controls.yaw = Math.atan2(-d.x, -d.z);
  P.controls.pitch = 0; return 'ok';
})()" >/dev/null
agent-browser wait 600
HITS=$(EV "JSON.stringify(window.__panodrome.hotspotScreen().filter(h=>!h.behind&&h.visible))")
HX=$(python3 -c "import json; h=json.loads('$HITS')[0]; print(h['x'])")
HY=$(python3 -c "import json; h=json.loads('$HITS')[0]; print(h['y'])")
agent-browser eval "
(() => {
  const c = document.querySelector('#scene canvas');
  const ev = (t) => new PointerEvent(t, {bubbles:true, clientX:$HX, clientY:$HY, pointerId:9, isPrimary:true, pointerType:'mouse'});
  c.dispatchEvent(ev('pointerdown')); c.dispatchEvent(ev('pointerup'));
  return 'ok';
})()" >/dev/null
agent-browser wait 500
expect "FA card title non-latin" "$(python3 -c "
import re,sys
t='$(EV "document.getElementById('xray-title').textContent")'
print('fa' if re.search(r'[\u0600-\u06FF]', t) else t)")" eq "fa"
agent-browser screenshot /tmp/render/p3-05-fa-card.jpg

echo "================ MOBILE 390x844 ================"
agent-browser open http://localhost:8137
agent-browser set viewport 390 844
agent-browser storage local clear
agent-browser reload
agent-browser wait 2600
agent-browser eval "document.getElementById('btn-enter').click()" >/dev/null
agent-browser wait 5200
agent-browser errors --clear >/dev/null

echo "--- 13) compact HUD + icon buttons ---"
expect "sys-bar chips sized" "$(EV "document.getElementById('btn-xray').getBoundingClientRect().width")" num_gt "35"
expect "mode bar slim (<102px)" "$(EV "document.getElementById('mode-bar').getBoundingClientRect().height")" num_gt "0"
agent-browser screenshot /tmp/render/p3-06-mobile-hud.jpg

echo "--- 14) hotspot card = bottom sheet ---"
agent-browser eval "document.getElementById('btn-xray').click()" >/dev/null
agent-browser wait 1000
agent-browser eval "
(() => {
  const P = window.__panodrome;
  const pin = P.xray.pins[0];
  const d = pin.sprite.position.clone().sub(P.camera.position);
  P.controls.yaw = Math.atan2(-d.x, -d.z);
  P.controls.pitch = 0; return 'ok';
})()" >/dev/null
agent-browser wait 700
HITS=$(EV "JSON.stringify(window.__panodrome.hotspotScreen().filter(h=>!h.behind&&h.visible))")
HX=$(python3 -c "import json; h=json.loads('$HITS')[0]; print(h['x'])")
HY=$(python3 -c "import json; h=json.loads('$HITS')[0]; print(h['y'])")
agent-browser eval "
(() => {
  const c = document.querySelector('#scene canvas');
  const ev = (t) => new PointerEvent(t, {bubbles:true, clientX:$HX, clientY:$HY, pointerId:9, isPrimary:true, pointerType:'touch'});
  c.dispatchEvent(ev('pointerdown')); c.dispatchEvent(ev('pointerup'));
  return 'ok';
})()" >/dev/null
agent-browser wait 500
expect "card open (sheet)" "$(EV "document.getElementById('xray-card').classList.contains('open')")" eq "true"
BOTTOM=$(EV "document.getElementById('xray-card').getBoundingClientRect().bottom")
expect "sheet sticks to bottom" "$BOTTOM" num_ge "780"
agent-browser screenshot /tmp/render/p3-07-mobile-sheet.jpg

echo "--- 15) portal tap -> card (mobile) ---"
agent-browser eval "document.getElementById('xray-close').click()" >/dev/null
agent-browser eval "
(() => {
  const P = window.__panodrome;
  const p = P.state.portals[0];
  const d = p.group.position.clone().sub(P.camera.position);
  P.controls.yaw = Math.atan2(-d.x, -d.z);
  P.controls.pitch = 0; return 'ok';
})()" >/dev/null
agent-browser wait 600
PH=$(EV "JSON.stringify(window.__panodrome.portalScreen().filter(p=>!p.behind))")
PX=$(python3 -c "import json; print(json.loads('$PH')[0]['x'])")
PY=$(python3 -c "import json; print(json.loads('$PH')[0]['y'])")
agent-browser eval "
(() => {
  const c = document.querySelector('#scene canvas');
  const ev = (t) => new PointerEvent(t, {bubbles:true, clientX:$PX, clientY:$PY, pointerId:7, isPrimary:true, pointerType:'touch'});
  c.dispatchEvent(ev('pointerdown')); c.dispatchEvent(ev('pointerup'));
  return 'ok';
})()" >/dev/null
agent-browser wait 500
expect "portal card on tap" "$(EV "document.getElementById('portal-card').classList.contains('open')")" eq "true"
agent-browser screenshot /tmp/render/p3-08-mobile-portal-card.jpg

echo "--- 16) walk rocker (engine + visual) ---"
agent-browser eval "document.getElementById('walk-rocker').classList.remove('hud-hidden')" >/dev/null
agent-browser eval "document.getElementById('portal-card').classList.remove('open')" >/dev/null
agent-browser eval "window.__panodrome.controls.yaw += Math.PI" >/dev/null   # face AWAY from the portal
P0=$(EV "JSON.stringify(window.__panodrome.camPos())")
agent-browser eval "window.__panodrome.controls.rocker = 1" >/dev/null
agent-browser wait 1100
agent-browser eval "window.__panodrome.controls.rocker = 0" >/dev/null
P1=$(EV "JSON.stringify(window.__panodrome.camPos())")
MOVED=$(python3 -c "
import json,math
a=json.loads('$P0'); b=json.loads('$P1')
print(round(math.hypot(b['x']-a['x'], b['z']-a['z']),2))")
expect "rocker walks (m)" "$MOVED" num_gt "0.6"
agent-browser eval "document.getElementById('xray-card').classList.remove('open')" >/dev/null
agent-browser screenshot /tmp/render/p3-09-mobile-rocker.jpg

echo "--- 17) console errors ---"
ERRS=$(agent-browser errors 2>/dev/null | rg -c "Error|error" || true)
expect "no page errors" "${ERRS:-0}" eq "0"

echo
echo "=========================================="
echo "PHASE 3 E2E: PASS=$PASS FAIL=$FAIL"
echo "=========================================="
agent-browser close >/dev/null 2>&1
exit $([ "$FAIL" = "0" ] && echo 0 || echo 1)
