#!/bin/bash
# ============================================================================
# PANODROME — STAGE 1 E2E (gated pipeline)
# Desktop 1440x900 + iPhone 13 390x844 (mobile UA + touch emulation)
#
# Verifies the Stage-1 contract:
#   · pristine sphere (mathematical zero-distortion proof, float32 tolerance)
#   · 4K texture live
#   · ALL visible UI inside [8px, vw-8] x [8px, vh-8]  (LTR + RTL)
#   · optical glide (wheel / double-tap / thumb pad / reset / tap-out)
#   · doorway waypoint ring + optical warp (fov 70->38 ->70)
#   · Vazirmatn FA/EN toggle, Persian counter
#   · zero page errors
# ============================================================================
set -u
mkdir -p /tmp/render
cd /home/z/my-project/3d-idea/public
python3 -m http.server 8137 >/tmp/httpserver.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null' EXIT
sleep 1.5

PASS=0; FAIL=0
expect() { # expect "name" "value" "mode" "want"
  local name="$1" val="$2" mode="$3" want="${4:-}"
  local ok=0
  case "$mode" in
    contains)    [[ "$val" == *"$want"* ]] && ok=1 ;;
    num_lt)      python3 -c "exit(0 if float('${val:-99}') < float('$want') else 1)" 2>/dev/null && ok=1 ;;
    num_gt)      python3 -c "exit(0 if float('${val:-0}') > float('$want') else 1)" 2>/dev/null && ok=1 ;;
    num_lt_abs)  python3 -c "exit(0 if abs(float('${val:-99}')) < float('$want') else 1)" 2>/dev/null && ok=1 ;;
    eq)          [[ "$val" == "$want" ]] && ok=1 ;;
    nonempty)    [[ -n "$val" && "$val" != "null" && "$val" != "undefined" ]] && ok=1 ;;
    not_none)    [[ "$val" != "none" ]] && ok=1 ;;
    json_true)   [[ "$val" == "true" || "$val" == "True" ]] && ok=1 ;;
  esac
  if [ $ok = 1 ]; then PASS=$((PASS+1)); echo "  ✓ $name";
  else FAIL=$((FAIL+1)); echo "  ✗ FAIL: $name  → got: '$val' (want $mode '$want')"; fi
}

EV_D() {
  agent-browser --session d eval "$1" --json >/tmp/ev.json 2>/dev/null
  python3 -c "
import json
try:
    d = json.load(open('/tmp/ev.json'))
    r = d.get('data', {}).get('result', '')
    print(r if isinstance(r, str) else json.dumps(r))
except Exception:
    print('')"
}
EV_M() {
  agent-browser --session m eval "$1" --json >/tmp/ev.json 2>/dev/null
  python3 -c "
import json
try:
    d = json.load(open('/tmp/ev.json'))
    r = d.get('data', {}).get('result', '')
    print(r if isinstance(r, str) else json.dumps(r))
except Exception:
    print('')"
}
ERRCOUNT() {
  agent-browser --session "$1" errors --json 2>/dev/null | python3 -c "
import json,sys
try:
    d = json.load(sys.stdin)
    print(len(d.get('data',{}).get('errors',[])))
except Exception:
    print('?')"
}

BOUNDS_JS='(() => { const b = window.__panodrome.uiBounds(); return JSON.stringify({all: b.every(x => x.inside), items: b}); })()'
AIM_JS="(() => { const P = window.__panodrome; const d = P.state.waypoint.group.position.clone().sub(P.camera.position); P.controls.yaw = Math.atan2(-d.x, -d.z); P.controls.pitch = Math.atan2(d.y, Math.hypot(d.x, d.z)); return 'aimed'; })()"

# deterministic in-page tap on the 3D canvas (pointer events, zero CLI lag)
TAP_JS='((x, y) => { const c = document.querySelector("#scene canvas"); const o = {bubbles: true, cancelable: true, pointerId: 77, isPrimary: true, pointerType: "mouse", clientX: x, clientY: y}; c.dispatchEvent(new PointerEvent("pointerdown", o)); c.dispatchEvent(new PointerEvent("pointerup", o)); return "tapped"; })(%s, %s)'

agent-browser close --all >/dev/null 2>&1 || true
sleep 1

echo "================ DESKTOP 1440x900 ================"
agent-browser --session d open http://localhost:8137 >/dev/null 2>&1
agent-browser --session d set viewport 1440 900 >/dev/null 2>&1
agent-browser --session d storage local clear >/dev/null 2>&1
agent-browser --session d reload >/dev/null 2>&1
agent-browser --session d wait 2600
agent-browser --session d errors --clear >/dev/null 2>&1

echo "--- 1) intro is present, button in-bounds ---"
expect "intro visible" "$(EV_D "document.getElementById('intro').classList.contains('gone') ? 'hidden' : 'visible'")" eq "visible"
expect "enter btn in bounds" "$(EV_D "(() => { const r = document.getElementById('btn-enter').getBoundingClientRect(); return r.x >= 8 && r.y >= 8 && r.x + r.width <= innerWidth - 8 && r.y + r.height <= innerHeight - 8; })()")" json_true
agent-browser --session d screenshot /tmp/render/s1_intro.jpg >/dev/null 2>&1

echo "--- 2) enter -> room 1 loads ---"
agent-browser --session d eval "document.getElementById('btn-enter').click()" >/dev/null 2>&1
agent-browser --session d wait 4000
expect "room title" "$(EV_D "document.getElementById('room-title').textContent")" eq "Anniversary Lounge"
expect "6 curated rooms" "$(EV_D "window.__panodrome.rooms().length")" eq "6"
expect "designer shown" "$(EV_D "document.getElementById('room-designer').textContent")" eq "Greg Zaal"
expect "source badge" "$(EV_D "document.getElementById('room-source').textContent")" eq "PolyHaven · CC0"
expect "counter" "$(EV_D "document.getElementById('nav-count').textContent")" eq "(1 of 6)"
expect "hint present" "$(EV_D "document.getElementById('nav-hint').textContent")" nonempty

echo "--- 3) MATHEMATICAL zero-distortion proof (pristine sphere) ---"
expect "sphere radius deviation < 1mm on 500m sphere (float32 rounding only)" "$(EV_D "window.__panodrome.spherePurity()")" num_lt "0.001"
expect "4K texture live" "$(EV_D "window.__panodrome.textureSize().join('x')")" eq "4096x2048"

echo "--- 4) UI bounds LTR (all visible elements strictly inside 8px) ---"
expect "all UI in bounds (EN)" "$(EV_D "$BOUNDS_JS")" contains '"all":true'
agent-browser --session d screenshot /tmp/render/s1_desktop_rest.jpg >/dev/null 2>&1

echo "--- 5) optical glide: wheel ---"
agent-browser --session d eval "(() => { const c = document.querySelector('#scene canvas'); for (let i = 0; i < 7; i++) c.dispatchEvent(new WheelEvent('wheel', {deltaY: -140, bubbles: true, cancelable: true})); return 'done'; })()" >/dev/null 2>&1
agent-browser --session d wait 1700
expect "w glided > 0.5" "$(EV_D "window.__panodrome.controls.w")" num_gt "0.5"
expect "fov narrowed < 58" "$(EV_D "window.__panodrome.camera.fov")" num_lt "58"
expect "camera leaned in (micro-parallax 0.18m)" "$(EV_D "window.__panodrome.camera.position.distanceTo(window.__panodrome.controls.base)")" num_gt "0.08"
agent-browser --session d screenshot /tmp/render/s1_desktop_glided.jpg >/dev/null 2>&1
expect "all UI in bounds (glided)" "$(EV_D "$BOUNDS_JS")" contains '"all":true'

echo "--- 6) step back: scroll reverse ---"
agent-browser --session d eval "(() => { const c = document.querySelector('#scene canvas'); for (let i = 0; i < 4; i++) c.dispatchEvent(new WheelEvent('wheel', {deltaY: 140, bubbles: true, cancelable: true})); return 'done'; })()" >/dev/null 2>&1
agent-browser --session d wait 1900
expect "scroll back: w returns toward 0" "$(EV_D "window.__panodrome.controls.w")" num_lt_abs "0.4"
expect "fov back near rest (~70)" "$(EV_D "Math.abs(window.__panodrome.camera.fov - 70) < 10")" json_true
agent-browser --session d eval "window.__panodrome.resetView()" >/dev/null 2>&1
agent-browser --session d wait 1500

echo "--- 7) reset-view button (بازگشت به مرکز فضا) ---"
agent-browser --session d eval "window.__panodrome.setGlide(1)" >/dev/null 2>&1
agent-browser --session d wait 1600
expect "view button = reset mode (icon swapped)" "$(EV_D "document.getElementById('btn-view-reset').style.display")" not_none
agent-browser --session d eval "document.getElementById('btn-view').click()" >/dev/null 2>&1
agent-browser --session d wait 1600
expect "w reset to ~0" "$(EV_D "window.__panodrome.controls.w")" num_lt_abs "0.12"
expect "view button = fullscreen mode again" "$(EV_D "document.getElementById('btn-view-full').style.display")" not_none

echo "--- 8) double-click = turn toward point + glide ---"
agent-browser --session d eval "(() => { window.__yaw0 = window.__panodrome.controls.yaw; const c = document.querySelector('#scene canvas'); const o = {bubbles: true, cancelable: true, pointerId: 9, isPrimary: true, pointerType: 'mouse', clientX: 980, clientY: 420}; c.dispatchEvent(new PointerEvent('pointerdown', o)); c.dispatchEvent(new PointerEvent('pointerup', o)); c.dispatchEvent(new PointerEvent('pointerdown', o)); c.dispatchEvent(new PointerEvent('pointerup', o)); return 'dbl'; })()" >/dev/null 2>&1
agent-browser --session d wait 1800
expect "dbl: glide engaged" "$(EV_D "window.__panodrome.controls.wTarget")" num_gt "0.6"
expect "dbl: camera turned (yaw moved)" "$(EV_D "Math.abs(window.__panodrome.controls.yaw - window.__yaw0)")" num_gt "0.05"
agent-browser --session d eval "window.__panodrome.resetView()" >/dev/null 2>&1
agent-browser --session d wait 1400

echo "--- 9) doorway waypoint ring on-screen + optical warp ---"
agent-browser --session d eval "$AIM_JS" >/dev/null 2>&1
agent-browser --session d wait 350
WPJSON="$(EV_D "JSON.stringify(window.__panodrome.waypointScreen())")"
echo "    waypoint: $WPJSON"
expect "waypoint in front, on screen" "$(EV_D "(() => { const w = window.__panodrome.waypointScreen(); return !w.behind && w.x > 8 && w.x < innerWidth - 8 && w.y > 8 && w.y < innerHeight - 8; })()")" json_true
expect "waypoint targets art_studio" "$(EV_D "window.__panodrome.waypointScreen().target")" eq "art_studio"
# hover the ring (desktop) -> chip appears
WPX="$(EV_D "window.__panodrome.waypointScreen().x")"
WPY="$(EV_D "window.__panodrome.waypointScreen().y")"
agent-browser --session d mouse move "$WPX" "$WPY" >/dev/null 2>&1
agent-browser --session d wait 500
expect "hover chip opens" "$(EV_D "!document.getElementById('wp-chip').classList.contains('hud-hidden')")" json_true
expect "chip in bounds" "$(EV_D "(() => { const r = document.getElementById('wp-chip').getBoundingClientRect(); return r.x >= 8 && r.y >= 8 && r.x + r.width <= innerWidth - 8 && r.y + r.height <= innerHeight - 8; })()")" json_true
agent-browser --session d screenshot /tmp/render/s1_desktop_waypoint.jpg >/dev/null 2>&1
# deterministic in-page click on the ring -> optical warp
agent-browser --session d eval "$(printf "$TAP_JS" "$WPX" "$WPY")" >/dev/null 2>&1
agent-browser --session d wait 3500
expect "warped to room 2" "$(EV_D "window.__panodrome.state.room.id")" eq "art_studio"
expect "counter = 2 of 6" "$(EV_D "document.getElementById('nav-count').textContent")" eq "(2 of 6)"
expect "fov settled ~70 after warp" "$(EV_D "Math.abs(window.__panodrome.camera.fov - 70)")" num_lt "3"
expect "sphere purity room 2" "$(EV_D "window.__panodrome.spherePurity()")" num_lt "0.001"

echo "--- 10) capsule prev / next ---"
agent-browser --session d eval "document.getElementById('nav-next').click()" >/dev/null 2>&1
agent-browser --session d wait 2800
expect "next -> cabin" "$(EV_D "window.__panodrome.state.room.id")" eq "cabin"
agent-browser --session d eval "document.getElementById('nav-prev').click()" >/dev/null 2>&1
agent-browser --session d wait 2800
expect "prev -> art_studio" "$(EV_D "window.__panodrome.state.room.id")" eq "art_studio"

echo "--- 11) FA / RTL + Vazirmatn ---"
agent-browser --session d eval "document.getElementById('btn-lang').click()" >/dev/null 2>&1
agent-browser --session d wait 800
expect "dir=rtl" "$(EV_D "document.documentElement.dir")" eq "rtl"
expect "fa room title" "$(EV_D "document.getElementById('room-title').textContent")" eq "استودیوی نقاشی"
expect "persian counter" "$(EV_D "document.getElementById('nav-count').textContent")" eq "(۲ از ۶)"
expect "fa hint" "$(EV_D "document.getElementById('nav-hint').textContent")" eq "برای جلو رفتن اسکرول کنید یا دو بار ضربه بزنید"
expect "vazirmatn active" "$(EV_D "getComputedStyle(document.body).fontFamily")" contains "Vazirmatn"
expect "all UI in bounds (FA RTL)" "$(EV_D "$BOUNDS_JS")" contains '"all":true'
agent-browser --session d wait 700
agent-browser --session d screenshot /tmp/render/s1_desktop_fa.jpg >/dev/null 2>&1
expect "no page errors (desktop)" "$(ERRCOUNT d)" eq "0"

echo
echo "================ MOBILE · iPhone 13 390x844 (touch) ================"
cat > /tmp/s1_touch_init.js <<'EOF'
Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 5, configurable: true});
const __mm = window.matchMedia.bind(window);
window.matchMedia = (q) => {
  if (q.includes('pointer: coarse')) {
    return { matches: true, media: q, onchange: null,
      addListener(){}, removeListener(){}, addEventListener(){}, removeEventListener(){}, dispatchEvent(){ return false; } };
  }
  return __mm(q);
};
EOF
agent-browser --session m open http://localhost:8137 --init-script /tmp/s1_touch_init.js >/dev/null 2>&1
agent-browser --session m set device "iPhone 15" >/dev/null 2>&1
agent-browser --session m set viewport 390 844 >/dev/null 2>&1
agent-browser --session m storage local clear >/dev/null 2>&1
agent-browser --session m reload >/dev/null 2>&1
agent-browser --session m wait 2600
agent-browser --session m errors --clear >/dev/null 2>&1

echo "--- 12) mobile intro + enter ---"
expect "viewport 390" "$(EV_M "innerWidth")" eq "390"
expect "touch emulated (coarse)" "$(EV_M "matchMedia('(pointer: coarse)').matches")" json_true
agent-browser --session m eval "document.getElementById('btn-enter').click()" >/dev/null 2>&1
agent-browser --session m wait 4200
expect "mobile room loads" "$(EV_M "document.getElementById('room-title').textContent")" eq "Anniversary Lounge"
expect "walk pad visible" "$(EV_M "!document.getElementById('walk-pad').classList.contains('hud-hidden')")" json_true
expect "all UI in bounds (mobile EN)" "$(EV_M "$BOUNDS_JS")" contains '"all":true'
agent-browser --session m screenshot /tmp/render/s1_mobile_rest.jpg >/dev/null 2>&1

echo "--- 13) thumb pad optical walk ---"
agent-browser --session m eval "(() => { document.getElementById('btn-fwd').dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, pointerId: 3})); return 'held'; })()" >/dev/null 2>&1
agent-browser --session m wait 1100
expect "pad held: gliding in" "$(EV_M "window.__panodrome.controls.wTarget")" num_gt "0.5"
agent-browser --session m eval "(() => { document.getElementById('btn-fwd').dispatchEvent(new PointerEvent('pointerup', {bubbles: true, pointerId: 3})); return 'released'; })()" >/dev/null 2>&1
agent-browser --session m wait 1200
expect "pad released: stays glided" "$(EV_M "window.__panodrome.controls.w")" num_gt "0.3"

echo "--- 14) tap-out resets to centre ---"
agent-browser --session m eval "$(printf "$TAP_JS" 195 200)" >/dev/null 2>&1
agent-browser --session m wait 1400
expect "tap-out: w back to ~0" "$(EV_M "window.__panodrome.controls.w")" num_lt_abs "0.15"

echo "--- 15) waypoint: tap1 = chip, tap2 = warp ---"
agent-browser --session m eval "$AIM_JS" >/dev/null 2>&1
agent-browser --session m wait 350
WPX="$(EV_M "window.__panodrome.waypointScreen().x")"
WPY="$(EV_M "window.__panodrome.waypointScreen().y")"
agent-browser --session m eval "$(printf "$TAP_JS" "$WPX" "$WPY")" >/dev/null 2>&1
agent-browser --session m wait 600
expect "tap1 shows chip" "$(EV_M "!document.getElementById('wp-chip').classList.contains('hud-hidden')")" json_true
expect "chip in bounds (mobile)" "$(EV_M "(() => { const r = document.getElementById('wp-chip').getBoundingClientRect(); return r.x >= 8 && r.y >= 8 && r.x + r.width <= innerWidth - 8 && r.y + r.height <= innerHeight - 8; })()")" json_true
agent-browser --session m screenshot /tmp/render/s1_mobile_chip.jpg >/dev/null 2>&1
agent-browser --session m eval "$(printf "$TAP_JS" "$WPX" "$WPY")" >/dev/null 2>&1
agent-browser --session m wait 3500
expect "tap2 warps to art_studio" "$(EV_M "window.__panodrome.state.room.id")" eq "art_studio"
expect "mobile counter" "$(EV_M "document.getElementById('nav-count').textContent")" eq "(2 of 6)"

echo "--- 16) mobile FA + bounds + double-tap glide ---"
agent-browser --session m eval "document.getElementById('btn-lang').click()" >/dev/null 2>&1
agent-browser --session m wait 800
expect "fa dir" "$(EV_M "document.documentElement.dir")" eq "rtl"
expect "fa counter" "$(EV_M "document.getElementById('nav-count').textContent")" eq "(۲ از ۶)"
expect "all UI in bounds (mobile FA)" "$(EV_M "$BOUNDS_JS")" contains '"all":true'
agent-browser --session m wait 600
agent-browser --session m screenshot /tmp/render/s1_mobile_fa.jpg >/dev/null 2>&1
agent-browser --session m eval "(() => { const c = document.querySelector('#scene canvas'); const o = {bubbles: true, cancelable: true, pointerId: 7, isPrimary: true, pointerType: 'touch', clientX: 200, clientY: 380}; c.dispatchEvent(new PointerEvent('pointerdown', o)); c.dispatchEvent(new PointerEvent('pointerup', o)); c.dispatchEvent(new PointerEvent('pointerdown', o)); c.dispatchEvent(new PointerEvent('pointerup', o)); return 'dbl'; })()" >/dev/null 2>&1
agent-browser --session m wait 1600
expect "mobile dbl-tap glide" "$(EV_M "window.__panodrome.controls.wTarget")" num_gt "0.6"
expect "no page errors (mobile)" "$(ERRCOUNT m)" eq "0"

echo
echo "================================"
echo "STAGE 1 E2E: PASS=$PASS FAIL=$FAIL"
[ $FAIL -eq 0 ] && echo "ALL GREEN" || echo "HAS FAILURES"
exit $FAIL
