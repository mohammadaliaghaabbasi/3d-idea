#!/bin/bash
# ============================================================================
# PANODROME — R&D LOOP RUNNER
#
#   bash scripts/rd_converge.sh            # calibrate + loop to convergence
#   bash scripts/rd_converge.sh --quick    # smoke run (3 candidates, 1 iteration)
#
# Stage 1  calibrate the scorer (self-test must pass, else the run aborts: a
#          scorer that cannot reproduce a reference built from itself cannot rank
#          anything).
# Stage 2  iterate: grid -> refine around the winner until the gain drops below
#          --min-gain (0.05 dB).
# Stage 3  print the winning configuration in the exact terms the bake uses
#          (splats per photographed pixel, splat radius in pixel footprints).
#
# Read-only: it writes docs/agent-work/2026-11-12-rd-loop/rd_results.json and
# touches nothing in public/. Adopting the winner is a separate, deliberate step.
# ============================================================================
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"
OUT="docs/agent-work/2026-11-12-rd-loop/rd_results.json"
mkdir -p "$(dirname "$OUT")"

QUICK=""
ITERS=6
for a in "$@"; do
  case "$a" in
    --quick) QUICK="--quick"; ITERS=2 ;;
  esac
done

echo "== 1. calibrate =="
python3 skills/rd_loop.py --self-test || {
  echo "SELF-TEST FAILED — the scorer is not trustworthy; stopping before ranking." >&2
  exit 2
}

echo
echo "== 2. loop =="
python3 skills/rd_loop.py --iters "$ITERS" $QUICK --out "$OUT" || exit 3

echo
echo "== 3. winner =="
python3 - "$OUT" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
w = d["winner"]
c = w["config"]
print(f"  density      {c['density']} splats per photographed pixel")
print(f"  sigma        {c['sigma_px']} pixel footprints")
print(f"  aspect       {c['aspect']}  (1.0 = isotropic)")
print(f"  mean PSNR    {w['mean_psnr']} dB   {w['per_pose']}")
print(f"  splats       {w['splats']}  ({w['size_mb_est']} MB estimated in SPZ)")
print(f"  iterations   {len(d['iterations'])}  (self-test {d['self_test']['psnr']} dB)")
PY

echo
echo "NEXT (manual, deliberate): apply the winner to skills/bake_splat.py, re-bake,"
echo "then re-run skills/engine_sweep.py to confirm the real clouds improved."
