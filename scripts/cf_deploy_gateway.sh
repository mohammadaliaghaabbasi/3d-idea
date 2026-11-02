#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Deploys / updates the Panodrome AI Gateway on Cloudflare:
#   edge Worker + Durable Object pinned to North America (locationHint enam)
#   -> reverse proxy for generativelanguage.googleapis.com
#
# Usage:   bash scripts/cf_deploy_gateway.sh
# Needs:   .env in the repo root with CLOUDFLARE_API_TOKEN=...
#          (.env is git-ignored, mode 600 — NEVER hardcode the token)
#
# After success it prints:  GATEWAY_URL=https://<name>.<subdomain>.workers.dev
# Put that URL into .env as GEMINI_PROXY_URL=... and skills/ai_router.py
# will automatically route all Gemini tiers through the gateway.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."

WORKER_NAME="${WORKER_NAME:-panodrome-ai-gw}"
NS_NAME="${NS_NAME:-panodrome-gemini-fetcher}"
API="https://api.cloudflare.com/client/v4"

TOKEN="$(grep -E '^CLOUDFLARE_API_TOKEN=' .env | head -1 | cut -d= -f2- | tr -d '[:space:]')"
if [ -z "$TOKEN" ]; then echo "ERROR: CLOUDFLARE_API_TOKEN missing in .env" >&2; exit 1; fi

auth() { echo "Authorization: Bearer $TOKEN"; }

echo "[1/6] verifying token ..."
curl -sS -m 30 -H "$(auth)" "$API/user/tokens/verify" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("success"), d.get("errors"); print("      token OK (status: %s)" % d["result"]["status"])'

echo "[2/6] resolving account ..."
ACC="$(curl -sS -m 30 -H "$(auth)" "$API/accounts?per_page=5" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("success"), d.get("errors"); print(d["result"][0]["id"])')"
echo "      account: $ACC"

echo "[3/6] ensuring Durable Object namespace '$NS_NAME' (create-or-reuse) ..."
NS_ID="$(curl -sS -m 30 -X POST "$API/accounts/$ACC/workers/durable_objects/namespaces" \
  -H "$(auth)" -H "Content-Type: application/json" -d "{\"name\":\"$NS_NAME\"}" \
  | python3 -c 'import json,sys
d=json.load(sys.stdin)
print(d["result"]["id"] if d.get("success") else "")')"
if [ -z "$NS_ID" ]; then
  NS_ID="$(curl -sS -m 30 -H "$(auth)" "$API/accounts/$ACC/workers/durable_objects/namespaces?per_page=100" \
    | NS_NAME="$NS_NAME" python3 -c 'import json,sys,os
d=json.load(sys.stdin)
assert d.get("success"), d.get("errors")
print(next(n["id"] for n in d["result"] if n["name"]==os.environ["NS_NAME"]))')"
fi
echo "      namespace: $NS_ID"

echo "[4/6] deploying worker '$WORKER_NAME' (edge + pinned DO) ..."
META="{\"main_module\":\"worker.js\",\"compatibility_date\":\"2026-10-01\",\"bindings\":[{\"type\":\"durable_object_namespace\",\"name\":\"ORIGIN_FETCHER\",\"class_name\":\"GeminiOriginFetcher\",\"namespace_id\":\"$NS_ID\"}],\"migrations\":[{\"tag\":\"v1\",\"new_classes\":[\"GeminiOriginFetcher\"]}]}"
curl -sS -m 120 -X PUT "$API/accounts/$ACC/workers/scripts/$WORKER_NAME" \
  -H "$(auth)" \
  -F "metadata=$META;type=application/json" \
  -F 'worker.js=@scripts/cf_gateway_worker.js;filename=worker.js;type=application/javascript+module' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("success"), d.get("errors"); print("      deployed:", (d.get("result") or {}).get("id") or "OK")'

echo "[5/6] enabling workers.dev route ..."
curl -sS -m 30 -X POST "$API/accounts/$ACC/workers/scripts/$WORKER_NAME/subdomain" \
  -H "$(auth)" -H "Content-Type: application/json" -d '{"enabled":true}' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("success"), d.get("errors"); print("      workers.dev enabled")'

echo "[6/6] resolving gateway URL ..."
SUB="$(curl -sS -m 30 -H "$(auth)" "$API/accounts/$ACC/workers/subdomain" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("success"), d.get("errors"); print(d["result"]["subdomain"])')"

echo
echo "GATEWAY_URL=https://$WORKER_NAME.$SUB.workers.dev"
