"""漂移检测：`maixcam_deploy/shape_geometry_lite.py` 必须与
`sorting_vision/shape_geometry.py` **逐一对拍一致**。

## 为什么需要这个测试

本项目已经**多次**栽在"两份实现悄悄不一致"上：

- `ec_motion_plan_interp.c` 与 `ec_motion_plan.c` 分叉，前者从没参与构建
- `视觉` 的 `COLOR_TO_MATERIAL`（颜色→形状）与 `[BoxMap]`（(颜色,形状)→盒）不一致
- `pipeline.py` 用了 `encoding.py`，而真正上板的 `stage1_color_v6_send.py` 没用

**根因**：换个部署目标就得复制一份逻辑（MaixCAM 上没有 `sorting_vision` 包），
而复制之后就没人保证两边还一样。

**对策**：本测试把两份实现放在**同一批输入**上跑，逐字段比较
`shape` / `confidence` / `evidence` 的关键量。
任何一处阈值或分支改动没同步，这里立刻红。

⇒ 改任意一边，都必须同步改另一边并重跑本测试。

运行：
    python -m pytest 视觉/tests/test_shape_geometry_parity.py -q
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

_THIS = Path(__file__).resolve()
_SRC = _THIS.parent.parent / "src"
_DEPLOY = _SRC / "maixcam_deploy"
for _p in (str(_SRC), str(_DEPLOY)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sorting_vision.shape_geometry as canonical  # noqa: E402
import shape_geometry_lite as lite  # noqa: E402


# ── 合成轮廓语料（覆盖所有分支 + 旋转 + 尺度 + 退化）─────────────────────

def _poly(points):
    return np.array(points, np.float32).reshape(-1, 1, 2).astype(np.int32)


def _regular(n, radius, center=(200.0, 200.0), start=0.0):
    pts = []
    for i in range(n):
        a = math.radians(start + 360.0 * i / n)
        pts.append((center[0] + radius * math.cos(a),
                    center[1] + radius * math.sin(a)))
    return _poly(pts)


def _rect(w, h, center=(200.0, 200.0), angle=0.0):
    hw, hh = w / 2.0, h / 2.0
    base = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    a = math.radians(angle)
    ca, sa = math.cos(a), math.sin(a)
    pts = [(center[0] + x * ca - y * sa, center[1] + x * sa + y * ca)
           for x, y in base]
    return _poly(pts)


def _corpus():
    """返回 [(名称, 轮廓)] —— 覆盖每个判定分支与边界。"""
    items = []
    # 四边形：正方体 / 长方体 / 各种旋转
    for ang in (0.0, 8.0, 20.0, 45.0):
        items.append((f"square@{ang}", _rect(100, 100, angle=ang)))
    for ang in (0.0, 15.0, 30.0):
        items.append((f"rect2to1@{ang}", _rect(160, 80, angle=ang)))
    items.append(("rect3.33to1", _rect(200, 60)))
    items.append(("rect_tall", _rect(70, 150)))
    # 三角形 / 五边形，含旋转与尺度
    for ang in (0.0, 25.0, 45.0):
        items.append((f"tri@{ang}", _regular(3, 90, start=ang)))
    for ang in (0.0, 36.0, 50.0):
        items.append((f"penta@{ang}", _regular(5, 90, start=ang)))
    # 圆 / 六边形 / 其他多边形
    items.append(("circle120", _regular(120, 90)))
    items.append(("circle120_small", _regular(120, 50)))
    items.append(("hexagon", _regular(6, 90)))
    items.append(("octagon", _regular(8, 90)))
    # 尺度变化
    for s in (20, 40, 120, 180):
        items.append((f"square{s}", _rect(s, s)))
        items.append((f"tri{s}", _regular(3, s)))
    # 退化 / 异常
    items.append(("collinear", _poly([(0, 0), (50, 50), (100, 100)])))
    items.append(("two_points", _poly([(0, 0), (10, 10)])))
    # ⚠️ 细长条两种形态要分别覆盖：
    #   · 400×6：高 6px < approxPolyDP 精度(0.02×周长≈16px) ⇒ 被简化成 2 顶点
    #             ⇒ 走 vertex_count_not_in_ruleset
    #   · 400×20：高 20px > 精度 ⇒ 保持 4 顶点，aspect=20 > RECT_ASPECT_MAX
    #             ⇒ 走 4_vertices_but_extreme_aspect
    # 两种都必须判 unknown —— 细长残片绝不能被骗成正四面体或长方体。
    items.append(("sliver_2vert", _rect(400, 6)))
    items.append(("sliver_4vert", _rect(400, 20)))
    items.append(("sliver_200x30", _rect(200, 30)))
    items.append(("tiny", _rect(3, 3)))
    return items


class ParityTest(unittest.TestCase):
    """两份实现必须在所有语料上给出相同结论。"""

    def test_01_shape_matches_on_all_corpus(self):
        """`shape` 必须完全一致 —— 这是最关键的字段（决定分箱）。"""
        mismatches = []
        for name, contour in _corpus():
            a = canonical.classify_contour_shape(contour)
            b = lite.classify_contour_shape(contour)
            if a.shape != b.shape:
                mismatches.append(
                    f"{name}: canonical={a.shape!r} lite={b.shape!r} "
                    f"(rules: {a.evidence.get('rule')!r} vs {b.evidence.get('rule')!r})"
                )
        self.assertEqual(
            mismatches, [],
            "两份实现的 shape 判定不一致 —— 必须同步修改：\n  " +
            "\n  ".join(mismatches),
        )

    def test_02_confidence_matches(self):
        """`confidence` 必须一致（certain/ambiguous/unknown）。"""
        mismatches = []
        for name, contour in _corpus():
            a = canonical.classify_contour_shape(contour)
            b = lite.classify_contour_shape(contour)
            if a.confidence != b.confidence:
                mismatches.append(f"{name}: {a.confidence!r} vs {b.confidence!r}")
        self.assertEqual(mismatches, [], "\n  ".join(mismatches))

    def test_03_is_decided_matches(self):
        """`is_decided` 必须一致（决定"能否直接分箱"）。"""
        for name, contour in _corpus():
            a = canonical.classify_contour_shape(contour)
            b = lite.classify_contour_shape(contour)
            self.assertEqual(a.is_decided, b.is_decided, f"{name} 不一致")

    def test_04_core_evidence_matches(self):
        """参与判定的四个量必须数值一致（阈值不同会在这里暴露）。"""
        keys = ("rect_fill", "rect_aspect", "circularity", "n_vertices")
        for name, contour in _corpus():
            a = canonical.classify_contour_shape(contour)
            b = lite.classify_contour_shape(contour)
            for k in keys:
                if k not in a.evidence or k not in b.evidence:
                    # 退化情形两边都可能缺 evidence，只要"缺"也一致即可
                    self.assertEqual(k in a.evidence, k in b.evidence,
                                     f"{name} 的 {k} 存在性不一致")
                    continue
                va, vb = a.evidence[k], b.evidence[k]
                if isinstance(va, float):
                    self.assertAlmostEqual(
                        va, vb, places=9,
                        msg=f"{name} 的 {k}: {va} vs {vb}",
                    )
                else:
                    self.assertEqual(va, vb, f"{name} 的 {k}")

    def test_05_threshold_constants_match(self):
        """阈值常量必须逐个相等 —— 这是最容易被改成一边的唯一地方。"""
        names = (
            "CIRCULARITY_ROUND_MIN",
            "RECT_FILL_QUAD_MIN",
            "ASPECT_SQUARE_TOL",
            "RECT_ASPECT_MAX",
            "N_VERT_TRIANGLE",
            "N_VERT_QUAD",
            "N_VERT_PENTA",
            "APPROX_EPS_RATIO",
        )
        for n in names:
            self.assertTrue(hasattr(canonical, n), f"权威版缺常量 {n}")
            self.assertTrue(hasattr(lite, n), f"部署版缺常量 {n}")
            self.assertEqual(
                getattr(canonical, n), getattr(lite, n),
                f"常量 {n} 不一致："
                f"canonical={getattr(canonical, n)} lite={getattr(lite, n)}",
            )

    def test_06_shape_names_match(self):
        """形状名必须逐字一致（会显示到屏幕上，赛规要求"完全一致"）。"""
        names = ("SHAPE_CUBE", "SHAPE_CUBOID", "SHAPE_CYLINDER",
                 "SHAPE_PENTAGONAL_PRISM", "SHAPE_CONE", "SHAPE_TETRAHEDRON",
                 "ROUND_AMBIGUOUS", "UNKNOWN")
        for n in names:
            self.assertEqual(getattr(canonical, n), getattr(lite, n),
                             f"形状名 {n} 不一致")

    def test_07_shape_keys_match(self):
        """SHAPE_KEYS 集合必须一致。"""
        self.assertEqual(set(canonical.SHAPE_KEYS), set(lite.SHAPE_KEYS))

    def test_08_priority_matches(self):
        """判别顺位必须一致（调度层按它排序）。"""
        for s in canonical.SHAPE_KEYS:
            self.assertEqual(canonical.shape_priority(s), lite.shape_priority(s),
                             f"{s} 的顺位不一致")

    def test_09_box_mapping_matches(self):
        """形状→盒号映射必须一致 —— 不一致会导致同一件投到不同盒。"""
        for s in canonical.SHAPE_KEYS:
            self.assertEqual(canonical.shape_to_box(s), lite.shape_to_box(s),
                             f"{s} 的盒号不一致")
        # 歧义/未知必须两边都是 None
        for s in (canonical.ROUND_AMBIGUOUS, canonical.UNKNOWN):
            self.assertEqual(canonical.shape_to_box(s), lite.shape_to_box(s))
            self.assertIsNone(canonical.shape_to_box(s))

    def test_10_corpus_actually_covers_branches(self):
        """语料本身必须真的覆盖到各分支，否则对拍是空转。

        这条防"以后有人把语料删空了，对拍还绿"。
        """
        seen_rules = set()
        seen_shapes = set()
        for _name, contour in _corpus():
            r = canonical.classify_contour_shape(contour)
            seen_rules.add(r.evidence.get("rule"))
            seen_shapes.add(r.shape)
        # 每个判定分支都必须被至少一条语料命中
        for rule in (
            "high_circularity_round_ambiguous",
            "5_vertices_pentagonal_prism",
            "3_vertices_tetrahedron",
            "4_vertices_rect_aspect_square",
            "4_vertices_rect_aspect_non_square",
            "4_vertices_but_extreme_aspect",
        ):
            self.assertIn(rule, seen_rules,
                          f"语料没覆盖到分支 {rule}（对拍会漏检！）")
        # 可判定的形状最多 4 种：圆柱/圆锥**永远**返回 round_ambiguous，
        # 不会出现在 shape 里（这是设计，不是缺陷）⇒ 上限就是 4。
        decided = set(canonical.SHAPE_KEYS) - {canonical.SHAPE_CYLINDER,
                                               canonical.SHAPE_CONE}
        self.assertEqual(len(decided), 4,
                         "可判定形状应为 4 种（圆柱/圆锥归歧义）")
        self.assertEqual(
            seen_shapes & decided, decided,
            f"语料没覆盖全部可判定形状：期望 {decided}，实际 {seen_shapes & decided}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
