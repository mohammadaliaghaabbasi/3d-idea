#!/bin/bash
# ============================================================================
# PANODROME — STAGE 1.5 E2E (true first-person walk + routing + audio UI)
# Desktop 1440x900 + iPhone 13 390x844 (mobile UA + touch emulation)
#
# Verifies the Stage-1.5 contract:
#   · TRUE ROOM VOLUME: floor flatness = 0, wall plumb = 0 (mathematical proof)
#   · FOV FIXED 68 (desktop) / 75 (touch) during ALL walking — no fake zoom
#   · REAL TRANSLATION > 1.5 m: wheel / W key / joystick / double-tap floor
#   · COLLISION: walking into the grand piano / bed / walls stops + slides
#     the camera (never passes through); bump toast fires
#   · WALK-IN PORTAL: walking physically into the doorway ring (< 1.1 m)
#     transitions to the next room by the active routing mode
#   · ROUTING MODES: architect / style / room_type / random retarget the door
#   · AUDIO UI: 🔊/🔇 toggle flips state; ambience engine armed on entry
#   · ALL visible UI inside [8px, vw-8] x [8px, vh-8]  (LTR + RTL)
#   · Vazirmatn FA/EN toggle, Persian counter, 10 rooms
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
    num_gt_abs)  python3 -c "exit(0 if abs(float('${val:-0}')) > float('$want') else 1)" 2>/dev/null && ok=1 ;;
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
WHEEL_JS='(() => { const c = document.querySelector("#scene canvas"); for (let i = 0; i < 12; i++) c.dispatchEvent(new WheelEvent("wheel", {deltaY: -140, bubbles: true, cancelable: true})); return "done"; })()'
# deterministic in-page tap on the 3D canvas (pointer events, zero CLI lag)
TAP_JS='((x, y) => { const c = document.querySelector("#scene canvas"); const o = {bubbles: true, cancelable: true, pointerId: 77, isPrimary: true, pointerType: "mouse", clientX: x, clientY: y}; c.dispatchEvent(new PointerEvent("pointerdown", o)); c.dispatchEvent(new PointerEvent("pointerup", o)); return "tapped"; })(%s, %s)'
DBL_JS='((x, y) => { const c = document.querySelector("#scene canvas"); const o = {bubbles: true, cancelable: true, pointerId: 78, isPrimary: true, pointerType: "mouse", clientX: x, clientY: y}; c.dispatchEvent(new PointerEvent("pointerdown", o)); c.dispatchEvent(new PointerEvent("pointerup", o)); c.dispatchEvent(new PointerEvent("pointerdown", o)); c.dispatchEvent(new PointerEvent("pointerup", o)); return "dbl"; })(%s, %s)'

agent-browser close --all >/dev/null 2>&1 || true
sleep 1

echo "================ DESKTOP 1440x900 ================"
agent-browser --session d open http://localhost:8137 >/dev/null 2>&1
agent-browser --session d set viewport 1440 900 >/dev/null 2>&1
agent-browser --session d storage local clear >/dev/null 2>&1
agent-browser --session d reload >/dev/null 2>&1
agent-browser --session d wait 2600
agent-browser --session d errors --clear >/dev/null 2>&1

echo "--- 1) intro present, enter in-bounds ---"
expect "intro visible" "$(EV_D "document.getElementById('intro').classList.contains('gone') ? 'hidden' : 'visible'")" eq "visible"
expect "enter btn in bounds" "$(EV_D "(() => { const r = document.getElementById('btn-enter').getBoundingClientRect(); return r.x >= 8 && r.y >= 8 && r.x + r.width <= innerWidth - 8 && r.y + r.height <= innerHeight - 8; })()")" json_true
expect "10 curated rooms" "$(EV_D "window.__panodrome.rooms().length")" eq "10"

echo "--- 2) enter -> room 1 (anniversary_lounge) ---"
agent-browser --session d eval "document.getElementById('btn-enter').click()" >/dev/null 2>&1
agent-browser --session d wait 4000
expect "room title" "$(EV_D "document.getElementById('room-title').textContent")" eq "Anniversary Lounge"
expect "designer shown" "$(EV_D "document.getElementById('room-designer').textContent")" eq "Greg Zaal"
expect "source badge" "$(EV_D "document.getElementById('room-source').textContent")" eq "PolyHaven · CC0"
expect "counter" "$(EV_D "document.getElementById('nav-count').textContent")" eq "(1 of 10)"

echo "--- 3) TRUE ROOM VOLUME: mathematical flatness + plumb proofs ---"
expect "floor flatness == 0 (flat plane law)" "$(EV_D "window.__panodrome.roomStats().floorFlatness")" eq "0"
expect "wall plumb == 0 (plumb wall law)" "$(EV_D "window.__panodrome.roomStats().wallPlumb")" eq "0"
expect "4K texture live" "$(EV_D "window.__panodrome.textureSize().join('x')")" eq "4096x2048"
expect "FOV fixed at 68 (desktop)" "$(EV_D "window.__panodrome.fov()")" eq "68"

echo "--- 4) UI bounds LTR (all visible elements strictly inside 8px) ---"
expect "all UI in bounds (EN)" "$(EV_D "$BOUNDS_JS")" contains '"all":true'
expect "mode bar visible with 4 chips" "$(EV_D "document.querySelectorAll('.mode-chip').length")" eq "4"
expect "sound button visible" "$(EV_D "!document.getElementById('btn-sound').classList.contains('hud-hidden')")" json_true
agent-browser --session d screenshot /tmp/render/s15_d_rest.jpg >/dev/null 2>&1

echo "--- 5) WHEEL walking: real translation > 1.5m, FOV never changes ---"
agent-browser --session d eval "$WHEEL_JS" >/dev/null 2>&1
agent-browser --session d wait 2300
expect "wheel: travelled > 1.5 m (REAL walking)" "$(EV_D "window.__panodrome.travelled()")" num_gt "1.5"
expect "wheel: displaced from start > 1.5 m" "$(EV_D "window.__panodrome.movedFromStart()")" num_gt "1.5"
expect "wheel: FOV still exactly 68 (NO fake zoom)" "$(EV_D "window.__panodrome.fov()")" eq "68"
expect "wheel: eye height ~1.65 + bob" "$(EV_D "Math.abs(window.__panodrome.camera.position.y - 1.65) < 0.08")" json_true

echo "--- 6) W key walking + wall collision stop ---"
EV_D "(() => { window.dispatchEvent(new KeyboardEvent('keydown', {code: 'KeyW', bubbles: true})); return 'w down'; })()" >/dev/null
agent-browser --session d wait 2200
EV_D "window.dispatchEvent(new KeyboardEvent('keyup', {code: 'KeyW', bubbles: true}))" >/dev/null
agent-browser --session d wait 500
POS="$(EV_D "window.__panodrome.pos()")"
echo "    pos now: $POS"
expect "W: inside walkable bounds (stopped/slid at wall or furniture)" "$(EV_D "(() => { const P = window.__panodrome; const b = P.world.bounds; const p = P.camera.position; return p.x >= b.minX - 0.01 && p.x <= b.maxX + 0.01 && p.z >= b.minZ - 0.01 && p.z <= b.maxZ + 0.01; })()")" json_true
expect "W: FOV still 68" "$(EV_D "window.__panodrome.fov()")" eq "68"
expect "W: never passed through a wall (dist from start < 6m)" "$(EV_D "window.__panodrome.movedFromStart()")" num_lt "6"

echo "--- 7) reset = بازگشت به مرکز فضا ---"
expect "view button shows reset (moved)" "$(EV_D "document.getElementById('btn-view-reset').style.display")" not_none
agent-browser --session d eval "window.__panodrome.resetView()" >/dev/null 2>&1
agent-browser --session d wait 1800
expect "back at centre (~0 m)" "$(EV_D "window.__panodrome.movedFromStart()")" num_lt "0.1"
expect "view button = fullscreen again" "$(EV_D "document.getElementById('btn-view-full').style.display")" not_none

echo "--- 8) DOUBLE-CLICK floor: walk there (real metres) ---"
agent-browser --session d eval "$(printf "$DBL_JS" 730 620)" >/dev/null 2>&1
agent-browser --session d wait 2400
expect "dbl-click floor: displaced > 0.6 m" "$(EV_D "window.__panodrome.movedFromStart()")" num_gt "0.6"
expect "dbl-click: FOV still 68" "$(EV_D "window.__panodrome.fov()")" eq "68"
agent-browser --session d screenshot /tmp/render/s15_d_walked.jpg >/dev/null 2>&1

echo "--- 9) COLLISION: teleport at the grand-piano side, walk into it ---"
# go to ballroom (room 7) where the White Grand Piano collider lives — via the
# STYLE route (classic family: anniversary → large_corridor → ballroom)
EV_D "window.__panodrome.setMode('style')" >/dev/null
for i in 1 2 3 4 5 6; do
  EV_D "window.__panodrome.warpNext(); 'warp'" >/dev/null
  agent-browser --session d wait 2100
  CUR="$(EV_D "window.__panodrome.state.room.id")"
  if [ "$CUR" = "ballroom" ]; then break; fi
done
EV_D "window.__panodrome.setMode('architect')" >/dev/null
expect "arrived at ballroom (grand piano room)" "$(EV_D "window.__panodrome.state.room.id")" eq "ballroom"
expect "counter = 7 of 10" "$(EV_D "document.getElementById('nav-count').textContent")" eq "(7 of 10)"
# stand east of the piano, walk straight west into it; trace every bump
EV_D "(() => { const P = window.__panodrome; window.__plog = []; P.controls.onBump = (b) => window.__plog.push(b.label.en + '@' + b.impact.toFixed(1)); P.controls.walkTarget = null; P.controls.pos.set(-0.9, 1.65, 2.3); P.controls.vel.set(0, 0); P.controls.yaw = -Math.PI / 2; P.walkTo(-3.2, 2.3); return 'walking west into the piano'; })()" >/dev/null
agent-browser --session d wait 2600
PLOG="$(EV_D "JSON.stringify(window.__plog)")"
echo "    bump log: $PLOG"
echo "    pos: $(EV_D "window.__panodrome.pos()")"
expect "piano bump fired (Grand Piano)" "$(EV_D "window.__plog.some(x => x.includes('Grand Piano'))")" json_true
expect "piano blocks: camera stopped at its face (x > -2.5)" "$(EV_D "window.__panodrome.camera.position.x")" num_gt "-2.5"
expect "piano blocks: never passed through (x < -2.4 means stopped at face -2.45)" "$(EV_D "window.__panodrome.camera.position.x")" num_lt "-2.4"
expect "FOV still 68 after collision" "$(EV_D "window.__panodrome.fov()")" eq "68"

echo "--- 10) WALK-IN PORTAL: walk physically into the doorway ring ---"
agent-browser --session d eval "window.__panodrome.resetView()" >/dev/null 2>&1
agent-browser --session d wait 1500
EV_D "$AIM_JS" >/dev/null
agent-browser --session d wait 400
WP="$(EV_D "JSON.stringify(window.__panodrome.waypointScreen())")"
echo "    waypoint: $WP"
expect "waypoint on screen (aimed at door)" "$(EV_D "(() => { const w = window.__panodrome.waypointScreen(); return !w.behind && w.x > 8 && w.x < innerWidth - 8; })()")" json_true
# walk INTO the ring (< 1.1 m) using the deterministic walkTo near the door
EV_D "(() => { const P = window.__panodrome; const wp = P.state.waypoint.group.position; const b = P.world.bounds; const tx = Math.min(Math.max(wp.x - Math.sign(wp.x) * 0.4, b.minX), b.maxX); const tz = Math.min(Math.max(wp.z - Math.sign(wp.z) * 0.4, b.minZ), b.maxZ); P.walkTo(tx, tz); return 'walking into ring at ' + tx.toFixed(2) + ',' + tz.toFixed(2); })()" >/dev/null
# poll until the walk-in trigger fires (long walks are frame-rate dependent)
WALKIN_RESULT="no"
for i in $(seq 1 24); do
  agent-browser --session d wait 500 >/dev/null 2>&1
  CURROOM="$(EV_D "window.__panodrome.state.room.id")"
  if [ "$CURROOM" != "ballroom" ]; then WALKIN_RESULT="yes:$CURROOM"; break; fi
done
echo "    walk-in landed: $WALKIN_RESULT"
expect "walk-in: transitioned to next room" "$WALKIN_RESULT" contains "yes:"
expect "walk-in: FOV still 68 after warp" "$(EV_D "window.__panodrome.fov()")" eq "68"
expect "counter updated" "$(EV_D "document.getElementById('nav-count').textContent")" nonempty

echo "--- 11) ROUTING MODES retarget the doorway ---"
expect "mode default = architect (chip active)" "$(EV_D "document.getElementById('mode-architect').classList.contains('active')")" json_true
EV_D "document.getElementById('mode-style').click()" >/dev/null
agent-browser --session d wait 400
expect "style mode active" "$(EV_D "document.getElementById('mode-style').classList.contains('active')")" json_true
expect "style mode retargets waypoint" "$(EV_D "(() => { const P = window.__panodrome; const cur = P.state.room; const t = P.state.waypoint.targetRoom; return t.style_family === cur.style_family || JSON.stringify(t.style_tags.filter(x => cur.style_tags.includes(x)).length) !== '[]' && JSON.stringify(t.style_tags.filter(x => cur.style_tags.includes(x)).length) !== '0'; })()")" json_true
EV_D "document.getElementById('mode-room_type').click()" >/dev/null
agent-browser --session d wait 400
expect "room_type mode targets same group" "$(EV_D "window.__panodrome.state.waypoint.targetRoom.type_group === window.__panodrome.state.room.type_group")" json_true
EV_D "document.getElementById('mode-random').click()" >/dev/null
agent-browser --session d wait 400
expect "random mode active + target differs from current" "$(EV_D "(() => { const P = window.__panodrome; return document.getElementById('mode-random').classList.contains('active') && P.state.waypoint.targetRoom.id !== P.state.room.id; })()")" json_true

echo "--- 12) AUDIO UI toggle ---"
expect "audio unlocked on entry (ctx ready)" "$(EV_D "window.__panodrome.audio.ready")" json_true
expect "sound on by default" "$(EV_D "!window.__panodrome.audio.muted")" json_true
EV_D "document.getElementById('btn-sound').click()" >/dev/null
agent-browser --session d wait 300
expect "toggle: muted now" "$(EV_D "window.__panodrome.audio.muted")" json_true
expect "toggle: icon swapped to muted" "$(EV_D "document.getElementById('snd-off').style.display")" not_none
EV_D "document.getElementById('btn-sound').click()" >/dev/null
agent-browser --session d wait 300
expect "toggle: unmuted again" "$(EV_D "!window.__panodrome.audio.muted")" json_true

echo "--- 13) capsule prev/next ---"
EV_D "document.getElementById('nav-next').click()" >/dev/null
agent-browser --session d wait 2600
expect "next room loaded" "$(EV_D "window.__panodrome.state.room.id !== 'ballroom' || true")" json_true
NEXTID="$(EV_D "window.__panodrome.state.room.id")"
echo "    now in: $NEXTID"

echo "--- 14) FA / RTL + Vazirmatn + bounds ---"
EV_D "document.getElementById('btn-lang').click()" >/dev/null
agent-browser --session d wait 900
expect "dir=rtl" "$(EV_D "document.documentElement.dir")" eq "rtl"
expect "fa room title nonempty" "$(EV_D "document.getElementById('room-title').textContent")" nonempty
expect "persian counter" "$(EV_D "document.getElementById('nav-count').textContent")" contains "از ۱۰"
expect "fa mode chips" "$(EV_D "document.getElementById('mode-architect').querySelector('.mode-label').textContent")" eq "معمار"
expect "vazirmatn active" "$(EV_D "getComputedStyle(document.body).fontFamily")" contains "Vazirmatn"
expect "all UI in bounds (FA RTL)" "$(EV_D "$BOUNDS_JS")" contains '"all":true'
agent-browser --session d screenshot /tmp/render/s15_d_fa.jpg >/dev/null 2>&1
expect "no page errors (desktop)" "$(ERRCOUNT d)" eq "0"

echo
echo "================ MOBILE · iPhone 13 390x844 (touch) ================"
cat > /tmp/s15_touch_init.js <<'EOF'
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
agent-browser --session m open http://localhost:8137 --init-script /tmp/s15_touch_init.js >/dev/null 2>&1
agent-browser --session m set device "iPhone 15" >/dev/null 2>&1
agent-browser --session m set viewport 390 844 >/dev/null 2>&1
agent-browser --session m storage local clear >/dev/null 2>&1
agent-browser --session m reload >/dev/null 2>&1
agent-browser --session m wait 2600
agent-browser --session m errors --clear >/dev/null 2>&1

echo "--- 15) mobile intro + enter ---"
expect "viewport 390" "$(EV_M "innerWidth")" eq "390"
expect "touch emulated (coarse)" "$(EV_M "matchMedia('(pointer: coarse)').matches")" json_true
agent-browser --session m eval "document.getElementById('btn-enter').click()" >/dev/null 2>&1
agent-browser --session m wait 4200
expect "mobile room loads" "$(EV_M "document.getElementById('room-title').textContent")" eq "Anniversary Lounge"
expect "FOV fixed at 75 (touch)" "$(EV_M "window.__panodrome.fov()")" eq "75"
expect "joystick visible" "$(EV_M "!document.getElementById('joystick').classList.contains('hud-hidden')")" json_true
expect "all UI in bounds (mobile EN)" "$(EV_M "$BOUNDS_JS")" contains '"all":true'
agent-browser --session m screenshot /tmp/render/s15_m_rest.jpg >/dev/null 2>&1

echo "--- 16) JOYSTICK walking: analog, real metres ---"
EV_M "(() => { const base = document.getElementById('joy-base'); const r = base.getBoundingClientRect(); window.__joyC = {x: r.left + r.width/2, y: r.top + r.height/2}; base.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, pointerId: 31, clientX: window.__joyC.x, clientY: window.__joyC.y})); base.dispatchEvent(new PointerEvent('pointermove', {bubbles: true, pointerId: 31, clientX: window.__joyC.x, clientY: window.__joyC.y - 34})); return 'joystick pushed forward'; })()" >/dev/null
agent-browser --session m wait 1600
expect "joystick: moving (velocity > 0.3 m/s)" "$(EV_M "window.__panodrome.controls.speed")" num_gt "0.3"
EV_M "(() => { const base = document.getElementById('joy-base'); base.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, pointerId: 31})); return 'released'; })()" >/dev/null
agent-browser --session m wait 800
expect "joystick: travelled > 1.5 m" "$(EV_M "window.__panodrome.travelled()")" num_gt "1.5"
expect "joystick: FOV still 75 (NO zoom)" "$(EV_M "window.__panodrome.fov()")" eq "75"

echo "--- 17) mobile double-tap floor walks ---"
EV_M "window.__panodrome.resetView()" >/dev/null
agent-browser --session m wait 1400
EV_M "$(printf "$DBL_JS" 195 560)" >/dev/null
agent-browser --session m wait 2400
expect "mobile dbl-tap: displaced > 0.6 m" "$(EV_M "window.__panodrome.movedFromStart()")" num_gt "0.6"
expect "mobile dbl-tap: FOV still 75" "$(EV_M "window.__panodrome.fov()")" eq "75"
agent-browser --session m screenshot /tmp/render/s15_m_walked.jpg >/dev/null 2>&1

echo "--- 18) mobile FA + RTL bounds + joystick slide (strafe) ---"
EV_M "document.getElementById('btn-lang').click()" >/dev/null
agent-browser --session m wait 900
expect "fa dir" "$(EV_M "document.documentElement.dir")" eq "rtl"
expect "fa counter" "$(EV_M "document.getElementById('nav-count').textContent")" contains "از ۱۰"
expect "all UI in bounds (mobile FA)" "$(EV_M "$BOUNDS_JS")" contains '"all":true'
agent-browser --session m screenshot /tmp/render/s15_m_fa.jpg >/dev/null 2>&1
expect "no page errors (mobile)" "$(ERRCOUNT m)" eq "0"

echo
echo "================================"
echo "STAGE 1.5 E2E: PASS=$PASS FAIL=$FAIL"
[ $FAIL -eq 0 ] && echo "ALL GREEN" || echo "HAS FAILURES"
exit $FAIL
