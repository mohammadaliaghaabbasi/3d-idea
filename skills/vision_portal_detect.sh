#!/bin/bash
# Panodrome — AI vision pass: detect doorways + best facing per room.
# Writes /tmp/vlm_<room>.json per room (raw VLM responses).
set -u
cd "$(dirname "$0")/.."

PROMPT='This is a 360-degree equirectangular panorama of an architectural interior (the right edge continues into the left edge). You are standing at its center. A horizontal position in the image can be expressed as a fraction: 0.0 = left edge, 0.5 = exact center, 1.0 = right edge (same direction as 0.0). Look carefully for REAL doorways, doors, archways or open passages leading to another space (not windows, not mirrors, not paintings of doors). Answer with STRICT JSON only, no prose: {"facing": <single number 0-1, the fraction of the most interesting direction to look at initially, e.g. toward the main furniture or window light>, "doors": [<up to 2 numbers 0-1, horizontal fractions where real doorways/archways/openings are visible>], "notes": ["<short description of each door>", ...]}. If no real doorway is visible, use an empty array.'

ROOMS="anniversary_lounge photo_studio_loft_hall art_studio ballroom large_corridor comfy_cafe castle_zavelstein_cellar cabin quadrangle_sunny school_hall"

for rid in $ROOMS; do
  echo "--- $rid ---"
  z-ai vision -p "$PROMPT" -i "public/assets/preview/$rid.jpg" -o "/tmp/vlm_$rid.json" 2>&1 | rg "File saved|error|Error" || true
done
echo "ALL DONE"
