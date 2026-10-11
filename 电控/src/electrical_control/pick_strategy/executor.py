"""执行器抽象：把"策略"与"硬件通信"分开。

三个执行器
----------
* :class:`ExecutorPort` —— 状态机唯一认识的接口。策略层不知道串口、GPIO、
  舵机脉宽、步数的存在。
* :class:`SimExecutor` —— **离线模拟执行器**。按配置的每步耗时产生"完成"事件，
  并可注入故障。它**不模拟任何物理**（不模拟电机、舵机、摩擦、丢步），
  只模拟"这一步要多久、会不会报错"。
* :class:`ItemTaskExecutor` —— 把计划映射到现有 ``ITEM_TASK`` 的适配器。
  它**不实现串口**：只做①可行性判定（计划能否被现有线格式表达）
  ②按现有编码组帧（复用 `electrical_control.protocol.encode_item_task_payload`）
  ③把帧交给注入的 sink。sink 默认是 ``None`` = 只回显字节、什么都不发。

⚠️ 重要事实（决定了第二条的性质）
--------------------------------
现有 ``ITEM_TASK`` 线上**只有两个位置**（抓取点 offset 8-11 + 落料点 offset 3-6，
`ec_protocol.h:153-157`），固件把它们编译成固定 10 步程序
（`ec_motion_plan.c:193-225`）。因此：

* 计划形状若需要"退出中间路径点"，现有线格式**表达不了** ——
  :meth:`ItemTaskExecutor.execute` 会抛 :class:`NotExpressible`，**不降级、不猜**。
* 即使形状可表达，**逐步完成反馈也没有**：STM32 只在整段程序跑完后发一次
  ``MOTION_DONE``（`ec_protocol_gateway.c:71-90`）。故它的
  :meth:`feedback_granularity` 是 ``whole_program``，状态机会把这一点记进本件
  记录，避免"看起来逐步确认了"。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from electrical_control.protocol import ItemTaskPayload, encode_item_task_payload

from electrical_control.pick_strategy.config import StrategyConfig
from electrical_control.pick_strategy.planner import (
    STEP_GRASP,
    STEP_MOVE,
    STEP_RELEASE,
    PickPlan,
)

FEEDBACK_PER_STEP = "per_step"
FEEDBACK_WHOLE_PROGRAM = "whole_program"

FB_DONE = "done"
FB_FAULT = "fault"
FB_STOPPED = "stopped"


class NotExpressible(Exception):
    """现有 ITEM_TASK 无法表达这份计划（缺能力），拒绝下发。"""


@dataclass(frozen=True)
class Feedback:
    """一条来自执行层的反馈。

    ``kind==FB_DONE`` 才代表"这一步真的完成了"。**ACK 不是完成**
    （`ec_app.c:218-220` 的 DISPLAY_ACK 才关窗口；`ec_protocol.h:123` 的
    ACK 只表示"帧被受理"），故本模块**不产生** ACK 类反馈，只产生完成/故障。
    """

    kind: str
    step_index: int
    detail: str = ""


class ExecutorPort(Protocol):
    def feedback_granularity(self) -> str: ...
    def execute(self, plan: PickPlan, step_index: int) -> None: ...
    def poll(self, now_s: float) -> list[Feedback]: ...
    def stop_and_hold(self) -> None: ...
    def describe(self) -> str: ...


class SimExecutor:
    """离线模拟执行器：每步耗时取配置，可按注入表制造故障。"""

    def __init__(
        self,
        config: StrategyConfig,
        *,
        faults: dict[int, str] | None = None,
        stalled_steps: dict[int, str] | None = None,
    ) -> None:
        """
        Args:
            faults: ``{步序号: 原因}`` —— 该步到点后报故障（模拟"运动超时/受阻"）。
            stalled_steps: ``{步序号: 原因}`` —— 该步**永远不报完成**
                （模拟"卡住/无反馈"，用于验证策略侧的运动超时）。
        """
        self._config = config
        self._faults = dict(faults or {})
        self._stalled = dict(stalled_steps or {})
        self._running: tuple[int, float, str] | None = None
        self._started_at = 0.0
        self._stops = 0

    # ---- ExecutorPort ----
    def feedback_granularity(self) -> str:
        return FEEDBACK_PER_STEP

    def execute(self, plan: PickPlan, step_index: int) -> None:
        if step_index < 0 or step_index >= len(plan.steps):
            raise IndexError(f"步序号 {step_index} 不在计划范围内")
        step = plan.steps[step_index]
        # 每步耗时用一条【演示】参数，避免在执行器里再内置第二套运动学模型。
        self._running = (step_index, self._config.step_duration_s, step.name)

    def poll(self, now_s: float) -> list[Feedback]:
        if self._running is None:
            return []
        index, duration, name = self._running
        if index in self._stalled:
            return []  # 永远不完成 → 由状态机的超时兜底
        if now_s - self._started_at < duration:
            return []
        self._started_at = now_s
        self._running = None
        if index in self._faults:
            return [Feedback(FB_FAULT, index, f"{name}: {self._faults[index]}")]
        return [Feedback(FB_DONE, index, name)]

    def stop_and_hold(self) -> None:
        """停止后续动作。**不发送任何松爪/释放指令**（需求五.7）。"""
        self._running = None
        self._stops += 1

    def describe(self) -> str:
        return (f"SimExecutor（离线模拟，每步 {self._config.step_duration_s:.2f}s；"
                f"故障注入={self._faults}，卡死注入={self._stalled}）")

    @property
    def stop_count(self) -> int:
        return self._stops


class ItemTaskExecutor:
    """把计划映射到现有 ``ITEM_TASK``（组帧复用项目既有编码）。**不碰串口。**"""

    def __init__(
        self,
        config: StrategyConfig,
        *,
        sink: Callable[[bytes], None] | None = None,
    ) -> None:
        self._config = config
        self._sink = sink
        self._frames: list[bytes] = []

    def feedback_granularity(self) -> str:
        return FEEDBACK_WHOLE_PROGRAM

    def build_frame(self, plan: PickPlan) -> bytes:
        """按现有 12 字节 ITEM_TASK 编码组帧；不可表达的方案直接抛。"""
        if not plan.check.expressible_with_item_task:
            raise NotExpressible(
                "现有 ITEM_TASK 表达不了这份计划，缺：\n  - "
                + "\n  - ".join(plan.check.missing_capabilities)
            )
        det = plan.selection.detection
        offset_x = int(round(self._config.tool_offset.x_mm * 10.0))
        offset_y = int(round(self._config.tool_offset.y_mm * 10.0))
        payload = ItemTaskPayload(
            target_seq=det.target_seq,
            class_id=det.class_id,
            image_id=det.class_id,          # 冻结不变量 image_id == class_id
            # 落点：线上就是滑台记账坐标，不再叠加 ToolOffset
            x_position=int(round(plan.drop_physical.x_mm * 10.0)) + offset_x,
            y_position=int(round(plan.drop_physical.y_mm * 10.0)) + offset_y,
            grip_angle=0xFF,
            pick_x_position=int(round(plan.pick.x_mm * 10.0)) + offset_x,
            pick_y_position=int(round(plan.pick.y_mm * 10.0)) + offset_y,
        )
        return encode_item_task_payload(payload)

    # ---- ExecutorPort ----
    def execute(self, plan: PickPlan, step_index: int) -> None:
        step = plan.steps[step_index]
        if step_index == 0:
            frame = self.build_frame(plan)
            self._frames.append(frame)
            if self._sink is not None:
                self._sink(frame)
            return
        # 其余步骤都已被那一份 ITEM_TASK 覆盖（固件按固定程序推进），
        # 不需要也无法单独下发。
        if step.kind in (STEP_MOVE, STEP_GRASP, STEP_RELEASE):
            return
        raise AssertionError(f"未知步骤种类 {step.kind!r}")

    def poll(self, now_s: float) -> list[Feedback]:
        # 本适配器没有真实入站通道（不读串口），所以永远不会自证"完成"。
        # 这是刻意的：把"完成"交给真实的 MOTION_DONE 通道，而不是在这里假装。
        return []

    def stop_and_hold(self) -> None:
        return None

    def describe(self) -> str:
        sink = ("未接入（None，只回显字节、不发任何东西）"
                if self._sink is None else "已注入 sink")
        return (f"ItemTaskExecutor（现有 ITEM_TASK 适配器；sink={sink}；"
                f"组帧数={len(self._frames)}）")

    @property
    def frames(self) -> tuple[bytes, ...]:
        return tuple(self._frames)


__all__ = [
    "ExecutorPort",
    "FB_DONE",
    "FB_FAULT",
    "FB_STOPPED",
    "FEEDBACK_PER_STEP",
    "FEEDBACK_WHOLE_PROGRAM",
    "Feedback",
    "ItemTaskExecutor",
    "NotExpressible",
    "SimExecutor",
]
