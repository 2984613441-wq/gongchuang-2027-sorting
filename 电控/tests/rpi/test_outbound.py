from __future__ import annotations

import unittest
from typing import Protocol

from electrical_control.protocol import (
    Command,
    Device,
    OuterFrame,
    VERSION,
    PayloadError,
    decode_item_task_payload,
    decode_outer_frame,
    encode_item_task_payload,
    encode_outer_frame,
)
from electrical_control.rpi import (
    DisplayAckIntent,
    FakeRenderer,
    FakeTaskSource,
    ItemTaskContext,
    ItemTaskPayload,
    Scheduler,
    SchedulerState,
    VerifiedNewRound,
)
from electrical_control.rpi.gateway import PiProtocolGateway
from electrical_control.rpi.outbound import OutboundConfig, OutboundGateway
from electrical_control.rpi.serial_link import FakeSerialLink, SerialLink


ROUND_TASK_ID = 7


def task_context(
    *,
    task_id: int = ROUND_TASK_ID,
    frame_seq: int = 11,
    target_seq: int = 1,
    image_id: int = 3,
) -> ItemTaskContext:
    return ItemTaskContext(
        "round-new",
        task_id,
        frame_seq,
        # grip_angle must be 0xFF on the wire: the claw does not rotate.
        ItemTaskPayload(target_seq, 2, image_id, 0, 0, 0xFF),
    )


def new_gateway(
    *, round_task_id: int = ROUND_TASK_ID,
) -> tuple[FakeSerialLink, OutboundGateway]:
    link = FakeSerialLink()
    gateway = OutboundGateway(link, config=OutboundConfig(round_task_id))
    return link, gateway


def stm32_frame(
    command: Command,
    *,
    frame_seq: int,
    task_id: int = ROUND_TASK_ID,
    payload: bytes = b"",
) -> bytes:
    return encode_outer_frame(
        OuterFrame(
            VERSION, Device.STM32, Device.RASPI, task_id, frame_seq, int(command), payload
        )
    )


def unlocked_scheduler_with_item() -> Scheduler:
    scheduler = Scheduler()
    scheduler.start_verified_new_round(VerifiedNewRound("round-new", True, True, True))
    scheduler.load_source(FakeTaskSource([task_context()]))
    scheduler.next_task()
    return scheduler


def rendered_intent(scheduler: Scheduler) -> DisplayAckIntent:
    inbound = PiProtocolGateway(scheduler)
    inbound.feed_frame(stm32_frame(Command.MOTION_DONE, frame_seq=10))
    inbound.feed_frame(
        stm32_frame(
            Command.ITEM_RESULT,
            frame_seq=11,
            payload=bytes((1, 0x00, 0x00)),
        )
    )
    receipt = FakeRenderer(scheduler.current_task).present(scheduler.display_model).complete()
    return scheduler.accept_render_receipt(receipt)


class SerialLinkTests(unittest.TestCase):
    def test_serial_link_is_a_structural_protocol(self) -> None:
        self.assertTrue(issubclass(SerialLink, Protocol))
        self.assertTrue(callable(SerialLink.send))
        self.assertTrue(callable(SerialLink.receive))

    def test_fake_serial_link_records_outbound_frames_in_order(self) -> None:
        link = FakeSerialLink()

        self.assertEqual((), link.sent)
        link.send(b"first")
        link.send(b"second")

        self.assertEqual((b"first", b"second"), link.sent)
        self.assertIsInstance(link.sent, tuple)

    def test_fake_serial_link_receive_is_fifo_and_empty_returns_none(self) -> None:
        link = FakeSerialLink()

        self.assertIsNone(link.receive())
        link.queue_inbound(b"a")
        link.queue_inbound(b"b")

        self.assertEqual(b"a", link.receive())
        self.assertEqual(b"b", link.receive())
        self.assertIsNone(link.receive())


class OutboundConfigTests(unittest.TestCase):
    def test_config_requires_u16_round_task_id(self) -> None:
        self.assertEqual(ROUND_TASK_ID, OutboundConfig(ROUND_TASK_ID).round_task_id)
        for bad in (0x10000, -1, "7", True):
            with self.subTest(round_task_id=bad):
                with self.assertRaises(PayloadError):
                    OutboundConfig(bad)  # type: ignore[arg-type]

    def test_config_is_frozen(self) -> None:
        config = OutboundConfig(ROUND_TASK_ID)
        with self.assertRaises(AttributeError):
            config.round_task_id = 8  # type: ignore[misc]


class SendItemTaskTests(unittest.TestCase):
    def test_send_item_task_encodes_valid_outer_frame_and_sends_it(self) -> None:
        link, gateway = new_gateway()
        task = task_context()

        frame = gateway.send_item_task(task)
        decoded = decode_outer_frame(frame)

        self.assertEqual(frame, link.sent[0])
        self.assertEqual(1, len(link.sent))
        self.assertEqual(Device.RASPI, decoded.sender)
        self.assertEqual(Device.STM32, decoded.receiver)
        self.assertEqual(Command.ITEM_TASK, Command(decoded.command))
        self.assertEqual(task.task_id, decoded.task_id)
        self.assertEqual(1, decoded.frame_seq)
        expected_payload = encode_item_task_payload(task.payload)
        self.assertEqual(expected_payload, decoded.payload)
        self.assertEqual(8, len(decoded.payload))
        # The frozen 8-byte payload round-trips to the same logical fields.
        self.assertEqual(task.payload, decode_item_task_payload(decoded.payload))

    def test_send_item_task_increments_tx_seq_from_one_per_frame(self) -> None:
        link, gateway = new_gateway()

        self.assertEqual(0, gateway.tx_seq)
        first = gateway.send_item_task(task_context(frame_seq=11))
        second = gateway.send_item_task(task_context(frame_seq=12))

        self.assertEqual(1, decode_outer_frame(first).frame_seq)
        self.assertEqual(2, decode_outer_frame(second).frame_seq)
        self.assertEqual(2, gateway.tx_seq)
        self.assertEqual(2, len(link.sent))

    def test_send_item_task_rejects_task_id_mismatching_round(self) -> None:
        link, gateway = new_gateway(round_task_id=ROUND_TASK_ID)

        with self.assertRaises(PayloadError):
            gateway.send_item_task(task_context(task_id=ROUND_TASK_ID + 1))

        self.assertEqual((), link.sent)
        self.assertEqual(0, gateway.tx_seq)

    def test_send_item_task_rejects_non_int_and_out_of_range_task_id(self) -> None:
        link, gateway = new_gateway()

        for bad in ("7", 0x10000, -1, True):
            with self.subTest(task_id=bad):
                with self.assertRaises(PayloadError):
                    gateway.send_item_task(task_context(task_id=bad))  # type: ignore[arg-type]

        self.assertEqual((), link.sent)
        self.assertEqual(0, gateway.tx_seq)

    def test_send_item_task_rejects_invalid_payload_fail_closed(self) -> None:
        link, gateway = new_gateway()
        task = ItemTaskContext(
            "round-new",
            ROUND_TASK_ID,
            11,
            ItemTaskPayload(1, 2, 3, 0, 0, 0x05),  # grip_angle != 0xFF
        )

        with self.assertRaises(PayloadError):
            gateway.send_item_task(task)

        self.assertEqual((), link.sent)
        self.assertEqual(0, gateway.tx_seq)


class ResendItemTaskTests(unittest.TestCase):
    def test_resend_replays_exact_last_frame_without_incrementing_tx_seq(self) -> None:
        link, gateway = new_gateway()
        task = task_context(frame_seq=11)

        first = gateway.send_item_task(task)
        self.assertEqual(1, gateway.tx_seq)
        replayed = gateway.resend_item_task(task)

        # Byte-for-byte replay of the first send; the same (task_id, frame_seq)
        # hits the STM32 dedup -> RESEND path instead of being a fresh task.
        self.assertEqual(first, replayed)
        self.assertEqual((first, first), link.sent)
        self.assertEqual(1, decode_outer_frame(replayed).frame_seq)
        self.assertEqual(1, gateway.tx_seq)

    def test_resend_reuses_the_wire_seq_of_the_latest_send(self) -> None:
        link, gateway = new_gateway()
        first = gateway.send_item_task(task_context(frame_seq=11))
        second = gateway.send_item_task(task_context(frame_seq=12))

        replayed = gateway.resend_item_task(task_context(frame_seq=12))

        self.assertEqual(second, replayed)
        self.assertEqual(2, decode_outer_frame(replayed).frame_seq)
        self.assertEqual((first, second, second), link.sent)
        self.assertEqual(2, gateway.tx_seq)

    def test_resend_before_any_send_raises(self) -> None:
        link, gateway = new_gateway()

        with self.assertRaisesRegex(ValueError, "no cached ITEM_TASK frame"):
            gateway.resend_item_task(task_context())

        self.assertEqual((), link.sent)
        self.assertEqual(0, gateway.tx_seq)

    def test_resend_rejects_task_id_mismatch(self) -> None:
        link, gateway = new_gateway()
        gateway.send_item_task(task_context(frame_seq=11))

        with self.assertRaises(ValueError):
            gateway.resend_item_task(task_context(task_id=ROUND_TASK_ID + 1, frame_seq=11))

        self.assertEqual(1, len(link.sent))
        self.assertEqual(1, gateway.tx_seq)

    def test_resend_rejects_frame_seq_mismatch(self) -> None:
        link, gateway = new_gateway()
        gateway.send_item_task(task_context(frame_seq=11))

        with self.assertRaises(ValueError):
            gateway.resend_item_task(task_context(frame_seq=12))

        self.assertEqual(1, len(link.sent))
        self.assertEqual(1, gateway.tx_seq)

    def test_resend_cache_tracks_the_latest_send(self) -> None:
        link, gateway = new_gateway()
        first = gateway.send_item_task(task_context(frame_seq=11))
        second = gateway.send_item_task(task_context(frame_seq=12))

        # The cache holds only the most recent ITEM_TASK; an older task cannot
        # be replayed and must not silently send stale bytes.
        with self.assertRaises(ValueError):
            gateway.resend_item_task(task_context(frame_seq=11))

        self.assertEqual(second, gateway.resend_item_task(task_context(frame_seq=12)))
        self.assertEqual((first, second, second), link.sent)
        self.assertEqual(2, gateway.tx_seq)

    def test_resend_invokes_on_retransmit_hook(self) -> None:
        link = FakeSerialLink()
        calls: list[int] = []
        gateway = OutboundGateway(
            link,
            config=OutboundConfig(ROUND_TASK_ID),
            on_retransmit=lambda: calls.append(1),
        )
        task = task_context(frame_seq=11)

        gateway.send_item_task(task)
        gateway.resend_item_task(task)
        gateway.resend_item_task(task)

        self.assertEqual([1, 1], calls)
        self.assertEqual(3, len(link.sent))
        self.assertEqual(1, gateway.tx_seq)

    def test_resend_without_hook_is_backward_compatible(self) -> None:
        # The default constructor takes no on_retransmit and must not call it.
        link, gateway = new_gateway()
        task = task_context(frame_seq=11)

        gateway.send_item_task(task)
        replayed = gateway.resend_item_task(task)

        self.assertEqual((replayed, replayed), link.sent)


class SendDisplayAckTests(unittest.TestCase):
    def test_send_display_ack_encodes_intent_fields_and_sends(self) -> None:
        scheduler = unlocked_scheduler_with_item()
        intent = rendered_intent(scheduler)
        link, gateway = new_gateway()

        frame = gateway.send_display_ack(intent)
        decoded = decode_outer_frame(frame)

        self.assertEqual(frame, link.sent[0])
        self.assertEqual(1, len(link.sent))
        self.assertEqual(Device.RASPI, decoded.sender)
        self.assertEqual(Device.STM32, decoded.receiver)
        self.assertEqual(Command.DISPLAY_ACK, Command(decoded.command))
        self.assertEqual(intent.task.task_id, decoded.task_id)
        self.assertEqual(1, decoded.frame_seq)
        expected_payload = bytes((intent.target_seq, 0x00)) + intent.content_crc32_bytes
        self.assertEqual(expected_payload, decoded.payload)
        self.assertEqual(6, len(decoded.payload))

    def test_send_display_ack_rejects_non_rendered_intent(self) -> None:
        link, gateway = new_gateway()
        intent = DisplayAckIntent(
            task_context(), target_seq=1, render_result="FAILED", content_crc32=0
        )

        with self.assertRaises(ValueError):
            gateway.send_display_ack(intent)

        self.assertEqual((), link.sent)
        self.assertEqual(0, gateway.tx_seq)

    def test_tx_seq_is_independent_of_pi_gateway_inbound_counter(self) -> None:
        # The inbound Pi gateway owns its own reply counter.
        pi_gateway = PiProtocolGateway(unlocked_scheduler_with_item())
        intent = DisplayAckIntent(
            task_context(), target_seq=1, render_result="RENDERED", content_crc32=0
        )
        pi_gateway.emit_display_ack(intent)
        self.assertEqual(1, pi_gateway.tx_seq)

        # A fresh outbound gateway still starts its own counter at frame_seq 1.
        link, outbound = new_gateway()
        frame = outbound.send_item_task(task_context())

        self.assertEqual(1, decode_outer_frame(frame).frame_seq)
        self.assertEqual(1, outbound.tx_seq)
        self.assertEqual(1, len(link.sent))


class ClosedLoopTests(unittest.TestCase):
    def test_two_items_emit_item_task_display_ack_item_task_display_ack(self) -> None:
        scheduler = Scheduler()
        scheduler.start_verified_new_round(VerifiedNewRound("round-new", True, True, True))
        scheduler.load_source(
            FakeTaskSource(
                [
                    task_context(frame_seq=11, target_seq=1),
                    task_context(frame_seq=12, target_seq=2),
                ]
            )
        )
        inbound = PiProtocolGateway(scheduler)
        link, outbound = new_gateway()

        for stm32_seq, target_seq in ((10, 1), (13, 2)):
            active = scheduler.next_task()
            self.assertIsNotNone(active)
            self.assertEqual(target_seq, active.payload.target_seq)
            task_frame = outbound.send_item_task(active)
            self.assertEqual(Command.ITEM_TASK, Command(decode_outer_frame(task_frame).command))

            self.assertEqual(
                "MOTION_DONE",
                inbound.feed_frame(
                    stm32_frame(Command.MOTION_DONE, frame_seq=stm32_seq)
                ).event,
            )
            self.assertEqual(
                "ITEM_RESULT",
                inbound.feed_frame(
                    stm32_frame(
                        Command.ITEM_RESULT,
                        frame_seq=stm32_seq + 1,
                        payload=bytes((target_seq, 0x00, 0x00)),
                    )
                ).event,
            )
            receipt = FakeRenderer(scheduler.current_task).present(scheduler.display_model).complete()
            intent = scheduler.accept_render_receipt(receipt)
            outbound.send_display_ack(intent)

        commands = [Command(decode_outer_frame(frame).command) for frame in link.sent]
        self.assertEqual(
            [
                Command.ITEM_TASK,
                Command.DISPLAY_ACK,
                Command.ITEM_TASK,
                Command.DISPLAY_ACK,
            ],
            commands,
        )
        self.assertEqual(4, len(link.sent))
        self.assertEqual(4, outbound.tx_seq)
        self.assertEqual(2, scheduler.success_count)
        self.assertEqual(SchedulerState.READY, scheduler.state)
        self.assertIsNone(scheduler.next_task())


if __name__ == "__main__":
    unittest.main()
