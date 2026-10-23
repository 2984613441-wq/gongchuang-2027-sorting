"""MaixCAM 部署用：几何形状判定（自包含，只依赖 cv2 + numpy）。

# ⚠️ 这份是 `sorting_vision/shape_geometry.py` 的**部署副本**

## 为什么必须有两份

- `视觉/src/sorting_vision/shape_geometry.py` 跑在**树莓派/主机**上，是权威实现，有 45 个测试。
- `视觉/src/maixcam_deploy/stage1_color_v6_send.py` 跑在 **MaixCAM** 上（独立设备，
  只有 cv2 + numpy，没有 `sorting_vision` 包），所以**必须把判定逻辑就地复制一份**。
- 形状判定**必须**在 MaixCAM 上做 —— 树莓派收到的线上数据只有
  `id_byte + confidence + X + Y + angle`，**没有轮廓**，无法在 Pi 侧再判形状。

## 🔴 防止两份漂移（本项目最大的反复故障）

本项目已多次栽在"两份实现悄悄不一致"上（`ec_motion_plan_interp.c` 与
`ec_motion_plan.c` 分叉、`COLOR_TO_MATERIAL` 与 `[BoxMap]` 不一致 等）。

**对策：`视觉/tests/test_shape_geometry_parity.py` 会把本文件与
`sorting_vision/shape_geometry.py` 在同一批合成轮廓上逐一对拍。**
**任何一处阈值或分支改动没同步，那个测试立刻红。**

⇒ 改这里的任何判定逻辑，**必须同步改** `sorting_vision/shape_geometry.py`，
   反之亦然。两个文件的常量块刻意保持**逐行一致**，便于肉眼 diff。

## 判定规则（与权威版完全一致）

1. `circularity = 4πA/P² ≥ 0.93` ⇒ 圆类 ⇒ `round_ambiguous`（**不猜圆柱/圆锥**）
2. 否则按 `approxPolyDP` 顶点数：
   - 3 ⇒ 正四面体
   - 4 + `rect_fill ≥ 0.93`：`|rect_aspect-1| ≤ 0.12` ⇒ 正方体，否则长方体
     （`rect_aspect > 6` ⇒ unknown，防残片）
   - 5 ⇒ 五棱柱
   - 其他 ⇒ unknown

实测依据见权威版文件末尾的 13 行特征表。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

__all__ = [
    "ContourShape",
    "classify_contour_shape",
    "shape_priority",
    "shape_to_box",
    "SHAPE_KEYS",
    "SHAPE_PRIORITY",
    "SHAPE_TO_BOX",
    "SHAPE_CUBE",
    "SHAPE_CUBOID",
    "SHAPE_CYLINDER",
    "SHAPE_PENTAGONAL_PRISM",
    "SHAPE_CONE",
    "SHAPE_TETRAHEDRON",
    "ROUND_AMBIGUOUS",
    "UNKNOWN",
]

# ── 形状名（与赛规表1的"货物名称"逐字对齐，屏幕显示"完全一致"）──────────
SHAPE_CUBE = "正方体"
SHAPE_CUBOID = "长方体"
SHAPE_CYLINDER = "圆柱"
SHAPE_PENTAGONAL_PRISM = "五棱柱"
SHAPE_CONE = "圆锥"
SHAPE_TETRAHEDRON = "正四面体"

ROUND_AMBIGUOUS = "round_ambiguous"
UNKNOWN = "unknown"

SHAPE_KEYS = (
    SHAPE_CUBE,
    SHAPE_CUBOID,
    SHAPE_CYLINDER,
    SHAPE_PENTAGONAL_PRISM,
    SHAPE_CONE,
    SHAPE_TETRAHEDRON,
)

# ── 判别可靠性排序（用户裁决「最简单、判别最不容易出问题的在前面」）──
SHAPE_PRIORITY = {
    SHAPE_TETRAHEDRON: 1,
    SHAPE_CUBOID: 2,
    SHAPE_CUBE: 3,
    SHAPE_PENTAGONAL_PRISM: 4,
    SHAPE_CYLINDER: 5,
    SHAPE_CONE: 6,
    ROUND_AMBIGUOUS: 9,
    UNKNOWN: 10,
}

# shape → box_id（1..6）
SHAPE_TO_BOX = {
    SHAPE_TETRAHEDRON: 1,
    SHAPE_CUBOID: 2,
    SHAPE_CUBE: 3,
    SHAPE_PENTAGONAL_PRISM: 4,
    SHAPE_CYLINDER: 5,
    SHAPE_CONE: 6,
}

# ── 阈值（2026-10-23 实测标定，与权威版一致）──────────────────────────
CIRCULARITY_ROUND_MIN = 0.93
RECT_FILL_QUAD_MIN = 0.93
ASPECT_SQUARE_TOL = 0.12
RECT_ASPECT_MAX = 6.0
N_VERT_TRIANGLE = 3
N_VERT_QUAD = 4
N_VERT_PENTA = 5
APPROX_EPS_RATIO = 0.02


@dataclass(frozen=True)
class ContourShape:
    """形状判定结果（不可变）。"""

    shape: str
    confidence: str
    evidence: dict[str, Any]

    @property
    def is_decided(self) -> bool:
        return self.confidence == "certain"


def _contour_array(contour: Any) -> np.ndarray | None:
    """统一轮廓表示成 (N,1,2) int32；不可用返回 None。"""
    if contour is None:
        return None
    arr = np.asarray(contour)
    if arr.size == 0:
        return None
    if arr.ndim == 1:
        if arr.size % 2 != 0:
            return None
        arr = arr.reshape(-1, 2)
    if arr.ndim == 3 and arr.shape[1] == 1:
        arr = arr[:, 0, :]
    if arr.ndim != 2 or arr.shape[1] != 2:
        return None
    if arr.shape[0] < 3:
        return None
    return arr.astype(np.int32, copy=False)


def classify_contour_shape(contour: Any) -> ContourShape:
    """按几何特征判形状（与颜色无关）。规则见模块 docstring。"""
    arr = _contour_array(contour)
    if arr is None:
        return ContourShape(UNKNOWN, "unknown", {"reason": "bad_input"})

    area = float(cv2.contourArea(arr))
    perimeter = float(cv2.arcLength(arr, True))
    _x, _y, w, h = cv2.boundingRect(arr)

    if area <= 0.0 or perimeter <= 0.0 or w <= 0 or h <= 0:
        return ContourShape(
            UNKNOWN, "unknown",
            {"reason": "degenerate", "area": area,
             "perimeter": perimeter, "w": w, "h": h},
        )

    circularity = 4.0 * math.pi * area / (perimeter * perimeter)

    rect = cv2.minAreaRect(arr)
    (rw, rh) = rect[1]
    if rw <= 0.0 or rh <= 0.0:
        return ContourShape(
            UNKNOWN, "unknown",
            {"reason": "min_area_rect_degenerate",
             "min_rect_w": rw, "min_rect_h": rh},
        )
    rect_fill = area / (float(rw) * float(rh))
    long_side, short_side = (rw, rh) if rw >= rh else (rh, rw)
    rect_aspect = long_side / short_side

    approx = cv2.approxPolyDP(arr, APPROX_EPS_RATIO * perimeter, True)
    n_vertices = int(len(approx))

    evidence: dict[str, Any] = {
        "area": area,
        "perimeter": perimeter,
        "rect_fill": rect_fill,
        "rect_aspect": rect_aspect,
        "n_vertices": n_vertices,
        "circularity": circularity,
        "min_rect_angle_deg": float(rect[2]),
    }

    # 第 1 步：圆类（圆柱或圆锥，**不猜**）
    if circularity >= CIRCULARITY_ROUND_MIN:
        evidence["rule"] = "high_circularity_round_ambiguous"
        return ContourShape(ROUND_AMBIGUOUS, "ambiguous", evidence)

    # 第 2 步：按顶点数
    if n_vertices == N_VERT_PENTA:
        evidence["rule"] = "5_vertices_pentagonal_prism"
        return ContourShape(SHAPE_PENTAGONAL_PRISM, "certain", evidence)

    if n_vertices == N_VERT_TRIANGLE:
        evidence["rule"] = "3_vertices_tetrahedron"
        return ContourShape(SHAPE_TETRAHEDRON, "certain", evidence)

    if n_vertices == N_VERT_QUAD:
        if rect_fill < RECT_FILL_QUAD_MIN:
            evidence["rule"] = "4_vertices_but_low_rect_fill"
            return ContourShape(UNKNOWN, "unknown", evidence)
        if rect_aspect > RECT_ASPECT_MAX:
            evidence["rule"] = "4_vertices_but_extreme_aspect"
            return ContourShape(UNKNOWN, "unknown", evidence)
        if abs(rect_aspect - 1.0) <= ASPECT_SQUARE_TOL:
            evidence["rule"] = "4_vertices_rect_aspect_square"
            return ContourShape(SHAPE_CUBE, "certain", evidence)
        evidence["rule"] = "4_vertices_rect_aspect_non_square"
        return ContourShape(SHAPE_CUBOID, "certain", evidence)

    evidence["rule"] = "vertex_count_not_in_ruleset"
    return ContourShape(UNKNOWN, "unknown", evidence)


def shape_priority(shape: str) -> int:
    """判别可靠性顺位：越小越可靠 ⇒ 越早处理。"""
    return SHAPE_PRIORITY.get(shape, 10)


def shape_to_box(shape: str) -> int | None:
    """形状 → 盒号；歧义/未知返回 None（**禁止分箱**，防混装计 0 分）。"""
    return SHAPE_TO_BOX.get(shape)
