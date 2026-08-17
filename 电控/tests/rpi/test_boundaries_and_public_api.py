from __future__ import annotations

import unittest

import electrical_control.rpi as rpi
from electrical_control.protocol import ItemTaskPayload


def ctx(frame_seq: int, target_seq: int = 1, *, image_id: int = 3) -> rpi.ItemTaskContext:
    return rpi.ItemTaskContext(
        "round-new", 7, frame_seq, ItemTaskPayload(target_seq, 2, image_id, 0, 0, 0)
    )


def unlock(scheduler: rpi.Scheduler) -> None:
    scheduler.start_verified_new_round(rpi.VerifiedNewRound("round-new", True, True, True))


class CountBoundaryTests(unittest.TestCase):
    def test_RPI_COUNT_BOUNDARY_001_254_to_255_is_legal_and_does_not_wrap(self) -> None:
        scheduler = rpi.Scheduler()
        unlock(scheduler)
        tasks = [ctx(frame_seq, target_seq=((frame_seq - 1) % 255) + 1) for frame_seq in range(1, 256)]
        scheduler.load_source(rpi.FakeTaskSource(tasks))
        for frame_seq in range(1, 255):
            active = scheduler.next_task()
            model = scheduler.accept_item_result(
                rpi.ItemResult("round-new", 7, frame_seq, active.payload.target_seq, 0)
            )
            scheduler.accept_render_receipt(
                rpi.FakeRenderer(scheduler.current_task).present(model).complete()
            )

        active = scheduler.next_task()
        model = scheduler.accept_item_result(
            rpi.ItemResult("round-new", 7, 255, active.payload.target_seq, 0)
        )

        self.assertEqual(255, scheduler.success_count)
        self.assertEqual(255, model.success_count)

    def test_RPI_COUNT_OVERFLOW_001_255_refuses_new_item_and_locks(self) -> None:
        scheduler = rpi.Scheduler()
        unlock(scheduler)
        tasks = [ctx(frame_seq, target_seq=((frame_seq - 1) % 255) + 1) for frame_seq in range(1, 257)]
        scheduler.load_source(rpi.FakeTaskSource(tasks))
        for frame_seq in range(1, 256):
            active = scheduler.next_task()
            model = scheduler.accept_item_result(
                rpi.ItemResult("round-new", 7, frame_seq, active.payload.target_seq, 0)
            )
            scheduler.accept_render_receipt(
                rpi.FakeRenderer(scheduler.current_task).present(model).complete()
            )

        with self.assertRaises(rpi.SchedulerFault):
            scheduler.next_task()

        self.assertEqual(255, scheduler.success_count)
        self.assertTrue(scheduler.is_faulted)


class IdentityAndRecoveryBoundaryTests(unittest.TestCase):
    def test_RPI_CONFLICT_001_same_identity_with_different_payload_faults_after_first_item(self) -> None:
        first = ctx(1, image_id=3)
        conflicting = ctx(1, image_id=4)
        scheduler = rpi.Scheduler()
        unlock(scheduler)
        scheduler.load_source(rpi.FakeTaskSource([first, conflicting]))
        scheduler.next_task()
        model = scheduler.accept_item_result(rpi.ItemResult("round-new", 7, 1, 1, 5))
        receipt = rpi.FakeRenderer(scheduler.current_task).present(model).complete()
        scheduler.accept_render_receipt(receipt)

        with self.assertRaises(rpi.SchedulerFault):
            scheduler.next_task()

    def test_RPI_NEWROUND_002_operational_events_cannot_unlock_recovery(self) -> None:
        scheduler = rpi.Scheduler()

        scheduler.note_reconnect()
        scheduler.note_retransmission()
        scheduler.note_display_retry()

        self.assertEqual(rpi.SchedulerState.RECOVERY_LOCK, scheduler.state)
        self.assertEqual(0, scheduler.success_count)

    def test_RPI_NONTOUCH_001_public_api_has_no_touch_click_reset_or_skip_entry(self) -> None:
        forbidden = ("touch", "click", "tap", "gesture", "skip", "screen_reset")
        public_names = set(rpi.__all__) | set(dir(rpi.Scheduler))

        self.assertFalse(any(token in name.lower() for name in public_names for token in forbidden))


if __name__ == "__main__":
    unittest.main()
