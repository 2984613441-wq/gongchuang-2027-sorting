"""Host-only end-to-end demo of the preliminary-round visual chain.

It strings together the three pure-logic pieces:

1. shape comes from a detection (here a synthetic detector output),
2. color comes from ``color_quant`` on each cropped ROI,
3. ``sort_plan`` groups items and assigns storage boxes,
4. ``info_decode`` is exercised as the optional final-round slot.

No camera, model, serial port, or wire frame is involved.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from sorting_vision.info_decode import FakeInfoDecoder, InfoDecodeConfig
from sorting_vision.sort_plan import classify_and_plan
from sorting_vision.types import BoundingBox, RawDetection


BLOCKS = (
    ("red", (205, 25, 25)),
    ("blue", (25, 25, 205)),
    ("green", (25, 175, 60)),
    ("yellow", (225, 200, 20)),
    ("gray", (128, 128, 128)),
    ("cyan", (25, 200, 200)),
)


def build_frame(width: int, height: int, block_width: int):
    pixels: list[int] = []
    for y in range(height):
        for x in range(width):
            index = min(x // block_width, len(BLOCKS) - 1)
            r, g, b = BLOCKS[index][1]
            pixels += [r, g, b, 255]
    return pixels


def main() -> None:
    width, height, block_width = 600, 400, 100
    pixels = build_frame(width, height, block_width)

    detections = tuple(
        RawDetection(
            class_id=i,
            confidence=0.90,
            bbox=BoundingBox(i * block_width, 0, (i + 1) * block_width, height),
        )
        for i in range(len(BLOCKS))
    )

    plan = classify_and_plan(pixels, width, height, detections, box_count=6)

    print(f"plan: groups={plan.group_count} boxes={plan.box_count} valid={plan.valid}")
    for i, item in enumerate(plan.items, start=1):
        center = item.bbox.center
        print(
            f"item seq={i} shape={item.shape_id} color={item.color_name} "
            f"box={item.box_id} center=({center[0]:.0f},{center[1]:.0f})"
        )

    info = FakeInfoDecoder(InfoDecodeConfig(enable_ocr=True))
    print(f"info slot (final-round only): {info.decode(None)}")


if __name__ == "__main__":
    main()
