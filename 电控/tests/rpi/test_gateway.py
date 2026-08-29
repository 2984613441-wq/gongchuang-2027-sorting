from __future__ import annotations

import unittest

from electrical_control.protocol import (
    Command,
    Device,
    OuterFrame,
    VERSION,
    decode_outer_frame,
    encode_outer_frame,
)
from electrical_control.rpi import (
    FakeRenderer,
    FakeTaskSource,
    ItemTaskContext,
    ItemTaskPayload,
    Scheduler,
    SchedulerState,
    VerifiedNewRound,
)
from electrical_control.rpi.gateway import PiProtocolGateway


def context(frame_seq: int = 11, target_seq: int = 1) -> ItemTaskContext:
    return ItemTaskContext(
        "round-new",
        7,
        frame_seq,
        ItemTaskPayload(target_seq, 2, 3, 0, 0, 0),
    )


def unlocked_scheduler() -> Scheduler:
    scheduler = Scheduler()
    scheduler.start_verified_new_round(VerifiedNewRound("round-new", True, True, True))
    scheduler.load_source(FakeTaskSource([context()]))
    scheduler.next_task()
    return scheduler


def stm32_frame(
    command: Command,
    *,
    task_id: int = 7,
    frame_seq: int = 11,
    payload: bytes = b"",
) -> bytes:
    return encode_outer_frame(
        OuterFrame(
            VERSION,
            Device.STM32,
            Device.RASPI,
            task_id,
            frame_seq,
            int(command),
            payload,
        )
    )


class PiProtocolGatewayTests(unittest.TestCase):
    def test_barrier_ready_and_motion_done_are_dispatched(self) -> None:
        gateway = PiProtocolGateway(unlocked_scheduler())

        self.assertEqual("BARRIER_READY", gateway.feed_frame(stm32_frame(Command.BARRIER_READY)).event)
        self.assertEqual(
            "MOTION_DONE",
            gateway.feed_frame(stm32_frame(Command.MOTION_DONE, frame_seq=12)).event,
        )

    def test_item_result_builds_display_model_and_counts_once(self) -> None:
        scheduler = unlocked_scheduler()
        gateway = PiProtocolGateway(scheduler)
        frame = stm32_frame(Command.ITEM_RESULT, payload=bytes.fromhex("01 00 00"))

        # Pass the MOTION_DONE safety gate before the ITEM_RESULT frame. Use a
        # distinct wire frame_seq so it does not collide with the ITEM_RESULT
        # frame in the gateway inbound dedup cache.
        self.assertEqual(
            "MOTION_DONE",
            gateway.feed_frame(stm32_frame(Command.MOTION_DONE, frame_seq=10)).event,
        )
        outcome = gateway.feed_frame(frame)
        duplicate = gateway.feed_frame(frame)

        self.assertEqual("ITEM_RESULT", outcome.event)
        self.assertEqual("DUPLICATE", duplicate.event)
        self.assertEqual(SchedulerState.WAIT_RENDER, scheduler.state)
        self.assertEqual(1, scheduler.success_count)

    def test_item_result_out_of_context_is_ignored(self) -> None:
        scheduler = Scheduler()
        gateway = PiProtocolGateway(scheduler)

        outcome = gateway.feed_frame(
            stm32_frame(Command.ITEM_RESULT, payload=bytes.fromhex("01 00 00"))
        )

        self.assertEqual("ITEM_RESULT_IGNORED", outcome.event)
        self.assertFalse(scheduler.is_faulted)

    def test_render_receipt_emits_valid_display_ack_frame(self) -> None:
        scheduler = unlocked_scheduler()
        gateway = PiProtocolGateway(scheduler)
        gateway.feed_frame(stm32_frame(Command.MOTION_DONE, frame_seq=10))
        gateway.feed_frame(stm32_frame(Command.ITEM_RESULT, payload=bytes.fromhex("01 00 00")))

        receipt = FakeRenderer(scheduler.current_task).present(scheduler.display_model).complete()
        intent = scheduler.accept_render_receipt(receipt)
        outbound = gateway.emit_display_ack(intent)
        frame = decode_outer_frame(outbound)

        self.assertEqual(Device.RASPI, frame.sender)
        self.assertEqual(Device.STM32, frame.receiver)
        self.assertEqual(Command.DISPLAY_ACK, Command(frame.command))
        self.assertEqual(7, frame.task_id)
        self.assertEqual(bytes((1, 0)) + scheduler.display_ack_intent.content_crc32_bytes, frame.payload)

    def test_estop_is_recorded(self) -> None:
        gateway = PiProtocolGateway(unlocked_scheduler())

        outcome = gateway.feed_frame(stm32_frame(Command.ESTOP))

        self.assertEqual("ESTOP", outcome.event)
        self.assertTrue(gateway.estop_active)

    def test_reverse_direction_is_rejected(self) -> None:
        gateway = PiProtocolGateway(unlocked_scheduler())
        reverse = encode_outer_frame(
            OuterFrame(VERSION, Device.RASPI, Device.STM32, 7, 11, int(Command.MOTION_DONE), b"")
        )

        outcome = gateway.feed_frame(reverse)

        self.assertEqual("DIRECTION_REJECTED", outcome.event)
        self.assertIsNotNone(outcome.fault)

    def test_feed_byte_assembles_and_resyncs_after_noise(self) -> None:
        scheduler = unlocked_scheduler()
        gateway = PiProtocolGateway(scheduler)
        frame = stm32_frame(Command.ITEM_RESULT, payload=bytes.fromhex("01 00 00"))
        gateway.feed_frame(stm32_frame(Command.MOTION_DONE, frame_seq=10))

        outcome = None
        for byte in (0x00, *frame):
            outcome = gateway.feed_byte(byte)

        self.assertEqual("ITEM_RESULT", outcome.event)
        self.assertEqual(1, scheduler.success_count)

    def test_unexpected_scheduler_exception_becomes_crash_outcome(self) -> None:
        class ExplodingScheduler:
            current_task = object()

            def accept_motion_done(self, **identity: object) -> None:
                raise ValueError("unexpected internal fault")

        gateway = PiProtocolGateway(ExplodingScheduler())

        outcome = gateway.feed_frame(stm32_frame(Command.MOTION_DONE))

        self.assertEqual("CRASH", outcome.event)
        self.assertIsNotNone(outcome.fault)


if __name__ == "__main__":
    unittest.main()
