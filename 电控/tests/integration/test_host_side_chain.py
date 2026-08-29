"""Host-side closed-loop integration test: "显示完成后才能分拣下一件" (赛题 R-D04).

The chain under test is all-fake and host-only — no serial port, HDMI display,
camera, or actuator is touched (per project AGENTS.md: host results must never
be presented as firmware/serial/screen/motor/passed-on-hardware evidence).

    vision batch (BatchTargets/VisionTarget)
      -> build_item_task_queue(image_id_for_class, drop_point_for_box)
      -> Scheduler.start_verified_new_round + load_source(FakeTaskSource(items))
      -> scheduler.next_task() -> OutboundGateway.send_item_task()   # into FakeSerialLink
      -> simulated STM32 decodes the outer frame
      -> PiProtocolGateway.feed_frame(MOTION_DONE) / feed_frame(ITEM_RESULT)
      -> scheduler.accept_item_result(...) -> build_display_view(content, names)
      -> FakeDisplayRenderer(task).present(view).complete() -> accept_render_receipt()
      -> OutboundGateway.send_display_ack()
      -> next item

Assertion coverage per docs/design/2026-08-29-host-side-chain-interfaces.md §4:
  1. exactly one decodable ITEM_TASK per item (header/version/CRC + payload);
  2. MOTION_DONE gate: a premature ITEM_RESULT is rejected (FAULT), the ordered
     MOTION_DONE -> ITEM_RESULT flow then succeeds;
  3. next_task() returns None while a display is still pending (R-D04);
  4. the displayed success total equals the scheduler success counter;
  5. after two closed items FakeSerialLink.sent is exactly
     [ITEM_TASK, DISPLAY_ACK, ITEM_TASK, DISPLAY_ACK].

Dependency note: OutboundGateway (rpi/outbound.py), build_display_view /
FakeDisplayRenderer (rpi/display.py) and FakeSerialLink (rpi/serial_link.py)
are implemented in parallel; this suite is intentionally RED until they land.
The wire contract they implement is frozen and this file depends only on it.
"""

from __future__ import annotations

import unittest

from electrical_control.protocol import (
    Command,
    Device,
    OuterFrame,
    VERSION,
    decode_item_task_payload,
    decode_outer_frame,
    encode_outer_frame,
)
from electrical_control.rpi import (
    BatchTargets,
    FakeTaskSource,
    ItemTaskContext,
    Scheduler,
    SchedulerState,
    VerifiedNewRound,
    VisionTarget,
    build_item_task_queue,
)
from electrical_control.rpi.display import FakeDisplayRenderer, build_display_view
from electrical_control.rpi.gateway import PiProtocolGateway
from electrical_control.rpi.outbound import OutboundConfig, OutboundGateway
from electrical_control.rpi.serial_link import FakeSerialLink

ROUND_ID = "round-new"
ROUND_TASK_ID = 7

# class_id -> 货物名称（树莓派本地 TF 卡映射；只传类别 ID / 图片 ID，不传图片文件）
NAMES = {2: "红方柱", 4: "蓝圆柱"}
# class_id -> image_id
IMAGE_IDS = {2: 102, 4: 104}
# box_id -> (x, y) 落料点；注入后 ITEM_TASK payload 才可序列化（grip_angle=0xFF）
DROP_POINTS = {1: (100, 200), 2: (300, 400)}


def stm32_frame(
    command: Command,
    *,
    frame_seq: int,
    task_id: int = ROUND_TASK_ID,
    payload: bytes = b"",
) -> bytes:
    """Frame as emitted by the simulated STM32 (STM32 -> RASPI)."""
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


def item_result_frame(frame_seq: int, target_seq: int) -> bytes:
    """ITEM_RESULT with result_code 0x00 = SUCCESS, basis 0x00."""
    return stm32_frame(
        Command.ITEM_RESULT,
        frame_seq=frame_seq,
        payload=bytes((target_seq, 0x00, 0x00)),
    )


class HostSideChainTests(unittest.TestCase):
    def setUp(self) -> None:
        batch = BatchTargets(
            ROUND_TASK_ID,
            (
                VisionTarget(1, 2, box_id=1),  # 红方柱
                VisionTarget(2, 4, box_id=2),  # 蓝圆柱
            ),
        )
        queue = build_item_task_queue(
            batch,
            image_id_for_class=IMAGE_IDS.__getitem__,
            drop_point_for_box=DROP_POINTS.__getitem__,
        )
        self.contexts = tuple(
            ItemTaskContext(
                ROUND_ID, ROUND_TASK_ID, frame_seq=10 + index, payload=payload
            )
            for index, payload in enumerate(queue)
        )

        self.scheduler = Scheduler()
        self.scheduler.start_verified_new_round(
            VerifiedNewRound(ROUND_ID, True, True, True)
        )
        self.scheduler.load_source(FakeTaskSource(self.contexts))

        self.gateway = PiProtocolGateway(self.scheduler)
        self.link = FakeSerialLink()
        self.outbound = OutboundGateway(
            self.link, config=OutboundConfig(round_task_id=ROUND_TASK_ID)
        )

    # ------------------------------------------------------------- helpers ---

    def assert_item_task_frame(
        self,
        raw: bytes,
        task: ItemTaskContext,
        *,
        expected_seq: int,
        expected_class: int,
        expected_x: int,
        expected_y: int,
    ) -> None:
        """decode_outer_frame validates header 0xA5 0x5A / version 0x01 / CRC16."""
        frame = decode_outer_frame(raw)
        self.assertEqual(VERSION, frame.version)
        self.assertEqual(Device.RASPI, frame.sender)
        self.assertEqual(Device.STM32, frame.receiver)
        self.assertEqual(Command.ITEM_TASK, Command(frame.command))
        self.assertEqual(task.task_id, frame.task_id)
        self.assertEqual(8, len(frame.payload))
        # decode_item_task_payload additionally enforces grip_angle == 0xFF and
        # the +-1450 coordinate range at the wire boundary.
        payload = decode_item_task_payload(frame.payload)
        self.assertEqual(expected_seq, payload.target_seq)
        self.assertEqual(expected_class, payload.class_id)
        self.assertEqual(task.payload.image_id, payload.image_id)
        self.assertEqual(expected_x, payload.x_position)
        self.assertEqual(expected_y, payload.y_position)
        self.assertEqual(0xFF, payload.grip_angle)

    def complete_item(
        self,
        task: ItemTaskContext,
        *,
        motion_seq: int,
        result_seq: int,
        image_ids=None,
    ) -> tuple:
        """Drive one item through MOTION_DONE -> ITEM_RESULT -> render -> DISPLAY_ACK.

        Every intermediate gate is asserted here; returns (view, intent).
        """
        outcome = self.gateway.feed_frame(
            stm32_frame(Command.MOTION_DONE, frame_seq=motion_seq)
        )
        self.assertEqual("MOTION_DONE", outcome.event)

        outcome = self.gateway.feed_frame(
            item_result_frame(result_seq, task.payload.target_seq)
        )
        self.assertEqual("ITEM_RESULT", outcome.event)
        self.assertEqual(SchedulerState.WAIT_RENDER, self.scheduler.state)

        # 显示尚未完成：下一件不可派发（赛题 R-D04）
        self.assertIsNone(self.scheduler.next_task())

        content = self.scheduler.display_model
        self.assertIsNotNone(content)
        view = build_display_view(content, NAMES, image_ids)
        self.assertEqual(content.target_seq, view.target_seq)
        self.assertEqual(content.image_id, view.image_id)
        self.assertEqual(content.success_count, view.success_count)
        self.assertEqual(content.result_code, view.result_code)

        receipt = (
            FakeDisplayRenderer(self.scheduler.current_task).present(view).complete()
        )
        intent = self.scheduler.accept_render_receipt(receipt)
        raw_ack = self.outbound.send_display_ack(intent)
        self.assertEqual(SchedulerState.READY, self.scheduler.state)

        ack = decode_outer_frame(raw_ack)
        self.assertEqual(Device.RASPI, ack.sender)
        self.assertEqual(Device.STM32, ack.receiver)
        self.assertEqual(Command.DISPLAY_ACK, Command(ack.command))
        self.assertEqual(task.task_id, ack.task_id)
        self.assertEqual(view.target_seq, ack.payload[0])
        self.assertEqual(0x00, ack.payload[1])  # RENDERED
        self.assertEqual(intent.content_crc32_bytes, ack.payload[2:6])
        self.assertEqual(6, len(ack.payload))
        return view, intent

    # ------------------------------------------------------- 断言点 1 ---------

    def test_each_item_sends_exactly_one_decodeable_item_task_frame(self) -> None:
        first = self.scheduler.next_task()
        self.assertIsNotNone(first)
        raw1 = self.outbound.send_item_task(first)
        self.assert_item_task_frame(
            raw1, first, expected_seq=1, expected_class=2,
            expected_x=100, expected_y=200,
        )
        self.complete_item(first, motion_seq=101, result_seq=102)

        second = self.scheduler.next_task()
        self.assertIsNotNone(second)
        raw2 = self.outbound.send_item_task(second)
        self.assert_item_task_frame(
            raw2, second, expected_seq=2, expected_class=4,
            expected_x=300, expected_y=400,
        )
        self.complete_item(second, motion_seq=103, result_seq=104)

        item_tasks = [
            decode_outer_frame(raw)
            for raw in self.link.sent
            if Command(decode_outer_frame(raw).command) == Command.ITEM_TASK
        ]
        self.assertEqual(2, len(item_tasks))
        self.assertEqual([1, 3], [frame.frame_seq for frame in item_tasks])

    # ------------------------------------------------------- 断言点 2 ---------

    def test_motion_done_gate_rejects_premature_item_result(self) -> None:
        first = self.scheduler.next_task()
        self.assertIsNotNone(first)
        self.outbound.send_item_task(first)

        # 未收 MOTION_DONE 前 ITEM_RESULT 被拒（FAULT）：不计数、不生成显示内容
        rejected = self.gateway.feed_frame(
            item_result_frame(frame_seq=200, target_seq=1)
        )
        self.assertEqual("FAULT", rejected.event)
        self.assertTrue(self.scheduler.is_faulted)
        self.assertEqual(0, self.scheduler.success_count)
        self.assertIsNone(self.scheduler.display_model)

        # 故障恢复（新一轮 verified round）后，按序 MOTION_DONE + ITEM_RESULT 成功
        self.scheduler.start_verified_new_round(
            VerifiedNewRound(ROUND_ID, True, True, True)
        )
        self.scheduler.load_source(FakeTaskSource(self.contexts))
        redone = self.scheduler.next_task()
        self.assertIsNotNone(redone)
        self.outbound.send_item_task(redone)

        self.assertEqual(
            "MOTION_DONE",
            self.gateway.feed_frame(
                stm32_frame(Command.MOTION_DONE, frame_seq=201)
            ).event,
        )
        outcome = self.gateway.feed_frame(
            item_result_frame(frame_seq=202, target_seq=1)
        )
        self.assertEqual("ITEM_RESULT", outcome.event)
        self.assertEqual(1, self.scheduler.success_count)
        self.assertFalse(self.scheduler.is_faulted)

    # ------------------------------------------------------- 断言点 3 ---------

    def test_second_item_not_dispatched_until_first_display_completes(self) -> None:
        first = self.scheduler.next_task()
        self.assertIsNotNone(first)
        self.assertEqual(1, first.payload.target_seq)
        self.outbound.send_item_task(first)

        # 运动阶段（WAIT_MOTION_DONE）不可派发下一件
        self.assertIsNone(self.scheduler.next_task())
        self.assertEqual(
            "MOTION_DONE",
            self.gateway.feed_frame(
                stm32_frame(Command.MOTION_DONE, frame_seq=101)
            ).event,
        )
        self.assertIsNone(self.scheduler.next_task())

        # ITEM_RESULT 已到、显示尚未完成（WAIT_RENDER）：仍不可派发
        outcome = self.gateway.feed_frame(
            item_result_frame(frame_seq=102, target_seq=1)
        )
        self.assertEqual("ITEM_RESULT", outcome.event)
        self.assertEqual(SchedulerState.WAIT_RENDER, self.scheduler.state)
        self.assertIsNone(self.scheduler.next_task())

        # 完成显示并确认后才放行第二件
        view = build_display_view(self.scheduler.display_model, NAMES)
        receipt = (
            FakeDisplayRenderer(self.scheduler.current_task).present(view).complete()
        )
        intent = self.scheduler.accept_render_receipt(receipt)
        self.outbound.send_display_ack(intent)
        self.assertEqual(SchedulerState.READY, self.scheduler.state)

        second = self.scheduler.next_task()
        self.assertIsNotNone(second)
        self.assertEqual(2, second.payload.target_seq)

    # ------------------------------------------------------- 断言点 4 ---------

    def test_displayed_success_total_tracks_scheduler_counter(self) -> None:
        first = self.scheduler.next_task()
        self.outbound.send_item_task(first)
        view1, _ = self.complete_item(
            first, motion_seq=101, result_seq=102, image_ids=IMAGE_IDS
        )
        self.assertEqual(1, self.scheduler.success_count)
        self.assertEqual(view1.success_count, self.scheduler.success_count)
        self.assertEqual("红方柱", view1.name)
        self.assertEqual(102, view1.image_id)

        second = self.scheduler.next_task()
        self.outbound.send_item_task(second)
        view2, _ = self.complete_item(
            second, motion_seq=103, result_seq=104, image_ids=IMAGE_IDS
        )
        self.assertEqual(2, self.scheduler.success_count)
        self.assertEqual(view2.success_count, self.scheduler.success_count)
        self.assertEqual("蓝圆柱", view2.name)
        self.assertEqual(104, view2.image_id)

    # ------------------------------------------------------- 断言点 5 ---------

    def test_sent_sequence_is_item_task_ack_pair_per_item(self) -> None:
        first = self.scheduler.next_task()
        self.outbound.send_item_task(first)
        self.complete_item(first, motion_seq=101, result_seq=102)

        second = self.scheduler.next_task()
        self.outbound.send_item_task(second)
        self.complete_item(second, motion_seq=103, result_seq=104)

        sent = self.link.sent
        self.assertEqual(4, len(sent))
        decoded = [decode_outer_frame(raw) for raw in sent]
        self.assertEqual(
            [
                Command.ITEM_TASK,
                Command.DISPLAY_ACK,
                Command.ITEM_TASK,
                Command.DISPLAY_ACK,
            ],
            [Command(frame.command) for frame in decoded],
        )
        # tx_seq 单调递增（1 起，ITEM_TASK 与 DISPLAY_ACK 共用计数器）
        self.assertEqual([1, 2, 3, 4], [frame.frame_seq for frame in decoded])
        for frame in decoded:
            self.assertEqual(Device.RASPI, frame.sender)
            self.assertEqual(Device.STM32, frame.receiver)
        for frame, target_seq in zip(decoded[1::2], (1, 2)):
            self.assertEqual(target_seq, frame.payload[0])

    # ----------------------------------------------- 全链路闭环（1/3/4/5）-----

    def test_full_two_item_closed_loop(self) -> None:
        first = self.scheduler.next_task()
        self.assertIsNotNone(first)
        self.assertEqual(1, first.payload.target_seq)
        raw1 = self.outbound.send_item_task(first)
        self.assert_item_task_frame(
            raw1, first, expected_seq=1, expected_class=2,
            expected_x=100, expected_y=200,
        )

        view1, _ = self.complete_item(first, motion_seq=101, result_seq=102)
        self.assertEqual(1, view1.success_count)
        self.assertEqual(0, view1.result_code)

        second = self.scheduler.next_task()
        self.assertIsNotNone(second)
        self.assertEqual(2, second.payload.target_seq)
        raw2 = self.outbound.send_item_task(second)
        self.assert_item_task_frame(
            raw2, second, expected_seq=2, expected_class=4,
            expected_x=300, expected_y=400,
        )

        view2, _ = self.complete_item(second, motion_seq=103, result_seq=104)
        self.assertEqual(2, view2.success_count)
        self.assertEqual(0, view2.result_code)

        self.assertEqual(2, self.scheduler.success_count)
        self.assertIsNone(self.scheduler.next_task())  # 源已耗尽

        commands = [
            Command(decode_outer_frame(raw).command) for raw in self.link.sent
        ]
        self.assertEqual(
            [
                Command.ITEM_TASK,
                Command.DISPLAY_ACK,
                Command.ITEM_TASK,
                Command.DISPLAY_ACK,
            ],
            commands,
        )


if __name__ == "__main__":
    unittest.main()
