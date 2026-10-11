"""把 `pick_strategy` 的**选择器**接到实链的 payload 层（α 模式）。

边界（先写清楚）
----------------
本模块是**适配器**，只做一件事：给实链提供一个 `orderer(payloads) -> ordered_payloads`。
它**只改顺序，绝不丢件**（α 语义，见 `夹取策略接入方案-2026-09-21.md` §2.2）：

* 策略认为"不可用"的件**不会被丢掉**，而是排到队尾（原相对顺序不变）；
* 任何异常 → 返回**原顺序**（= 接入前的行为），只记 WARNING，不抛；
* 件数 < 2 → 直接返回原样（**单件行为与接入前逐字节一致**）。

它**不**碰协议、**不**碰固件、**不**碰串口；也不接 `planner`/`state_machine`/`executor`
（那三个会与 `Scheduler` 形成两个权威，且现有 `ITEM_TASK` 表达不了它们的计划形状）。

坐标换算（关键，别搞错）
------------------------
`payload.pick_x_position / pick_y_position` 是 **0.1mm** 的
**【滑台记账坐标】**（`PICK = 物料装置坐标 + ToolOffset`，见
`electrical_control/rpi/pixel_to_device.py:478-503`）。

而 `pick_strategy.selector.Detection` 要的是 **物料【装置坐标】mm**。
⇒ **装置坐标 = pick/10 − ToolOffset**（本工程 ToolOffset = (−120.5, −43.5) ⇒ 实际是 +120.5 / +43.5）。
算错这一跳，排序会整体偏一个 ToolOffset，**等于按另一个点排序**。

已实测 / 待实测（决定这个适配器现在能给出什么）
----------------------------------------------
* `selection_mode = center`【实测】：现有视觉线格式**只给中心像素、不给宽高**
  （`视觉/src/maixcam_deploy/main.py:342-368` 丢弃 `obj.w/h`）⇒ 只能用**中心**到无壁边的距离，
  不是真正的轮廓距离（最坏差约 20mm）。局限已由 `describe_selection_limitation()` 打印。
* `[Tray]` 的四个边界与 `open_side` **【待实测】**（`电控/deploy/pick_strategy.ini:24`）
  ⇒ **无壁边在哪一侧从未实测**。本适配器**不猜**：直接把该 ini 的值拿来用，
  并把未核实项清单打进日志，由现场决定要不要改那一行。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Sequence

from electrical_control.pick_strategy.config import StrategyConfig, build_config
from electrical_control.pick_strategy.geometry import Point
from electrical_control.pick_strategy.selector import (
    Detection,
    VisionFrame,
    describe_selection_limitation,
    order_by_open_edge,
)

logger = logging.getLogger(__name__)

__all__ = ["PayloadOrderer", "make_payload_orderer", "payload_orderer_from_ini"]

PayloadOrderer = Callable[[Sequence[object]], tuple]


def _device_coords(payload: object, tool_offset: Point) -> tuple[float, float] | None:
    """payload 的记账坐标 → 物料装置坐标（mm）。缺抓取点时返回 None。"""
    px = getattr(payload, "pick_x_position", None)
    py = getattr(payload, "pick_y_position", None)
    if px is None or py is None:
        return None
    return (px / 10.0 - tool_offset.x_mm, py / 10.0 - tool_offset.y_mm)


def make_payload_orderer(
    config: StrategyConfig, *, frame_id_base: int = 0
) -> PayloadOrderer:
    """由一份 `StrategyConfig` 造出一个 payload 排序器（α 模式）。"""

    if config.selection_mode:
        logger.info("夹取策略选择模式=%s；%s",
                    config.selection_mode, describe_selection_limitation(config.selection_mode))
    unverified = config.unverified_params()
    if unverified:
        logger.warning(
            "夹取策略仍有【待实测】参数 %d 项，排序结果的可信度受其影响：%s",
            len(unverified), ", ".join(unverified),
        )

    def orderer(payloads: Sequence[object]) -> tuple:
        seq = tuple(payloads)
        if len(seq) < 2:
            return seq  # 单件：与接入前逐字节一致

        dets: list[Detection] = []
        # target_seq -> payload（用于最后按序还原）
        by_seq: dict[int, object] = {}
        no_point: list[object] = []  # 缺抓取点：不参与排序，保持原相对顺序排到最后
        for p in seq:
            ts = getattr(p, "target_seq", None)
            cls = getattr(p, "class_id", None)
            if ts is None or cls is None:
                no_point.append(p)
                continue
            pt = _device_coords(p, config.tool_offset)
            if pt is None:
                no_point.append(p)
                continue
            by_seq[ts] = p
            dets.append(
                Detection(
                    target_seq=int(ts),
                    # payload 不带 box_id；本工程 class_id → box_id 是冻结 1:1
                    # （当前进度与交接.md §14.1「货格映射 class_id N → 货格 N」）。
                    # box_id 只参与「可用性过滤」，不参与排序键本身。
                    box_id=int(cls),
                    class_id=int(cls),
                    x_mm=pt[0],
                    y_mm=pt[1],
                )
            )

        if len(dets) < 2:
            return seq  # 可排序的不足 2 件：原顺序

        frame = VisionFrame(
            frame_id=frame_id_base, received_at_s=0.0, detections=tuple(dets)
        )
        ordered_dets = order_by_open_edge(frame, config)   # 只按规则排序，不拒识

        ordered: list[object] = [by_seq[d.target_seq] for d in ordered_dets]
        # α：策略没排进来的件**不丢**，按原相对顺序接到队尾
        placed = {id(p) for p in ordered}
        for p in seq:
            if id(p) not in placed:
                ordered.append(p)
        return tuple(ordered)

    return orderer


def payload_orderer_from_ini(
    ini_path: str | Path, *, frame_id_base: int = 0
) -> PayloadOrderer | None:
    """从 `pick_strategy.ini` 造排序器。**任何失败都返回 None**（调用方保持默认行为）。"""
    path = Path(ini_path)
    if not path.exists():
        logger.warning("夹取策略：配置不存在 %s ⇒ 不启用（保持原顺序）", path)
        return None
    try:
        cfg = build_config(path)
    except Exception:
        logger.warning("夹取策略：配置解析失败 %s ⇒ 不启用（保持原顺序）", path, exc_info=True)
        return None
    try:
        return make_payload_orderer(cfg, frame_id_base=frame_id_base)
    except Exception:
        logger.warning("夹取策略：排序器构造失败 ⇒ 不启用（保持原顺序）", exc_info=True)
        return None
