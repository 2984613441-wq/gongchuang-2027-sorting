"""每件一个循环的状态机（策略层，不碰硬件）。

流程（任务要求二，逐条对应）
----------------------------
``WAIT_FRAME``（等**新的**识别结果，返回初始位置后才接受）
  → ``MOVING_EMPTY`` 空爪直接平移至目标上方（不先退出托盘）
  → ``GRASPING`` 到位停稳后夹取
  → ``MOVING_CARRY_EXIT`` 携带物料沿无壁边法线退出托盘
  → ``MOVING_CARRY_TRAVERSE``（完全退出后才横向搬运；能免则免）
  → ``RELEASING`` 到位后松爪
  → ``MOVING_RETURN`` 回初始位置
  → ``WAIT_RESULT`` 等本件结果确认（ITEM_RESULT）
  → ``WAIT_DISPLAY`` 等显示流程完成（DISPLAY_ACK）
  → 回到 ``WAIT_FRAME``，**重新识别**（不沿用上一轮缓存的坐标）

设计约束（任务要求五，逐条对应）
--------------------------------
* 五.5「每一步依据真实完成反馈」：只有 :data:`.executor.FB_DONE` 才推进；
  ACK 只被记录（:meth:`on_ack_accepted` 不改变状态）。开闭爪命令**不等于**
  夹取成功 —— 固件没有夹持传感器，故本机把"夹取"记为未证实
  （:attr:`ItemRecord.grasp_verified`），除非注入真实确认。
* 五.6 故障处理：夹取失败 / 运动超时 / 相机断连 / 旧画面 / 重复反馈 /
  路径受阻，全部有明确分支。
* 五.7 故障时**禁止继续派发**，且**不自动松开**可能仍夹持的物料：
  :meth:`_fault` 只调 ``executor.stop_and_hold()``，从不发 ``release``。
* 五.8 回初始位置 + 本件结果确认 + 显示流程完成之后，才允许开始下一件。
* 五.9 连续多个**有效新画面**确认托盘为空才结束；相机故障/识别失败不计入。

⚠️ 本机不使用 ``time.time()``：一切时间由调用方注入，便于离线复现与测试。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from electrical_control.pick_strategy.config import StrategyConfig
from electrical_control.pick_strategy.executor import (
    FB_DONE,
    FB_FAULT,
    ExecutorPort,
    NotExpressible,
)
from electrical_control.pick_strategy.planner import (
    MOVE_EMPTY_TRAVEL,
    MOVE_EXIT,
    MOVE_RETURN,
    MOVE_TRAVERSE,
    PickPlan,
    plan,
)
from electrical_control.pick_strategy.selector import (
    Refusal,
    VisionFrame,
    select_target,
    usable_detections,
)


class State(enum.Enum):
    IDLE = "IDLE"
    WAIT_FRAME = "WAIT_FRAME"
    MOVING_EMPTY = "MOVING_EMPTY"
    GRASPING = "GRASPING"
    MOVING_CARRY_EXIT = "MOVING_CARRY_EXIT"
    MOVING_CARRY_TRAVERSE = "MOVING_CARRY_TRAVERSE"
    RELEASING = "RELEASING"
    MOVING_RETURN = "MOVING_RETURN"
    WAIT_RESULT = "WAIT_RESULT"
    WAIT_DISPLAY = "WAIT_DISPLAY"
    ROUND_DONE = "ROUND_DONE"
    FAULT = "FAULT"


class FaultCode:
    MOTION_TIMEOUT = "MOTION_TIMEOUT"
    MOTION_FAULT = "MOTION_FAULT"
    GRASP_FAILED = "GRASP_FAILED"
    GRASP_UNCONFIRMED = "GRASP_UNCONFIRMED"
    CAMERA_LOST = "CAMERA_LOST"
    PATH_BLOCKED = "PATH_BLOCKED"
    NOT_EXPRESSIBLE = "NOT_EXPRESSIBLE"
    UNEXPECTED_FEEDBACK = "UNEXPECTED_FEEDBACK"


# 步名 → 状态
_STEP_STATE = {
    MOVE_EMPTY_TRAVEL: State.MOVING_EMPTY,
    "grasp": State.GRASPING,
    MOVE_EXIT: State.MOVING_CARRY_EXIT,
    MOVE_TRAVERSE: State.MOVING_CARRY_TRAVERSE,
    "release": State.RELEASING,
    MOVE_RETURN: State.MOVING_RETURN,
}


@dataclass
class Fault:
    code: str
    detail: str
    at_state: str
    retained_grasp: bool   # 故障时是否可能仍夹着物料（决定"不得自动松爪"的适用范围）


@dataclass
class ItemRecord:
    """本件的可复核记录（写日志/交接用）。"""

    target_seq: int
    box_id: int | None
    plan_total_mm: float = 0.0
    exit_distance_mm: float = 0.0
    steps_done: int = 0
    steps_total: int = 0
    grasp_verified: bool = False
    feedback_granularity: str = ""
    result_code: int | None = None
    display_confirmed: bool = False
    unverified_params: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default=())


class PickStrategyMachine:
    """一件一轮的夹取策略状态机。"""

    def __init__(
        self,
        config: StrategyConfig,
        executor: ExecutorPort,
        *,
        drop_command_provider,
        now_s: float = 0.0,
    ) -> None:
        """
        Args:
            drop_command_provider: ``box_id -> Point | None``，返回**滑台记账坐标**
                的落点（与现有 ``drop_strategy.get_drop_point`` 同口径）。
                返回 None = 该盒没有落点 → 拒识本件，绝不猜。
        """
        self._config = config
        self._executor = executor
        self._drop_provider = drop_command_provider

        self.state = State.IDLE
        self.fault: Fault | None = None
        self.current_plan: PickPlan | None = None
        self.last_refusal: Refusal | None = None
        self.item_records: list[ItemRecord] = []
        self.log: list[tuple[float, str]] = []

        self._step_index = 0
        self._step_started_at = 0.0
        self._last_frame_id: int | None = None
        self._empty_streak = 0
        self._carrying = False
        self._grasp_outcome: bool | None = None
        self._current_record: ItemRecord | None = None
        self._now = now_s
        # 统计（供测试与运行入口汇报）
        self.counters = {
            "frames_accepted": 0,
            "frames_stale": 0,
            "frames_out_of_window": 0,
            "frames_unrecognized": 0,
            "ack_received": 0,
            "duplicate_feedback": 0,
            "refusals": 0,
        }

    # ------------------------------------------------------------------
    # 只读视图
    # ------------------------------------------------------------------
    @property
    def empty_streak(self) -> int:
        return self._empty_streak

    @property
    def is_faulted(self) -> bool:
        return self.state is State.FAULT

    def _log(self, text: str) -> None:
        self.log.append((self._now, text))

    # ------------------------------------------------------------------
    # 入向事件
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self.state is State.IDLE:
            self._log("状态机启动：进入 WAIT_FRAME（等第一帧新画面）")
            self.state = State.WAIT_FRAME

    def on_frame(self, frame: VisionFrame, now_s: float) -> None:
        """收到一帧识别结果。"""
        self._now = now_s
        if self.is_faulted:
            return
        if self.state is not State.WAIT_FRAME:
            # 需求三.6：每轮只锁定一件；不在等待窗口内的画面一律不采用，
            # 也绝不缓存下来给下一件用。
            self.counters["frames_out_of_window"] += 1
            self._log(f"忽略画面 {frame}：当前状态 {self.state.value} "
                      "不接受新目标（每轮只锁一件，且必须回初始位置后重识别）")
            return

        # 旧画面判定（需求五.6）。线格式没有时间戳（interface-contract.md:129-143），
        # 所以 age 是**本机接收时刻**到现在的间隔，不是相机拍摄时刻。
        age = now_s - frame.received_at_s
        if age > self._config.stale_frame_timeout_s:
            self.counters["frames_stale"] += 1
            self._log(f"丢弃画面 {frame}：距本机接收已 {age:.2f}s > "
                      f"{self._config.stale_frame_timeout_s:.2f}s（旧画面）")
            return
        if self._last_frame_id is not None and frame.frame_id <= self._last_frame_id:
            self.counters["frames_stale"] += 1
            self._log(f"丢弃画面 {frame}：帧号不大于上一帧 "
                      f"#{self._last_frame_id}（旧画面/重复画面）")
            return

        self._last_frame_id = frame.frame_id
        self.counters["frames_accepted"] += 1

        # 托盘清空判定（需求五.9）：只有"画面有效且一件都没识别到"才计数；
        # "识别到东西但没有一件可用"是**识别失败**，不算清空。
        if len(frame.detections) == 0:
            self._empty_streak += 1
            self._log(f"画面 {frame} 无目标：连续空画面 "
                      f"{self._empty_streak}/{self._config.empty_confirmation_frames}")
            if self._empty_streak >= self._config.empty_confirmation_frames:
                self.state = State.ROUND_DONE
                self._log("连续多帧有效新画面确认托盘为空 → 本轮结束")
            return
        self._empty_streak = 0

        selection = select_target(frame, self._config)
        if isinstance(selection, Refusal):
            self.counters["refusals"] += 1
            self.last_refusal = selection
            self._log(f"拒识本帧：{selection}")
            if selection.code == "NO_USABLE_TARGET":
                self.counters["frames_unrecognized"] += 1
            return

        drop_command = self._drop_provider(selection.detection.box_id)
        if drop_command is None:
            self.counters["refusals"] += 1
            self._log(f"拒识本件：box_id={selection.detection.box_id} "
                      "在落点表里没有落点（绝不猜坐标）")
            return

        planned = plan(selection, frame, self._config, drop_command)
        if isinstance(planned, Refusal):
            self.counters["refusals"] += 1
            self.last_refusal = planned
            self._log(f"拒识本件：{planned}")
            return

        self.current_plan = planned
        self._current_record = ItemRecord(
            target_seq=selection.detection.target_seq,
            box_id=selection.detection.box_id,
            plan_total_mm=planned.total_travel_mm,
            exit_distance_mm=planned.exit_distance_mm,
            steps_total=len(planned.steps),
            feedback_granularity=self._executor.feedback_granularity(),
            unverified_params=planned.unverified_params,
            warnings=planned.check.warnings,
        )
        self._log(f"锁定本件：{selection}（候选 {selection.candidate_count} 件，"
                  f"模式={selection.mode}）")
        for warn in planned.check.warnings:
            self._log(f"  ⚠ {warn}")
        if not planned.check.expressible_with_item_task:
            self._log("  ⚠ 现有 ITEM_TASK **表达不了**这份计划，缺：")
            for cap in planned.check.missing_capabilities:
                self._log(f"    · {cap}")
        self._grasp_outcome = None
        self._carrying = False
        self._step_index = 0
        self._dispatch_current_step()

    def on_camera_lost(self, detail: str, now_s: float) -> None:
        """相机断连（需求五.6/五.9：绝不能被当成托盘清空）。"""
        self._now = now_s
        self._fault(FaultCode.CAMERA_LOST, f"相机/视觉源断连：{detail}")

    def on_ack_accepted(self, target_seq: int, now_s: float) -> None:
        """收到 ACK。**只记录，不推进**：ACK = 帧被受理 ≠ 运动完成。"""
        self._now = now_s
        self.counters["ack_received"] += 1
        self._log(f"收到 ACK(target_seq={target_seq})：仅表示帧被受理，"
                  "不作为任何步骤的完成依据（ec_app.c:218-220 的 DISPLAY_ACK 关窗口，"
                  "MOTION_DONE 才是完成）")

    def on_grasp_outcome(self, confirmed: bool | None, detail: str,
                         now_s: float) -> None:
        """外部注入的夹持判据（若日后装了传感器/视觉复核）。"""
        self._now = now_s
        self._grasp_outcome = confirmed
        self._log(f"夹持判据注入：{confirmed}（{detail}）")

    def on_item_result(self, result_code: int, now_s: float) -> None:
        """本件结果确认（现有链路的 ITEM_RESULT）。"""
        self._now = now_s
        if self.state is not State.WAIT_RESULT:
            self._log(f"忽略 ITEM_RESULT(result_code={result_code})："
                      f"当前状态 {self.state.value} 不在等结果")
            return
        if self._current_record is not None:
            self._current_record.result_code = result_code
        self._log(f"本件结果确认：result_code={result_code}"
                  "（注意：它是固件「整段程序跑完 + 无故障」的产物，"
                  "不等于「确实夹住了」——见 ec_app.c:527-529）")
        self.state = State.WAIT_DISPLAY

    def on_display_ack(self, now_s: float) -> None:
        """显示流程完成（现有链路的 DISPLAY_ACK，也是固件关 15s 窗口的信号）。"""
        self._now = now_s
        if self.state is not State.WAIT_DISPLAY:
            self._log("忽略 DISPLAY_ACK：当前状态 "
                      f"{self.state.value} 不在等显示确认")
            return
        if self._current_record is not None:
            self._current_record.display_confirmed = True
            self.item_records.append(self._current_record)
            self._log(
                f"本件闭环完成：target_seq={self._current_record.target_seq} "
                f"步数 {self._current_record.steps_done}/"
                f"{self._current_record.steps_total} "
                f"夹持已证实={self._current_record.grasp_verified} "
                f"反馈粒度={self._current_record.feedback_granularity}"
            )
        self._current_record = None
        self.current_plan = None
        self._empty_streak = 0
        self._log("回到 WAIT_FRAME：必须用**新的**画面重新识别，"
                  "不得沿用上一轮坐标")
        self.state = State.WAIT_FRAME

    def tick(self, now_s: float) -> None:
        """推进时间：拉取执行层反馈、检查运动超时。"""
        self._now = now_s
        if self.is_faulted:
            return
        for fb in self._executor.poll(now_s):
            if fb.kind == FB_FAULT:
                self._fault(FaultCode.MOTION_FAULT,
                            f"第 {fb.step_index} 步报故障：{fb.detail}")
                return
            if fb.kind == FB_DONE:
                self._on_step_done(fb.step_index, fb.detail)
                if self.is_faulted:
                    return
        self._check_step_timeout(now_s)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _dispatch_current_step(self) -> None:
        planned = self.current_plan
        assert planned is not None
        if self._step_index >= len(planned.steps):
            self._log("全部步骤已完成 → 等本件结果确认（ITEM_RESULT）")
            self.state = State.WAIT_RESULT
            return
        step = planned.steps[self._step_index]
        self.state = _STEP_STATE.get(step.name, State.MOVING_EMPTY)
        self._carrying = step.carrying or step.kind == "grasp"
        try:
            self._executor.execute(planned, self._step_index)
        except NotExpressible as exc:
            self._fault(FaultCode.NOT_EXPRESSIBLE, str(exc))
            return
        self._step_started_at = self._now
        self._log(f"派出第 {self._step_index + 1}/{len(planned.steps)} 步：{step}")

    def _on_step_done(self, index: int, detail: str) -> None:
        if index < self._step_index:
            self.counters["duplicate_feedback"] += 1
            self._log(f"忽略重复/过期完成反馈（第 {index} 步，当前 "
                      f"{self._step_index}）")
            return
        if index >= len(self.current_plan.steps if self.current_plan else ()):
            self._fault(FaultCode.UNEXPECTED_FEEDBACK,
                        f"完成反馈的步序号 {index} 超出计划范围")
            return
        # 粗粒度执行器（如现有 ITEM_TASK 适配器）一次只报最后一步：
        # 这里按顺序补完中间步骤，保证"顺序推进"的语义不被绕过。
        while self._step_index <= index and not self.is_faulted:
            step = self.current_plan.steps[self._step_index]
            record = self._current_record
            if record is not None:
                record.steps_done = self._step_index + 1
            self._log(f"  ✓ 第 {self._step_index + 1} 步完成：{step.name}"
                      + (f"（{detail}）" if detail else ""))
            if step.name == "grasp":
                if not self._after_grasp_step():
                    return
            self._step_index += 1
            if self._step_index > index:
                break
            self._log(f"  （粗粒度反馈：第 {self._step_index + 1} 步视为已随整段完成）")
        self._dispatch_current_step()

    def _after_grasp_step(self) -> bool:
        """夹取步之后的判据。**发闭爪命令 ≠ 夹取成功**（需求五.5）。"""
        record = self._current_record
        if self._grasp_outcome is True:
            if record is not None:
                record.grasp_verified = True
            self._log("  夹持已由外部判据证实")
            return True
        if self._grasp_outcome is False:
            self._fault(FaultCode.GRASP_FAILED,
                        "外部判据明确报夹取失败")
            return False
        if not self._config.assume_grasp_without_fault:
            self._fault(
                FaultCode.GRASP_UNCONFIRMED,
                "夹取步已完成，但本机**没有任何夹持确认信号**"
                "（固件无夹持传感器；MOTION_DONE 只表示程序跑完），"
                "且 [Feedback] assume_grasp_without_fault=false → 停止本件。"
                "此时物料可能已被夹起也可能没有，按需求五.7 不自动松爪",
            )
            return False
        self._log("  ⚠ 夹取步完成但**未证实**：无夹持传感器。"
                  "按 assume_grasp_without_fault=true 继续，"
                  "本件记录会标注 grasp_verified=False")
        return True

    def _check_step_timeout(self, now_s: float) -> None:
        if self.state in (State.WAIT_FRAME, State.WAIT_RESULT,
                          State.WAIT_DISPLAY, State.ROUND_DONE, State.IDLE):
            return
        elapsed = now_s - self._step_started_at
        if elapsed > self._config.step_timeout_s:
            planned = self.current_plan
            name = (planned.steps[self._step_index].name
                    if planned and self._step_index < len(planned.steps) else "?")
            self._fault(
                FaultCode.MOTION_TIMEOUT,
                f"第 {self._step_index + 1} 步（{name}）已 {elapsed:.2f}s 无完成反馈，"
                f"超过 [Feedback] step_timeout_s="
                f"{self._config.step_timeout_s:.2f}s",
            )

    def _fault(self, code: str, detail: str) -> None:
        """进入故障：停派发 + 保持夹持（需求五.7）。"""
        if self.is_faulted:
            return
        self.fault = Fault(code=code, detail=detail,
                           at_state=self.state.value,
                           retained_grasp=self._carrying)
        self.state = State.FAULT
        self._executor.stop_and_hold()
        self._log(f"🔴 故障 {code} @ {self.fault.at_state}：{detail}")
        if self._carrying:
            self._log("  → 保持当前夹持状态，**不发松爪指令**，等待人工处置"
                      f"（[Feedback] retain_grasp_on_fault="
                      f"{self._config.retain_grasp_on_fault}）")


# ---------------------------------------------------------------------------
# 驱动助手（离线/测试用）
# ---------------------------------------------------------------------------
class VirtualClock:
    """虚拟时钟：不读墙钟，保证离线可复现。"""

    def __init__(self, start_s: float = 0.0) -> None:
        self.now = start_s

    def advance(self, dt: float) -> float:
        self.now += dt
        return self.now


def drive_until_settled(
    machine: PickStrategyMachine,
    clock: VirtualClock,
    *,
    idle_states: tuple[State, ...] = (
        State.IDLE, State.WAIT_FRAME, State.WAIT_RESULT, State.WAIT_DISPLAY,
        State.ROUND_DONE, State.FAULT),
    dt: float = 0.05,
    max_seconds: float = 600.0,
) -> list[str]:
    """反复 tick 直到状态机落在**等待外部事件**的态（或超时）。返回事件日志。

    ``WAIT_RESULT`` / ``WAIT_DISPLAY`` 也算空闲：它们在等 STM32 发来的
    ITEM_RESULT / 显示确认，靠 tick 是等不到的，继续 tick 只会把虚拟时钟推飞。
    """
    elapsed = 0.0
    start = len(machine.log)
    while elapsed < max_seconds:
        machine.tick(clock.now)
        if machine.state in idle_states:
            break
        clock.advance(dt)
        elapsed += dt
    return [f"{t:8.2f}s  {msg}" for t, msg in machine.log[start:]]


__all__ = [
    "Fault",
    "FaultCode",
    "ItemRecord",
    "PickStrategyMachine",
    "State",
    "VirtualClock",
    "drive_until_settled",
    "usable_detections",
]
