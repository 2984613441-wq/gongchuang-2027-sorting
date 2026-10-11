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


def task_context(frame_seq: int, target_seq: int) -> ItemTaskContext:
    return ItemTaskContext(
        "round-new",
        7,
        frame_seq,
        ItemTaskPayload(target_seq, 2, target_seq + 10, 0, 0, 0, None, None),
    )


def stm32_frame(
    command: Command,
    *,
    frame_seq: int,
    payload: bytes = b"",
) -> bytes:
    return encode_outer_frame(
        OuterFrame(VERSION, Device.STM32, Device.RASPI, 7, frame_seq, int(command), payload)
    )


class OfflineMainChainTests(unittest.TestCase):
    def test_two_items_complete_with_display_ack_between_items(self) -> None:
        scheduler = Scheduler()
        scheduler.start_verified_new_round(VerifiedNewRound("round-new", True, True, True))
        scheduler.load_source(
            FakeTaskSource([task_context(11, 1), task_context(12, 2)])
        )
        gateway = PiProtocolGateway(scheduler)

        for stm32_seq, target_seq in ((1, 1), (4, 2)):
            self.assertEqual(
                "BARRIER_READY",
                gateway.feed_frame(stm32_frame(Command.BARRIER_READY, frame_seq=stm32_seq)).event,
            )
            active = scheduler.next_task()
            self.assertIsNotNone(active)
            self.assertEqual(target_seq, active.payload.target_seq)

            self.assertEqual(
                "MOTION_DONE",
                gateway.feed_frame(
                    stm32_frame(Command.MOTION_DONE, frame_seq=stm32_seq + 1)
                ).event,
            )
            result = gateway.feed_frame(
                stm32_frame(
                    Command.ITEM_RESULT,
                    frame_seq=stm32_seq + 2,
                    payload=bytes((target_seq, 0x00, 0x00)),
                )
            )
            self.assertEqual("ITEM_RESULT", result.event)
            self.assertEqual(SchedulerState.WAIT_RENDER, scheduler.state)

            receipt = FakeRenderer(scheduler.current_task).present(scheduler.display_model).complete()
            intent = scheduler.accept_render_receipt(receipt)
            outbound = gateway.emit_display_ack(intent)
            frame = decode_outer_frame(outbound)

            self.assertEqual(Command.DISPLAY_ACK, Command(frame.command))
            self.assertEqual(target_seq, frame.payload[0])
            self.assertEqual(0x00, frame.payload[1])
            self.assertEqual(intent.content_crc32_bytes, frame.payload[2:6])
            self.assertEqual(SchedulerState.READY, scheduler.state)

        self.assertEqual(2, scheduler.success_count)
        self.assertIsNone(scheduler.next_task())


if __name__ == "__main__":
    unittest.main()
