"""pick_strategy 离线测试的公共夹具。

不触碰任何硬件：所有用例只用虚拟时钟 + 离线模拟执行器。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_EC = Path(__file__).resolve().parents[2]        # 电控/
_SRC = _EC / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from electrical_control.pick_strategy import (  # noqa: E402
    Detection,
    PickStrategyMachine,
    Point,
    SimExecutor,
    StrategyConfig,
    VirtualClock,
    VisionFrame,
    build_config,
    drive_until_settled,
)

DEMO_INI = _EC / "deploy" / "pick_strategy.demo.ini"
REAL_INI = _EC / "deploy" / "pick_strategy.ini"


@pytest.fixture
def demo_config() -> StrategyConfig:
    return build_config(DEMO_INI)


def frame(frame_id: int, detections, now: float = 0.0) -> VisionFrame:
    return VisionFrame(frame_id=frame_id, received_at_s=now,
                       detections=tuple(detections))


def det(seq: int, box_id: int | None, x: float, y: float,
        class_id: int | None = None, conf: int = 90) -> Detection:
    return Detection(target_seq=seq, box_id=box_id,
                     class_id=class_id if class_id is not None else (box_id or 0),
                     x_mm=x, y_mm=y, confidence=conf)


def make_machine(config: StrategyConfig, *, drop: Point | None = None,
                 executor=None, **sim_kwargs):
    """建一个状态机 + 离线执行器；返回 (machine, executor, clock)。"""
    execu = executor if executor is not None else SimExecutor(config, **sim_kwargs)
    drop_command = drop if drop is not None else Point(20.0, 74.0)
    machine = PickStrategyMachine(
        config, execu, drop_command_provider=lambda box_id: drop_command)
    clock = VirtualClock()
    machine.start()
    return machine, execu, clock


def run_item(machine, clock, fr, *, result_code: int = 0):
    """喂一帧并把它跑完（含 ITEM_RESULT / DISPLAY_ACK 两个收尾信号）。"""
    from electrical_control.pick_strategy import State

    machine.on_frame(fr, clock.now)
    drive_until_settled(machine, clock)
    if machine.state is State.WAIT_RESULT:
        machine.on_item_result(result_code, clock.now)
        drive_until_settled(machine, clock)
    if machine.state is State.WAIT_DISPLAY:
        machine.on_display_ack(clock.now)
        drive_until_settled(machine, clock)
    return machine


__all__ = [
    "DEMO_INI",
    "REAL_INI",
    "det",
    "frame",
    "make_machine",
    "run_item",
]
