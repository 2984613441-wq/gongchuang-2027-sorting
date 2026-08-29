from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from sorting_vision.color_quant import dominant_color, mmcq


class ColorQuantTests(unittest.TestCase):
    def test_mmcq_reaches_requested_count_when_distinct_colors_allow_it(self) -> None:
        colors = (
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (255, 255, 0),
            (0, 255, 255),
            (255, 0, 255),
        )
        pixels = [channel for rgb in colors for _ in range(4) for channel in (*rgb, 255)]
        self.assertEqual(6, len(mmcq(pixels, color_count=6)))

    def test_all_transparent_roi_fails_with_explicit_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "visible"):
            dominant_color([0, 0, 0, 0] * 4)

    def test_incomplete_rgba_pixel_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "RGBA"):
            mmcq([255, 0, 0, 255, 1], color_count=2)


if __name__ == "__main__":
    unittest.main()
