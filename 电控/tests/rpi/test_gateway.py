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
from electrical_control.rpi.log import STAGE, CentralLog


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

    def test_estop_blocks_new_tasks_until_verified_new_round(self) -> None:
        scheduler = Scheduler()
        scheduler.start_verified_new_round(VerifiedNewRound("round-new", True, True, True))
        scheduler.load_source(FakeTaskSource([context()]))
        gateway = PiProtocolGateway(scheduler)

        gateway.feed_frame(stm32_frame(Command.ESTOP))

        self.assertTrue(scheduler.estop_active)
        self.assertIsNone(scheduler.next_task())

        scheduler.start_verified_new_round(VerifiedNewRound("round-new", True, True, True))
        self.assertFalse(scheduler.estop_active)
        self.assertIsNotNone(scheduler.next_task())

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


class AckNackTests(unittest.TestCase):
    def test_ack_accepted_is_parsed(self) -> None:
        gateway = PiProtocolGateway(unlocked_scheduler())

        outcome = gateway.feed_frame(
            stm32_frame(Command.ACK, payload=bytes((0x00, 0x03)))
        )

        self.assertEqual("ACK_ACCEPTED", outcome.event)
        self.assertIsNone(outcome.outbound)
        self.assertIsNone(outcome.fault)

    def test_ack_consumed_is_parsed(self) -> None:
        gateway = PiProtocolGateway(unlocked_scheduler())

        outcome = gateway.feed_frame(
            stm32_frame(Command.ACK, payload=bytes((0x01, 0x01)))
        )

        self.assertEqual("ACK_ACK_CONSUMED", outcome.event)

    def test_every_nack_reason_is_named(self) -> None:
        cases = (
            (0x10, "NACK_STALE_OR_ORDER"),
            (0x11, "NACK_UNEXPECTED_MESSAGE"),
            (0x12, "NACK_SINGLE_TASK_ONLY"),
            (0x13, "NACK_ACK_NOT_APPLICABLE"),
            (0x14, "NACK_WRONG_ROUND"),
            (0x15, "NACK_TASK_REJECTED"),
        )
        for reason_code, expected in cases:
            with self.subTest(reason_code=reason_code):
                gateway = PiProtocolGateway(unlocked_scheduler())
                outcome = gateway.feed_frame(
                    stm32_frame(Command.NACK, payload=bytes((reason_code, 0x07)))
                )
                self.assertEqual(expected, outcome.event)

    def test_unknown_reason_code_stays_observable(self) -> None:
        gateway = PiProtocolGateway(unlocked_scheduler())

        ack = gateway.feed_frame(stm32_frame(Command.ACK, payload=bytes((0x99, 0x00))))
        nack = gateway.feed_frame(
            stm32_frame(Command.NACK, payload=bytes((0x20, 0x00)), frame_seq=12)
        )

        self.assertEqual("ACK_UNKNOWN(0x99)", ack.event)
        self.assertEqual("NACK_UNKNOWN(0x20)", nack.event)

    def test_malformed_ack_nack_payload_is_rejected(self) -> None:
        gateway = PiProtocolGateway(unlocked_scheduler())

        for index, payload in enumerate((b"", b"\x00", b"\x00\x01\x02")):
            with self.subTest(payload=payload):
                outcome = gateway.feed_frame(
                    # Distinct wire identity per case: the inbound dedup cache
                    # is keyed by (task_id, frame_seq) and would otherwise
                    # answer DUPLICATE for the later malformed frames.
                    stm32_frame(Command.ACK, payload=payload, frame_seq=12 + index)
                )
                self.assertEqual("FRAME_REJECTED", outcome.event)
                self.assertIsNotNone(outcome.fault)

    def test_ack_nack_does_not_disturb_the_scheduler(self) -> None:
        scheduler = unlocked_scheduler()
        gateway = PiProtocolGateway(scheduler)

        gateway.feed_frame(stm32_frame(Command.NACK, payload=bytes((0x12, 0x07))))
        gateway.feed_frame(stm32_frame(Command.ACK, payload=bytes((0x00, 0x03)), frame_seq=12))

        self.assertEqual(SchedulerState.WAIT_MOTION_DONE, scheduler.state)
        self.assertFalse(scheduler.is_faulted)

    def test_duplicate_ack_is_deduped_like_other_frames(self) -> None:
        gateway = PiProtocolGateway(unlocked_scheduler())
        frame = stm32_frame(Command.ACK, payload=bytes((0x00, 0x03)))

        self.assertEqual("ACK_ACCEPTED", gateway.feed_frame(frame).event)
        self.assertEqual("DUPLICATE", gateway.feed_frame(frame).event)

    def test_ack_logs_stage_entry_when_logger_provided(self) -> None:
        log = CentralLog(64)
        scheduler = unlocked_scheduler()
        gateway = PiProtocolGateway(scheduler, logger=log)

        gateway.feed_frame(
            stm32_frame(Command.ACK, task_id=7, frame_seq=42, payload=bytes((0x00, 0x03)))
        )

        entry = log.last
        self.assertIsNotNone(entry)
        self.assertEqual(STAGE, entry.kind)
        self.assertEqual(7, entry.task_id)
        self.assertEqual(42, entry.frame_seq)
        self.assertEqual(3, entry.target_seq)
        self.assertEqual("ACK:ACCEPTED seq=3", entry.detail)
        self.assertIsInstance(entry.now, float)

    def test_nack_logs_stage_entry_when_logger_provided(self) -> None:
        log = CentralLog(64)
        gateway = PiProtocolGateway(unlocked_scheduler(), logger=log)

        gateway.feed_frame(
            stm32_frame(Command.NACK, frame_seq=9, payload=bytes((0x12, 0x07)))
        )

        entry = log.last
        self.assertIsNotNone(entry)
        self.assertEqual(STAGE, entry.kind)
        self.assertEqual(9, entry.frame_seq)
        self.assertEqual(7, entry.target_seq)
        self.assertEqual("NACK:SINGLE_TASK_ONLY seq=7", entry.detail)

    def test_no_log_entry_without_logger(self) -> None:
        # Default construction (no logger) must not log and must still parse.
        gateway = PiProtocolGateway(unlocked_scheduler())

        outcome = gateway.feed_frame(
            stm32_frame(Command.NACK, payload=bytes((0x15, 0x00)))
        )

        self.assertEqual("NACK_TASK_REJECTED", outcome.event)


if __name__ == "__main__":
    unittest.main()
