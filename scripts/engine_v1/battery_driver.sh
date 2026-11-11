#!/bin/bash
# battery_driver.sh — v12 still battery on the 3 riskiest scenes (daemon driver).
# main1 = hero + sweep scene; main2 = far-view risk (entrance->living 13-38 m);
# bed3a = curved-wardrobe quadrant risk (worst holes scene in the v11 battery).
cd /home/z/my-project/3d-idea/scripts/engine_v1
for s in moradi_main1 moradi_main2 moradi_bed3a; do
  echo "=== BATTERY v12 $s ==="
  python3 moradi_battery_gen.py "$s" gen=v12
done
echo "=== BATTERY v12 ALL DONE ==="
