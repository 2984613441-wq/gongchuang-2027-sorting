from __future__ import annotations

import unittest

from electrical_control.protocol import ItemTaskPayload
from electrical_control.rpi import FakeTaskSource, Scheduler, SchedulerState, VerifiedNewRound


def task(target_seq: int) -> ItemTaskPayload:
    return ItemTaskPayload(target_seq, 2, target_seq + 10, 0, 0, 0, None, None)


class FakeSourceAndRecoveryTests(unittest.TestCase):
    def test_RPI_FAKE_001_source_is_deterministic_and_gate_controlled(self) -> None:
        source = FakeTaskSource([task(1), task(2)])

        self.assertIsNone(source.next_if_permitted())
        source.set_permitted(True)
        self.assertEqual(1, source.next_if_permitted().target_seq)
        self.assertEqual(2, source.next_if_permitted().target_seq)
        self.assertIsNone(source.next_if_permitted())

    def test_RPI_RESTART_001_process_starts_locked_and_old_snapshot_is_diagnostic_only(self) -> None:
        scheduler = Scheduler(diagnostic_snapshot={"round_id": "old", "success_count": 99})
        scheduler.load_source(FakeTaskSource([task(1)]))

        self.assertEqual(SchedulerState.RECOVERY_LOCK, scheduler.state)
        self.assertEqual(0, scheduler.success_count)
        self.assertIsNone(scheduler.next_task())
        self.assertEqual({"round_id": "old", "success_count": 99}, scheduler.diagnostic_snapshot)

    def test_RPI_NEWROUND_001_requires_all_new_round_authorities_and_resets_to_zero(self) -> None:
        scheduler = Scheduler()

        with self.assertRaises(PermissionError):
            scheduler.start_verified_new_round(
                VerifiedNewRound("new", human_confirmed=True, stm32_safe=False, both_nodes_initialized=True)
            )
        scheduler.start_verified_new_round(
            VerifiedNewRound("new", human_confirmed=True, stm32_safe=True, both_nodes_initialized=True)
        )

        self.assertEqual(SchedulerState.READY, scheduler.state)
        self.assertEqual(0, scheduler.success_count)


if __name__ == "__main__":
    unittest.main()
