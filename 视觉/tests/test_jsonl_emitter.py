from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from jsonl_emitter import detection_line, fake_detection_lines


class JsonlEmitterTests(unittest.TestCase):
    def test_detection_line_keeps_exact_bridge_schema(self) -> None:
        payload = json.loads(detection_line(7, "class_a", 0.91, 123456))
        self.assertEqual(
            {"frame_id", "label", "confidence", "ts_ms"}, set(payload)
        )

    def test_detection_line_rejects_non_finite_or_out_of_range_confidence(self) -> None:
        for confidence in (math.nan, math.inf, -0.01, 1.01):
            with self.subTest(confidence=confidence), self.assertRaises(ValueError):
                detection_line(1, "class_a", confidence, 1)

    def test_detection_line_rejects_invalid_identifiers(self) -> None:
        invalid_calls = (
            (-1, "class_a", 0.5, 1),
            (True, "class_a", 0.5, 1),
            (1, "", 0.5, 1),
            (1, "class_a", 0.5, -1),
        )
        for args in invalid_calls:
            with self.subTest(args=args), self.assertRaises(ValueError):
                detection_line(*args)

    def test_fake_source_rejects_zero_frames_even_for_direct_callers(self) -> None:
        with self.assertRaises(ValueError):
            list(fake_detection_lines("class_a", 0.5, 0))


if __name__ == "__main__":
    unittest.main()
