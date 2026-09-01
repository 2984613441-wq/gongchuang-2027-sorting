from __future__ import annotations

import io
import json
import unittest

from jsonl_emitter import detection_line, fake_detection_lines, stream_lines


class JsonlEmitterTests(unittest.TestCase):
    def test_detection_line_has_exactly_bridge_fields(self):
        line = detection_line(7, "class_a", 0.91, 123456)
        self.assertEqual(json.loads(line), {
            "frame_id": 7,
            "label": "class_a",
            "confidence": 0.91,
            "ts_ms": 123456,
        })
        self.assertEqual(set(json.loads(line)),
                         {"frame_id", "label", "confidence", "ts_ms"})

    def test_no_target_frame_uses_null_label(self):
        line = detection_line(8, None, 0.0, 123556)
        self.assertEqual(json.loads(line)["label"], None)

    def test_fake_source_has_release_window(self):
        lines = list(fake_detection_lines("a", 1.0, 3))
        self.assertEqual(len(lines), 6)
        self.assertEqual(json.loads(lines[0])["label"], "a")
        self.assertEqual(json.loads(lines[3])["label"], None)

    def test_stream_lines_writes_flushed_lines(self):
        buffer = io.StringIO()
        stream_lines(["a", "b"], buffer)
        self.assertEqual(buffer.getvalue(), "a\nb\n")


if __name__ == "__main__":
    unittest.main()
