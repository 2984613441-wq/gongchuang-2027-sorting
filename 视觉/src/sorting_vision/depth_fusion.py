"""深度融合：用 ToF 点云消解「俯视投影相同」的形状歧义。

## 为什么需要这个模块

省赛表1 的货物名称只有 6 种（`docs/references/赛题原文-提取文本/
2026补充说明-原文.txt` L28~38 逐字）：

    正方体 / 长方体 / 圆柱 / 五棱柱 / 圆锥 / 正四面体

对**俯视**的相机来说，这 6 个形状的投影是：

| 形状 | 俯视轮廓 | 是否唯一 |
|---|---|---|
| 正方体 | 正方形 | 唯一 |
| 长方体 | 长方形 | 唯一（靠长宽比） |
| **圆柱** | **圆** | ⚠️ **与圆锥冲突** |
| 五棱柱 | 五边形 | 唯一 |
| **圆锥** | **圆** | ⚠️ **与圆柱冲突** |
| 正四面体 | 三角形 | 唯一 |

**⇒ 真正需要 ToF 的歧义只有一组：`圆柱 vs 圆锥`。**

## 怎么区分

TOFSense-M S 是 **8×8 点阵**（FOV 65°），所以它给的不是"一个高度"，
而是**一小片高度图**。圆柱和圆锥在这张图上的差别非常明显：

```
圆柱：顶面平坦 ── 落在物体上的各点距离**几乎相同**
                  ■ ■ ■
                  ■ ■ ■     ← 所有点到传感器的距离一致
                  ■ ■ ■

圆锥：锥形梯度 ── 中心点离传感器**近**，边缘点**远**
                  · ■ ·     ← 边缘远
                  ■ ■ ■     ← 中间
                  · ■ ·     ← 中心近
```

**⇒ 判据 = 落在物体上的那批点的「高度标准差 / 物体直径」：**

| 量 | 圆柱 | 圆锥 |
|---|---|---|
| `std_mm / diameter_mm`（下称 flatness） | **< 0.05** | **> 0.12** |

中间地带（0.05~0.12）→ **保持 YOLO 的答案，不强行改**，
因为此时证据不足，强行改反而可能把对的改错。

## ⚠️ 现状与限制（务必读）

1. **阈值是理论值，未经实测**。等 TOFSense-M S 到货 + 圆锥件到手后，
   需要在白托盘上实测圆柱/圆锥各 20+ 次再定。
2. **圆锥现在零训练数据** —— 所以目前的 YOLO 模型（5 类）**根本不会输出
   `"cone"`。本模块的 `disambiguate_round()` 只有在 YOLO 吐出
   `cylinder` 时才有意义（用来判"这其实是不是圆锥"）。
3. **本模块不依赖任何硬件**，纯函数，可以在主机上单测。
   ToF 驱动（`电控/firmware/.../ec_tof.c`）负责把点云变成
   `PointCloudProfile` 再喂进来。

## 历史

- 2026-10-XX 初版写的是**旧 7 类**的三组歧义
  （圆柱vs球 / 三棱柱vs正四面体 / 正方体vs四棱锥）。
- **2026-10-26 重写**：旧 7 类里 `sphere` 表1 没有、`triangular_prism`
  用户已裁决删除、`square_pyramid` 已改名为 `tetrahedron`（且俯视是三角形，
  不再与正方体歧义）⇒ **三组全部作废**，重建为表1 六类的单组歧义。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Sequence

# ─────────────────────────────────────────────────────────────────────────────
# 阈值（⚠️ 理论值，待实测标定）
# ─────────────────────────────────────────────────────────────────────────────

#: 圆柱顶面平坦 ⇒ flatness 低于此值判为圆柱
CYLINDER_FLATNESS_MAX: float = 0.05

#: 圆锥有锥形梯度 ⇒ flatness 高于此值判为圆锥
CONE_FLATNESS_MIN: float = 0.12

#: 少于这么多有效点，不下结论（点太少统计无意义）
MIN_POINTS: int = 3

#: 点云里"这个点是物体"的判定：距离比背景近多少 mm 以上
OBJECT_DEPTH_MARGIN_MM: float = 8.0


# ─────────────────────────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PointCloudProfile:
    """一次 ToF 测量中，**落在同一个物体上**的那部分点的统计。

    调用方（ToF 驱动 / 上位机）负责：
      1. 从 8×8 = 64 点里挑出属于该物体的点
         （典型做法：先用相机 bbox 反投影到 8×8 网格，或按距离聚类）
      2. 把它们的距离统计填进来

    Attributes:
        point_count: 有效点数（0~64）
        min_mm: 最近的点距离（mm）—— 对应圆锥的锥顶 / 圆柱的顶面
        max_mm: 最远的点距离（mm）—— 对应圆锥的边缘
        mean_mm: 平均距离（mm）
        std_mm: 距离标准差（mm）—— **本模块的核心判据**
        diameter_mm: 物体俯视直径（mm），用于把 std 归一化。
                     省略时按 1.0 处理（此时 flatness 退化成裸 std，
                     只在"所有物体尺寸相近"时可以这么用）。
    """

    point_count: int
    min_mm: float
    max_mm: float
    mean_mm: float
    std_mm: float
    diameter_mm: float | None = None

    def __post_init__(self) -> None:
        if self.point_count < 0:
            raise ValueError(f"point_count 不能为负，收到 {self.point_count}")
        for name in ("min_mm", "max_mm", "mean_mm", "std_mm"):
            v = getattr(self, name)
            if not math.isfinite(v):
                raise ValueError(f"{name} 必须是有限数，收到 {v!r}")
        if self.std_mm < 0.0:
            raise ValueError(f"std_mm 不能为负，收到 {self.std_mm}")
        if self.min_mm > self.max_mm:
            raise ValueError(
                f"min_mm({self.min_mm}) 不能大于 max_mm({self.max_mm})")
        if self.diameter_mm is not None and self.diameter_mm <= 0.0:
            raise ValueError(f"diameter_mm 必须为正，收到 {self.diameter_mm}")

    def flatness(self) -> float:
        """高度平坦度 = std_mm / diameter_mm。

        圆柱（平顶）→ 接近 0；圆锥（尖顶）→ 明显大于 0。
        `diameter_mm` 缺省时按 1.0，返回裸 std。
        """
        d = self.diameter_mm if self.diameter_mm is not None else 1.0
        return self.std_mm / d

    def peak_to_peak_mm(self) -> float:
        """最高点到最低点的落差（mm）。圆锥 ≈ 锥高，圆柱 ≈ 0。"""
        return self.max_mm - self.min_mm


# ─────────────────────────────────────────────────────────────────────────────
# 类型别名
# ─────────────────────────────────────────────────────────────────────────────

#: 表1 的 6 个形状名（与 names.json / YOLO 类别名保持一致）
ShapeName = Literal[
    "cube",              # 正方体
    "cuboid",            # 长方体
    "cylinder",          # 圆柱
    "pentagonal_prism",  # 五棱柱
    "cone",              # 圆锥
    "tetrahedron",       # 正四面体
]

#: 表1 里唯一需要 ToF 消歧的一组
ROUND_AMBIGUOUS_GROUP: Literal["cylinder_or_cone"] = "cylinder_or_cone"


# ─────────────────────────────────────────────────────────────────────────────
# 主逻辑
# ─────────────────────────────────────────────────────────────────────────────


def disambiguate_round(profile: PointCloudProfile) -> ShapeName | None:
    """在「圆柱 vs 圆锥」之间给出判断。

    Args:
        profile: 落在物体上的点云统计。

    Returns:
        ``"cylinder"`` —— 顶面平坦，判为圆柱
        ``"cone"``     —— 有锥形梯度，判为圆锥
        ``None``       —— 证据不足（点太少 / 落在阈值中间地带 / 参数非法），
                          **调用方应保留原有判断，不要改**

    Example:
        >>> p = PointCloudProfile(point_count=6, min_mm=250.0, max_mm=251.0,
        ...                       mean_mm=250.5, std_mm=0.4, diameter_mm=40.0)
        >>> disambiguate_round(p)      # std/dia = 0.01 ⇒ 平顶
        'cylinder'

        >>> p = PointCloudProfile(point_count=6, min_mm=245.0, max_mm=262.0,
        ...                       mean_mm=253.0, std_mm=6.5, diameter_mm=40.0)
        >>> disambiguate_round(p)      # std/dia = 0.1625 ⇒ 锥形
        'cone'
    """
    # ── 证据不足：点太少 ──────────────────────────────────────────────
    if profile.point_count < MIN_POINTS:
        return None

    flat = profile.flatness()

    # ── 圆柱：足够平坦 ────────────────────────────────────────────────
    if flat < CYLINDER_FLATNESS_MAX:
        return "cylinder"

    # ── 圆锥：梯度足够大 ──────────────────────────────────────────────
    if flat > CONE_FLATNESS_MIN:
        return "cone"

    # ── 中间地带：不下结论 ────────────────────────────────────────────
    # 理由：这个区间里圆柱（浅的锥度）和圆锥（矮胖的锥）真的分不开，
    #       强行判会 50% 概率把对的改错。保留 YOLO 答案更安全。
    return None


def requires_depth_disambiguation(shape: str) -> bool:
    """这个形状是否属于「俯视投影相同」的歧义组（即需要 ToF）。

    Args:
        shape: 形状名（YOLO 输出）。

    Returns:
        True 仅当 shape 是 ``cylinder`` 或 ``cone`` ——
        表1 六类里**只有这一组**需要 ToF。
    """
    return shape in ("cylinder", "cone")


def ambiguity_group_of(shape: str) -> str | None:
    """返回形状所属的歧义组标识，不属于任何组返回 None。"""
    return ROUND_AMBIGUOUS_GROUP if requires_depth_disambiguation(shape) else None


# ─────────────────────────────────────────────────────────────────────────────
# 从原始 8×8 点云算 profile（便于驱动侧调用）
# ─────────────────────────────────────────────────────────────────────────────


def profile_from_raw_depths(
    depths_mm: Sequence[float],
    *,
    diameter_mm: float | None = None,
    background_mm: float | None = None,
    margin_mm: float = OBJECT_DEPTH_MARGIN_MM,
) -> PointCloudProfile:
    """从原始距离数组算出 ``PointCloudProfile``。

    这是给 ToF 驱动 / 上位机用的便利函数：输入 8×8=64 个距离（mm，
    无效点用 ``float('nan')`` 或负数表示），自动挑出"属于物体"的点。

    挑点规则（`background_mm` 给定时）：
        物体点 = 距离 < background_mm - margin_mm
    即：比背景托盘更近一个 margin 以上的点，才算落在物体上。

    `background_mm` 省略时：把所有有限正数都当作物体点
    （适合"画面里只有一件物料"的场景）。

    Args:
        depths_mm: 各点距离（mm）。非有限值 / <=0 视为无效点。
        diameter_mm: 物体俯视直径（mm），用于归一化。
        background_mm: 托盘到传感器的距离（mm）。省略则不按背景筛。
        margin_mm: 判定为物体的最小近距差（mm）。

    Returns:
        统计结果。有效点不足时 ``point_count`` 会很小，
        ``disambiguate_round()`` 随后会返回 None。

    Raises:
        ValueError: `margin_mm` 为负。
    """
    if margin_mm < 0.0:
        raise ValueError(f"margin_mm 不能为负，收到 {margin_mm}")

    pts: list[float] = []
    for d in depths_mm:
        if d is None:
            continue
        try:
            v = float(d)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(v) or v <= 0.0:
            continue
        if background_mm is not None:
            if v >= (background_mm - margin_mm):
                continue
        pts.append(v)

    n = len(pts)
    if n == 0:
        return PointCloudProfile(
            point_count=0, min_mm=0.0, max_mm=0.0,
            mean_mm=0.0, std_mm=0.0, diameter_mm=diameter_mm)

    mean = sum(pts) / n
    # 样本标准差（n-1）；n==1 时记 0
    if n > 1:
        var = sum((v - mean) ** 2 for v in pts) / (n - 1)
        std = math.sqrt(var)
    else:
        std = 0.0

    return PointCloudProfile(
        point_count=n,
        min_mm=min(pts),
        max_mm=max(pts),
        mean_mm=mean,
        std_mm=std,
        diameter_mm=diameter_mm,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 自检（python -m sorting_vision.depth_fusion）
# ─────────────────────────────────────────────────────────────────────────────


def _self_test() -> int:
    """跑几个内联样例，供现场快速确认模块行为。"""
    cases: list[tuple[str, PointCloudProfile, ShapeName | None]] = [
        (
            "平顶圆柱（std/dia = 0.01）",
            PointCloudProfile(6, 250.0, 251.0, 250.5, 0.4, 40.0),
            "cylinder",
        ),
        (
            "锥形圆锥（std/dia = 0.16）",
            PointCloudProfile(6, 245.0, 262.0, 253.0, 6.5, 40.0),
            "cone",
        ),
        (
            "中间地带（std/dia = 0.08）⇒ 不下结论",
            PointCloudProfile(6, 247.0, 257.0, 252.0, 3.2, 40.0),
            None,
        ),
        (
            "点太少（2 点）⇒ 不下结论",
            PointCloudProfile(2, 250.0, 251.0, 250.5, 0.5, 40.0),
            None,
        ),
    ]
    failed = 0
    for label, prof, want in cases:
        got = disambiguate_round(prof)
        ok = got == want
        if not ok:
            failed += 1
        print(f"  {'OK ' if ok else 'FAIL'}  {label}: got={got!r} want={want!r}")
    print(f"\n  {len(cases) - failed}/{len(cases)} 通过")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(_self_test())
