"""夹取策略的几何原语（纯函数，无 IO、无硬件、不读配置）。

坐标系
------
全部使用**装置坐标 mm**：原点 = 装置中心（`interface-contract.md:163`）。
两个不同的点要分清：

* **抓取点坐标系（"夹爪系"）** —— 本模块与 :mod:`.planner` 里的一切几何都在这里做。
  一个物料的"位置"就是它的抓取点；夹爪中心与该点重合（这正是 tool_offset 的定义）。
* **滑台记账坐标** —— 固件实际下发的坐标。二者差一个 ``tool_offset``：
  下发目标 = 物料坐标 + tool_offset（`pixel_to_device.py:468-470`）。
  转换只发生在 :meth:`StrategyConfig` 使用方一处（``planner.to_commands``），
  避免"同一个物理量有两处口径"。

不做什么
--------
* 不生成任何 Z 轴动作、舵机脉宽、GPIO、串口字节。
* 不做"像素 → mm"换算（那属于 :mod:`electrical_control.rpi.pixel_to_device`）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# 无壁边（托盘没有围壁的那一条边）在装置坐标里的表示。
OPEN_SIDE_X_MIN = "x_min"
OPEN_SIDE_X_MAX = "x_max"
OPEN_SIDE_Y_MIN = "y_min"
OPEN_SIDE_Y_MAX = "y_max"
OPEN_SIDES = (OPEN_SIDE_X_MIN, OPEN_SIDE_X_MAX, OPEN_SIDE_Y_MIN, OPEN_SIDE_Y_MAX)


class GeometryError(Exception):
    """几何前置条件不满足（不构成"计划不可行"，只说明参数自相矛盾）。"""


@dataclass(frozen=True)
class Point:
    x_mm: float
    y_mm: float

    def __add__(self, other: "Point") -> "Point":
        return Point(self.x_mm + other.x_mm, self.y_mm + other.y_mm)

    def __sub__(self, other: "Point") -> "Point":
        return Point(self.x_mm - other.x_mm, self.y_mm - other.y_mm)

    def __str__(self) -> str:
        return f"({self.x_mm:.1f},{self.y_mm:.1f})"

    def distance_to(self, other: "Point") -> float:
        return math.hypot(self.x_mm - other.x_mm, self.y_mm - other.y_mm)


@dataclass(frozen=True)
class Rect:
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    @property
    def center(self) -> Point:
        return Point((self.x_min + self.x_max) / 2.0,
                     (self.y_min + self.y_max) / 2.0)

    @property
    def half(self) -> Point:
        return Point((self.x_max - self.x_min) / 2.0,
                     (self.y_max - self.y_min) / 2.0)

    def inflate(self, dx: float, dy: float | None = None) -> "Rect":
        dy = dx if dy is None else dy
        return Rect(self.x_min - dx, self.x_max + dx, self.y_min - dy, self.y_max + dy)

    def contains_point(self, p: Point) -> bool:
        return (self.x_min <= p.x_mm <= self.x_max
                and self.y_min <= p.y_mm <= self.y_max)

    def contains_rect(self, other: "Rect") -> bool:
        return (self.x_min <= other.x_min and other.x_max <= self.x_max
                and self.y_min <= other.y_min and other.y_max <= self.y_max)

    def intersects_rect(self, other: "Rect") -> bool:
        return not (other.x_max <= self.x_min or other.x_min >= self.x_max
                    or other.y_max <= self.y_min or other.y_min >= self.y_max)

    def __str__(self) -> str:
        return (f"[x {self.x_min:.1f}..{self.x_max:.1f}, "
                f"y {self.y_min:.1f}..{self.y_max:.1f}]")


@dataclass(frozen=True)
class Segment:
    start: Point
    end: Point

    def __str__(self) -> str:
        return f"{self.start}->{self.end}"

    @property
    def length_mm(self) -> float:
        return self.start.distance_to(self.end)

    def swept_rect(self, half_perp_mm: float) -> Rect:
        """以本段为轴、横向半宽 ``half_perp_mm`` 的扫掠矩形（轴对齐）。

        只对**轴向段**（纯 X 或纯 Y）有意义 —— 本项目所有携带物料的搬运都
        沿无壁边法线或平行于托盘边，故不实现任意角度扫掠（YAGNI）。
        """
        if abs(self.start.y_mm - self.end.y_mm) < 1e-9:
            return Rect(min(self.start.x_mm, self.end.x_mm),
                        max(self.start.x_mm, self.end.x_mm),
                        self.start.y_mm - half_perp_mm,
                        self.start.y_mm + half_perp_mm)
        if abs(self.start.x_mm - self.end.x_mm) < 1e-9:
            return Rect(self.start.x_mm - half_perp_mm,
                        self.start.x_mm + half_perp_mm,
                        min(self.start.y_mm, self.end.y_mm),
                        max(self.start.y_mm, self.end.y_mm))
        # 斜段：退化为包围盒（保守 —— 只会多拦、不会漏拦）
        return Rect(min(self.start.x_mm, self.end.x_mm),
                    max(self.start.x_mm, self.end.x_mm),
                    min(self.start.y_mm, self.end.y_mm),
                    max(self.start.y_mm, self.end.y_mm))


@dataclass(frozen=True)
class Tray:
    """托盘几何。

    ``rect`` = **托盘内域**（可放物料的范围），不含围壁厚度。
    ``open_side`` = 没有围壁的那一条边；携带物料的退出必须穿过它。
    ``gap_known`` = 中间缝隙的实测几何是否已配置（见 :attr:`require_gap_geometry`）。
    ``row_tolerance_mm`` = "算同一排"的 Y 容差（mm），供
    :func:`~electrical_control.pick_strategy.selector.order_by_row_scan` 分桶用。
    默认 ``0.0`` **不是容差取值**，而是"关闭分桶"（= 只认 Y 完全相等的旧行为）：
    仅用于不经 ini 的直接构造（几何单测）；实机路径一律由
    ``build_config`` 从 ``[Tray] row_tolerance_mm`` 读取，缺键即 ``ConfigError``，
    **没有内置容差默认值**。
    """

    rect: Rect
    open_side: str
    gap_known: bool
    require_gap_geometry: bool
    row_tolerance_mm: float = 0.0

    def outward_normal(self) -> Point:
        """从托盘内部指向外部的单位法线（只沿一条轴，故分量是 0/±1）。"""
        return {
            OPEN_SIDE_X_MIN: Point(-1.0, 0.0),
            OPEN_SIDE_X_MAX: Point(1.0, 0.0),
            OPEN_SIDE_Y_MIN: Point(0.0, -1.0),
            OPEN_SIDE_Y_MAX: Point(0.0, 1.0),
        }[self.open_side]

    def open_edge_coordinate(self) -> float:
        return {
            OPEN_SIDE_X_MIN: self.rect.x_min,
            OPEN_SIDE_X_MAX: self.rect.x_max,
            OPEN_SIDE_Y_MIN: self.rect.y_min,
            OPEN_SIDE_Y_MAX: self.rect.y_max,
        }[self.open_side]

    def normal_axis(self) -> str:
        return "x" if self.open_side in (OPEN_SIDE_X_MIN, OPEN_SIDE_X_MAX) else "y"

    def to_open_edge_mm(self, p: Point) -> float:
        """点（抓取点 = 夹爪中心）沿法线到无壁边的**有符号**距离。

        在托盘内为正、在托盘外为负。这是"目标选择规则"用的量
        （任务要求三.1/三.3）。
        """
        edge = self.open_edge_coordinate()
        coordinate = p.x_mm if self.normal_axis() == "x" else p.y_mm
        if self.open_side in (OPEN_SIDE_X_MIN, OPEN_SIDE_Y_MIN):
            return coordinate - edge
        return edge - coordinate

    def is_inside(self, p: Point) -> bool:
        return self.rect.contains_point(p)

    def walled_sides(self) -> tuple[str, ...]:
        """除无壁边之外的其它三边（这三边有围壁，不可越过）。"""
        return tuple(s for s in OPEN_SIDES if s != self.open_side)

    def wall_violations(self, rect: Rect) -> tuple[str, ...]:
        """矩形越过**围壁**的那几条边；未越界返回空元组。

        ⚠️ 无壁边**不参与**判定：夹爪/物料伸出托盘开口是允许的（那正是出口），
        而"夹爪必须完全落在托盘内域"会把"离开口最近的那件"永远判死
        —— 因为按定义它就贴着开口。这是本项目容易写错的一处。
        """
        bad: list[str] = []
        if OPEN_SIDE_X_MIN in self.walled_sides() and rect.x_min < self.rect.x_min:
            bad.append(OPEN_SIDE_X_MIN)
        if OPEN_SIDE_X_MAX in self.walled_sides() and rect.x_max > self.rect.x_max:
            bad.append(OPEN_SIDE_X_MAX)
        if OPEN_SIDE_Y_MIN in self.walled_sides() and rect.y_min < self.rect.y_min:
            bad.append(OPEN_SIDE_Y_MIN)
        if OPEN_SIDE_Y_MAX in self.walled_sides() and rect.y_max > self.rect.y_max:
            bad.append(OPEN_SIDE_Y_MAX)
        return tuple(bad)


def contour_distance_to_open_edge(tray: Tray, center: Point, half: Point) -> float:
    """用**矩形包围盒**近似"靠近无壁边的轮廓到该边的垂直距离"。

    ⚠️ 这是近似，不是真轮廓距离：真正的实现需要视觉侧给出多边形/轮廓点。
    现有线格式（``BATCH_TARGETS`` 每目标 7 字节）**只有中心像素**，
    连宽高都没有（``interface-contract.md:137-143``），所以：
      * ``half`` 必须由人**实测填入** ``[ObjectSize]``，程序不虚构；
      * 近似误差 = 物料实际外形与轴对齐矩形之差（立方体≈0，圆柱/三棱柱/四棱锥>0）。
    """
    return tray.to_open_edge_mm(center) - (half.x_mm if tray.normal_axis() == "x"
                                           else half.y_mm)


# ---------------------------------------------------------------------------
# 线段 / 矩形求交（用于"退出必须穿过无壁边"与"不能跨越围壁"）
# ---------------------------------------------------------------------------
def segment_crosses_side(seg: Segment, trap: Tray) -> str | None:
    """线段穿出托盘内域时穿过的是哪一条边；未穿出返回 None。

    用于判定携带物料的退出方向是否合法：必须等于 ``trap.open_side``。
    """
    r = trap.rect
    if r.contains_point(seg.start) and r.contains_point(seg.end):
        return None
    t = _clip_param(seg, r)
    if t is None:
        return None
    # 用穿出点所在的那条边判定（取两条候选边里更贴近的一方）
    exit_pt = Point(seg.start.x_mm + (seg.end.x_mm - seg.start.x_mm) * t[1],
                    seg.start.y_mm + (seg.end.y_mm - seg.start.y_mm) * t[1])
    hits = []
    if abs(exit_pt.x_mm - r.x_min) < 1e-6:
        hits.append(OPEN_SIDE_X_MIN)
    if abs(exit_pt.x_mm - r.x_max) < 1e-6:
        hits.append(OPEN_SIDE_X_MAX)
    if abs(exit_pt.y_mm - r.y_min) < 1e-6:
        hits.append(OPEN_SIDE_Y_MIN)
    if abs(exit_pt.y_mm - r.y_max) < 1e-6:
        hits.append(OPEN_SIDE_Y_MAX)
    if not hits:
        return None
    # 起点就在无壁边外侧（例如从托盘外开始）时可能同时贴两条边，
    # 取"沿运动方向先撞上的那条" —— 用点的归属更稳：取与出射点最近的边。
    if len(hits) == 1:
        return hits[0]
    entry_pt = Point(seg.start.x_mm + (seg.end.x_mm - seg.start.x_mm) * t[0],
                     seg.start.y_mm + (seg.end.y_mm - seg.start.y_mm) * t[0])
    return min(
        hits,
        key=lambda side: _edge_point(r, side).distance_to(entry_pt),
    )


def _edge_point(r: Rect, side: str) -> Point:
    if side == OPEN_SIDE_X_MIN:
        return Point(r.x_min, r.center.y_mm)
    if side == OPEN_SIDE_X_MAX:
        return Point(r.x_max, r.center.y_mm)
    if side == OPEN_SIDE_Y_MIN:
        return Point(r.center.x_mm, r.y_min)
    return Point(r.center.x_mm, r.y_max)


def _clip_param(seg: Segment, rect: Rect) -> tuple[float, float] | None:
    """Liang–Barsky：返回线段与矩形相交的参数区间 [t0, t1]；不相交返回 None。"""
    dx = seg.end.x_mm - seg.start.x_mm
    dy = seg.end.y_mm - seg.start.y_mm
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, seg.start.x_mm - rect.x_min),
                 (dx, rect.x_max - seg.start.x_mm),
                 (-dy, seg.start.y_mm - rect.y_min),
                 (dy, rect.y_max - seg.start.y_mm)):
        if abs(p) < 1e-12:
            if q < 0.0:
                return None
            continue
        t = q / p
        if p < 0.0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    return (t0, t1)


def segment_intersects_rect(seg: Segment, rect: Rect) -> bool:
    return _clip_param(seg, rect) is not None


__all__ = [
    "GeometryError",
    "OPEN_SIDES",
    "OPEN_SIDE_X_MIN",
    "OPEN_SIDE_X_MAX",
    "OPEN_SIDE_Y_MIN",
    "OPEN_SIDE_Y_MAX",
    "Point",
    "Rect",
    "Segment",
    "Tray",
    "contour_distance_to_open_edge",
    "segment_crosses_side",
    "segment_intersects_rect",
]
