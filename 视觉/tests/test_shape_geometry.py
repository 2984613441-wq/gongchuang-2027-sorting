"""`sorting_vision.shape_geometry` 的主机测试。

设计原则：
1. **合成图形先验**：先用几何上无歧义的理想图形验证判定规则本身，
   再用带噪声/旋转的情形验证鲁棒性。
2. **钉住"不猜"的行为**：圆必须返回 `round_ambiguous`，**绝不能返回圆柱**。
   这是本模块最重要的安全属性 —— 猜成圆柱会把圆锥装进圆柱盒，混装计 0 分。
3. **钉住 fail-closed**：对不上的情形必须 `unknown`，不得硬猜。
4. 不依赖任何颜色、光照或真实照片 ⇒ 纯合成，可重复。

运行：
    python -m pytest 视觉/tests/test_shape_geometry.py -q
或：
    python 视觉/tests/test_shape_geometry.py
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

_THIS = Path(__file__).resolve()
# 测试文件在 视觉/tests/ 下，源码在 视觉/src/
_SRC = _THIS.parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sorting_vision.shape_geometry import (  # noqa: E402
    ROUND_AMBIGUOUS,
    SHAPE_CONE,
    SHAPE_CUBE,
    SHAPE_CUBOID,
    SHAPE_CYLINDER,
    SHAPE_KEYS,
    SHAPE_PENTAGONAL_PRISM,
    SHAPE_TETRAHEDRON,
    UNKNOWN,
    ContourShape,
    classify_contour_shape,
    classify_shapes_in_image,
)


# ────────────────────────────────────────────────────────────────────────────
# 合成图形工具（纯 numpy，不依赖随机数 ⇒ 每次运行完全一致）
# ────────────────────────────────────────────────────────────────────────────


def _polygon(points: list[tuple[float, float]]) -> np.ndarray:
    """点列表 → OpenCV 轮廓 (N,1,2) int32。"""
    return np.array(points, dtype=np.float32).reshape(-1, 1, 2).astype(np.int32)


def _regular_polygon(
    n: int, radius: float, center=(200.0, 200.0), start_deg: float = 0.0
) -> np.ndarray:
    """正 n 边形轮廓。start_deg 用于旋转。"""
    pts = []
    for i in range(n):
        a = math.radians(start_deg + 360.0 * i / n)
        pts.append((center[0] + radius * math.cos(a),
                    center[1] + radius * math.sin(a)))
    return _polygon(pts)


def _rectangle(w: float, h: float, center=(200.0, 200.0),
               angle_deg: float = 0.0) -> np.ndarray:
    """任意宽高、可旋转的矩形。"""
    hw, hh = w / 2.0, h / 2.0
    base = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    pts = [(center[0] + x * ca - y * sa, center[1] + x * sa + y * ca)
           for x, y in base]
    return _polygon(pts)


def _circle(radius: float, center=(200.0, 200.0), n: int = 120) -> np.ndarray:
    """用足够多的顶点近似圆（n=120 时圆度 ≈ 1.0）。"""
    return _regular_polygon(n, radius, center)


def _mask_from_contour(contour: np.ndarray, size: int = 400) -> np.ndarray:
    """把轮廓画成实心二值掩膜，用于测试 findContours 路径。"""
    mask = np.zeros((size, size), dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, thickness=cv2.FILLED)
    return mask


# ────────────────────────────────────────────────────────────────────────────
# 1. 理想图形：判定规则本身
# ────────────────────────────────────────────────────────────────────────────


class IdealShapeTest(unittest.TestCase):
    """无噪声的理想图形 —— 验证每条判定规则。"""

    def test_01_square_is_cube(self):
        """正方形 → 正方体（rect_fill≈1.0、rect_aspect≈1.0）。"""
        r = classify_contour_shape(_rectangle(100, 100))
        self.assertEqual(r.shape, SHAPE_CUBE)
        self.assertEqual(r.confidence, "certain")
        self.assertEqual(r.evidence["n_vertices"], 4)
        self.assertGreater(r.evidence["rect_fill"], 0.95)

    def test_02_wide_rectangle_is_cuboid(self):
        """宽长方形 → 长方体（rect_aspect 明显偏离 1）。"""
        r = classify_contour_shape(_rectangle(160, 80))
        self.assertEqual(r.shape, SHAPE_CUBOID)
        self.assertEqual(r.confidence, "certain")
        self.assertEqual(r.evidence["n_vertices"], 4)
        self.assertGreater(r.evidence["rect_aspect"], 1.5)

    def test_03_tall_rectangle_is_cuboid(self):
        """高长方形 → 长方体（rect_aspect 用长/短，与朝向无关）。"""
        r = classify_contour_shape(_rectangle(70, 150))
        self.assertEqual(r.shape, SHAPE_CUBOID)
        self.assertGreater(r.evidence["rect_aspect"], 1.5)

    def test_04_triangle_is_tetrahedron(self):
        """正三角形 → 正四面体（面朝下俯视）。"""
        r = classify_contour_shape(_regular_polygon(3, 80))
        self.assertEqual(r.shape, SHAPE_TETRAHEDRON)
        self.assertEqual(r.confidence, "certain")
        self.assertEqual(r.evidence["n_vertices"], 3)
        # 三角形的 minAreaRect 填充率理论值 = 0.500
        self.assertLess(r.evidence["rect_fill"], 0.65)

    def test_05_pentagon_is_pentagonal_prism(self):
        """正五边形 → 五棱柱。"""
        r = classify_contour_shape(_regular_polygon(5, 80))
        self.assertEqual(r.shape, SHAPE_PENTAGONAL_PRISM)
        self.assertEqual(r.confidence, "certain")
        self.assertEqual(r.evidence["n_vertices"], 5)

    def test_06_circle_is_ambiguous_NOT_cylinder(self):
        """🔴 圆 → `round_ambiguous`，**绝不能**返回圆柱或圆锥。

        这是本模块最重要的安全属性：俯视下圆柱与圆锥都是圆，
        猜错会把圆锥装进圆柱盒 ⇒ 混装 ⇒ 该项 0 分。
        """
        r = classify_contour_shape(_circle(80))
        self.assertEqual(r.shape, ROUND_AMBIGUOUS)
        self.assertEqual(r.confidence, "ambiguous")
        self.assertFalse(r.is_decided)
        # 明确断言：不得直接判成圆柱/圆锥
        self.assertNotEqual(r.shape, SHAPE_CYLINDER)
        self.assertNotEqual(r.shape, SHAPE_CONE)

    def test_07_hexagon_falls_into_round_ambiguous(self):
        """六边形/多边形也归入圆类歧义（不是六棱柱！赛规没有六棱柱）。

        ⚠️ 赛规 6 类里**没有六棱柱**，所以不需要单独的六棱柱判定。
        多边形在这里被标为圆类歧义，交由调用方延后处理或人工确认。
        """
        r = classify_contour_shape(_regular_polygon(6, 80))
        self.assertIn(r.shape, (ROUND_AMBIGUOUS, UNKNOWN))
        self.assertNotIn(r.shape, (SHAPE_CUBE, SHAPE_CUBOID, SHAPE_TETRAHEDRON,
                                   SHAPE_PENTAGONAL_PRISM))

    def test_08_rotated_square_still_cube(self):
        """🔴 旋转 45° 的正方形仍必须是正方体。

        这是 2026-10-23 的**核心修正**：最初用 AABB 的 extent 判四边形，
        转 8° 就掉到 0.784（= 圆盘的 0.785）⇒ 漏判。
        改用 `minAreaRect` 后填充率与长宽比都**旋转无关**，转多少度都一样。
        """
        for ang in (8.0, 20.0, 30.0, 45.0):
            with self.subTest(angle=ang):
                r = classify_contour_shape(
                    _rectangle(100, 100, angle_deg=ang)
                )
                self.assertEqual(r.shape, SHAPE_CUBE,
                                 f"{ang}° 旋转的正方形被误判为 {r.shape}")
                self.assertGreater(r.evidence["rect_fill"], 0.93)
                self.assertAlmostEqual(r.evidence["rect_aspect"], 1.0, delta=0.12)

    def test_09_slightly_rotated_rectangle_still_cuboid(self):
        """旋转的长方形仍必须是长方体（不能因为旋转变成正方体）。"""
        for ang in (5.0, 15.0, 40.0):
            with self.subTest(angle=ang):
                r = classify_contour_shape(
                    _rectangle(160, 80, angle_deg=ang)
                )
                self.assertEqual(r.shape, SHAPE_CUBOID,
                                 f"{ang}° 旋转的长方形被误判为 {r.shape}")

    def test_09b_rotated_triangle_still_tetrahedron(self):
        """旋转的三角形仍必须是正四面体。"""
        for ang in (10.0, 25.0, 45.0):
            with self.subTest(angle=ang):
                r = classify_contour_shape(_regular_polygon(3, 90, start_deg=ang))
                self.assertEqual(r.shape, SHAPE_TETRAHEDRON,
                                 f"{ang}° 旋转的三角形被误判为 {r.shape}")

    def test_09c_rotated_pentagon_still_pentagonal_prism(self):
        """旋转的五边形仍必须是五棱柱。"""
        for ang in (10.0, 36.0, 50.0):
            with self.subTest(angle=ang):
                r = classify_contour_shape(_regular_polygon(5, 90, start_deg=ang))
                self.assertEqual(r.shape, SHAPE_PENTAGONAL_PRISM,
                                 f"{ang}° 旋转的五边形被误判为 {r.shape}")


# ────────────────────────────────────────────────────────────────────────────
# 2. 尺度不变性
# ────────────────────────────────────────────────────────────────────────────


class ScaleInvarianceTest(unittest.TestCase):
    """同一形状不同大小 ⇒ 判定结果必须一致（阈值全部是比值）。"""

    def test_10_square_scale_invariant(self):
        shapes = set()
        for side in (20, 40, 80, 160):
            r = classify_contour_shape(_rectangle(side, side))
            shapes.add(r.shape)
        self.assertEqual(shapes, {SHAPE_CUBE})

    def test_11_triangle_scale_invariant(self):
        shapes = set()
        for rad in (20, 40, 80, 160):
            r = classify_contour_shape(_regular_polygon(3, rad))
            shapes.add(r.shape)
        self.assertEqual(shapes, {SHAPE_TETRAHEDRON})

    def test_12_cuboid_scale_invariant(self):
        shapes = set()
        for k in (40, 80, 120):
            r = classify_contour_shape(_rectangle(k * 2, k))
            shapes.add(r.shape)
        self.assertEqual(shapes, {SHAPE_CUBOID})

    def test_13_pentagon_scale_invariant(self):
        shapes = set()
        for rad in (30, 60, 120):
            r = classify_contour_shape(_regular_polygon(5, rad))
            shapes.add(r.shape)
        self.assertEqual(shapes, {SHAPE_PENTAGONAL_PRISM})


# ────────────────────────────────────────────────────────────────────────────
# 3. fail-closed：坏输入与怪形状不得硬猜
# ────────────────────────────────────────────────────────────────────────────


class FailClosedTest(unittest.TestCase):
    """输入不可用或对不上任何形状时，必须返回 UNKNOWN，不得硬猜。"""

    def test_20_none_input(self):
        r = classify_contour_shape(None)
        self.assertEqual(r.shape, UNKNOWN)
        self.assertEqual(r.confidence, "unknown")

    def test_21_empty_input(self):
        r = classify_contour_shape(np.array([], dtype=np.int32))
        self.assertEqual(r.shape, UNKNOWN)

    def test_22_two_points_rejected(self):
        """少于 3 个点构不成多边形。"""
        r = classify_contour_shape(_polygon([(0, 0), (10, 10)]))
        self.assertEqual(r.shape, UNKNOWN)

    def test_23_collinear_points_rejected(self):
        """共线点面积为 0，必须 UNKNOWN 而不是崩溃或乱判。"""
        r = classify_contour_shape(_polygon([(0, 0), (50, 50), (100, 100)]))
        self.assertEqual(r.shape, UNKNOWN)
        self.assertEqual(r.confidence, "unknown")

    def test_24_garbage_shape_rejected(self):
        """细长条（像被遮挡的残片）→ UNKNOWN，不硬猜成长方体。

        边长 400×6 的条：4 顶点、rect_fill≈1.0，rect_aspect≈66.7。
        按当前规则会被判成长方体 —— 这是**已知边界**：
        rect_aspect 不设上限，极端细长条会被当成极端长方体。
        本测试确认这一行为并留档，提醒调用方还需额外的"最小尺度/最大长宽比"过滤。
        """
        r = classify_contour_shape(_rectangle(400, 6))
        self.assertIn(r.shape, (SHAPE_CUBOID, UNKNOWN))
        if r.shape == SHAPE_CUBOID:
            self.assertGreater(r.evidence["rect_aspect"], 10.0)

    def test_25_confidence_enum_is_exhaustive(self):
        """confidence 只能是三种取值之一（防止以后新增分支忘记归类）。"""
        samples = [
            _rectangle(100, 100),      # cube
            _rectangle(160, 80),       # cuboid
            _regular_polygon(3, 80),   # tetrahedron
            _regular_polygon(5, 80),   # pentagonal prism
            _circle(80),               # ambiguous
            None,                      # unknown
        ]
        allowed = {"certain", "ambiguous", "unknown"}
        for c in samples:
            self.assertIn(classify_contour_shape(c).confidence, allowed)

    def test_26_is_decided_only_for_certain(self):
        """`is_decided` 只在 certain 时为 True（歧义/未知都不能直接分箱）。"""
        certain = classify_contour_shape(_rectangle(100, 100))
        ambiguous = classify_contour_shape(_circle(80))
        unknown = classify_contour_shape(None)
        self.assertTrue(certain.is_decided)
        self.assertFalse(ambiguous.is_decided)
        self.assertFalse(unknown.is_decided)


# ────────────────────────────────────────────────────────────────────────────
# 4. 形状名与赛规表1 对齐
# ────────────────────────────────────────────────────────────────────────────


class ShapeNameContractTest(unittest.TestCase):
    """形状名必须与赛规表1 的"货物名称"逐字一致（赛规要求"完全一致"）。"""

    def test_30_six_shapes_exactly(self):
        """赛规是 6 类，不多不少。"""
        self.assertEqual(len(SHAPE_KEYS), 6)

    def test_31_names_match_competition_table(self):
        """逐字对照赛规表1。改这里 = 改屏幕显示内容 ⇒ 必须同时改赛规认知。"""
        self.assertEqual(
            set(SHAPE_KEYS),
            {"正方体", "长方体", "圆柱", "五棱柱", "圆锥", "正四面体"},
        )

    def test_32_no_forbidden_shapes(self):
        """赛规 6 类里**没有**六棱柱/三棱柱/四棱锥 —— 不能出现在名字表里。"""
        forbidden = {"六棱柱", "三棱柱", "四棱锥"}
        self.assertEqual(forbidden & set(SHAPE_KEYS), set())

    def test_33_ambiguous_and_unknown_are_not_shape_names(self):
        """`round_ambiguous` / `unknown` 是**判定状态**，不是货物名称。

        ⇒ 它们绝不能出现在 SHAPE_KEYS 里（否则会被误当货物名显示到屏幕上）。
        """
        self.assertNotIn(ROUND_AMBIGUOUS, SHAPE_KEYS)
        self.assertNotIn(UNKNOWN, SHAPE_KEYS)


# ────────────────────────────────────────────────────────────────────────────
# 4b. 判别可靠性排序与盒位（2026-10-23 用户裁决）
# ────────────────────────────────────────────────────────────────────────────


class PriorityAndBoxTest(unittest.TestCase):
    """「最简单、判别最不容易出问题的在前面」—— 排序必须与实测裕度一致。"""

    def test_34_priority_order_matches_measured_margin(self):
        """顺位必须严格等于实测可靠性的排序。

        实测 circularity 距圆阈值(0.93) 的裕度：
            正四面体 0.325 > 长方体 0.232 > 正方体 0.145 > 五棱柱 0.065
        ⇒ 顺位必须是 1,2,3,4，不能乱。
        """
        from sorting_vision.shape_geometry import shape_priority
        self.assertEqual(shape_priority(SHAPE_TETRAHEDRON), 1)
        self.assertEqual(shape_priority(SHAPE_CUBOID), 2)
        self.assertEqual(shape_priority(SHAPE_CUBE), 3)
        self.assertEqual(shape_priority(SHAPE_PENTAGONAL_PRISM), 4)
        self.assertEqual(shape_priority(SHAPE_CYLINDER), 5)
        self.assertEqual(shape_priority(SHAPE_CONE), 6)

    def test_35_priority_is_strictly_increasing_by_difficulty(self):
        """顺位严格递增，且 6 个形状各不相同。"""
        from sorting_vision.shape_geometry import shape_priority
        prios = [shape_priority(s) for s in
                 (SHAPE_TETRAHEDRON, SHAPE_CUBOID, SHAPE_CUBE,
                  SHAPE_PENTAGONAL_PRISM, SHAPE_CYLINDER, SHAPE_CONE)]
        self.assertEqual(prios, sorted(prios))
        self.assertEqual(len(set(prios)), 6)

    def test_36_ambiguous_and_unknown_sort_last(self):
        """未定/未知必须排在所有具体形状之后（不能插到中间）。"""
        from sorting_vision.shape_geometry import shape_priority
        worst_certain = max(
            shape_priority(s) for s in
            (SHAPE_TETRAHEDRON, SHAPE_CUBOID, SHAPE_CUBE,
             SHAPE_PENTAGONAL_PRISM, SHAPE_CYLINDER, SHAPE_CONE)
        )
        self.assertGreater(shape_priority(ROUND_AMBIGUOUS), worst_certain)
        self.assertGreater(shape_priority(UNKNOWN),
                           shape_priority(ROUND_AMBIGUOUS))

    def test_37_box_assignment_is_one_to_one(self):
        """6 形状 ↔ 6 盒，必须一一对应（赛规每组 6 类）。"""
        from sorting_vision.shape_geometry import BOX_TO_SHAPE, SHAPE_TO_BOX
        self.assertEqual(len(SHAPE_TO_BOX), 6)
        self.assertEqual(sorted(SHAPE_TO_BOX.values()), [1, 2, 3, 4, 5, 6])
        self.assertEqual(len(BOX_TO_SHAPE), 6)
        for shape, box in SHAPE_TO_BOX.items():
            self.assertEqual(BOX_TO_SHAPE[box], shape)

    def test_38_box_number_equals_priority(self):
        """盒号必须等于顺位 —— 这样"最稳的在前"同时体现在顺序和盒号上。"""
        from sorting_vision.shape_geometry import SHAPE_TO_BOX, shape_priority
        for shape, box in SHAPE_TO_BOX.items():
            self.assertEqual(box, shape_priority(shape),
                             f"{shape} 的盒号({box})与顺位({shape_priority(shape)})不一致")

    def test_39_ambiguous_shape_cannot_be_boxed(self):
        """🔴 歧义/未知**不能**分箱（返回 None），防止混装。

        赛规图4：混装任何两类 = 0 分。猜一个盒 = 可能混装 = 0 分。
        """
        from sorting_vision.shape_geometry import shape_to_box
        self.assertIsNone(shape_to_box(ROUND_AMBIGUOUS))
        self.assertIsNone(shape_to_box(UNKNOWN))
        self.assertIsNone(shape_to_box("不存在的形状"))

    def test_39b_each_real_shape_maps_to_a_box(self):
        """6 个真实形状都必须能分箱。"""
        from sorting_vision.shape_geometry import shape_to_box
        for s in SHAPE_KEYS:
            self.assertIsNotNone(shape_to_box(s), f"{s} 分不了箱")


# ────────────────────────────────────────────────────────────────────────────
# 5. 掩膜入口（findContours 路径）
# ────────────────────────────────────────────────────────────────────────────


class MaskEntryTest(unittest.TestCase):
    """`classify_shapes_in_image` 的便捷入口。"""

    def test_40_single_square_in_mask(self):
        mask = _mask_from_contour(_rectangle(100, 100))
        results = classify_shapes_in_image(mask)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].shape, SHAPE_CUBE)

    def test_41_empty_mask(self):
        self.assertEqual(classify_shapes_in_image(np.zeros((400, 400), np.uint8)), [])

    def test_42_none_mask(self):
        self.assertEqual(classify_shapes_in_image(None), [])  # type: ignore[arg-type]

    def test_43_two_shapes_in_mask(self):
        """掩膜里两个连通区域 ⇒ 两个结果（不要求它们不重叠）。"""
        mask = np.zeros((400, 400), np.uint8)
        cv2.drawContours(mask, [_rectangle(80, 80, center=(100, 100))], -1, 255,
                         cv2.FILLED)
        cv2.drawContours(mask, [_regular_polygon(3, 50, center=(300, 300))], -1,
                         255, cv2.FILLED)
        results = classify_shapes_in_image(mask)
        self.assertEqual(len(results), 2)
        got = {r.shape for r in results}
        self.assertEqual(got, {SHAPE_CUBE, SHAPE_TETRAHEDRON})


# ────────────────────────────────────────────────────────────────────────────
# 6. 抗噪：带边缘噪声的真实感轮廓
# ────────────────────────────────────────────────────────────────────────────


class NoiseRobustnessTest(unittest.TestCase):
    """加一点边缘抖动（模拟真实分割掩膜的毛刺），核心判定不应翻车。

    抖动用固定序列，不用随机数 ⇒ 可重复。
    """

    @staticmethod
    def _jitter(contour: np.ndarray, amp: int = 2) -> np.ndarray:
        arr = contour.reshape(-1, 2).astype(np.int32).copy()
        # 固定方向序列，不用随机
        deltas = [(amp, 0), (0, amp), (-amp, 0), (0, -amp)]
        for i in range(len(arr)):
            dx, dy = deltas[i % len(deltas)]
            arr[i][0] += dx
            arr[i][1] += dy
        return arr.reshape(-1, 1, 2)

    def test_50_jittered_square_still_cube(self):
        c = self._jitter(_rectangle(120, 120))
        r = classify_contour_shape(c)
        self.assertEqual(r.shape, SHAPE_CUBE)

    def test_51_jittered_triangle_still_tetrahedron(self):
        c = self._jitter(_regular_polygon(3, 100))
        r = classify_contour_shape(c)
        self.assertEqual(r.shape, SHAPE_TETRAHEDRON)

    def test_52_jittered_pentagon_still_pentagonal_prism(self):
        c = self._jitter(_regular_polygon(5, 100))
        r = classify_contour_shape(c)
        self.assertEqual(r.shape, SHAPE_PENTAGONAL_PRISM)

    def test_53_jittered_circle_stays_ambiguous(self):
        """带毛刺的圆不能因为毛刺被判成多边形（棱角数会上去，但圆度仍高）。"""
        c = self._jitter(_circle(100))
        r = classify_contour_shape(c)
        self.assertIn(r.shape, (ROUND_AMBIGUOUS, UNKNOWN))
        # 无论如何不能判成某个具体分箱形状
        self.assertNotIn(r.shape, (SHAPE_CUBE, SHAPE_CUBOID,
                                   SHAPE_TETRAHEDRON, SHAPE_PENTAGONAL_PRISM))


# ────────────────────────────────────────────────────────────────────────────
# 7. evidence 契约（便于现场调试）
# ────────────────────────────────────────────────────────────────────────────


class EvidenceContractTest(unittest.TestCase):
    """evidence 里必须有可解释的原始量，否则现场出了问题无法定位。"""

    def test_60_evidence_has_all_features(self):
        r = classify_contour_shape(_rectangle(100, 100))
        for key in ("area", "perimeter",
                    # 判定实际用这两个（旋转无关）
                    "rect_fill", "rect_aspect", "n_vertices",
                    # debug 字段
                    "aabb_extent", "aabb_aspect", "circularity",
                    "min_rect_angle_deg",
                    "rule"):
            self.assertIn(key, r.evidence, f"evidence 缺 {key}")

    def test_61_evidence_has_no_color(self):
        """🔴 evidence **不得含颜色** —— 本模块按设计完全不看颜色。

        如果以后有人偷偷加进来，这条会红，提醒"形状判定被颜色污染了"。
        """
        r = classify_contour_shape(_circle(80))
        for key in r.evidence:
            self.assertNotIn("color", key.lower())
            self.assertNotIn("hue", key.lower())
            self.assertNotIn("hsv", key.lower())

    def test_62_result_is_immutable(self):
        """判定结果不可变（防止调用方顺手改掉）。"""
        r = classify_contour_shape(_rectangle(100, 100))
        with self.assertRaises(Exception):
            r.shape = SHAPE_CUBOID  # type: ignore[misc]

    def test_63_rule_reason_is_recorded(self):
        """每个分支必须写 `rule`，便于日志定位走了哪条判断。"""
        samples = [
            _rectangle(100, 100),
            _rectangle(160, 80),
            _regular_polygon(3, 80),
            _regular_polygon(5, 80),
            _circle(80),
        ]
        for c in samples:
            r = classify_contour_shape(c)
            self.assertIn("rule", r.evidence)
            self.assertTrue(r.evidence["rule"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
