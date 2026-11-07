#!/usr/bin/env python3
"""Review-page thumbnails for the 10 moradi scenes (one house, Kuula/Mojtaba87).

Reads the existing 4096x2048 equirects in public/assets/panoramas/ and writes
960x480 q80 thumbs to public/labs/engine-v1/assets/moradi_thumbs/.
Source files are never modified (read-only inputs).
"""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]  # 3d-idea/
PANO = ROOT / "public" / "assets" / "panoramas"
OUT = ROOT / "public" / "labs" / "engine-v1" / "assets" / "moradi_thumbs"

SCENES = [
    "moradi_main1", "moradi_main2", "moradi_main3", "moradi_main4",
    "moradi_kit1", "moradi_kit2",
    "moradi_bed1a", "moradi_bed1b", "moradi_bed2a", "moradi_bed3a",
]
SIZE = (960, 480)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for s in SCENES:
        src = PANO / f"{s}.jpg"
        im = Image.open(src).convert("RGB")
        im = im.resize(SIZE, Image.LANCZOS)
        dst = OUT / f"{s}.jpg"
        im.save(dst, "JPEG", quality=80, optimize=True)
        print(f"{s}: {src.stat().st_size // 1024}KB -> {dst.stat().st_size // 1024}KB")
    print("done:", OUT)


if __name__ == "__main__":
    main()
