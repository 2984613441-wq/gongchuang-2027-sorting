from __future__ import annotations

import unittest

from electrical_control.rpi.log import (
    CentralLog,
    DISPLAY,
    FAULT,
    RESULT,
    STARTUP,
    TASK,
)


class CentralLogTests(unittest.TestCase):
    def test_capacity_is_explicit_positive_non_boolean(self) -> None:
        for value in (0, -1, True, False, None):
            with self.subTest(value=value):
                with self.assertRaises((TypeError, ValueError)):
                    CentralLog(value)

    def test_records_structured_events_in_order(self) -> None:
        log = CentralLog(4)

        log.record(STARTUP, now=1.0, round_id="round-new", detail="boot")
        log.record(TASK, now=2.0, round_id="round-new", task_id=7, frame_seq=11, target_seq=1)
        log.record(RESULT, now=3.0, round_id="round-new", task_id=7, result_code=0, success_count=1)
        log.record(DISPLAY, now=4.0, round_id="round-new", task_id=7, target_seq=1)

        self.assertEqual(4, len(log.entries))
        self.assertEqual(STARTUP, log.entries[0].kind)
        self.assertEqual(RESULT, log.entries[2].kind)
        self.assertEqual(1, log.entries[2].success_count)

    def test_oldest_entry_is_dropped_when_full(self) -> None:
        log = CentralLog(2)

        log.record(STARTUP, now=1.0)
        log.record(TASK, now=2.0, task_id=7)
        log.record(FAULT, now=3.0, detail="DISPLAY_ACK_TIMEOUT")

        self.assertEqual(2, len(log.entries))
        self.assertEqual(TASK, log.entries[0].kind)
        self.assertEqual(FAULT, log.entries[1].kind)

    def test_rejects_unknown_kind_and_non_finite_time(self) -> None:
        log = CentralLog(2)

        with self.assertRaises(ValueError):
            log.record("video", now=1.0)
        with self.assertRaises(ValueError):
            log.record(FAULT, now=float("nan"))


if __name__ == "__main__":
    unittest.main()
