from __future__ import annotations

import unittest

from electrical_control.protocol import DisplayContent, ItemTaskPayload
from electrical_control.rpi import (
    FakeRenderer,
    FakeTaskSource,
    ItemResult,
    ItemTaskContext,
    RenderReceipt,
    Scheduler,
    SchedulerFault,
    VerifiedNewRound,
)


def context(target_seq: int, *, round_id: str = "round-new") -> ItemTaskContext:
    return ItemTaskContext(
        round_id=round_id,
        task_id=7,
        frame_seq=target_seq,
        payload=ItemTaskPayload(target_seq, 2, target_seq + 10, 0, 0, 0),
    )


def unlocked_scheduler(*tasks: ItemTaskContext) -> Scheduler:
    scheduler = Scheduler()
    scheduler.start_verified_new_round(VerifiedNewRound("round-new", True, True, True))
    scheduler.load_source(FakeTaskSource(tasks))
    return scheduler


def accept_motion_done_for(scheduler: Scheduler, task: ItemTaskContext) -> None:
    """Pass the safety gate MOTION_DONE -> WAIT_ITEM_RESULT for the active task."""
    scheduler.accept_motion_done(
        round_id=task.round_id, task_id=task.task_id, frame_seq=task.frame_seq
    )


class SchedulerGateTests(unittest.TestCase):
    def test_RPI_GATE_001_next_item_waits_for_render_receipt(self) -> None:
        scheduler = unlocked_scheduler(context(1), context(2))
        first = scheduler.next_task()

        self.assertEqual(1, first.payload.target_seq)
        self.assertIsNone(scheduler.next_task())
        accept_motion_done_for(scheduler, first)
        scheduler.accept_item_result(ItemResult("round-new", 7, 1, 1, 0))
        self.assertIsNone(scheduler.next_task())

    def test_RPI_EVENT_001_motion_done_does_not_count_display_or_advance(self) -> None:
        scheduler = unlocked_scheduler(context(1), context(2))
        scheduler.next_task()

        self.assertIsNone(scheduler.accept_motion_done(round_id="round-new", task_id=7, frame_seq=1))
        self.assertEqual(0, scheduler.success_count)
        self.assertIsNone(scheduler.display_model)
        self.assertIsNone(scheduler.next_task())

    def test_RPI_RESULT_001_success_builds_exact_five_field_model_and_counts_once(self) -> None:
        scheduler = unlocked_scheduler(context(1))
        active = scheduler.next_task()
        accept_motion_done_for(scheduler, active)

        model = scheduler.accept_item_result(ItemResult("round-new", 7, 1, 1, 0))
        duplicate = scheduler.accept_item_result(ItemResult("round-new", 7, 1, 1, 0))

        self.assertEqual(bytes((1, 2, 11, 1, 0)), model.canonical_bytes())
        self.assertIs(model, duplicate)
        self.assertEqual(1, scheduler.success_count)

    def test_RPI_COUNT_FAIL_001_failure_is_displayed_without_increment(self) -> None:
        scheduler = unlocked_scheduler(context(1))
        active = scheduler.next_task()
        accept_motion_done_for(scheduler, active)

        model = scheduler.accept_item_result(ItemResult("round-new", 7, 1, 1, 5))

        self.assertEqual(bytes((1, 2, 11, 0, 5)), model.canonical_bytes())
        self.assertEqual(0, scheduler.success_count)

    def test_RPI_RESULT_002_stale_or_wrong_item_result_preserves_active_item(self) -> None:
        scheduler = unlocked_scheduler(context(1), context(2))
        active = scheduler.next_task()
        accept_motion_done_for(scheduler, active)

        with self.assertRaises(SchedulerFault):
            scheduler.accept_item_result(ItemResult("old-round", 7, 1, 1, 0))
        with self.assertRaises(SchedulerFault):
            scheduler.accept_item_result(ItemResult("round-new", 7, 2, 2, 0))

        self.assertIs(active, scheduler.current_task)
        self.assertEqual(0, scheduler.success_count)

    def test_RPI_CONFLICT_001_conflicting_duplicate_result_locks_scheduler(self) -> None:
        scheduler = unlocked_scheduler(context(1))
        active = scheduler.next_task()
        accept_motion_done_for(scheduler, active)
        scheduler.accept_item_result(ItemResult("round-new", 7, 1, 1, 5))

        with self.assertRaises(SchedulerFault):
            scheduler.accept_item_result(ItemResult("round-new", 7, 1, 1, 0))

        self.assertTrue(scheduler.is_faulted)


class RenderingReceiptTests(unittest.TestCase):
    def test_RPI_RENDER_FORGE_001_matching_fields_without_pending_completion_are_rejected(self) -> None:
        scheduler = unlocked_scheduler(context(1), context(2))
        active = scheduler.next_task()
        accept_motion_done_for(scheduler, active)
        model = scheduler.accept_item_result(ItemResult("round-new", 7, 1, 1, 0))
        FakeRenderer(scheduler.current_task).present(model)
        forged = RenderReceipt("round-new", 7, 1, model.crc32)

        with self.assertRaises(SchedulerFault):
            scheduler.accept_render_receipt(forged)

        self.assertIsNone(scheduler.display_ack_intent)
        self.assertIsNone(scheduler.next_task())

    def test_RPI_RENDER_RED_001_starting_render_cannot_create_ack(self) -> None:
        scheduler = unlocked_scheduler(context(1))
        active = scheduler.next_task()
        accept_motion_done_for(scheduler, active)
        model = scheduler.accept_item_result(ItemResult("round-new", 7, 1, 1, 0))
        pending = FakeRenderer(scheduler.current_task).present(model)

        self.assertIsNone(pending.receipt)
        self.assertIsNone(scheduler.display_ack_intent)
        self.assertIsNone(scheduler.next_task())

    def test_RPI_RENDER_001_only_explicit_completed_receipt_creates_ack_and_releases_gate(self) -> None:
        scheduler = unlocked_scheduler(context(1), context(2))
        active = scheduler.next_task()
        accept_motion_done_for(scheduler, active)
        model = scheduler.accept_item_result(ItemResult("round-new", 7, 1, 1, 0))
        pending = FakeRenderer(scheduler.current_task).present(model)

        receipt = pending.complete()
        intent = scheduler.accept_render_receipt(receipt)

        self.assertEqual("RENDERED", intent.render_result)
        self.assertEqual(model.crc32, intent.content_crc32)
        self.assertEqual(2, scheduler.next_task().payload.target_seq)

    def test_RPI_ACK_CRC_001_known_vector_uses_network_order_integer(self) -> None:
        scheduler = unlocked_scheduler(
            ItemTaskContext("round-new", 7, 1, ItemTaskPayload(1, 2, 3, 0, 0, 0))
        )
        active = scheduler.next_task()
        accept_motion_done_for(scheduler, active)
        model = scheduler.accept_item_result(ItemResult("round-new", 7, 1, 1, 5))
        receipt = FakeRenderer(scheduler.current_task).present(model).complete()

        intent = scheduler.accept_render_receipt(receipt)

        self.assertEqual(bytes.fromhex("01 02 03 00 05"), model.canonical_bytes())
        self.assertEqual(model.crc32, intent.content_crc32)
        self.assertEqual(model.crc32.to_bytes(4, "big"), intent.content_crc32_bytes)
        self.assertEqual(0x470B99F4, DisplayContent(1, 2, 3, 4, 5).crc32)

    def test_RPI_RENDER_STALE_001_wrong_receipt_is_rejected_without_release(self) -> None:
        scheduler = unlocked_scheduler(context(1), context(2))
        active = scheduler.next_task()
        accept_motion_done_for(scheduler, active)
        scheduler.accept_item_result(ItemResult("round-new", 7, 1, 1, 0))

        with self.assertRaises(SchedulerFault):
            scheduler.accept_render_receipt(RenderReceipt("round-new", 7, 1, 999))

        self.assertIsNone(scheduler.next_task())

    def test_RPI_RENDER_FAIL_001_failure_or_cancel_has_no_receipt_or_ack(self) -> None:
        for outcome in ("failed", "cancelled"):
            with self.subTest(outcome=outcome):
                scheduler = unlocked_scheduler(context(1), context(2))
                active = scheduler.next_task()
                accept_motion_done_for(scheduler, active)
                model = scheduler.accept_item_result(ItemResult("round-new", 7, 1, 1, 0))
                pending = FakeRenderer(scheduler.current_task).present(model)

                getattr(pending, outcome)()

                self.assertIsNone(pending.receipt)
                self.assertIsNone(scheduler.display_ack_intent)
                self.assertIsNone(scheduler.next_task())

    def test_RPI_ACK_DUP_001_duplicate_receipt_reuses_one_cached_intent(self) -> None:
        scheduler = unlocked_scheduler(context(1))
        active = scheduler.next_task()
        accept_motion_done_for(scheduler, active)
        model = scheduler.accept_item_result(ItemResult("round-new", 7, 1, 1, 0))
        receipt = FakeRenderer(scheduler.current_task).present(model).complete()

        first = scheduler.accept_render_receipt(receipt)
        second = scheduler.accept_render_receipt(receipt)

        self.assertIs(first, second)
        self.assertEqual(1, scheduler.success_count)


if __name__ == "__main__":
    unittest.main()
