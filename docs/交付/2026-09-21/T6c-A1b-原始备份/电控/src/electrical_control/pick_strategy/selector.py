"""目标选择：每轮锁定**离托盘无壁边最近**的一件物料。

规则来源（任务要求三）
----------------------
1. 优先级 = 物料到**无壁边**的距离，**不是**到夹爪当前位置的距离。
   ⚠️ 这与现有整链的排序**相反**：`socket_vision_source.py:180-213` 用
   `greedy_tsp(payloads, self._current_position, ...)` 按"离当前位置最近"排序，
   而 `_current_position` 是构造参数，`run_chain.py:1070-1076` 没有传 →
   恒为默认锚点 `(0,0)`（`socket_vision_source.py:94,105-111`，且 :110 有
   `ponytail:` 注明是固定锚点）。本模块**不修改**那条路径（改它会动到
   已实测跑通的整链）；它只提供符合新规则的选择器，由调用方决定是否接入。
2. 用**标定后的装置坐标**（mm）比较，不用像素。
3. 优先用"靠近无壁边的**轮廓**到该边的垂直距离"；现有视觉只给中心 ⇒ 见
   :func:`select_target` 的 ``mode`` 说明与 :mod:`.geometry` 的
   :func:`contour_distance_to_open_edge` 局限。
4. 距离相同时按（空爪移动距离, target_seq）定序。
5. 每轮只锁定一件。返回初始位置后重新识别（由状态机保证，见
   :mod:`.state_machine` 的 ``WAIT_FRAME``）。
6. **最近目标不可行时不得改抓更远的件**（任务要求三.7）：本模块先按距离选出
   最近的一件，再判可行；不可行就整体拒识本件并给出原因。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from electrical_control.pick_strategy.config import (
    SELECTION_CENTER,
    SELECTION_CONTOUR,
    StrategyConfig,
)
from electrical_control.pick_strategy.geometry import (
    Point,
    contour_distance_to_open_edge,
)


class RefusalCode:
    """拒识原因码（字符串常量，便于日志与测试断言）。"""

    NO_USABLE_TARGET = "NO_USABLE_TARGET"
    OUT_OF_REACH_WINDOW = "OUT_OF_REACH_WINDOW"
    GRASP_SPACE_BLOCKED = "GRASP_SPACE_BLOCKED"
    EXIT_BLOCKED = "EXIT_BLOCKED"
    STALE_FRAME = "STALE_FRAME"
    CAMERA_LOST = "CAMERA_LOST"
    TIME_SYNC_UNKNOWN = "TIME_SYNC_UNKNOWN"
    GAP_GEOMETRY_UNVERIFIED = "GAP_GEOMETRY_UNVERIFIED"


@dataclass(frozen=True)
class Refusal:
    """本件**不做**的结构化原因。"""

    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True)
class Detection:
    """一帧里的一件物料（装置坐标 mm，抓取点 = 夹爪中心，见 :mod:`.geometry`）。"""

    target_seq: int
    box_id: int | None
    class_id: int
    x_mm: float
    y_mm: float
    confidence: int = 0

    @property
    def point(self) -> Point:
        return Point(self.x_mm, self.y_mm)


@dataclass(frozen=True)
class VisionFrame:
    """一整帧识别结果。

    ``frame_id`` 必须单调递增（由帧来源负责）。线格式
    （``interface-contract.md:129-143``）**没有时间戳**，所以"旧画面"只能靠
    帧号单调性 + 本机接收时刻判定，无法判定相机端的拍摄时刻 —— 见
    :mod:`.state_machine` 的 ``age_s`` 语义说明。
    """

    frame_id: int
    received_at_s: float
    detections: tuple[Detection, ...]

    def __str__(self) -> str:
        return f"frame#{self.frame_id}({len(self.detections)}件)"


@dataclass(frozen=True)
class Selection:
    """被锁定的一件，以及它是怎么被选出来的（可复核）。"""

    detection: Detection
    distance_to_open_edge_mm: float
    empty_travel_mm: float
    candidate_count: int
    mode: str
    unverified_params: tuple[str, ...] = field(default=())

    def __str__(self) -> str:
        return (f"target_seq={self.detection.target_seq} "
                f"box_id={self.detection.box_id} {self.detection.point} "
                f"到无壁边={self.distance_to_open_edge_mm:.1f}mm")


def usable_detections(
    frame: VisionFrame, config: StrategyConfig
) -> tuple[tuple[Detection, ...], list[str]]:
    """过滤出可用于决策的件，并返回被丢弃件的原因说明。"""
    usable: list[Detection] = []
    notes: list[str] = []
    for det in frame.detections:
        if det.box_id is None:
            notes.append(
                f"target_seq={det.target_seq} 无 box_id（颜色真值缺失）→ 拒识该件"
            )
            continue
        usable.append(det)
    if config.selection_mode == SELECTION_CONTOUR:
        without_size = [d for d in usable if config.half_size_of(d.box_id) is None]
        if without_size:
            seqs = [d.target_seq for d in without_size]
            notes.append(
                f"contour 模式下这些件缺 [ObjectSize] 半尺寸：{seqs} → 拒识"
            )
            usable = [d for d in usable if config.half_size_of(d.box_id) is not None]
    return tuple(usable), notes


def _distance_to_open_edge(det: Detection, config: StrategyConfig) -> float:
    """沿无壁边法线、从物料（抓取点）到该边的距离。

    ``center`` 模式 = 中心到边的距离（**近似**：真实"轮廓到边"会更近，
    差额 = 沿法线方向的一半尺寸，最坏为物料半尺寸）。
    ``contour`` 模式 = 中心距离 − 该件的包围盒半尺寸（矩形近似真轮廓）。
    """
    if config.selection_mode == SELECTION_CONTOUR:
        half = config.half_size_of(det.box_id)
        assert half is not None  # usable_detections 已保证
        return contour_distance_to_open_edge(config.tray, det.point, half)
    return config.tray.to_open_edge_mm(det.point)


def select_target(
    frame: VisionFrame, config: StrategyConfig
) -> Selection | Refusal:
    """选出本件要抓的目标，或给出拒识原因。"""
    usable, notes = usable_detections(frame, config)
    if not usable:
        detail = "本帧没有可用件（无 box_id 或缺少实测尺寸）"
        if notes:
            detail += "；" + "；".join(notes)
        return Refusal(RefusalCode.NO_USABLE_TARGET, detail)

    # 规则三.4：距离为主键；并列时用（空爪移动距离, target_seq）。
    def sort_key(det: Detection) -> tuple[float, float, int]:
        return (
            _distance_to_open_edge(det, config),
            config.home.distance_to(det.point),
            det.target_seq,
        )

    nearest = min(usable, key=sort_key)
    distance = _distance_to_open_edge(nearest, config)

    # 规则三.7（前半）：最近件本身不可达 → 拒识本件，**不改抓更远的件**。
    if not config.object_window.contains_point(nearest.point):
        commanded = nearest.point + config.tool_offset
        return Refusal(
            RefusalCode.OUT_OF_REACH_WINDOW,
            f"最近件 target_seq={nearest.target_seq} 在 {nearest.point}，"
            f"叠加 ToolOffset={config.tool_offset} 后滑台目标 {commanded} 不在"
            f"可达域 {config.workspace} 内；物料可抓窗口 "
            f"{config.object_window}。按需求三.7 **不**改为抓更远的件",
        )

    return Selection(
        detection=nearest,
        distance_to_open_edge_mm=distance,
        empty_travel_mm=config.home.distance_to(nearest.point),
        candidate_count=len(usable),
        mode=config.selection_mode,
        unverified_params=config.unverified_params(),
    )


def ordering_key(config: StrategyConfig, det: Detection) -> tuple[float, float, int]:
    """排序键的公开形式（测试用，保证与 :func:`select_target` 同源）。"""
    return (
        _distance_to_open_edge(det, config),
        config.home.distance_to(det.point),
        det.target_seq,
    )


def order_by_open_edge(
    frame: VisionFrame, config: StrategyConfig
) -> tuple[Detection, ...]:
    """把一帧里的可用件按规则三的优先级排序（供复核/日志，不改变锁定规则）。"""
    usable, _ = usable_detections(frame, config)
    return tuple(sorted(usable, key=lambda d: ordering_key(config, d)))


def describe_selection_limitation(mode: str) -> str:
    """把当前选择模式的局限写清楚（写进日志，避免"看起来精确"的假象）。"""
    if mode == SELECTION_CONTOUR:
        return (
            "selection_mode=contour：用[ObjectSize]的轴对齐包围盒近似轮廓距离。"
            "现有视觉线格式只给中心像素、不给宽高或轮廓点，故半尺寸必须是"
            "实测值；对圆柱/三棱柱/四棱锥，矩形近似会低估或高估真实轮廓距离"
            "（误差 = 外形与轴对齐矩形之差，需按实测外形评估）"
        )
    return (
        "selection_mode=center：只有中心坐标可用 ⇒ 用的是**中心**到无壁边的"
        "距离，不是轮廓距离。它与真实轮廓距离相差'沿法线方向的一半尺寸'"
        "（对 ≤40mm 的件最坏约 20mm）。要改成真正的轮廓距离，需要视觉侧"
        "补发 bbox 宽高（或轮廓点），见交付报告§视觉接口局限"
    )


__all__ = [
    "Detection",
    "Refusal",
    "RefusalCode",
    "Selection",
    "VisionFrame",
    "describe_selection_limitation",
    "order_by_open_edge",
    "ordering_key",
    "select_target",
    "usable_detections",
]
