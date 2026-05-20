#!/usr/bin/env python3
"""Run the Divide Scanned Images core pipeline against an image on disk."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "divide-scanned-images"))

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - environment-specific message
    raise SystemExit("Pillow is required for disk image loading: python -m pip install pillow") from exc

from divide_scanned_images_core import detect_crops
from divide_scanned_images_core import extract_crop_rgba
from divide_scanned_images_core import postprocess_crop_item
from divide_scanned_images_core import sample_background
from divide_scanned_images_core import sample_corner_background


CORNER_CHOICES = ("top-left", "top-right", "bottom-left", "bottom-right")


def load_rgba(path: Path) -> tuple[bytes, int, int]:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
    return rgba.tobytes(), rgba.width, rgba.height


def save_rgba(path: Path, rgba: bytes, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.frombytes("RGBA", (width, height), rgba).save(path)


def worker_count(task_count: int) -> int:
    return min(task_count, max(1, (os.cpu_count() or 2) - 1))


def run(args: argparse.Namespace) -> int:
    rgba, width, height = load_rgba(args.input)
    if args.background == "corners":
        background = sample_corner_background(rgba, width, height)
    else:
        background = sample_background(
            rgba,
            width,
            height,
            args.sample_corner,
            args.sample_x,
            args.sample_y,
        )

    settings = {
        "square": args.square_crop,
        "padding": args.padding,
        "threshold": args.threshold,
        "min_size": args.min_size,
        "limit": args.limit,
        "deskew": args.deskew,
        "deskew_max_angle": args.deskew_max_angle,
        "deskew_crop_padding": args.deskew_crop_padding,
    }

    crops = detect_crops(
        rgba,
        width,
        height,
        background,
        threshold=args.threshold,
        min_size=args.min_size,
        limit=args.limit,
        padding=args.padding,
        square=args.square_crop,
    )

    print(f"Loaded: {args.input} ({width} x {height})")
    print(f"Background: {background}")
    print(f"Detected crops: {len(crops)}")

    items = []
    for index, crop in enumerate(crops):
        crop_bytes, crop_width, crop_height = extract_crop_rgba(rgba, width, height, crop, background)
        items.append(
            {
                "index": index,
                "bytes": crop_bytes,
                "width": crop_width,
                "height": crop_height,
                "rotation": 0,
                "deskew_angle": 0.0,
            }
        )

    if len(items) > 1:
        workers = worker_count(len(items))
        print(f"Processing crops with {workers} worker(s)")
        with ProcessPoolExecutor(max_workers=workers) as executor:
            processed_items = list(executor.map(postprocess_crop_item, items, [background] * len(items), [settings] * len(items)))
    else:
        processed_items = [postprocess_crop_item(item, background, settings) for item in items]

    for item in sorted(processed_items, key=lambda value: value["index"]):
        index = item["index"]
        output = args.output_dir / f"{args.prefix}{index + args.start_number:05d}.png"
        save_rgba(output, item["bytes"], item["width"], item["height"])
        print(
            f"{index + 1}: {output.name} "
            f"{item['width']} x {item['height']} deskew={item['deskew_angle']:.2f}"
        )

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("disk-test-output"))
    parser.add_argument("--prefix", default="Crop")
    parser.add_argument("--start-number", type=int, default=1)
    parser.add_argument("--threshold", type=int, default=25)
    parser.add_argument("--min-size", type=int, default=100)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--padding", type=int, default=0)
    parser.add_argument("--square-crop", action="store_true")
    parser.add_argument("--deskew", action="store_true")
    parser.add_argument("--deskew-max-angle", type=int, default=15)
    parser.add_argument("--deskew-crop-padding", type=int, default=0)
    parser.add_argument("--background", choices=("sample", "corners"), default="sample")
    parser.add_argument("--sample-corner", choices=CORNER_CHOICES, default="top-left")
    parser.add_argument("--sample-x", type=int, default=25)
    parser.add_argument("--sample-y", type=int, default=25)
    return parser


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
