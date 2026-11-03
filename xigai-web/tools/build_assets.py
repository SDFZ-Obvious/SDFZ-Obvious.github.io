#!/usr/bin/env python3
"""Convert PowerPoint slide PNG exports into web-ready WebP assets.

Usage:
    python tools/build_assets.py [--source slides-export] [--root .]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="slides-export", help="directory with slide-XX.png")
    parser.add_argument("--root", default=".", help="project root")
    parser.add_argument("--quality", type=int, default=92, help="WebP quality for slides")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    source = (root / args.source).resolve()
    slide_dir = root / "assets" / "slides"
    thumb_dir = root / "assets" / "thumbs"
    slide_dir.mkdir(parents=True, exist_ok=True)
    thumb_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(source.glob("slide-*.png"))
    if not files:
        raise SystemExit(f"No slide-*.png found in {source}")

    total_slide = 0
    total_thumb = 0
    for file in files:
        image = Image.open(file).convert("RGB")

        slide_path = slide_dir / f"{file.stem}.webp"
        image.save(slide_path, "WEBP", quality=args.quality, method=6)

        thumb = image.copy()
        thumb.thumbnail((640, 360), Image.Resampling.LANCZOS)
        thumb_path = thumb_dir / f"{file.stem}.webp"
        thumb.save(thumb_path, "WEBP", quality=82, method=6)

        total_slide += slide_path.stat().st_size
        total_thumb += thumb_path.stat().st_size
        print(f"{file.name}: {image.width}x{image.height} -> {slide_path.name}")

    print(f"\nslides: {total_slide / 1024 / 1024:.2f} MB")
    print(f"thumbs: {total_thumb / 1024 / 1024:.2f} MB")


if __name__ == "__main__":
    main()
