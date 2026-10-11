"""建轮次吞帧补偿的单测（纯 host：不碰串口、不碰 /dev/fb0、不碰固件）。

背景（2026-09-18 实机定位，别再凭直觉改）：
    板子上电在 FAULT_LOCK、round_id=0。收到**第一发** ITEM_TASK 时它只用这一发
    建轮次（ec_state_machine.c:76-86 → BEGIN_POST），随后自跑 POST→HOMING→
    PREPARE_BARRIER→WAIT_TASK，到 WAIT_TASK 才 emit BARRIER_READY（:127-131）。
    而建轮次那一发在 consume_and_emit 里**没有任何分支**（ec_protocol_gateway.c:
    66-110），tx_len 保持 0 —— 一个字节都不回；同时 :79 清了 dedup、:85 直接
    return，identity 从未被记录，所以**重发同一帧会被当作"全新首件"而正常 ACK**。

    于是：BARRIER_READY 到达时若 Pi 还在等 MOTION_DONE，就应当立刻原样重发，
    而不是干等 5 秒超时。本文件覆盖那个判据，以及"重发确实是原样字节、
    且不推进 tx_seq"。
"""

from __future__ import annotations

import runpy
import unittest
from pathlib import Path

from electrical_control.rpi import (
    FakeTaskSource,
    ItemTaskContext,
    ItemTaskPayload,
    Scheduler,
    SchedulerState,
    VerifiedNewRound,
)
from electrical_control.rpi.outbound import OutboundConfig, OutboundGateway
from electrical_control.rpi.serial_link import FakeSerialLink

_RUN_CHAIN = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "deploy" / "run_chain.py")
)
_should_resend_on_barrier_ready = _RUN_CHAIN["_should_resend_on_barrier_ready"]
_should_stop_resend_on_ack_accept = _RUN_CHAIN["_should_stop_resend_on_ack_accept"]


def _context(frame_seq: int = 10, target_seq: int = 3) -> ItemTaskContext:
    return ItemTaskContext(
        "r1",
        1,
        frame_seq,
        # grip_angle 必须 0xFF（夹爪不转），抓取点必须给全，否则 payload 不可序列化
        ItemTaskPayload(target_seq, 6, 6, 50, 50, 0xFF, 0, -450),
    )


def _ready_scheduler() -> Scheduler:
    scheduler = Scheduler()
    scheduler.start_verified_new_round(VerifiedNewRound("r1", True, True, True))
    return scheduler


class BarrierReadyResendTests(unittest.TestCase):
    def test_resend_fires_while_an_item_is_in_flight(self) -> None:
        scheduler = _ready_scheduler()
        scheduler.load_source(FakeTaskSource([_context()]))

        context = scheduler.next_task()

        self.assertIsNotNone(context)
        self.assertIs(SchedulerState.WAIT_MOTION_DONE, scheduler.state)
        self.assertTrue(_should_resend_on_barrier_ready(scheduler, context))

    def test_no_resend_without_an_in_flight_task(self) -> None:
        scheduler = _ready_scheduler()

        self.assertIs(SchedulerState.READY, scheduler.state)
        self.assertFalse(_should_resend_on_barrier_ready(scheduler, None))
        # 板子每完成一件也会再报一次 BARRIER_READY，那时 state 已不是
        # WAIT_MOTION_DONE，绝不能误触发重发。
        self.assertFalse(_should_resend_on_barrier_ready(scheduler, _context()))

    def test_resend_replays_exact_bytes_without_bumping_tx_seq(self) -> None:
        link = FakeSerialLink()
        outbound = OutboundGateway(link, config=OutboundConfig(round_task_id=1))
        context = _context()

        first = outbound.send_item_task(context)
        replay = outbound.resend_item_task(context)

        self.assertEqual(first, replay)
        self.assertEqual((first, first), link.sent)  # 线上确实是同一串字节
        self.assertEqual(1, outbound.tx_seq)         # 重发不占新序号


class AckAcceptedStopsResendTests(unittest.TestCase):
    """A5（2026-09-22）：板子受理后在飞件就不该再被 5s 定时重传。

    背景：收到 MOTION_DONE 只重置 last_task_sent_at、**没清 last_task_context**，
    而在飞判据只看"有上下文 + 超时" ⇒ 没等到 ITEM_RESULT 之前每 5s 重传一次
    （实机一轮 23 次）。修法是收到 ACK_ACCEPTED 时按身份核对后清上下文。
    """

    def test_stops_when_task_id_matches(self) -> None:
        self.assertTrue(_should_stop_resend_on_ack_accept(_context(), 1))

    def test_does_not_stop_without_an_in_flight_task(self) -> None:
        self.assertFalse(_should_stop_resend_on_ack_accept(None, 1))

    def test_does_not_stop_on_mismatched_task_id(self) -> None:
        # 别的轮次的迟到 ACK：宁可多传一次，也不误清本件的在飞上下文。
        self.assertFalse(_should_stop_resend_on_ack_accept(_context(), 2))

    def test_does_not_stop_when_ack_identity_is_unavailable(self) -> None:
        """🔴 实机回归（round-R8-075620）：取不到 ACK 身份时必须**返回 False**，
        而不是抛异常。

        现场：调用点把 `link.receive()` 的**原始 bytes** 当解析后的帧用
        （`frame.task_id`）⇒ `AttributeError: 'bytes' object has no attribute
        'task_id'` 冒到 run() 兜底 ⇒ 整条链退出码 1。
        本条保证"身份不可得"是一条**能走通的 fail-closed 分支**。
        """
        self.assertFalse(_should_stop_resend_on_ack_accept(_context(), None))


if __name__ == "__main__":
    unittest.main()
