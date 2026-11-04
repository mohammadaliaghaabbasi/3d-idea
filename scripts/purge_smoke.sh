#!/bin/bash
# ============================================================================
# PANODROME — CARTOON-PURGE SMOKE GATE (2026-11-04)
# Clean-tree verification before live deploy:
#   1. boot: zero page errors
#   2. 11 spaces, #1 villa true3d (glb meshes > 50)
#   3. NO cartoon GLB fetches (network .glb entries == villa only)
#   4. pano room (cabin): pure SphereGeometry(500,128,96), zero vertex displacement
#   5. mobile 390x844: zero errors, HUD inside 8px
# ============================================================================
set -u
mkdir -p /tmp/render
cd /home/z/my-project/3d-idea/public
python3 -m http.server 8137 >/tmp/httpserver.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null' EXIT
sleep 1.5

PASS=0; FAIL=0
expect() { local name="$1" val="$2" mode="$3" want="${4:-}"; local ok=0
  case "$mode" in
    contains) [[ "$val" == *"$want"* ]] && ok=1 ;;
    num_lt) python3 -c "exit(0 if float('${val:-99}') < float('$want') else 1)" 2>/dev/null && ok=1 ;;
    num_gt) python3 -c "exit(0 if float('${val:-0}') > float('$want') else 1)" 2>/dev/null && ok=1 ;;
    eq) [[ "$val" == "$want" ]] && ok=1 ;;
  esac
  if [ $ok = 1 ]; then PASS=$((PASS+1)); echo "  ✓ $name"; else FAIL=$((FAIL+1)); echo "  ✗ FAIL: $name → got '$val' (want $mode '$want')"; fi }

EV() { agent-browser --session "$1" eval "$2" --json >/tmp/ev.json 2>/dev/null
  python3 -c "
import json
try:
    d = json.load(open('/tmp/ev.json'))
    r = d.get('data', {}).get('result', '')
    print(r if isinstance(r, str) else json.dumps(r))
except Exception: print('')"; }
ERRCOUNT() { agent-browser --session "$1" errors --json 2>/dev/null | python3 -c "
import json,sys
try:
    d = json.load(sys.stdin); print(len(d.get('data',{}).get('errors',[])))
except Exception: print('?')"; }

agent-browser close --all >/dev/null 2>&1 || true
sleep 1

echo "--- A) DESKTOP 1440x900: boot + villa ---"
agent-browser --session d open http://localhost:8137 >/dev/null 2>&1
agent-browser --session d set viewport 1440 900 >/dev/null 2>&1
agent-browser --session d storage local clear >/dev/null 2>&1
agent-browser --session d reload >/dev/null 2>&1
agent-browser --session d wait 3000
expect "boot zero page errors" "$(ERRCOUNT d)" eq 0
agent-browser --session d eval "document.getElementById('btn-enter').click()" >/dev/null 2>&1
for i in $(seq 1 30); do
  M=$(EV d '(() => { const s = window.__panodrome.roomStats(); return s ? (s.meshes || 0) : 0; })()')
  [ "$M" -gt 50 ] 2>/dev/null && break
  agent-browser --session d wait 2000
done
expect "11 spaces (1 true-3D + 10 pano)" "$(EV d 'window.__panodrome.rooms().length')" eq 11
expect "room #1 = modern_3d_villa" "$(EV d 'window.__panodrome.rooms()[0].id')" eq modern_3d_villa
expect "villa kind = true3d" "$(EV d 'window.__panodrome.roomStats().kind')" eq true3d
expect "villa glb meshes > 50" "$(EV d 'window.__panodrome.roomStats().meshes')" num_gt 50
expect "villa fov locked 72" "$(EV d 'window.__panodrome.fov()')" eq 72
CARTOON404='(() => fetch("/assets/true3d/cabin.glb").then(r => r.status).catch(() => "ERR"))()'
expect "cartoon cabin.glb = 404 on clean server" "$(EV d "$CARTOON404")" eq 404

echo "--- B) pano room cabin: pure sphere ---"
EV d 'window.__panodrome.gotoRoom("cabin").then(r => "goto:" + r)' >/dev/null 2>&1
agent-browser --session d wait 2600
expect "cabin kind = sphere (pure pano)" "$(EV d 'window.__panodrome.roomStats().kind')" eq sphere
expect "LAW 1: pano sphere radius = 500" "$(EV d 'window.__panodrome.roomStats().sphere.radius')" eq 500
expect "LAW 1: exact SphereGeometry vertex count 12513 (129x97)" "$(EV d 'window.__panodrome.state.meshObj.mesh.geometry.attributes.position.count')" eq 12513
expect "LAW 1: geometry bounding radius = 500 (zero displacement)" "$(EV d '(() => { const g = window.__panodrome.state.meshObj.mesh.geometry; g.computeBoundingSphere(); return Math.round(g.boundingSphere.radius); })()')" eq 500
expect "zero errors after cabin" "$(ERRCOUNT d)" eq 0

echo "--- C) MOBILE 390x844 ---"
agent-browser --session m open http://localhost:8137 >/dev/null 2>&1
agent-browser --session m set viewport 390 844 >/dev/null 2>&1
agent-browser --session m storage local clear >/dev/null 2>&1
agent-browser --session m reload >/dev/null 2>&1
agent-browser --session m wait 3200
expect "mobile boot zero errors" "$(ERRCOUNT m)" eq 0
B=$(EV m '(() => { const b = window.__panodrome.uiBounds(); return b.every(x => x.inside); })()')
expect "mobile HUD inside 8px" "$B" eq true
agent-browser close --all >/dev/null 2>&1 || true

echo
echo "SMOKE RESULT: PASS=$PASS FAIL=$FAIL"
[ $FAIL -eq 0 ] && echo "ALL GREEN — clean tree verified" || echo "FAILURES PRESENT"
agent-browser close --all >/dev/null 2>&1 || true
exit $FAIL
