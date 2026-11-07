#!/bin/bash
# moradi_runner.sh — sequential Phase C battery for all remaining scenes + ladders.
# main1 partial (px/mx + pano refs done) — re-run skips fresh positions.
set -x
cd /home/z/my-project/3d-idea
S=scripts/engine_v1/moradi_battery.py
for sc in moradi_main1 moradi_main2 moradi_main3 moradi_main4 moradi_kit1 moradi_kit2 moradi_bed1a moradi_bed1b moradi_bed2a moradi_bed3a; do
  echo "=== SCENE $sc $(date +%T) ==="
  python3 $S $sc || echo "BATTERY_FAIL $sc"
done
# distance ladders (predicted-worst dir + calm dir, 0.2..1.3 m)
echo "=== LADDER moradi_bed1a (mx worst, px calm) $(date +%T) ==="
python3 $S moradi_bed1a --ladder --dirs=mx,px || echo "BATTERY_FAIL ladder bed1a"
echo "=== LADDER moradi_main3 (pz worst, px calm) $(date +%T) ==="
python3 $S moradi_main3 --ladder --dirs=pz,px || echo "BATTERY_FAIL ladder main3"
echo "=== ALL DONE $(date +%T) ==="
