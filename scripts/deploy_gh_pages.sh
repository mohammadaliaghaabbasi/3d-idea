#!/bin/bash
# ============================================================================
# PANODROME — publish public/ as a GitHub Pages site (live preview URL)
# Token ONLY via env var T.  Usage:  T="github_pat_..." bash scripts/deploy_gh_pages.sh
# Result: https://mohammadaliaghaabbasi.github.io/3d-idea/
# ============================================================================
set -e
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OWNER="mohammadaliaghaabbasi"
REPO="3d-idea"
API="https://api.github.com"

if [ -z "$T" ]; then echo "ERROR: set T (GitHub token)"; exit 1; fi
cd "$REPO_DIR"

AUTH=$(printf 'x-access-token:%s' "$T" | base64 | tr -d '\n')

# ---------- 1) build an orphan gh-pages branch containing public/ ----------
git worktree add -q /tmp/panodrome-ghpages gh-pages 2>/dev/null || git worktree add -q --orphan -b gh-pages /tmp/panodrome-ghpages 2>/dev/null || {
  rm -rf /tmp/panodrome-ghpages
  git worktree add -q --orphan -b gh-pages /tmp/panodrome-ghpages
}
cd /tmp/panodrome-ghpages
git checkout --orphan gh-pages 2>/dev/null || true
git rm -rfq . 2>/dev/null || true
cp -r "$REPO_DIR/public/" .
git add -A
git commit -qm "panodrome: deploy public/ (Phase 1 spatial engine)" || true

# ---------- 2) push gh-pages ----------
if git -c "http.extraheader=Authorization: Basic $AUTH" push -q -f origin gh-pages 2>&1 | sed "s|$T|***|g"; then
  echo "gh-pages pushed"
else
  echo "gh-pages push failed"; cd "$REPO_DIR"; git worktree remove --force /tmp/panodrome-ghpages; exit 1
fi

# ---------- 3) enable GitHub Pages on gh-pages / root ----------
CODE=$(curl -s -o /tmp/gh_pages.json -w "%{http_code}" -X POST \
  -H "Authorization: token $T" -H "Accept: application/vnd.github+json" \
  "$API/repos/$OWNER/$REPO/pages" \
  -d '{"source":{"branch":"gh-pages","path":"/"}}')
if [ "$CODE" = "201" ]; then
  echo "GitHub Pages enabled"
elif [ "$CODE" = "409" ]; then
  curl -s -X PUT -H "Authorization: token $T" -H "Accept: application/vnd.github+json" \
    "$API/repos/$OWNER/$REPO/pages" \
    -d '{"source":{"branch":"gh-pages","path":"/"}}' > /dev/null
  echo "GitHub Pages source updated to gh-pages/"
else
  echo "Pages API HTTP $CODE (check /tmp/gh_pages.json — the site may already be enabled)"
fi

cd "$REPO_DIR"
git worktree remove --force /tmp/panodrome-ghpages

echo
echo "LIVE: https://$OWNER.github.io/$REPO/   (first build takes ~1 min)"
echo "Cloudflare Pages alternative: wrangler pages deploy public --project-name panodrome"
