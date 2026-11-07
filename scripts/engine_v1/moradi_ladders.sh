#!/bin/bash
# moradi_ladders.sh — distance ladders (fixed dir names)
set -x
cd /home/z/my-project/3d-idea
S=scripts/engine_v1/moradi_battery.py
echo "=== LADDER moradi_bed1a (travel -x worst-family, +x calm) $(date +%T) ==="
python3 $S moradi_bed1a --ladder "--dirs=-x,+x" || echo "BATTERY_FAIL ladder bed1a"
echo "=== LADDER moradi_main3 (travel +z worst-family, +x calm) $(date +%T) ==="
python3 $S moradi_main3 --ladder "--dirs=+z,+x" || echo "BATTERY_FAIL ladder main3"
echo "=== LADDERS DONE $(date +%T) ==="
