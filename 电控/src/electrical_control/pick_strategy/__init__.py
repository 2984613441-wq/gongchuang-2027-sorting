"""夹取策略模块（pick strategy）—— 目标选择 / 路径规划 / 状态机 / 通信分离。

四层，依赖单向（config → geometry → selector/planner → state_machine → executor）：

===================  ==========================================================
模块                 职责
===================  ==========================================================
:mod:`.config`       读 ini + **强制来源标注**（实测/固件常量/演示/待实测）
:mod:`.geometry`     纯几何：点/矩形/托盘/无壁边/线段穿越
:mod:`.selector`     目标选择（离无壁边最近；并列时按空爪距离与 target_seq）
:mod:`.planner`      路径规划（空爪平移→夹取→垂直退出→横搬→松爪→回位）
:mod:`.state_machine` 一件一轮的状态机（含全部故障分支）
:mod:`.executor`     执行器接口 + 离线模拟执行器 + 现有 ITEM_TASK 适配器
===================  ==========================================================

⚠️ 边界声明：本包**不**连接或驱动任何实物、不烧录固件、不发串口、
不产生舵机脉宽/步数/GPIO，也不把"模拟跑通"表述为"实机可用"。
所有坐标只用于离线推演与现有 ITEM_TASK 的组帧。
"""

from __future__ import annotations

from electrical_control.pick_strategy.config import (
    ConfigError,
    RawConfig,
    StrategyConfig,
    build_config,
)
from electrical_control.pick_strategy.executor import (
    FB_DONE,
    FB_FAULT,
    FEEDBACK_PER_STEP,
    FEEDBACK_WHOLE_PROGRAM,
    ExecutorPort,
    Feedback,
    ItemTaskExecutor,
    NotExpressible,
    SimExecutor,
)
from electrical_control.pick_strategy.geometry import (
    OPEN_SIDES,
    Point,
    Rect,
    Segment,
    Tray,
)
from electrical_control.pick_strategy.planner import (
    MOVE_EMPTY_TRAVEL,
    MOVE_EXIT,
    MOVE_RETURN,
    MOVE_TRAVERSE,
    Command,
    PickPlan,
    PlanStep,
    plan,
    to_commands,
)
from electrical_control.pick_strategy.selector import (
    Detection,
    Refusal,
    RefusalCode,
    Selection,
    VisionFrame,
    describe_selection_limitation,
    order_by_open_edge,
    order_by_row_scan,
    row_scan_key,
    select_target,
)
from electrical_control.pick_strategy.state_machine import (
    Fault,
    FaultCode,
    ItemRecord,
    PickStrategyMachine,
    State,
    VirtualClock,
    drive_until_settled,
)

__all__ = [
    "Command",
    "ConfigError",
    "Detection",
    "ExecutorPort",
    "FB_DONE",
    "FB_FAULT",
    "FEEDBACK_PER_STEP",
    "FEEDBACK_WHOLE_PROGRAM",
    "Fault",
    "FaultCode",
    "Feedback",
    "ItemRecord",
    "ItemTaskExecutor",
    "MOVE_EMPTY_TRAVEL",
    "MOVE_EXIT",
    "MOVE_RETURN",
    "MOVE_TRAVERSE",
    "NotExpressible",
    "OPEN_SIDES",
    "PickPlan",
    "PickStrategyMachine",
    "PlanStep",
    "Point",
    "RawConfig",
    "Rect",
    "Refusal",
    "RefusalCode",
    "Segment",
    "Selection",
    "SimExecutor",
    "State",
    "StrategyConfig",
    "Tray",
    "VirtualClock",
    "VisionFrame",
    "build_config",
    "describe_selection_limitation",
    "drive_until_settled",
    "order_by_open_edge",
    "order_by_row_scan",
    "plan",
    "row_scan_key",
    "select_target",
    "to_commands",
]
