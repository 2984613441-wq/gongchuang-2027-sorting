"""状态机：完成反馈、故障处置、旧画面、重复反馈、托盘清空（需求五）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import det, frame, make_machine, run_item

from electrical_control.pick_strategy import (
    FB_DONE,
    Feedback,
    FaultCode,
    RefusalCode,
    SimExecutor,
    State,
    VisionFrame,
    describe_selection_limitation,  # noqa: F401  (保持导出面与包一致)
    drive_until_settled,
)
from electrical_control.pick_strategy.config import build_config

GOOD_DETECTIONS = [det(2, 6, 55.0, 30.0), det(1, 3, -20.0, 20.0)]


class RecordingExecutor(SimExecutor):
    """记录每一次 dispatch 与 stop_and_hold，用于断言"故障后不再派发/不松爪"。"""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)
        self.executed: list[tuple[int, str, bool]] = []
        self.stopped = 0

    def execute(self, plan, step_index):
        step = plan.steps[step_index]
        self.executed.append((step_index, step.name, step.carrying))
        return super().execute(plan, step_index)

    def stop_and_hold(self):
        self.stopped += 1
        return super().stop_and_hold()


class ReplayExecutor(SimExecutor):
    """重复投递同一条完成反馈（模拟重传/重放）。"""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)
        self._last: Feedback | None = None

    def poll(self, now_s):
        fresh = super().poll(now_s)
        if fresh:
            self._last = fresh[0]
            return fresh
        if self._last is not None:
            dup, self._last = self._last, None
            return [dup]
        return []


# ------------------------------------------------------------------ 正常路径
def test_normal_item_runs_all_steps_then_waits_for_result_and_display(demo_config):
    machine, _exec, clock = make_machine(demo_config)
    machine.on_frame(frame(1, GOOD_DETECTIONS), clock.now)
    drive_until_settled(machine, clock)
    assert machine.state is State.WAIT_RESULT, "步骤走完后必须等本件结果确认"
    machine.on_item_result(0, clock.now)
    assert machine.state is State.WAIT_DISPLAY, "结果确认后必须等显示流程完成"
    machine.on_display_ack(clock.now)
    assert machine.state is State.WAIT_FRAME
    assert len(machine.item_records) == 1
    record = machine.item_records[0]
    assert record.steps_done == record.steps_total == 6
    assert record.display_confirmed is True
    assert record.grasp_verified is False, "无夹持传感器 ⇒ 必须标为未证实"


def test_ack_never_advances_the_machine(demo_config):
    """需求五.5：收到 ACK ≠ 运动完成。"""
    machine, _exec, clock = make_machine(demo_config)
    machine.on_frame(frame(1, GOOD_DETECTIONS), clock.now)
    for _ in range(3):
        machine.on_ack_accepted(2, clock.now)
    assert machine.state is State.MOVING_EMPTY, "ACK 不得推进状态"
    assert machine.counters["ack_received"] == 3


def test_new_frame_ignored_until_back_home(demo_config):
    """需求三.6/五.8：每轮只锁一件；未回到初始位置并且本件闭环前不接受新画面。"""
    machine, _exec, clock = make_machine(demo_config)
    machine.on_frame(frame(1, GOOD_DETECTIONS), clock.now)
    assert machine.current_plan is not None
    first_plan = machine.current_plan
    machine.on_frame(frame(2, [det(5, 3, 20.0, -10.0)]), clock.now)
    assert machine.counters["frames_out_of_window"] == 1
    assert machine.current_plan is first_plan, "不得用新画面替换在飞的本件"


def test_next_item_requires_a_new_frame(demo_config):
    """需求二/三.6：投放后回初始位置再重新识别；不得沿用上一轮坐标。"""
    machine, _exec, clock = make_machine(demo_config)
    run_item(machine, clock, frame(1, GOOD_DETECTIONS))
    assert machine.state is State.WAIT_FRAME
    assert len(machine.item_records) == 1
    # 同样的数据但帧号更大、且接收时刻是"现在" → 视为新画面，正常出件
    run_item(machine, clock, frame(2, GOOD_DETECTIONS, now=clock.now))
    assert len(machine.item_records) == 2


# ------------------------------------------------------------------ 夹取失败
@pytest.mark.parametrize("confirmed,code", [(False, FaultCode.GRASP_FAILED)])
def test_grasp_failure_stops_without_releasing(demo_config, confirmed, code):
    """需求五.7：夹取失败 → 停派发、**不自动松爪**。"""
    machine, execu, clock = make_machine(demo_config, executor=None)
    execu = RecordingExecutor(demo_config)
    machine, execu, clock = make_machine(demo_config, executor=execu)
    machine.on_frame(frame(1, GOOD_DETECTIONS), clock.now)
    machine.on_grasp_outcome(confirmed, "演示：外部判据报夹取失败", clock.now)
    drive_until_settled(machine, clock)

    assert machine.state is State.FAULT
    assert machine.fault.code == code
    assert machine.fault.retained_grasp is True
    assert execu.stopped >= 1, "故障必须调 stop_and_hold"
    dispatched = [name for _, name, _ in execu.executed]
    assert "release" not in dispatched, "故障后绝不能派发松爪"
    assert dispatched == ["empty_travel", "grasp"], dispatched


def test_grasp_unconfirmed_stops_when_policy_says_do_not_assume(demo_config):
    """没有夹持传感器且策略要求"未证实即停" → 故障，而不是假装夹住了。"""
    from tests.pick_strategy.test_planner import _variant_ini

    strict = build_config(_variant_ini(
        demo_config,
        assume_grasp_without_fault="assume_grasp_without_fault = false  # 【演示】"))
    machine, execu, clock = make_machine(strict)
    machine.on_frame(frame(1, GOOD_DETECTIONS), clock.now)
    drive_until_settled(machine, clock)
    assert machine.state is State.FAULT
    assert machine.fault.code == FaultCode.GRASP_UNCONFIRMED
    assert "夹持确认信号" in machine.fault.detail
    assert machine.fault.retained_grasp is True


def test_grasp_confirmed_by_sensor_is_recorded(demo_config):
    machine, _exec, clock = make_machine(demo_config)
    machine.on_frame(frame(1, GOOD_DETECTIONS), clock.now)
    machine.on_grasp_outcome(True, "演示：装了夹持传感器", clock.now)
    run_item(machine, clock, VisionFrame(0, 0.0, ()))  # 仅推进收尾（帧会被忽略）
    drive_until_settled(machine, clock)
    if machine.state is State.WAIT_RESULT:
        machine.on_item_result(0, clock.now)
        machine.on_display_ack(clock.now)
    assert machine.item_records
    assert machine.item_records[0].grasp_verified is True


# ------------------------------------------------------------------ 运动超时
def test_motion_timeout_faults(demo_config):
    """需求五.6：运动超时 → 故障停机。"""
    machine, _exec, clock = make_machine(
        demo_config, stalled_steps={1: "演示：卡住、无完成反馈"})
    machine.on_frame(frame(1, GOOD_DETECTIONS), clock.now)
    drive_until_settled(machine, clock)
    assert machine.state is State.FAULT
    assert machine.fault.code == FaultCode.MOTION_TIMEOUT
    assert "grasp" in machine.fault.detail
    assert machine.fault.retained_grasp is True  # 夹取步之后失败


def test_timeout_does_not_fire_while_waiting_for_external_events(demo_config):
    machine, _exec, clock = make_machine(demo_config)
    machine.on_frame(frame(1, GOOD_DETECTIONS), clock.now)
    drive_until_settled(machine, clock)
    assert machine.state is State.WAIT_RESULT
    clock.advance(demo_config.step_timeout_s * 5)
    machine.tick(clock.now)
    assert machine.state is State.WAIT_RESULT, "等外部事件时不得触发运动超时"


# ------------------------------------------------------------------ 相机断连
def test_camera_lost_is_a_fault_and_not_an_empty_tray(demo_config):
    """需求五.9：相机故障不能当成托盘清空。"""
    machine, _exec, clock = make_machine(demo_config)
    machine.on_camera_lost("演示：心跳超时", clock.now)
    assert machine.state is State.FAULT
    assert machine.fault.code == FaultCode.CAMERA_LOST
    assert machine.empty_streak == 0
    assert machine.state is not State.ROUND_DONE


# ------------------------------------------------------------------ 旧画面
def test_frame_with_old_id_is_dropped(demo_config):
    """需求五.6：旧画面必须丢弃，不得重新出件。"""
    machine, _exec, clock = make_machine(demo_config)
    run_item(machine, clock, frame(5, GOOD_DETECTIONS))
    before = len(machine.item_records)
    machine.on_frame(frame(5, GOOD_DETECTIONS), clock.now)
    assert machine.counters["frames_stale"] == 1
    assert len(machine.item_records) == before
    machine.on_frame(frame(4, GOOD_DETECTIONS), clock.now)
    assert machine.counters["frames_stale"] == 2


def test_frame_older_than_the_stale_timeout_is_dropped(demo_config):
    machine, _exec, clock = make_machine(demo_config)
    clock.advance(demo_config.stale_frame_timeout_s + 1.0)
    machine.on_frame(frame(1, GOOD_DETECTIONS, now=0.0), clock.now)
    assert machine.counters["frames_stale"] == 1
    assert machine.current_plan is None


# ------------------------------------------------------------------ 重复反馈
def test_duplicate_feedback_is_ignored(demo_config):
    """需求五.6：重复反馈不得导致重复推进/重复派发。"""
    execu = ReplayExecutor(demo_config)
    machine, execu, clock = make_machine(demo_config, executor=execu)
    machine.on_frame(frame(1, GOOD_DETECTIONS), clock.now)
    drive_until_settled(machine, clock)
    assert machine.counters["duplicate_feedback"] >= 1
    # 仍然只走完 6 步，不会因为重复反馈多派发或提前完成
    if machine.state is State.WAIT_RESULT:
        assert machine._step_index == 6


# ------------------------------------------------------------------ 托盘清空
def test_tray_empty_needs_consecutive_valid_frames(demo_config):
    """需求五.9：连续多个有效新画面确认托盘为空才结束。"""
    machine, _exec, clock = make_machine(demo_config)
    need = demo_config.empty_confirmation_frames
    for i in range(1, need):
        machine.on_frame(frame(i, ()), clock.now)
        assert machine.state is State.WAIT_FRAME, "不足帧数时不得判定清空"
        assert machine.empty_streak == i
    machine.on_frame(frame(need, ()), clock.now)
    assert machine.state is State.ROUND_DONE
    assert machine.empty_streak == need


def test_recognition_failure_is_not_an_empty_tray(demo_config):
    """需求五.9：识别失败（有目标但都不带颜色真值）不能当成托盘清空。"""
    machine, _exec, clock = make_machine(demo_config)
    for i in range(1, demo_config.empty_confirmation_frames + 2):
        machine.on_frame(frame(i, [det(1, None, 30.0, 30.0)]), clock.now)
        assert machine.state is State.WAIT_FRAME
    assert machine.empty_streak == 0
    assert machine.counters["frames_unrecognized"] >= 1


def test_empty_frame_resets_streak_after_a_real_item(demo_config):
    machine, _exec, clock = make_machine(demo_config)
    machine.on_frame(frame(1, ()), clock.now)
    assert machine.empty_streak == 1
    run_item(machine, clock, frame(2, GOOD_DETECTIONS))
    assert machine.empty_streak == 0, "出过件之后必须重新累计"


def test_fault_stops_dispatching_and_records_retained_grasp(demo_config):
    """需求五.6/五.7：故障后禁止继续派发。"""
    execu = RecordingExecutor(demo_config, faults={2: "演示：退出段受阻"})
    machine, execu, clock = make_machine(demo_config, executor=execu)
    machine.on_frame(frame(1, GOOD_DETECTIONS), clock.now)
    drive_until_settled(machine, clock)
    assert machine.state is State.FAULT
    assert machine.fault.code == FaultCode.MOTION_FAULT
    assert [n for _, n, _ in execu.executed] == ["empty_travel", "grasp", "exit"]
    assert execu.stopped == 1
    # 故障后再 tick 也不会推进
    clock.advance(100.0)
    machine.tick(clock.now)
    assert machine.state is State.FAULT


def test_refusal_does_not_fault_the_machine(demo_config):
    """拒识是"本件不做"，不是故障：链路可以继续等下一帧。"""
    machine, _exec, clock = make_machine(demo_config)
    machine.on_frame(frame(1, [det(1, 3, 10.0, 55.0)]), clock.now)
    assert machine.state is State.WAIT_FRAME
    assert machine.last_refusal is not None
    assert machine.last_refusal.code == RefusalCode.OUT_OF_REACH_WINDOW
    assert machine.fault is None
