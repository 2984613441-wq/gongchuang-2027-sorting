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

排序规则（2026-09-21 用户口径，**已从"离无壁边最近"改成行扫描**）
------------------------------------------------------------------
:func:`~electrical_control.pick_strategy.selector.order_by_row_scan`：第一键
**Y 从大到小**（从靠 Y 正方向那排开始、逐排往里），第二键 **同行 X 从小到大**
（每排从最靠 HOME 那件沿 +X 抓）⇒ 效果"从上到下、每排从左到右"。
排序键**不读 `[Tray]`/`[Home]`**，故结果不再取决于托盘四边与无壁边配在哪一侧
（那几项改了也不影响先后）。

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
* `[Tray] open_side = y_max` 已于 2026-09-21 现场【实测】确认
  （`电控/deploy/pick_strategy.ini:38`：X 轴全部被挡住、只有 Y 正方向敞开）；
  托盘四边其余值仍带【待实测】，`pick_strategy.demo.ini:45` 那份也还是【待实测】。
  2026-09-21 起排序键改成行扫描、**不再读它们** ⇒ 这些项的取值**不再影响件的先后**
  （现役键只在 `open_side = y_max` 时才与行扫描主键同序，见
  `selector.row_scan_key` 的说明）；但它们仍进"未核实参数"清单
  （`usable_detections` 的可用性过滤、contour 模式半尺寸仍取自 config），日志照打。
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
    difficulty_tier_of,
    is_pending,
    order_by_difficulty_scan,
    order_by_group_scan,
    order_by_open_edge,
    order_by_row_scan,
)

from electrical_control.pick_strategy.orderer import (
    ORDER_MODES,
    SettleTracker,
    order_by_five_key,
)

logger = logging.getLogger(__name__)

__all__ = ["PayloadOrderer", "make_payload_orderer", "payload_orderer_from_ini",
           "ORDER_MODES"]

PayloadOrderer = Callable[[Sequence[object]], tuple]


def _device_coords(payload: object, tool_offset: Point) -> tuple[float, float] | None:
    """payload 的记账坐标 → 物料装置坐标（mm）。缺抓取点时返回 None。"""
    px = getattr(payload, "pick_x_position", None)
    py = getattr(payload, "pick_y_position", None)
    if px is None or py is None:
        return None
    return (px / 10.0 - tool_offset.x_mm, py / 10.0 - tool_offset.y_mm)


def make_payload_orderer(
    config: StrategyConfig,
    *,
    frame_id_base: int = 0,
    order_mode: str | None = None,
    settle: "SettleTracker | None" = None,
    last_drop_provider=None,
) -> PayloadOrderer:
    """由一份 `StrategyConfig` 造出一个 payload 排序器（α 模式）。

    2026-11-01 新增 `order_mode` 灰度开关（见 docs/reports/审核-夹取策略-20261101.md）：

    * ``legacy``     不排序（原顺序）
    * ``group``      分组→待定→难度→行扫描（**默认**，= 接入前的现状口径）
    * ``difficulty`` 待定→难度→行扫描
    * ``open_edge``  离托盘无壁边最近
    * ``five_key``   停稳→待定→难度→隔离度→落点距离→seq（本次新增）

    ``last_drop_provider``：返回「上一次落料点」``Point``(mm) 的函数；
    为 None 或返回 None 时按「锚点未知」处理（落点距离键记 0，不惩罚）。
    """
    if order_mode is None:                      # None ⇒ 用 ini 的 [Strategy] order_mode
        order_mode = getattr(config, "order_mode", "legacy")
    if order_mode not in ORDER_MODES:
        raise ValueError("order_mode=%r 非法，只能是 %s" % (order_mode, ORDER_MODES))

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
        # 🔴 2026-09-23 修复（用户批准）：原先用 target_seq 当键（``by_seq[ts] = p``）再按序回填，
        #   只要**两件 target_seq 相同**就会键碰撞、字典里只剩后一件 ⇒ 排序结果与派发对象错位。
        #   实测证据：``round-R8-001619`` 日志里出现**两个 target_seq=1**
        #   （``ITEM_TASK sent: target_seq=1 class_id=3`` 与 ``… target_seq=1 class_id=6``）。
        #   现改为**按对象身份配对**（``id(det) -> payload``）：身份唯一，绝不碰撞。
        p_of: dict[int, object] = {}
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
            det = Detection(
                target_seq=int(ts),
                # payload 不带 box_id；本工程 class_id → box_id 是冻结 1:1
                # （当前进度与交接.md §14.1「货格映射 class_id N → 货格 N」）。
                # box_id 只参与「可用性过滤」，不参与排序键本身。
                box_id=int(cls),
                class_id=int(cls),
                x_mm=pt[0],
                y_mm=pt[1],
            )
            p_of[id(det)] = p          # 对象身份配对（理由见上方 2026-09-23 修复说明）
            dets.append(det)

        if len(dets) < 2:
            return seq  # 可排序的不足 2 件：原顺序

        frame = VisionFrame(
            frame_id=frame_id_base, received_at_s=0.0, detections=tuple(dets)
        )
        # 🔴 2026-09-22 观测点（一次钉死"为什么先夹的不是最靠 −X 那件"）：
        #   离线用同一份排序器喂真实坐标时，输出是正确的（青 y 最大 ⇒ 先夹）；
        #   但实机第 1 件派的是【黑】，与 p_look2 的坐标不符。两条可能：
        #     ① 链自己那一帧的坐标与 p_look2 不同（两次实测差过 1~7mm）
        #     ② 某件被 order_by_row_scan 的【可用性过滤】判掉 ⇒ 走 α 补尾 ⇒ 排到最后
        #   故这里把【输入坐标】与【策略输出】都打出来，并单独告警 α 补尾的件。
        logger.info(
            "排序输入（装置坐标 mm）: %s",
            ", ".join(
                "seq=%d cls=%d(%.1f,%.1f)" % (d.target_seq, d.class_id, d.x_mm, d.y_mm)
                for d in dets
            ),
        )
        # 🔴 2026-10-26 用户裁决 + 赛规原文确认（省赛规则.txt L262-264）：
        #   原文「多个颜色和形状相同的货物放进同一个储物盒，**每个货物得 5 分**」
        #   ⇒ 2 件 = 10 分、4 件 = 20 分 ⇒ **每件都有 5 分边际收益**
        #   ⇒ 所以「先一类再一类」（填满一个类再换下一个）是**正确策略**——
        #     落点集中在同一格、减少来回换箱，且不会把时间浪费在组间跳转上。
        #   ⚠️ 第 3/4 件**不是**边际 0（此前基于"整盒 5 分"的误解已纠正）。
        #
        #   同时保留难度分层：好判的先抓（正方体/长方体/五棱柱/正四面体），
        #   圆柱(tier1)/圆锥(tier2) 留到托盘稀疏、遮挡少时再判 —— 用户口径。
        #
        #   ⚠️ 前提：class_id 必须是**打包码 code = shape_idx*5 + color_idx + 1**（1..30），
        #   这样按 class_id 分组 == 按 (颜色,形状) 分组，与货格绑定口径一致。
        #   一键回退：换回 order_by_difficulty_scan（只分层不分类）。
        if settle is not None:
            settle.observe(frame)          # 每帧喂一次，供停稳判据使用

        if order_mode == "legacy":
            ordered_dets = tuple(dets)
        elif order_mode == "difficulty":
            ordered_dets = order_by_difficulty_scan(frame, config)
        elif order_mode == "open_edge":
            ordered_dets = order_by_open_edge(frame, config)
        elif order_mode == "five_key":
            last_drop = None
            if last_drop_provider is not None:
                try:
                    last_drop = last_drop_provider()
                except Exception:
                    logger.warning("取上一次落料点失败：五键排序按锚点未知处理", exc_info=True)
            ordered_dets = order_by_five_key(
                frame, config, settle=settle, last_drop=last_drop)
        else:   # group（默认 = 现状口径）
            ordered_dets = order_by_group_scan(frame, config)   # 只按规则排序，不拒识
        logger.info(
            "排序分层: %s",
            " → ".join(
                "code=%d(tier=%d,pending=%s)" % (
                    d.class_id, difficulty_tier_of(d),
                    "Y" if is_pending(d) else "N")
                for d in ordered_dets
            ),
        )
        logger.info(
            "排序输出（策略序）: %s",
            " → ".join("cls=%d(dev_y=%.1f)" % (d.class_id, d.y_mm) for d in ordered_dets),
        )

        # 按**身份**回填（不再用 target_seq：它在本项目里不保证唯一，见上方修复说明）
        ordered: list[object] = [p_of[id(d)] for d in ordered_dets]
        # α：策略没排进来的件**不丢**，按原相对顺序接到队尾
        placed = {id(p) for p in ordered}
        for p in seq:
            if id(p) not in placed:
                ordered.append(p)
        if len(ordered_dets) < len(dets):
            # 这条告警就是"顺序看起来不对"的直因：件被策略判为不可用 ⇒ 被补到队尾。
            logger.warning(
                "α 补尾：%d 件**没被策略排进来**（可用性过滤判掉：托盘几何/缝隙未实测）"
                "⇒ 按原相对顺序接到队尾（不丢件，但顺序会与预期不同）",
                len(dets) - len(ordered_dets),
            )
        return tuple(ordered)

    return orderer


def payload_orderer_from_ini(
    ini_path: str | Path,
    *,
    frame_id_base: int = 0,
    order_mode: str | None = None,
    settle: "SettleTracker | None" = None,
    last_drop_provider=None,
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
        return make_payload_orderer(
            cfg, frame_id_base=frame_id_base, order_mode=order_mode,
            settle=settle, last_drop_provider=last_drop_provider,
        )
    except Exception:
        logger.warning("夹取策略：排序器构造失败 ⇒ 不启用（保持原顺序）", exc_info=True)
        return None
