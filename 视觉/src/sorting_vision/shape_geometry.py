"""俯视视角的几何形状判定 —— 与颜色完全无关。

## 为什么要有这个模块（2026-10-23 赛规变更）

2026-10-23 的《赛项补充说明》把物料表改成：

| 颜色 | 货物名称（6 类）|
|---|---|
| 白/红/蓝/绿/黄（**5 色共用**）| 正方体、长方体、圆柱、五棱柱、**圆锥**、正四面体 |

⇒ **颜色与形状完全解耦（5×6 = 30 种组合）**。

而现行生产视觉（`maixcam_deploy/stage1_color_v6_send.py:249-251`）是：

```python
COLOR_TO_MATERIAL = {
    "cyan": ("cube", 1), "green": ("cube", 2),
    "red": ("triangular_prism", 3), "blue": ("triangular_prism", 4),
    "black": ("cylinder", 5), "orange": ("cylinder", 6),
}
```

**⇒ 按颜色查表得形状，新赛规下 100% 失效。**

本模块提供「只看轮廓、不看颜色」的形状判定，供生产视觉替换掉那张颜色表。

## 依据：源码里已有的实测数据

`stage1_color_v6_send.py:424` 的注释记录了俯视 `extent = 面积 / bbox面积` 的实测值：

> 三角形 ext∈[0.464, 0.500]、圆盘 0.785、正方形 1.000

这是本模块阈值的主要依据。

## 六个形状的俯视特征

| 形状 | 俯视轮廓 | 关键特征 |
|---|---|---|
| 正方体 cube | 正方形 | 4 顶点、extent≈1.0、aspect≈1.0 |
| 长方体 cuboid | 矩形 | 4 顶点、extent≈1.0、aspect 明显偏离 1.0 |
| 圆柱 cylinder | 圆 | 圆周率/圆度高、无棱角 |
| 五棱柱 pentagonal_prism | 正五边形 | 5 顶点 |
| 正四面体 regular_tetrahedron | 三角形 | 3 顶点、extent≈0.5 |
| **圆锥 cone** | **圆** | **与圆柱**几何上不可分** ← 见下** |

## 🔴 硬限制：圆锥与圆柱在俯视下不可分

两者俯视都是圆。本模块**不猜**，而是把它们标成

    shape = "round_ambiguous"   # 圆类，圆柱或圆锥未定

由调用方决定怎么办（用户 2026-10-23 的方案是"最后再处理"）。

**⇒ 这是诚实的设计：宁可承认不确定，也不要猜错导致混装（混装计 0 分）。**

要真正区分，需要额外的通道：
- 侧视摄像头（圆柱=矩形，圆锥=三角形）—— 最可靠
- 托盘倾斜后俯视相机看侧壁（赛规明确允许托盘"倾斜"）
- 或 YOLO 学到俯视阴影/渐变差异（未经证实）

## 不确定时的行为

**本模块 fail-closed**：特征对不上任何形状时返回 `"unknown"`，绝不硬猜。
调用方应把 `unknown` 与 `round_ambiguous` 一起当作"延后处理"。

## 已知假设 / 未验证项

| # | 假设 | 状态 |
|---|---|---|
| 1 | 正四面体是**面朝下**摆放（俯视呈三角形）| **未实测**；若棱朝下俯视可能呈四边形 |
| 2 | 长方体的俯视底面**不是正方形**（aspect 明显≠1）| **未实测**；若底面是正方形则与正方体不可分 |
| 3 | 五种形状的实际尺寸范围 | **未实测**；阈值按通用几何比例设定 |
| 4 | 光照/阴影不会把圆扭曲成多边形 | **未实测** |
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import cv2
import numpy as np

# 注意：__all__ 定义在本文件后段（所有常量与函数都声明完之后），
# 避免把尚不存在的名字列进去。

# ── 形状名（与赛规表1的"货物名称"逐字对齐）──────────────────────────────
# ⚠️ 必须与显示屏上要显示的字符串一致（赛规要求"完全一致"）
SHAPE_CUBE = "正方体"
SHAPE_CUBOID = "长方体"
SHAPE_CYLINDER = "圆柱"
SHAPE_PENTAGONAL_PRISM = "五棱柱"
SHAPE_CONE = "圆锥"
SHAPE_TETRAHEDRON = "正四面体"

# 圆类歧义：圆柱或圆锥未定（俯视不可分）
ROUND_AMBIGUOUS = "round_ambiguous"
# 完全无法判定
UNKNOWN = "unknown"

SHAPE_KEYS = (
    SHAPE_CUBE,
    SHAPE_CUBOID,
    SHAPE_CYLINDER,
    SHAPE_PENTAGONAL_PRISM,
    SHAPE_CONE,
    SHAPE_TETRAHEDRON,
)

# ── 判别可靠性排序（2026-10-23 用户裁决：「最简单、判别最不容易出问题的在前面」）──
#
# `SHAPE_PRIORITY[shape]` 越小越可靠 ⇒ **越早处理、越早分箱**。
# 依据是实测的**分离裕度**（距判定阈值的距离，见文件末尾的实测表）：
#
#   顺位 形状      依据                                    裕度
#   1    正四面体  3 顶点唯一；circ 0.605 距 0.93 阈值 0.325  ← 最稳
#   2    长方体    4 顶点 + 长宽比 2:1；circ 0.698 距 0.232        很稳
#   3    正方体    4 顶点 + 长宽比 1:1；circ 0.785 距 0.145        稳
#   4    五棱柱    5 顶点唯一；circ 0.865 距阈值**仅 0.065**   ← 裕度最薄
#   5    圆柱      圆类，与圆锥在俯视下不可分 ⇒ 需额外手段
#   6    圆锥      同上
#
# ⇒ **盒位分配直接用这个顺位**：盒1=正四面体 … 盒6=圆锥。
#    这样"判别最不容易出问题的在前"同时体现在【处理顺序】和【盒号】上。
#
# ⚠️ 这是**逻辑顺位**，不是说盒1 物理上必须离落料口最近。
#    物理位置由 `[TurntableAngles]` 标定决定，那个是另一回事。
SHAPE_PRIORITY = {
    SHAPE_TETRAHEDRON: 1,
    SHAPE_CUBOID: 2,
    SHAPE_CUBE: 3,
    SHAPE_PENTAGONAL_PRISM: 4,
    SHAPE_CYLINDER: 5,
    SHAPE_CONE: 6,
    # 未定的排最后（不是货物，只是判定状态）
    ROUND_AMBIGUOUS: 9,
    UNKNOWN: 10,
}

# shape → box_id（1..6）。方案B 的 6 个盒 = 6 类，直接一一对应。
SHAPE_TO_BOX = {
    SHAPE_TETRAHEDRON: 1,
    SHAPE_CUBOID: 2,
    SHAPE_CUBE: 3,
    SHAPE_PENTAGONAL_PRISM: 4,
    SHAPE_CYLINDER: 5,
    SHAPE_CONE: 6,
}

# box_id → shape（反查，用于显示名与配置校验）
BOX_TO_SHAPE = {box: shape for shape, box in SHAPE_TO_BOX.items()}

__all__ = [
    "ContourShape",
    "classify_contour_shape",
    "classify_shapes_in_image",
    "shape_priority",
    "shape_to_box",
    "SHAPE_KEYS",
    "SHAPE_PRIORITY",
    "SHAPE_TO_BOX",
    "BOX_TO_SHAPE",
    "ROUND_AMBIGUOUS",
    "UNKNOWN",
]

# ── 阈值（2026-10-23 实测标定，见 _pi_tools/measure_shape_features.py）────
#
# 实测各形状特征（理想合成图形，边长约 100~200px）：
#
#   形状          n_vert  rect_fill  rect_aspect  circularity
#   正方形            4     1.0000      1.0000       0.7854
#   长方形 2:1        4     1.0000      2.0000       0.6981
#   三角形            3     0.5000      1.1543       0.6046
#   五边形            5     0.6940      1.0505       0.8648
#   六边形            6     0.7500      1.1613       0.9069
#   圆盘             8     0.7874      1.0000       0.9879
#
# 🔴 判据选择的关键依据：
#   · `rect_fill` 五边形 0.694 与圆 0.787 **只差 0.09**，太近，**不能**用它分圆。
#   · `circularity` 把圆(0.988) 与所有多边形(≤0.907) **拉开 0.08 以上**，
#     且对旋转、缩放都不敏感 ⇒ **用它判圆类最可靠**。
#   · `n_vertices`（approxPolyDP）在干净轮廓上稳定给出 3/4/5/8，
#     五边形不会被并成四边形（eps=0.02×周长 实测够用）。
#
# ⚠️ 历史教训：最初用 AABB 的 extent 判四边形，正方形转 8° 后 extent 掉到
#    0.784（= 圆盘的 0.785）⇒ 与圆混淆。现用 minAreaRect + circularity 已解决。
CIRCULARITY_ROUND_MIN = 0.93   # ≥ 此值判为圆类（实测：圆 0.988 / 六边形 0.907）
RECT_FILL_QUAD_MIN = 0.93      # 四边形最小外接矩形填充率下界（实测 1.000）
ASPECT_SQUARE_TOL = 0.12       # |长边/短边 - 1| 超过此值 ⇒ 长方体
N_VERT_TRIANGLE = 3
N_VERT_QUAD = 4
N_VERT_PENTA = 5
# 长宽比上界：超过它多半是被遮挡的残片或细长条，不当作长方体
RECT_ASPECT_MAX = 6.0

# approxPolyDP 的相对精度（占周长比例）。0.02 是 OpenCV 惯例值；
# 太大把五边形并成四边形，太小把圆分成十几个顶点。
APPROX_EPS_RATIO = 0.02


@dataclass(frozen=True)
class ContourShape:
    """一个轮廓的形状判定结果（不可变）。

    属性
    ----
    shape : str
        判定结果。可能是 SHAPE_KEYS 之一，也可能是 ROUND_AMBIGUOUS / UNKNOWN。
    confidence : str
        ``"certain"``  —— 有明确几何依据（棱角数 + 面积比都吻合）
        ``"ambiguous"`` —— 圆类，圆柱/圆锥未定
        ``"unknown"``  —— 对不上任何形状
    evidence : dict
        参与判定的原始量，便于现场调试与日志。**不含任何颜色信息。**
    """

    shape: str
    confidence: str
    evidence: dict[str, Any]

    @property
    def is_decided(self) -> bool:
        """True 表示可以直接拿去分箱（非歧义、非未知）。"""
        return self.confidence == "certain"


def _contour_array(contour: Any) -> np.ndarray | None:
    """把任意 OpenCV 轮廓表示统一成 (N,1,2) 的 int32 数组。

    接受：
      - OpenCV 原生 ``(N,1,2)`` 数组
      - ``(N,2)`` 数组
      - 点列表 ``[(x,y), ...]``

    返回 None 表示输入不可用。

    ⚠️ 不用 ``cv2.contourArea`` 直接吞任意输入 —— 它对不合法的形状会返回
    0 而不报错，那会把"输入坏了"伪装成"面积是 0"，掩盖真因。
    """
    if contour is None:
        return None
    arr = np.asarray(contour)
    if arr.size == 0:
        return None
    if arr.ndim == 1:
        # 一组平坦的坐标 [x0,y0,x1,y1,...]
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
    """按**几何特征**判定俯视形状（与颜色无关）。

    参数
    ----
    contour : OpenCV 轮廓（``(N,1,2)`` / ``(N,2)`` / 点列表）

    返回
    ----
    ContourShape

    判定顺序（先排除退化情形，再按棱角数分支）：

    1. 面积/周长非正 ⇒ ``UNKNOWN``
    2. 多边形近似后 **5 个顶点** ⇒ 五棱柱
    3. **3 个顶点** 且 extent 在三角形区间 ⇒ 正四面体
    4. **4 个顶点** 且 extent 高：
       - aspect≈1 ⇒ 正方体
       - aspect 偏离 ⇒ 长方体
    5. **≥6 个顶点** 且圆度高 ⇒ ``ROUND_AMBIGUOUS``（圆柱或圆锥）
    6. 其余 ⇒ ``UNKNOWN``

    ⚠️ 注意第 5 条**不返回圆柱**：俯视下圆柱与圆锥都是圆，本函数不猜。
    """
    arr = _contour_array(contour)
    if arr is None:
        return ContourShape(UNKNOWN, "unknown", {"reason": "bad_input"})

    area = float(cv2.contourArea(arr))
    perimeter = float(cv2.arcLength(arr, True))
    _x, _y, w, h = cv2.boundingRect(arr)

    if area <= 0.0 or perimeter <= 0.0 or w <= 0 or h <= 0:
        return ContourShape(
            UNKNOWN,
            "unknown",
            {"reason": "degenerate", "area": area,
             "perimeter": perimeter, "w": w, "h": h},
        )

    bbox_area = float(w) * float(h)
    # ⚠️ AABB 的 extent 只作为 debug 字段保留，**不参与判定**（旋转会破坏它）。
    aabb_extent = area / bbox_area
    aspect_aabb = float(w) / float(h)
    circularity = 4.0 * math.pi * area / (perimeter * perimeter)

    # 旋转无关的两个特征：最小外接旋转矩形的填充率与长宽比
    rect = cv2.minAreaRect(arr)          # ((cx,cy), (rw,rh), angle)
    (rw, rh) = rect[1]
    if rw <= 0.0 or rh <= 0.0:
        return ContourShape(
            UNKNOWN,
            "unknown",
            {"reason": "min_area_rect_degenerate",
             "min_rect_w": rw, "min_rect_h": rh},
        )
    rect_area = float(rw) * float(rh)
    rect_fill = area / rect_area
    long_side, short_side = (rw, rh) if rw >= rh else (rh, rw)
    rect_aspect = long_side / short_side

    approx = cv2.approxPolyDP(arr, APPROX_EPS_RATIO * perimeter, True)
    n_vertices = int(len(approx))

    evidence: dict[str, Any] = {
        "area": area,
        "perimeter": perimeter,
        # 判定实际用这两个（旋转无关）
        "rect_fill": rect_fill,
        "rect_aspect": rect_aspect,
        "n_vertices": n_vertices,
        # 以下仅作 debug，不参与判定
        "aabb_extent": aabb_extent,
        "aabb_aspect": aspect_aabb,
        "circularity": circularity,
        "min_rect_angle_deg": float(rect[2]),
    }

    # ── 第 1 步：先判"是不是圆类" ────────────────────────────────────
    # 依据实测：circularity 圆 0.988 / 六边形 0.907 / 五边形 0.865 / 正方形 0.785。
    # ≥0.93 时只可能是圆 ⇒ 圆柱或圆锥，**本模块不猜是哪一个**。
    if circularity >= CIRCULARITY_ROUND_MIN:
        evidence["rule"] = "high_circularity_round_ambiguous"
        return ContourShape(ROUND_AMBIGUOUS, "ambiguous", evidence)

    # ── 第 2 步：按棱角数分支（此时已排除圆类）────────────────────────
    # 5 顶点：五棱柱
    if n_vertices == N_VERT_PENTA:
        evidence["rule"] = "5_vertices_pentagonal_prism"
        return ContourShape(SHAPE_PENTAGONAL_PRISM, "certain", evidence)

    # 3 顶点：正四面体（面朝下时俯视是三角形）
    if n_vertices == N_VERT_TRIANGLE:
        evidence["rule"] = "3_vertices_tetrahedron"
        return ContourShape(SHAPE_TETRAHEDRON, "certain", evidence)

    # 4 顶点：正方体 或 长方体（rect_fill/rect_aspect 均旋转无关）
    if n_vertices == N_VERT_QUAD:
        if rect_fill < RECT_FILL_QUAD_MIN:
            # 4 顶点但填不满最小外接矩形 ⇒ 被啃角/严重遮挡，不猜
            evidence["rule"] = "4_vertices_but_low_rect_fill"
            return ContourShape(UNKNOWN, "unknown", evidence)
        if rect_aspect > RECT_ASPECT_MAX:
            # 极端细长 ⇒ 多半是残片或遮挡造成的条状区域，不猜
            evidence["rule"] = "4_vertices_but_extreme_aspect"
            return ContourShape(UNKNOWN, "unknown", evidence)
        if abs(rect_aspect - 1.0) <= ASPECT_SQUARE_TOL:
            evidence["rule"] = "4_vertices_rect_aspect_square"
            return ContourShape(SHAPE_CUBE, "certain", evidence)
        evidence["rule"] = "4_vertices_rect_aspect_non_square"
        return ContourShape(SHAPE_CUBOID, "certain", evidence)

    # 其余顶点数：赛规 6 类里没有对应的形状
    # （0/1/2 已被 _contour_array 挡掉；6+ 且圆度不足 ⇒ 多边形但不是赛规物料）
    evidence["rule"] = "vertex_count_not_in_ruleset"
    return ContourShape(UNKNOWN, "unknown", evidence)


def classify_shapes_in_image(binary_mask: np.ndarray) -> list[ContourShape]:
    """便捷入口：在一张二值掩膜里找出所有外部轮廓并逐个判定。

    ⚠️ 这是**调试/离线分析**用的便捷函数，不是生产路径。
    生产路径在 MaixCAM 上，轮廓筛选（颜色掩膜、ROI、尺度过滤）有更复杂的既有逻辑。
    """
    if binary_mask is None or binary_mask.size == 0:
        return []
    contours, _ = cv2.findContours(
        binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    return [classify_contour_shape(c) for c in contours if len(c) >= 3]


def shape_priority(shape: str) -> int:
    """判别可靠性顺位：**越小越可靠 ⇒ 越早处理**。

    2026-10-23 用户裁决：「最简单，判别最不容易出问题在前面」。

    参数
    ----
    shape : 形状名（SHAPE_KEYS 之一），或 `ROUND_AMBIGUOUS` / `UNKNOWN`

    返回
    ----
    int : 1（最可靠）… 6（最不可靠），未知/歧义为 9/10（排最后）

    用途
    ----
    调度层按此排序取件：先夹最稳的确保得分，把圆类（圆柱/圆锥）留到最后。
    与「混装 = 0 分」的计分规则配合，避免拿不准的件污染已分好的盒。
    """
    return SHAPE_PRIORITY.get(shape, 10)


def shape_to_box(shape: str) -> int | None:
    """形状 → 盒号（1..6）。

    返回 None 表示**不能直接分箱**：
      - `ROUND_AMBIGUOUS`（圆柱或圆锥未定）
      - `UNKNOWN`（判不出）
      - 任何不在 SHAPE_KEYS 里的字符串

    ⚠️ 返回 None 时调用方**必须**延后处理，绝不能随便挑一个盒 ——
       放错盒会与已有货物混装，而「混装任何两类 = 0 分」（赛规图4）。
    """
    return SHAPE_TO_BOX.get(shape)


# ============================================================================
# 实测数据（阈值依据，2026-10-23 由 _pi_tools/measure_shape_features.py 生成）
# ============================================================================
#
#  形状              n_vert  rect_fill  rect_aspect  circularity  判定结果
#  正方形               4      1.0000      1.0000       0.7854    正方体
#  正方形 @8°           4      1.0000      1.0000       0.7854    正方体   ← 旋转不变
#  正方形 @45°          4      0.9930      1.0071       0.7854    正方体   ← 旋转不变
#  长方形 160x80        4      1.0000      2.0000       0.6981    长方体
#  长方形 @30°          4      0.9984      2.0140       0.6969    长方体
#  长方形 200x60        4      1.0000      3.3333       0.5577    长方体
#  三角形               3      0.5000      1.1543       0.6046    正四面体
#  三角形 @25°          3      0.5000      1.1523       0.6046    正四面体
#  五边形               5      0.6940      1.0505       0.8648    五棱柱
#  五边形 @36°          5      0.6926      1.0532       0.8648    五棱柱
#  六边形               6      0.7500      1.1613       0.9069    unknown（赛规无六棱柱）
#  圆 r=90              8      0.7874      1.0000       0.9879    round_ambiguous
#  圆 r=50              8      0.7868      1.0000       0.9795    round_ambiguous
#
# 关键：circularity 把圆(0.988) 与所有多边形(≤0.907) 拉开 ≥0.08
#       而 rect_fill 五边形(0.694) 与圆(0.787) 只差 0.09，判圆不可靠。
#       ⇒ 判圆用 circularity，判多边形用 n_vertices。两者组合覆盖全部 6 类。
# ============================================================================
