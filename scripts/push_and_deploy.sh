#!/bin/bash
# ============================================================================
# PANODROME — one-command publish for Stage 2.0 (zero-warp architecture)
# Token arrives ONLY via env var T (never stored in any file).
#
#   T="github_pat_..." bash scripts/push_and_deploy.sh
#
# 1) push the private source repo  mohammadaliaghaabbasi/3d-idea  (main)
# 2) deploy public/ to the live mirror mohammadaliaghaabbasi/panodrome
#    → https://mohammadaliaghaabbasi.github.io/panodrome/
# ============================================================================
set -e
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OWNER="mohammadaliaghaabbasi"
SRC="3d-idea"

if [ -z "$T" ]; then
  echo "ERROR: set T (GitHub token) — T=\"github_pat_...\" bash scripts/push_and_deploy.sh"
  exit 1
fi
cd "$REPO_DIR"

AUTH=$(printf 'x-access-token:%s' "$T" | base64 | tr -d '\n')

echo "—— 1) push $OWNER/$SRC (main) ——"
git -c "http.extraheader=Authorization: Basic $AUTH" push -q \
  "https://github.com/$OWNER/$SRC.git" main:main 2>&1 | sed "s|$T|***|g" || true
echo "   source repo pushed."

echo "—— 2) deploy the live site ——"
bash "$REPO_DIR/scripts/deploy_gh_pages.sh"
