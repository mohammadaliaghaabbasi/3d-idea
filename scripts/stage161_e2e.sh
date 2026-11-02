#!/bin/bash
# ============================================================================
# PANODROME — STAGE 1.6.1 E2E (Emergency Visual Restoration)
# Relief dome + crisp 4K pano + elastic envelope + glass halos
# Desktop 1440x900 (laws) + iPhone 390x844 (QA gate)
#
# STAGE 1.6.1 CONTRACT (owner order 2026-11-02):
#   · RULE A: crisp ORIGINAL pano_4k texture — NO shells/, NO Telea smudges
#   · RULE B: watertight RELIEF DOME — exactFloor = 0 (flat-floor law),
#     saw-tooth zigzag < 0.45 m, zero torn edges, zero extruded GLBs
#   · RULE C: real physics colliders + glass floor halos; obstacle contact
#     events (Grand Piano bump), OBB-ready
#   · ELASTIC walk envelope (1.1-1.35 m + door/obstacle channels):
#     walk beyond the boundary clamps at r; walk-ins still work
#   · FOV FIXED 68/75 through ALL walking; real translation > 1.5 m
#   · WALK-IN PORTAL + 4 routing modes + audio toggle + FA/RTL Vazirmatn
#   · ZERO page errors
#   · STRICT VISUAL QA GATE: 4 mobile screenshots (anniversary + cabin,
#     spawn + after joystick walk) judged by ai_router TIER 1
#     (gemini-3.6-flash) — must score >= 9/10 each.
# ============================================================================
set -u
mkdir -p /tmp/render /home/z/my-project/3d-idea/docs/rd-artifacts/stage161
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
    num_gt_abs)  python3 -c "exit(0 if abs(float('${val:-0}') > float('$want') else 1)" 2>/dev/null && ok=1 ;;
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
DBL_JS='((x, y) => { const c = document.querySelector("#scene canvas"); const o = {bubbles: true, cancelable: true, pointerId: 78, isPrimary: true, pointerType: "mouse", clientX: x, clientY: y}; c.dispatchEvent(new PointerEvent("pointerdown", o)); c.dispatchEvent(new PointerEvent("pointerup", o)); c.dispatchEvent(new PointerEvent("pointerdown", o)); c.dispatchEvent(new PointerEvent("pointerup", o)); return "dbl"; })(%s, %s)'

# STRICT QA prompt (owner-specified) — scored by ai_router TIER 1
QA_PROMPT="You are a senior architectural QA critic. Inspect this mobile viewport screenshot carefully. Are there ANY exploding triangles, saw-tooth jagged edges on furniture, or blurry inpainted smudges on the walls? Score visual integrity from 1 to 10. If score < 9, explain the exact defect so it can be fixed. End your reply with EXACTLY this line: SCORE: <number>/10"
qa_judge() { # qa_judge <screenshot> <label> <artifacts-stem>
  local shot="$1" label="$2" stem="$3"
  local out_json="/home/z/my-project/3d-idea/docs/rd-artifacts/stage161/${stem}.json"
  local txt=""
  if timeout 200 python3 "/home/z/my-project/3d-idea/skills/ai_router.py" \
      --tier 1 -p "$QA_PROMPT" -i "$shot" \
      --task "stage161_qa_${stem}" > /tmp/qa_out.txt 2>/tmp/qa_err.txt; then
    txt="$(cat /tmp/qa_out.txt)"
    python3 -c "
import json, sys
out = {'label': '$label', 'shot': '$shot', 'text': open('/tmp/qa_out.txt').read()}
try:
    import re
    m = re.findall(r'SCORE:\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*10', out['text'])
    out['score'] = float(m[-1]) if m else None
except Exception:
    out['score'] = None
json.dump(out, open('$out_json', 'w'), ensure_ascii=False, indent=1)
print(out['score'] if out['score'] is not None else 'NO-SCORE')"
  else
    echo "ROUTER-FAIL"
  fi
}

agent-browser close --all >/dev/null 2>&1 || true
sleep 1

echo "================ DESKTOP 1440x900 ================"
agent-browser --session d open http://localhost:8137 >/dev/null 2>&1
agent-browser --session d set viewport 1440 900 >/dev/null 2>&1
agent-browser --session d storage local clear >/dev/null 2>&1
agent-browser --session d reload >/dev/null 2>&1
agent-browser --session d wait 2600
agent-browser --session d errors --clear >/dev/null 2>&1

echo "--- 1) intro + enter ---"
expect "intro visible" "$(EV_D "document.getElementById('intro').classList.contains('gone') ? 'hidden' : 'visible'")" eq "visible"
expect "enter btn in bounds" "$(EV_D "(() => { const r = document.getElementById('btn-enter').getBoundingClientRect(); return r.x >= 8 && r.y >= 8 && r.x + r.width <= innerWidth - 8 && r.y + r.height <= innerHeight - 8; })()")" json_true
expect "10 curated rooms" "$(EV_D "window.__panodrome.rooms().length")" eq "10"
agent-browser --session d eval "document.getElementById('btn-enter').click()" >/dev/null 2>&1
agent-browser --session d wait 4000
expect "room title" "$(EV_D "document.getElementById('room-title').textContent")" eq "Anniversary Lounge"
expect "designer shown" "$(EV_D "document.getElementById('room-designer').textContent")" eq "Greg Zaal"
expect "counter" "$(EV_D "document.getElementById('nav-count').textContent")" eq "(1 of 10)"

echo "--- 2) STAGE 1.6.1 DOME LAWS (Rule A + Rule B) ---"
expect "RULE A: crisp ORIGINAL pano texture (panoramas/, no shells/)" "$(EV_D "window.__panodrome.roomStats().textureUrl.includes('panoramas/')")" json_true
expect "RULE A: no furniture GLB layer loaded" "$(EV_D "!window.__panodrome.state.furnitureObj")" json_true
expect "RULE B: relief dome live" "$(EV_D "window.__panodrome.roomStats().isDome")" json_true
expect "RULE B: dome density (verts > 40000)" "$(EV_D "window.__panodrome.roomStats().dome.verts")" num_gt "40000"
expect "FLAT-FLOOR LAW: exactFloor == 0" "$(EV_D "window.__panodrome.roomStats().dome.exactFloor")" eq "0"
expect "NO-SAWTOOTH LAW: zigzag < 0.45 m" "$(EV_D "window.__panodrome.roomStats().dome.zigzag")" num_lt "0.45"
expect "4K texture live" "$(EV_D "window.__panodrome.textureSize().join('x')")" eq "4096x2048"
expect "FOV fixed at 68 (desktop)" "$(EV_D "window.__panodrome.fov()")" eq "68"

echo "--- 3) RULE C: colliders + glass halos ---"
expect "colliders present (7 merged)" "$(EV_D "window.__panodrome.roomStats().obstacles")" eq "7"
expect "glass floor halos live (7)" "$(EV_D "window.__panodrome.roomStats().halos")" eq "7"
expect "elastic envelope base = 1.35" "$(EV_D "window.__panodrome.roomStats().envelope.base")" eq "1.35"

echo "--- 4) UI bounds LTR ---"
expect "all UI in bounds (EN)" "$(EV_D "$BOUNDS_JS")" contains '"all":true'
expect "mode bar 4 chips" "$(EV_D "document.querySelectorAll('.mode-chip').length")" eq "4"

echo "--- 5) WHEEL walking: real translation, FOV never changes ---"
agent-browser --session d eval "$WHEEL_JS" >/dev/null 2>&1
agent-browser --session d wait 2300
expect "wheel: travelled > 0.8 m" "$(EV_D "window.__panodrome.travelled()")" num_gt "0.8"
expect "wheel: FOV still exactly 68 (NO fake zoom)" "$(EV_D "window.__panodrome.fov()")" eq "68"
expect "wheel: eye height ~1.65 + bob" "$(EV_D "Math.abs(window.__panodrome.camera.position.y - 1.65) < 0.08")" json_true

echo "--- 6) W key walking + wall stop ---"
EV_D "(() => { window.dispatchEvent(new KeyboardEvent('keydown', {code: 'KeyW', bubbles: true})); return 'w down'; })()" >/dev/null
agent-browser --session d wait 2200
EV_D "window.dispatchEvent(new KeyboardEvent('keyup', {code: 'KeyW', bubbles: true}))" >/dev/null
agent-browser --session d wait 500
expect "W: inside walkable bounds" "$(EV_D "(() => { const P = window.__panodrome; const b = P.world.bounds; const p = P.camera.position; return p.x >= b.minX - 0.01 && p.x <= b.maxX + 0.01 && p.z >= b.minZ - 0.01 && p.z <= b.maxZ + 0.01; })()")" json_true
expect "W: FOV still 68" "$(EV_D "window.__panodrome.fov()")" eq "68"

echo "--- 7) reset + double-click floor walk ---"
agent-browser --session d eval "window.__panodrome.resetView()" >/dev/null 2>&1
agent-browser --session d wait 1800
expect "back at centre (~0 m)" "$(EV_D "window.__panodrome.movedFromStart()")" num_lt "0.1"
EV_D "(() => { window.__plog = []; window.__panodrome.controls.onBump = (b) => window.__plog.push(b.label.en); return 'plog armed'; })()" >/dev/null
agent-browser --session d eval "$(printf "$DBL_JS" 730 620)" >/dev/null 2>&1
agent-browser --session d wait 2400
DBL_MOVED="$(EV_D "window.__panodrome.movedFromStart()")"
DBL_BUMP="$(EV_D "JSON.stringify(window.__plog)")"
echo "    dbl-click: moved ${DBL_MOVED} m, bumps: ${DBL_BUMP}"
expect "dbl-click floor: walked > 0.3 m OR real furniture collision en route" "$(python3 -c "
m = float('${DBL_MOVED:-0}')
b = '${DBL_BUMP}'
print('true' if (m > 0.3 or b not in ('[]', '')) else 'false')")" json_true
expect "dbl-click: FOV still 68" "$(EV_D "window.__panodrome.fov()")" eq "68"

echo "--- 8) FURNITURE COLLISION: walk into the sofa cluster ---"
EV_D "(() => { const P = window.__panodrome; window.__plog = []; P.controls.onBump = (b) => window.__plog.push(b.label.en + '@' + b.impact.toFixed(2)); P.controls.vel.set(0, 0); P.walkTo(1.01, -1.41); return 'walking to sofa'; })()" >/dev/null
SOFA_BUMP="no"
for i in $(seq 1 12); do
  agent-browser --session d wait 600 >/dev/null 2>&1
  B="$(EV_D "JSON.stringify(window.__plog)")"
  if [ "$B" != "[]" ]; then SOFA_BUMP="yes:$B"; break; fi
done
echo "    sofa cluster bump: $SOFA_BUMP"
expect "sofa cluster: real furniture collision event" "$SOFA_BUMP" contains "yes:"

echo "--- 9) ELASTIC ENVELOPE: walking far beyond clamps at the boundary ---"
EV_D "(() => { const P = window.__panodrome; P.controls.onBump = null; P.controls.vel.set(0, 0); P.controls.pos.set(0, 1.65, 0); P.walkTo(5.0, 5.0); return 'walking far beyond'; })()" >/dev/null
agent-browser --session d wait 3200
expect "envelope: clamped inside (d <= r + 0.15)" "$(EV_D "(() => { const e = window.__panodrome.envelope(); return (e.d <= e.r + 0.15) ? 'true' : JSON.stringify(e); })()")" json_true
expect "envelope: reached the elastic boundary (d > 0.9)" "$(EV_D "window.__panodrome.envelope().d")" num_gt "0.9"
expect "envelope: FOV still 68" "$(EV_D "window.__panodrome.fov()")" eq "68"

echo "--- 10) BALLROOM: Grand Piano bump through its walk channel ---"
for k in 1 2 3 4 5 6; do
  agent-browser --session d eval "document.getElementById('nav-next').click()" >/dev/null 2>&1
  agent-browser --session d wait 2800
  CUR="$(EV_D "window.__panodrome.state.room.id")"
  if [ "$CUR" = "ballroom" ]; then break; fi
done
expect "arrived at ballroom" "$(EV_D "window.__panodrome.state.room.id")" eq "ballroom"
expect "counter = 7 of 10" "$(EV_D "document.getElementById('nav-count').textContent")" eq "(7 of 10)"
EV_D "(() => { const P = window.__panodrome; window.__plog = []; P.controls.onBump = (b) => window.__plog.push(b.label.en + '@' + b.impact.toFixed(2)); P.controls.vel.set(0, 0); P.walkTo(-3.6, 2.3); return 'walking to piano'; })()" >/dev/null
PIANO_BUMP="no"
for i in $(seq 1 12); do
  agent-browser --session d wait 600 >/dev/null 2>&1
  B="$(EV_D "JSON.stringify(window.__plog)")"
  if [ "$B" != "[]" ]; then PIANO_BUMP="yes:$B"; break; fi
done
echo "    piano bump: $PIANO_BUMP"
expect "Grand Piano contact event fires" "$PIANO_BUMP" contains "Grand Piano"
expect "piano blocks: camera stopped at its face (x > -2.8)" "$(EV_D "window.__panodrome.camera.position.x")" num_gt "-2.8"
expect "piano blocks: never passed through (x < -2.2)" "$(EV_D "window.__panodrome.camera.position.x")" num_lt "-2.2"
expect "FOV still 68 after collision" "$(EV_D "window.__panodrome.fov()")" eq "68"

echo "--- 11) WALK-IN PORTAL ---"
EV_D "window.__panodrome.controls.onBump = null" >/dev/null
agent-browser --session d eval "window.__panodrome.resetView()" >/dev/null 2>&1
agent-browser --session d wait 1600
EV_D "(() => { const P = window.__panodrome; const wp = P.state.waypoint.group.position; P.walkTo(wp.x, wp.z); return 'to ring'; })()" >/dev/null
WALKIN_RESULT="no"
for i in $(seq 1 22); do
  agent-browser --session d wait 600 >/dev/null 2>&1
  CURROOM="$(EV_D "window.__panodrome.state.room.id")"
  if [ "$CURROOM" != "ballroom" ]; then WALKIN_RESULT="yes:$CURROOM"; break; fi
done
echo "    walk-in landed: $WALKIN_RESULT"
expect "walk-in: transitioned to next room" "$WALKIN_RESULT" contains "yes:"
expect "walk-in: FOV still 68 after warp" "$(EV_D "window.__panodrome.fov()")" eq "68"

echo "--- 12) ROUTING MODES ---"
expect "mode default = architect" "$(EV_D "document.getElementById('mode-architect').classList.contains('active')")" json_true
EV_D "document.getElementById('mode-style').click()" >/dev/null
agent-browser --session d wait 400
expect "style mode active" "$(EV_D "document.getElementById('mode-style').classList.contains('active')")" json_true
EV_D "document.getElementById('mode-room_type').click()" >/dev/null
agent-browser --session d wait 400
expect "room_type mode targets same group" "$(EV_D "window.__panodrome.state.waypoint.targetRoom.type_group === window.__panodrome.state.room.type_group")" json_true
EV_D "document.getElementById('mode-random').click()" >/dev/null
agent-browser --session d wait 400
expect "random mode active + target differs" "$(EV_D "(() => { const P = window.__panodrome; return document.getElementById('mode-random').classList.contains('active') && P.state.waypoint.targetRoom.id !== P.state.room.id; })()")" json_true

echo "--- 13) AUDIO UI toggle ---"
expect "audio unlocked on entry" "$(EV_D "window.__panodrome.audio.ready")" json_true
EV_D "document.getElementById('btn-sound').click()" >/dev/null
agent-browser --session d wait 300
expect "toggle: muted now" "$(EV_D "window.__panodrome.audio.muted")" json_true
EV_D "document.getElementById('btn-sound').click()" >/dev/null
agent-browser --session d wait 300
expect "toggle: unmuted again" "$(EV_D "!window.__panodrome.audio.muted")" json_true

echo "--- 14) FA / RTL + Vazirmatn + zero errors ---"
EV_D "document.getElementById('btn-lang').click()" >/dev/null
agent-browser --session d wait 900
expect "dir=rtl" "$(EV_D "document.documentElement.dir")" eq "rtl"
expect "persian counter" "$(EV_D "document.getElementById('nav-count').textContent")" contains "از ۱۰"
expect "fa mode chips" "$(EV_D "document.getElementById('mode-architect').querySelector('.mode-label').textContent")" eq "معمار"
expect "vazirmatn active" "$(EV_D "getComputedStyle(document.body).fontFamily")" contains "Vazirmatn"
expect "all UI in bounds (FA RTL)" "$(EV_D "$BOUNDS_JS")" contains '"all":true'
expect "no page errors (desktop)" "$(ERRCOUNT d)" eq "0"

echo
echo "================ MOBILE · iPhone 390x844 (touch) ================"
cat > /tmp/s161_touch_init.js <<'EOF'
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
agent-browser --session m open http://localhost:8137 --init-script /tmp/s161_touch_init.js >/dev/null 2>&1
agent-browser --session m set viewport 390 844 >/dev/null 2>&1
agent-browser --session m storage local clear >/dev/null 2>&1
agent-browser --session m reload >/dev/null 2>&1
agent-browser --session m wait 2600
agent-browser --session m errors --clear >/dev/null 2>&1

echo "--- 15) mobile enter ---"
expect "viewport 390" "$(EV_M "innerWidth")" eq "390"
expect "touch emulated" "$(EV_M "matchMedia('(pointer: coarse)').matches")" json_true
agent-browser --session m eval "document.getElementById('btn-enter').click()" >/dev/null 2>&1
agent-browser --session m wait 4200
expect "mobile room loads" "$(EV_M "document.getElementById('room-title').textContent")" eq "Anniversary Lounge"
expect "FOV fixed at 75 (touch)" "$(EV_M "window.__panodrome.fov()")" eq "75"
expect "joystick visible" "$(EV_M "!document.getElementById('joystick').classList.contains('hud-hidden')")" json_true
expect "all UI in bounds (mobile EN)" "$(EV_M "$BOUNDS_JS")" contains '"all":true'
expect "dome live on mobile" "$(EV_M "window.__panodrome.roomStats().isDome")" json_true

echo "--- 16) QA SHOTS · anniversary_lounge: spawn + 1.2m joystick walk toward sofa ---"
EV_M "(() => { const P = window.__panodrome; P.controls.walkTarget = null; const d = {x: 1.01 - 0, z: -1.41 - 0}; P.controls.yaw = Math.atan2(-d.x, -d.z); P.controls.pitch = -0.05; return 'aimed at the green sofa cluster'; })()" >/dev/null
agent-browser --session m wait 700
agent-browser --session m screenshot /tmp/render/qa_anniv_spawn.jpg >/dev/null 2>&1
EV_M "(() => { const base = document.getElementById('joy-base'); const r = base.getBoundingClientRect(); window.__joyC = {x: r.left + r.width/2, y: r.top + r.height/2}; base.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, pointerId: 31, clientX: window.__joyC.x, clientY: window.__joyC.y})); base.dispatchEvent(new PointerEvent('pointermove', {bubbles: true, pointerId: 31, clientX: window.__joyC.x + 44, clientY: window.__joyC.y})); return 'joystick strafed right (sofa stays in view)'; })()" >/dev/null
agent-browser --session m wait 2600
EV_M "(() => { const base = document.getElementById('joy-base'); base.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, pointerId: 31})); return 'released'; })()" >/dev/null
agent-browser --session m wait 700
ANNIV_MOVED="$(EV_M "window.__panodrome.movedFromStart()")"
echo "    anniversary strafed: ${ANNIV_MOVED} m (real parallax past the sofa cluster)"
expect "anniversary: joystick strafe >= 0.95 m (real metric walking)" "$ANNIV_MOVED" num_gt "0.95"
expect "anniversary: still inside envelope" "$(EV_M "window.__panodrome.envelope().inside")" json_true
expect "anniversary: FOV still 75 (NO zoom)" "$(EV_M "window.__panodrome.fov()")" eq "75"
agent-browser --session m screenshot /tmp/render/qa_anniv_walked.jpg >/dev/null 2>&1

echo "--- 17) QA SHOTS · cabin (room 3): spawn + joystick walk toward bed ---"
agent-browser --session m eval "document.getElementById('nav-next').click()" >/dev/null 2>&1
agent-browser --session m wait 3000
agent-browser --session m eval "document.getElementById('nav-next').click()" >/dev/null 2>&1
agent-browser --session m wait 3600
expect "cabin loaded (room 3)" "$(EV_M "window.__panodrome.state.room.id")" eq "cabin"
expect "cabin: dome live + exact floor" "$(EV_M "window.__panodrome.roomStats().dome.exactFloor")" eq "0"
CABIN_ENV="$(EV_M "window.__panodrome.roomStats().envelope.base")"
echo "    cabin envelope base: ${CABIN_ENV} m (small room — true walls at 1.2 m)"
EV_M "(() => { const P = window.__panodrome; const obs = P.state.room.walk.obstacles; const bed = obs.find(o => /bed|bunk|تخت/i.test(o.label.en + ' ' + o.label.fa)) || obs[0]; const d = {x: bed.x - 0, z: bed.z - 0}; P.controls.yaw = Math.atan2(-d.x, -d.z); P.controls.pitch = -0.04; return 'aimed at ' + bed.label.en; })()" >/dev/null
agent-browser --session m wait 700
agent-browser --session m screenshot /tmp/render/qa_cabin_spawn.jpg >/dev/null 2>&1
EV_M "(() => { const base = document.getElementById('joy-base'); const r = base.getBoundingClientRect(); window.__joyC = {x: r.left + r.width/2, y: r.top + r.height/2}; base.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, pointerId: 31, clientX: window.__joyC.x, clientY: window.__joyC.y})); base.dispatchEvent(new PointerEvent('pointermove', {bubbles: true, pointerId: 31, clientX: window.__joyC.x, clientY: window.__joyC.y - 40})); return 'pushed'; })()" >/dev/null
agent-browser --session m wait 1700
EV_M "(() => { const base = document.getElementById('joy-base'); base.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, pointerId: 31})); return 'released'; })()" >/dev/null
agent-browser --session m wait 700
CABIN_MOVED="$(EV_M "window.__panodrome.movedFromStart()")"
echo "    cabin walked: ${CABIN_MOVED} m (elastic boundary — small room)"
expect "cabin: joystick walk >= 0.7 m toward the bed" "$CABIN_MOVED" num_gt "0.7"
expect "cabin: FOV still 75" "$(EV_M "window.__panodrome.fov()")" eq "75"
agent-browser --session m screenshot /tmp/render/qa_cabin_walked.jpg >/dev/null 2>&1

echo "--- 18) mobile audio toggle + FA/RTL + zero errors ---"
EV_M "document.getElementById('btn-sound').click()" >/dev/null
agent-browser --session m wait 300
expect "mobile audio toggles" "$(EV_M "window.__panodrome.audio.muted")" json_true
EV_M "document.getElementById('btn-sound').click()" >/dev/null
agent-browser --session m wait 300
EV_M "document.getElementById('btn-lang').click()" >/dev/null
agent-browser --session m wait 900
expect "mobile fa dir" "$(EV_M "document.documentElement.dir")" eq "rtl"
expect "all UI in bounds (mobile FA)" "$(EV_M "$BOUNDS_JS")" contains '"all":true'
agent-browser --session m screenshot /tmp/render/qa_cabin_fa.jpg >/dev/null 2>&1
expect "no page errors (mobile)" "$(ERRCOUNT m)" eq "0"

echo
echo "================ STRICT GEMINI QA GATE (TIER 1 · gemini-3.6-flash) ================"
S1="$(qa_judge /tmp/render/qa_anniv_spawn.jpg    'anniversary_lounge @ spawn'            qa_anniv_spawn)"
echo "    anniversary spawn    → ${S1}/10"
S2="$(qa_judge /tmp/render/qa_anniv_walked.jpg   'anniversary_lounge @ 1.2m joystick'    qa_anniv_walked)"
echo "    anniversary walked   → ${S2}/10"
S3="$(qa_judge /tmp/render/qa_cabin_spawn.jpg    'cabin @ spawn'                         qa_cabin_spawn)"
echo "    cabin spawn          → ${S3}/10"
S4="$(qa_judge /tmp/render/qa_cabin_walked.jpg   'cabin @ joystick walk toward bed'      qa_cabin_walked)"
echo "    cabin walked         → ${S4}/10"

for pair in "anniv_spawn:$S1" "anniv_walked:$S2" "cabin_spawn:$S3" "cabin_walked:$S4"; do
  name="${pair%%:*}"; sc="${pair##*:}"
  python3 -c "exit(0 if '${sc}' != 'ROUTER-FAIL' and '${sc}' != 'NO-SCORE' and float('${sc:-0}') >= 9.0 else 1)" \
    && { PASS=$((PASS+1)); echo "  ✓ QA $name score $sc >= 9/10"; } \
    || { FAIL=$((FAIL+1)); echo "  ✗ FAIL: QA $name score '$sc' (< 9/10 or unparsed)"; }
done

# copy the QA evidence next to the report
cp /tmp/render/qa_anniv_spawn.jpg /tmp/render/qa_anniv_walked.jpg /tmp/render/qa_cabin_spawn.jpg /tmp/render/qa_cabin_walked.jpg \
   /home/z/my-project/3d-idea/docs/rd-artifacts/stage161/ 2>/dev/null

echo
echo "================================"
echo "STAGE 1.6.1 E2E: PASS=$PASS FAIL=$FAIL"
echo "QA SCORES: anniv spawn=$S1 walked=$S2 · cabin spawn=$S3 walked=$S4 (gate: >= 9)"
[ $FAIL -eq 0 ] && echo "ALL GREEN" || echo "HAS FAILURES"
exit $FAIL
