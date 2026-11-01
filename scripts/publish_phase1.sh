#!/bin/bash
# ============================================================================
# PANODROME — Phase 1 publish: push main + update GitHub Issues #1/#2/#3
# Token arrives ONLY via env var T (never stored in any file).
#   Usage:  T="github_pat_..." bash scripts/publish_phase1.sh
# ============================================================================
set -e
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OWNER="mohammadaliaghaabbasi"
REPO="3d-idea"
API="https://api.github.com"

if [ -z "$T" ]; then echo "ERROR: set T (GitHub token) — T=\"...\" bash scripts/publish_phase1.sh"; exit 1; fi

cd "$REPO_DIR"

# ---------- 1) git identity from the real profile ----------
curl -s -H "Authorization: token $T" "$API/user" -o /tmp/gh_user.json
GIT_NAME=$(python3 -c "import json; d=json.load(open('/tmp/gh_user.json')); print(d.get('name') or d.get('login') or 'user')")
GIT_EMAIL=$(python3 -c "import json; d=json.load(open('/tmp/gh_user.json')); print(d.get('email') or (d.get('login')+'@users.noreply.github.com'))")
git config user.name "$GIT_NAME"
git config user.email "$GIT_EMAIL"

# ---------- 2) commit anything pending ----------
git add -A
if git diff --cached --quiet; then
  echo "nothing new to commit"
else
  git commit -m "phase1: Panodrome Spatial Engine v1 — 6DoF walkable rooms, smart portals, spatial audio, EN/FA HUD"
  echo "commit ok"
fi

# ---------- 3) push main ----------
AUTH=$(printf 'x-access-token:%s' "$T" | base64 | tr -d '\n')
if git -c "http.extraheader=Authorization: Basic $AUTH" push -q origin main 2>&1 | sed "s|$T|***|g"; then
  echo "push ok"
else
  echo "push failed"; exit 1
fi

# ---------- 4) GitHub Issues: close #1 #2 #3 as resolved ----------
comment_and_close() {
  local num="$1" title="$2" body="$3"
  local exists
  exists=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: token $T" "$API/repos/$OWNER/$REPO/issues/$num")
  if [ "$exists" = "200" ]; then
    curl -s -X POST -H "Authorization: token $T" \
      -d "$(python3 -c "import json,sys; print(json.dumps({'body': sys.argv[1]}))" "$body")" \
      "$API/repos/$OWNER/$REPO/issues/$num/comments" > /dev/null
    curl -s -X PATCH -H "Authorization: token $T" \
      -d '{"state":"closed"}' \
      "$API/repos/$OWNER/$REPO/issues/$num" > /dev/null
    echo "issue #$num ($title): commented + closed"
  else
    # create it already-closed so the decision history is recorded
    curl -s -X POST -H "Authorization: token $T" \
      -d "$(python3 -c "import json,sys; print(json.dumps({'title': sys.argv[1], 'body': sys.argv[2], 'labels': ['decision']}))" "$title" "$body")" \
      "$API/repos/$OWNER/$REPO/issues" > /dev/null
    local newnum
    newnum=$(curl -s -H "Authorization: token $T" "$API/repos/$OWNER/$REPO/issues?state=open&labels=decision" | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['number'])")
    curl -s -X PATCH -H "Authorization: token $T" -d '{"state":"closed"}' "$API/repos/$OWNER/$REPO/issues/$newnum" > /dev/null
    echo "issue #$num missing -> recreated as #$newnum and closed"
  fi
}

comment_and_close 1 "Platform name" \
"RESOLVED (owner approval, 2026-11-01): the platform name is **Panodrome** 🎉
Locked across codebase, UI, rooms DB and MEMORY_STATE.json. Domain research: panodrome.com / panodrome.io free at 2026-11-01 (docs/11). Next: owner registers the domain."

comment_and_close 2 "First build step: Phase 0 mockup vs Phase 1 engine" \
"RESOLVED (owner decision, 2026-11-01): skip static mockups — build the **Phase 1 Core Spatial Engine** directly, alongside the first 10 PolyHaven rooms (Issue #3).
Delivered: 6DoF walkable displaced-sphere engine in public/ (WASD/drag/scroll, safe-zone clamping, GSAP portal transitions, procedural spatial audio, glassmorphism EN/FA RTL HUD)."

comment_and_close 3 "First 10 PolyHaven interior panoramas" \
"RESOLVED (2026-11-01): 10 diverse rooms ingested by skills/ingest_polyhaven.py —
anniversary_lounge · photo_studio_loft_hall · art_studio · ballroom · large_corridor · comfy_cafe · castle_zavelstein_cellar · cabin · quadrangle_sunny · school_hall
Each with: 4K equirect JPG · seamless two-channel depth PNG (procedural box prior, DA2/PanDA upgrade hook) · AI-vision door portals (data/vision_overrides.json) · style tags · audio profiles · bilingual EN/FA metadata · CC0 attribution. Canonical DB: data/rooms_db.json."

# ---------- 5) verify ----------
curl -s -H "Authorization: token $T" "$API/repos/$OWNER/$REPO" -o /tmp/gh_repo2.json
python3 -c "import json; d=json.load(open('/tmp/gh_repo2.json')); print('VERIFY ->', d.get('full_name'), '| default_branch:', d.get('default_branch'), '| size:', d.get('size'), 'KB')"
echo
echo "DONE. Live preview (optional):  T=\$T bash scripts/deploy_gh_pages.sh"
