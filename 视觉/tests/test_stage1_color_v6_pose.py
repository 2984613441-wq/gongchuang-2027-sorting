# -*- coding: utf-8 -*-
"""三棱柱「双姿态」离线自测：矩形面朝上 vs 三角面朝上。

被测定对象
----------
`视觉/src/maixcam_deploy/stage1_color_v6_send.py` 的 `analyze()` / `encode_target()`。
（同目录 import；`maix` 只在 main() 里 import，主机侧不会执行。）

依赖
----
必需 numpy。合成图部分必需 opencv-python：
    py -3 -m pip install numpy opencv-python==4.5.5.64      # py3.7 可装到 4.5.5.64
没装 cv2 时：`PoseGeometryTest` / `BridgeWireTest` 照常跑，
`SyntheticPoseTest` 整体 skip 并打印安装提示。

用法
----
    py -3 视觉/tests/test_stage1_color_v6_pose.py          # 先打度量表，再跑断言
    py -3 -m unittest discover -s 视觉/tests -p "test_stage1_color_v6_pose.py" -v

断言口径
--------
* `test_spec_*`   = **应然**行为（目标规格）。`@expectedFailure` = 已确认的现存缺陷：
  现在预期失败；**一旦修好会变成 unexpectedSuccess = 失败**，届时删掉该装饰器。
* `test_char_*`   = **实然**行为（characterization）：锁定当前行为，防止改动时无声漂移。
* 数字来源：`stage1_color_v6_send.py` 的行号在注释里标注；三角形几何值由本文件算式复现。
"""
from __future__ import annotations

import ast
import importlib
import math
import struct
import sys
import types
import unittest
from pathlib import Path

import numpy as np

DEPLOY_DIR = Path(__file__).resolve().parents[1] / "src" / "maixcam_deploy"
if str(DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOY_DIR))

try:
    import cv2
except ImportError:  # pragma: no cover - 主机侧常见
    cv2 = None

v6 = None
if cv2 is not None:
    import stage1_color_v6_send as v6  # noqa: E402

NEEDS_CV2 = "需要 opencv-python：py -3 -m pip install opencv-python==4.5.5.64"

FRAME = 320                 # :166 FRAME_SIZE
DETECT = 224                # :167 DETECT_SIZE
MM_PER_PX320 = 0.4856       # 现场仿射给出的尺度（320 帧口径）
ROI_MARGIN = 0.01           # 2026-09-22 用户现场裁决：0.03 → 0.01（见 stage1_color_v6_send.py 的 ROI_MARGIN 注释）


# ─────────────────────────────────────────────────────────────────────────────
# 1) 纯数学：:235 / :241 的阈值 vs 等边三角形的实际值（不需要 cv2）
# ─────────────────────────────────────────────────────────────────────────────
class PoseGeometryTest(unittest.TestCase):
    """等边三角形 vs 正方形：逐闸的数值边界。全部可手算复核。"""

    @staticmethod
    def detect_frame():
        """复现 :208-221 的降采样与面积闸口径。"""
        w = h = int(round(FRAME * min(1.0, DETECT / float(FRAME))))
        x0 = int(w * ROI_MARGIN)
        return w, h, x0, 0.0015 * w * h, 0.22 * w * h      # min_area, max_area

    @staticmethod
    def tri_pts(side, rot_deg, apex_up=True):
        """等边三角形，外心=形心=原点。顶点相隔 120°；apex_up 时一个顶点朝上。

        rot_deg = 0  → 一个顶点朝上（bbox = s × 0.866s，extent = 0.5）
        rot_deg = 30 → 一条边朝上（bbox = 0.866s × s，extent = 0.5，aspect 0.577）
        """
        r = side / math.sqrt(3.0)
        base = -90.0 if apex_up else -30.0
        return [(r * math.cos(math.radians(base + 120 * k + rot_deg)),
                 r * math.sin(math.radians(base + 120 * k + rot_deg))) for k in range(3)]

    @staticmethod
    def shoelace(pts):
        s = 0.0
        for i, (x1, y1) in enumerate(pts):
            x2, y2 = pts[(i + 1) % len(pts)]
            s += x1 * y2 - x2 * y1
        return abs(s) / 2.0

    @staticmethod
    def min_area_rect_area(pts):
        """三角形最小外接矩形面积 = min(以各边为底时的 底×高)。"""
        best = None
        for i in range(3):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % 3]
            base = math.hypot(bx - ax, by - ay)
            hmax = max(abs((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / base
                       for px, py in pts)
            best = base * hmax if best is None else min(best, base * hmax)
        return best

    @staticmethod
    def axis_bbox(pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return max(xs) - min(xs), max(ys) - min(ys)

    def test_01_thresholds_match_source(self):
        """:220-221 / :176 / :179 / :235 / :241 的常量必须是这些数。"""
        w, h, x0, min_area, max_area = self.detect_frame()
        self.assertEqual((w, h), (224, 224))
        self.assertEqual(x0, 2)                       # ROI 起点（224 帧）；0.03 时为 6，2026-09-22 改 0.01
        self.assertAlmostEqual(min_area, 75.264, places=3)
        self.assertAlmostEqual(max_area, 11038.72, places=2)
        self.assertEqual(ROI_MARGIN, 0.01)

    def test_02_extent_band_0464_to_0500(self):
        """:241 `area/(w*h) >= 0.35`：三角形实际区间与余量（本闸余量最薄）。"""
        w, _, _, _, _ = self.detect_frame()
        side = 82.4 * (w / FRAME)                     # 40mm 件：320 帧 82.4px
        band = []
        for deg in range(0, 60, 5):
            pts = self.tri_pts(side, deg)
            bw, bh = self.axis_bbox(pts)
            band.append(self.shoelace(pts) / (bw * bh))
        self.assertAlmostEqual(min(band), 0.4641, places=3)   # 15/45/75°
        self.assertAlmostEqual(max(band), 0.5000, places=3)   # 0/30/60°
        self.assertGreater(min(band), 0.35, "理想三角形不违反 :241")
        self.assertLess(min(band) / 0.35, 1.35,
                        "三角形对 :241 的余量 < 1.35x —— 全案最薄的一道闸")
        # 对照：正方形 1.0、圆盘 pi/4 = 0.785，都远高于 0.35
        self.assertGreater(0.785 / min(band), 1.5)

    def test_03_aspect_gate_never_binds_for_triangles(self):
        """:241 `min(w,h)/max(w,h) >= 0.28`：三角形 0.866，余量 3.1x，永不触发。"""
        w, _, _, _, _ = self.detect_frame()
        side = 82.4 * (w / FRAME)
        for deg in range(0, 60, 5):
            bw, bh = self.axis_bbox(self.tri_pts(side, deg))
            ratio = min(bw, bh) / max(bw, bh)
            self.assertGreaterEqual(ratio, 0.86)
            self.assertGreater(ratio / 0.28, 3.0)

    def test_04_min_area_floor_is_153x_harsher_for_triangles(self):
        """:235 min_area：三角形检测下限（线性）是正方形的 1.52 倍。"""
        w, _, _, min_area, max_area = self.detect_frame()
        a_tri = math.sqrt(min_area / (math.sqrt(3) / 4))
        a_sq = math.sqrt(min_area)
        self.assertAlmostEqual(a_tri / a_sq, 1.5197, places=3)
        to_mm = lambda a224: a224 / (w / FRAME) * MM_PER_PX320
        self.assertAlmostEqual(to_mm(a_tri), 9.1, delta=0.2)   # 三角形 ~9.1mm
        self.assertAlmostEqual(to_mm(a_sq), 6.0, delta=0.2)    # 正方形 ~6.0mm
        # 40mm 件：三角形面积 1441px²(224)，min_area 75.3 → 余量 19x，不会卡这闸
        area40 = (math.sqrt(3) / 4) * (82.4 * w / FRAME) ** 2
        self.assertGreater(area40 / min_area, 15.0)
        self.assertLess(area40, max_area)

    def test_05_min_area_rect_extent_is_rotation_invariant(self):
        """方案 B 的数学依据：分母换成 minAreaRect 后 extent 恒为 0.5，与朝向无关。"""
        w, _, _, _, _ = self.detect_frame()
        side = 82.4 * (w / FRAME)
        for v in (self.shoelace(p) / self.min_area_rect_area(p)
                  for p in (self.tri_pts(side, d) for d in range(0, 60, 5))):
            self.assertAlmostEqual(v, 0.5, places=6)
        # 细长条：两种口径都能拒，但「哪一条款在干活」随角度变 —— 这才是脆弱点
        for deg, axis_clause in ((3.0, "aspect"), (45.0, "extent")):
            pts = self._strip(deg)
            bw, bh = self.axis_bbox(pts)
            area = self.shoelace(pts)
            axis_aspect = min(bw, bh) / max(bw, bh)
            axis_extent = area / (bw * bh)
            rw = math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
            rh = math.hypot(pts[2][0] - pts[1][0], pts[2][1] - pts[1][1])
            rect_aspect = min(rw, rh) / max(rw, rh)
            rect_extent = area / (rw * rh)
            with self.subTest(deg=deg):
                # minAreaRect 口径：长宽比恒为 4/100，永远靠 aspect 拒（与角度无关）
                self.assertAlmostEqual(rect_aspect, 4.0 / 100.0, places=6)
                self.assertLess(rect_aspect, 0.28, "minAreaRect：细条恒被 aspect 拒")
                self.assertAlmostEqual(rect_extent, 1.0, places=6,
                                       msg="细条就是自己的最小外接矩形 → extent 条款对它无效")
                # 轴对齐口径：拒它的条款随角度在 aspect / extent 之间跳
                if axis_clause == "aspect":
                    self.assertLess(axis_aspect, 0.28)      # 3°  靠长宽比被拒
                    self.assertGreater(axis_extent, 0.35)   # 而 extent 条款此时放过
                else:
                    self.assertGreater(axis_aspect, 0.28)   # 45° 长宽比放过
                    self.assertLess(axis_extent, 0.35)      # 只能靠 extent 被拒

    @staticmethod
    def _strip(deg):
        """长 100、宽 4 的矩形，绕原点转 deg。"""
        t = math.radians(deg)
        c, s = math.cos(t), math.sin(t)
        return [(x * c - y * s, x * s + y * c)
                for x, y in ((0, -2), (100, -2), (100, 2), (0, 2))]

    def test_06_bbox_center_is_not_the_centroid_of_a_triangle(self):
        """「三角面不好抓」的根因：bbox 中心 ≠ 轮廓质心，偏移 0.10~0.14·a。"""
        offs = {}
        for deg in range(0, 60, 5):
            pts = self.tri_pts(1.0, deg)
            cx = sum(p[0] for p in pts) / 3.0
            cy = sum(p[1] for p in pts) / 3.0
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            offs[deg] = math.hypot(cx - (max(xs) + min(xs)) / 2.0,
                                   cy - (max(ys) + min(ys)) / 2.0)
        self.assertAlmostEqual(offs[0], math.sqrt(3) / 12.0, places=6)   # 顶点朝上 h/6
        self.assertGreaterEqual(min(offs.values()), 0.10)
        self.assertLessEqual(max(offs.values()), 0.15)
        # 40mm 件 → 5.75mm 抓取点偏移；正方形/圆盘 = 0（对称）
        self.assertAlmostEqual(offs[0] * 82.4 * MM_PER_PX320, 5.75, places=1)
        for deg in range(0, 60, 5):                             # 正方形恒为 0
            t = math.radians(deg)
            c, s = math.cos(t), math.sin(t)
            r = [(x * c - y * s, x * s + y * c)
                 for x, y in ((0, 0), (1, 0), (1, 1), (0, 1))]
            xs = [p[0] for p in r]
            ys = [p[1] for p in r]
            with self.subTest(deg=deg, shape="square"):
                self.assertAlmostEqual(sum(xs) / 4 - (max(xs) + min(xs)) / 2.0, 0.0, places=9)
                self.assertAlmostEqual(sum(ys) / 4 - (max(ys) + min(ys)) / 2.0, 0.0, places=9)


# ─────────────────────────────────────────────────────────────────────────────
# 2) 合成图：跑真 analyze()
# ─────────────────────────────────────────────────────────────────────────────
def _palette():
    def bgr(h, s, v):
        return tuple(int(x) for x in cv2.cvtColor(np.uint8([[[h, s, v]]]),
                                                  cv2.COLOR_HSV2BGR)[0, 0])
    return {
        # 干净物料：取值都留 >=3 余量
        "cyan": bgr(95, 200, 200), "green": bgr(60, 200, 200),
        "red": bgr(1, 200, 200), "blue": bgr(120, 200, 200),
        "orange": bgr(12, 200, 200), "black": bgr(0, 10, 20),
        # 单边遮挡带（颜色纯、只是 V 掉下来）→ 不进彩色掩膜、也不进黑
        "red_dim": bgr(1, 200, 20),
        # 彩色窗口 ∩ black 窗口 ∩ :259 深色核心 的**重叠带**
        "blue_dark": bgr(120, 120, 34),    # blue 要 V>=30 → 命中
        "red_dark": bgr(1, 120, 36),       # red 要 V>=35 → 命中
        "green_dark": bgr(60, 120, 36),    # green 要 V>=35 → 命中
        # 托盘阴影
        "shadow_deep": bgr(0, 40, 30),     # 低饱和 + V<=50 → 现在会被当黑件
        "shadow_light": bgr(0, 25, 110),   # V>50 → 必须被挡
    }


@unittest.skipIf(v6 is None, NEEDS_CV2)
class SyntheticPoseTest(unittest.TestCase):
    """白托盘 + 单物件合成图，逐张断言「应检出 / 应丢弃 / 应是哪个 bin」。"""

    PAL = None

    @classmethod
    def setUpClass(cls):
        cls.PAL = _palette()

    # ── 画图 ────────────────────────────────────────────────────────────────
    @staticmethod
    def canvas():
        return np.full((FRAME, FRAME, 3), 235, dtype=np.uint8)   # 白托盘

    @staticmethod
    def square(img, cx, cy, side, color, dx=0):
        h = side // 2
        cv2.rectangle(img, (cx - h + dx, cy - h), (cx + h + dx, cy + h), color, -1)

    @staticmethod
    def disc(img, cx, cy, r, color, dx=0):
        cv2.circle(img, (cx + dx, cy), r, color, -1)

    @staticmethod
    def tri(img, cx, cy, side, color, rot=0.0, apex_up=True, dx=0):
        r = side / math.sqrt(3.0)
        base = -90.0 if apex_up else -30.0
        pts = np.array([[int(round(cx + dx + r * math.cos(math.radians(base + 120 * k + rot)))),
                         int(round(cy + r * math.sin(math.radians(base + 120 * k + rot))))]
                        for k in range(3)], dtype=np.int32)
        cv2.fillPoly(img, [pts], color, lineType=cv2.LINE_8)   # 硬边，不引入过渡色

    @classmethod
    def analyze(cls, img):
        results, roi = v6.analyze(img, input_rgb=False)
        return results, roi

    def bins(self, img):
        return sorted(r["bin"] for r in self.analyze(img)[0])

    def draw(self, shape, color, size=82, rot=0.0, dx=0, at=(160, 160)):
        img = self.canvas()
        if shape == "square":
            self.square(img, at[0], at[1], size, color, dx=dx)
        elif shape == "disc":
            self.disc(img, at[0], at[1], size // 2, color, dx=dx)
        elif shape == "tri":
            self.tri(img, at[0], at[1], size, color, rot=rot, dx=dx)
        else:
            raise ValueError(shape)
        return img

    # ── 1. 基准：两种姿态都必须在 ──────────────────────────────────────────
    def test_10_clean_shapes_all_six_bins(self):
        cases = (("square", "cyan", 82, 1), ("square", "green", 55, 2),
                 ("tri", "red", 82, 3), ("tri", "blue", 82, 4),
                 ("disc", "black", 82, 5), ("disc", "orange", 82, 6))
        for shape, cname, size, want in cases:
            with self.subTest(shape=shape, color=cname):
                self.assertEqual(self.bins(self.draw(shape, self.PAL[cname], size)), [want])

    def test_11_triangle_detected_at_every_orientation(self):
        """三角面朝上：0~60° 每 5° 一档都该报对 —— 证明几何闸不是朝向敏感的杀手。

        ⇒ 现场「三角面朝上识别不到」**不是**纯几何问题；必须先看掩膜是不是碎的。
        """
        for deg in range(0, 60, 5):
            for cname, want in (("red", 3), ("blue", 4)):
                with self.subTest(deg=deg, bin=want):
                    self.assertIn(want, self.bins(self.draw("tri", self.PAL[cname],
                                                            rot=float(deg))))

    def test_12_detection_floor_triangle_worse_than_square(self):
        """:235 → 实测「最小可检出边长」：三角形应明显大于正方形（预测 1.52 倍）。"""
        def floor_mm(shape, cname, want):
            lo, hi = 2, 60                     # mm
            while lo < hi:
                mid = (lo + hi + 1) // 2
                side = max(3, int(round(mid / MM_PER_PX320)))
                if want in self.bins(self.draw(shape, self.PAL[cname], side)):
                    lo = mid
                else:
                    hi = mid - 1
            return lo
        tri = floor_mm("tri", "red", 3)
        sq = floor_mm("square", "cyan", 1)
        ratio = tri / float(sq)
        print("\n[floor] 三角形可检出最小边长 = %d mm；正方形 = %d mm；比值 %.2f" % (tri, sq, ratio))
        self.assertGreater(tri, sq, "三角形的检测下限必须更差")
        self.assertAlmostEqual(ratio, 1.52, delta=0.45)

    # ── 2. 该丢的必须丢 ────────────────────────────────────────────────────
    def test_13_thin_diagonal_strip_is_dropped(self):
        img = self.canvas()
        cv2.fillPoly(img, [np.array([[30, 30], [290, 290], [281, 299], [21, 39]],
                                    dtype=np.int32)], self.PAL["red"],
                     lineType=cv2.LINE_8)
        self.assertEqual(self.bins(img), [], "斜细条必须被 :241 拒掉（此角度靠 extent 条款）")

    def test_14_light_shadow_is_not_a_black_cylinder(self):
        img = self.canvas()
        cv2.ellipse(img, (160, 160), (70, 45), 0, 0, 360, self.PAL["shadow_light"], -1)
        self.assertEqual(self.bins(img), [], "V>50 的浅阴影必须被 :191 挡在门外")

    def test_15_touching_roi_edge_is_dropped(self):
        """⚠️ 已知问题（:239-240），请勿在此处改；本用例只锁定现状。"""
        img = self.canvas()
        self.square(img, 20, 20, 60, self.PAL["cyan"])
        self.assertEqual(self.bins(img), [])

    def test_16_black_still_requires_a_dark_core(self):
        """中性灰（S=0，V=45）既能过 black 的盒子，深色核心也满足 → 会成黑件。

        这条锁定的是 :256-260 的**边界**：它挡的是"亮灰投影"（V>50），不是"深灰"。
        """
        img = self.canvas()
        cv2.circle(img, (160, 160), 41, _palette()["black"], -1)
        cv2.circle(img, (200, 200), 60, tuple(int(x) for x in cv2.cvtColor(
            np.uint8([[[0, 0, 45]]]), cv2.COLOR_HSV2BGR)[0, 0]), -1)
        self.assertIn(5, self.bins(img))

    # ── 3. 半遮挡容差：三角形 vs 正方形（Q1 的核心量化）──────────────────
    def _tolerable_band(self, shape, want):
        """二分：单边遮挡带多宽（320 帧像素）时该件不再被检出。"""
        lo, hi = 0, 120
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if shape == "tri":
                img = self.draw("tri", self.PAL["red_dim"])
                self.tri(img, 160, 160, 82, self.PAL["red"], dx=mid)
            else:
                img = self.draw("square", self.PAL["red_dim"])
                self.square(img, 160, 160, 82, self.PAL["red"], dx=mid)
            if want in self.bins(img):
                lo = mid
            else:
                hi = mid - 1
        return lo

    def test_17_triangle_tolerates_much_less_partial_occlusion(self):
        t_tri = self._tolerable_band("tri", 3)
        t_sq = self._tolerable_band("square", 1)
        print("\n[band] 三角面朝上 临界单边遮挡 = %d px(320) = %.1f mm"
              % (t_tri, t_tri * MM_PER_PX320))
        print("[band] 矩形面朝上 临界单边遮挡 = %d px(320) = %.1f mm"
              % (t_sq, t_sq * MM_PER_PX320))
        self.assertLess(t_tri / float(t_sq), 0.6,
                        "三角形应显著更脆弱（理论：需损失 30% 面积 vs 65%）；"
                        "若失败说明单边遮挡模型不对，改用真实截图复现")

    # ── 4. 误判路径：同一物体被同时报成两个 bin ───────────────────────────
    def test_20_black_window_overlap_arithmetic(self):
        """先证明「重叠带」在算术上存在，避免后面几条被当成偶然。"""
        hi_s, hi_v, core_v = 150, 50, 38            # :191 / :258
        floors = {"red": 35, "orange": 45, "yellow": 45,
                  "green": 35, "cyan": 35, "blue": 30}   # :184-192 的 V 下限
        windows = {k: max(0, min(hi_v, core_v) - v + 1) for k, v in floors.items()}
        self.assertEqual(windows["blue"], 9, "blue 的 V 窗口 [30,38]，暴露面最大")
        self.assertEqual(windows["red"], 4)
        self.assertEqual(windows["green"], 4)
        self.assertEqual(windows["cyan"], 4)
        self.assertEqual(windows["orange"], 0, ":259 的深色核心闸挡住了橙色的幻影")
        self.assertEqual(windows["yellow"], 0)
        self.assertLessEqual(hi_s, 150)

    @unittest.expectedFailure
    def test_21_spec_dark_blue_prism_is_only_bin4(self):
        """应然：一个暗蓝三棱柱只该报 bin4。实然：同时报 bin4 + bin5（幻影）。"""
        self.assertEqual(self.bins(self.draw("tri", self.PAL["blue_dark"])), [4])

    @unittest.expectedFailure
    def test_22_spec_dark_green_cube_is_only_bin2(self):
        """同一条窗口重叠也打中正方体：阴天/阴影下的绿色正方体可能报 bin2 + bin5。"""
        self.assertEqual(self.bins(self.draw("square", self.PAL["green_dark"])), [2])

    @unittest.expectedFailure
    def test_23_spec_prism_plus_tray_shadow_is_one_target(self):
        """应然：三棱柱 + 托盘深阴影只该报 1 件（bin3）。实然：多一个 bin5 幻影。"""
        img = self.draw("tri", self.PAL["red"], at=(120, 130))
        cv2.ellipse(img, (245, 235), (45, 30), 0, 0, 360, self.PAL["shadow_deep"], -1)
        self.assertEqual(self.bins(img), [3])

    def test_24_char_shadow_alone_becomes_black(self):
        """characterization：够大够暗的低饱和阴影块，现在会被当成黑色圆柱（bin5）。"""
        img = self.canvas()
        cv2.ellipse(img, (245, 235), (45, 30), 0, 0, 360, self.PAL["shadow_deep"], -1)
        self.assertEqual(self.bins(img), [5],
                         "若此项失败说明 :256-260 已能挡住阴影幻影（好事，更新本测试）")

    # ── 5. 抓取中心（走 wire）────────────────────────────────────────────
    @unittest.expectedFailure
    def test_30_spec_triangle_grab_center_is_the_centroid(self):
        """应然：三棱柱的 X/Y 应是轮廓质心。实然：bbox 中心，偏 0.144a ≈ 5.8mm。"""
        row = [r for r in self.analyze(self.draw("tri", self.PAL["red"]))[0]
               if r["color"] == "red"][0]
        self.assertIn("center", row, "analyze() 目前不产出 center 键")
        left, top, w, h = row["bbox"]
        self.assertAlmostEqual(abs(row["center"][1] - (top + h / 2.0)), 0.1443 * 82,
                               delta=4)

    def test_31_char_triangle_grab_center_is_bbox_center(self):
        """characterization：锁定当前口径 X=left+w/2、Y=top+h/2（:54-56）。"""
        row = [r for r in self.analyze(self.draw("tri", self.PAL["red"]))[0]
               if r["color"] == "red"][0]
        left, top, w, h = row["bbox"]
        packed = v6.encode_target(row)
        self.assertEqual(len(packed), 7)
        _b, _c, x, y, angle = struct.unpack(">BBHHB", packed)
        self.assertEqual((x, y), (int(left + w / 2), int(top + h / 2)))
        self.assertEqual(angle, 0xFF)

    def test_32_char_symmetric_shapes_centroid_equals_bbox_center(self):
        """方案 A 的前提：正方形/圆盘的质心 == bbox 中心 → 改质心对它们零影响。"""
        for shape, cname, want in (("square", "cyan", 1), ("disc", "orange", 6)):
            with self.subTest(shape=shape):
                row = [r for r in self.analyze(self.draw(shape, self.PAL[cname]))[0]
                       if r["bin"] == want][0]
                left, top, w, h = row["bbox"]
                self.assertAlmostEqual(left + w / 2.0, 160, delta=2)
                self.assertAlmostEqual(top + h / 2.0, 160, delta=2)

    # ── 6. StableTargets 稳定层 ──────────────────────────────────────────
    def test_40_confirm_then_hold_then_drop(self):
        """锁定 :276-321：2 帧确认 → HOLD 灰框 bin=None → 超 HOLD_SECONDS 删除。"""
        det, _ = self.analyze(self.draw("tri", self.PAL["red"]))
        trk = v6.StableTargets()
        self.assertEqual(trk.update(det, 0.0), [], "第 1 帧只累计 hits，未确认")
        out = trk.update(det, 1.0 / v6.TARGET_FPS)
        self.assertEqual(len(out), 1, "第 2 帧达成 CONFIRM_FRAMES=2")
        self.assertEqual(out[0]["bin"], 3)
        held = trk.update([], 2.0 / v6.TARGET_FPS)
        self.assertEqual(held[0]["bin"], None, "HOLD 灰框必须把 bin 置 None")
        self.assertTrue(held[0]["stale"])
        self.assertEqual(trk.update([], 2.0 / v6.TARGET_FPS + v6.HOLD_SECONDS + 0.01), [],
                         "超过 HOLD_SECONDS 后轨道必须被删掉")

    def test_41_reconfirm_resets_hits(self):
        """锁定 :288-302：轨道内目标跳太远（>max(30,0.9·max(w,h))）会重开确认。"""
        trk = v6.StableTargets()
        det, _ = self.analyze(self.draw("tri", self.PAL["red"]))
        trk.update(det, 0.0)
        self.assertEqual(len(trk.update(det, 0.1)), 1)
        far = [dict(det[0], bbox=(10, 10, 60, 60))]      # 跳 >100px
        self.assertEqual(trk.update(far, 0.2), [], "跳太远 → hits 归零 → 本帧不输出")
        self.assertEqual(len(trk.update(far, 0.3)), 1)


# ─────────────────────────────────────────────────────────────────────────────
# 3) wire 与 TASK_ID：改动不得触碰
# ─────────────────────────────────────────────────────────────────────────────
@unittest.skipIf(v6 is None, NEEDS_CV2)
class BridgeWireTest(unittest.TestCase):
    """冻结线格式回归（:37-44，每目标 7 字节 `>BBHHB`）。"""

    @staticmethod
    def row(bin_id, bbox, frac=0.95):
        return {"bin": bin_id, "bbox": bbox, "color_fraction": frac,
                "color": "red", "shape": "triangular_prism", "stale": False}

    def test_50_target_is_exactly_seven_bytes(self):
        self.assertEqual(v6._TARGET_BYTES, 7)          # :44
        self.assertEqual(len(v6.encode_target(self.row(3, (10, 20, 40, 40)))), 7)

    def test_51_batch_header_is_count_plus_be_task_id(self):
        data = v6.encode_batch_targets(
            [self.row(3, (10, 20, 40, 40)), self.row(4, (100, 120, 30, 30))], 1)
        self.assertEqual(data[0], 2)
        self.assertEqual(data[1:3], b"\x00\x01")       # 大端 task_id
        self.assertEqual(len(data), 3 + 2 * 7)

    def test_52_task_id_and_port_contract(self):
        self.assertEqual(v6.TASK_ID, 1)                # :39 绝不能是 0
        self.assertEqual(v6.GATEWAY_PORT, 8765)        # :38
        with self.assertRaises(ValueError):
            v6.encode_batch_targets([], 70000)

    def test_53_hold_and_out_of_range_bins_are_dropped(self):
        self.assertIsNone(v6.encode_target(self.row(None, (1, 2, 3, 4))))
        self.assertIsNone(v6.encode_target(self.row(0, (1, 2, 3, 4))))
        self.assertIsNone(v6.encode_target(self.row(7, (1, 2, 3, 4))))

    def test_54_confidence_is_color_fraction_times_100(self):
        packed = v6.encode_target(self.row(3, (0, 0, 10, 10), frac=0.83))
        self.assertEqual(struct.unpack(">BBHHB", packed)[1], 83)

    def test_55_hue_ranges_are_pairwise_disjoint(self):
        """「六色互不串」：5 个彩色色的 H 区间两两不交（black 是 S/V 盒，单列）。

        与 `SourceContractTest` 的同名检查重复，但这里读的是**已 import 的模块常量**。
        """
        hsv = v6.COLOR_RANGES
        flats = [(name, int(lo[0]), int(hi[0]))
                 for name in ("red", "orange", "yellow", "green", "cyan", "blue")
                 for lo, hi in hsv[name]]
        for i in range(len(flats)):
            for j in range(i + 1, len(flats)):
                n1, a1, b1 = flats[i]
                n2, a2, b2 = flats[j]
                if n1 == n2:
                    continue
                self.assertTrue(b1 < a2 or b2 < a1,
                                "%s[%d,%d] 与 %s[%d,%d] 色相重叠" % (n1, a1, b1, n2, a2, b2))

    @unittest.expectedFailure
    def test_56_spec_centroid_change_must_not_move_symmetric_shapes(self):
        """方案 A 的关键回归：正方形/圆盘质心 == bbox 中心 → 编码逐字节不变。"""
        for bin_id, bbox in ((1, (10, 20, 40, 40)), (5, (100, 100, 62, 62)),
                             (6, (200, 200, 50, 50))):
            with self.subTest(bin=bin_id):
                row = self.row(bin_id, bbox)
                row["center"] = (bbox[0] + bbox[2] // 2, bbox[1] + bbox[3] // 2)
                self.assertEqual(v6.encode_target(row),
                                 v6.encode_target(self.row(bin_id, bbox)))


# ─────────────────────────────────────────────────────────────────────────────
# 4) 源码契约：不需要 cv2，直接读源码常量（始终运行）
# ─────────────────────────────────────────────────────────────────────────────
SOURCE = DEPLOY_DIR / "stage1_color_v6_send.py"


class SourceContractTest(unittest.TestCase):
    """用 `ast` 读 `stage1_color_v6_send.py` 的常量 —— 不 import 模块，故不需要 cv2。"""

    @classmethod
    def setUpClass(cls):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        cls.consts = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                try:
                    cls.consts[node.targets[0].id] = ast.literal_eval(node.value)
                except ValueError:
                    pass          # 表达式（KERNEL = np.ones(...)）跳过

    def test_60_thresholds_are_the_documented_values(self):
        c = self.consts
        self.assertEqual(c["FRAME_SIZE"], 320)              # :166
        self.assertEqual(c["DETECT_SIZE"], 224)             # :167
        self.assertAlmostEqual(c["ROI_MARGIN"], 0.01)       # 2026-09-22 现场裁决 0.03→0.01
        self.assertAlmostEqual(c["MIN_AREA_FRACTION"], 0.0015)    # :177
        self.assertAlmostEqual(c["MAX_AREA_FRACTION"], 0.22)      # :178
        self.assertAlmostEqual(c["MIN_COLOR_FRACTION"], 0.70)     # :179
        self.assertEqual(c["CONFIRM_FRAMES"], 2)            # :169
        self.assertAlmostEqual(c["HOLD_SECONDS"], 0.30)     # :171
        self.assertEqual(c["TASK_ID"], 1)                   # :39
        self.assertEqual(c["GATEWAY_PORT"], 8765)           # :38

    def test_61_colors_never_share_a_hue_bin(self):
        """六色互不串（:184-192）：彩色色相两两不交；black 是 S/V 盒，单列。"""
        ranges = self.consts["COLOR_RANGES"]
        chroma = ("red", "orange", "yellow", "green", "cyan", "blue")
        flats = [(name, int(lo[0]), int(hi[0]))
                 for name in chroma for lo, hi in ranges[name]]
        for i in range(len(flats)):
            for j in range(i + 1, len(flats)):
                n1, a1, b1 = flats[i]
                n2, a2, b2 = flats[j]
                if n1 == n2:
                    continue
                with self.subTest(a=n1, b=n2):
                    self.assertTrue(b1 < a2 or b2 < a1,
                                    "%s[%d,%d] 与 %s[%d,%d] 色相重叠" % (n1, a1, b1, n2, a2, b2))
        # black 横跨全部 H —— 它只能靠 S/V 盒与 :254/:259 约束
        self.assertEqual(ranges["black"][0][0][0], 0)
        self.assertEqual(ranges["black"][0][1][0], 179)

    def test_62_black_window_overlaps_the_prism_colors(self):
        """:191 的 black 盒 vs :188/:185 的 V 下限 —— 幻影窗口的算术。"""
        ranges = self.consts["COLOR_RANGES"]
        black = ranges["black"][0]
        s_hi, v_hi = int(black[1][1]), int(black[1][2])     # (179,150,50) → 150, 50
        core_v = 38                                         # :258 深色核心上界
        self.assertLess(core_v, v_hi, ":259 的核心闸比 black 盒更严")
        floors = {name: int(ranges[name][0][0][2])          # 各色的 V 下限
                  for name in ("red", "orange", "yellow", "green", "cyan", "blue")}
        windows = {k: max(0, min(v_hi, core_v) - v + 1) for k, v in floors.items()}
        self.assertEqual(windows["blue"], 9, "blue V=[30,38] → 暴露面最大（棱柱 4）")
        self.assertEqual(windows["red"], 4, "red V=[35,38]（棱柱 3）")
        self.assertEqual(windows["green"], 4)
        self.assertEqual(windows["cyan"], 4)
        self.assertEqual(windows["orange"], 0, ":259 核心闸挡住了橙色幻影")
        self.assertEqual(windows["yellow"], 0)
        self.assertEqual(s_hi, 150, "V6 把 black 的 S 上限从 V3 的 100 放宽到 150")


# ─────────────────────────────────────────────────────────────────────────────
# 9) ②(2026-09-21) 拒绝计数按颜色分开 —— 不需要 cv2
#    cv2 只在函数体内被引用，故塞一个空模块即可完成 import。
# ─────────────────────────────────────────────────────────────────────────────
class RejectCounterTest(unittest.TestCase):
    """全局计数与按色计数必须同步，且没有闸口绕过 _bump 偷偷自增。"""

    @classmethod
    def setUpClass(cls):
        saved = sys.modules.get("cv2")
        sys.modules["cv2"] = types.ModuleType("cv2")
        try:
            cls.v6 = importlib.import_module("stage1_color_v6_send")
        finally:
            if saved is None:
                sys.modules.pop("cv2", None)
            else:
                sys.modules["cv2"] = saved
        cls.src = (DEPLOY_DIR / "stage1_color_v6_send.py").read_text(encoding="utf-8")

    def test_60_bump_updates_global_and_per_colour(self):
        v6 = self.v6
        v6._REJ.clear()
        v6._REJ_C.clear()
        v6._bump("c1_area", "red")
        v6._bump("c1_area", "red")
        v6._bump("c1_area", "black")
        v6._bump("c8_saturated")                      # 无颜色：只进全局
        self.assertEqual(v6._REJ, {"c1_area": 3, "c8_saturated": 1})
        self.assertEqual(v6._REJ_C, {"c1_area": {"red": 2, "black": 1}})

    def test_61_no_gate_bypasses_bump(self):
        """颜色循环里不许出现 `_REJ[...] += 1`，否则按色计数会静默漏掉。

        c8 不在颜色循环内，且它是 `_REJ["c8_saturated"] = _sat`（普通赋值：
        存的是像素数而不是次数），所以它既不该、也不会出现在这里。
        """
        raw = set()
        for node in ast.walk(ast.parse(self.src)):
            if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Subscript):
                base = node.target.value
                if isinstance(base, ast.Name) and base.id == "_REJ":
                    raw.add(getattr(node.target.slice, "value", "?"))
        self.assertEqual(raw, set(),
                         "这些闸口直接用 _REJ[...] += 1，按色计数会漏：%s" % sorted(raw))
        for gate in ("c1_area", "c2_border", "c3_aspect_extent", "c4_color_frac",
                     "c5_black_core", "c6_black_mutex", "c7_min_size"):
            self.assertIn('_bump("%s"' % gate, self.src, "闸口 %s 没有走 _bump" % gate)

    def _optional_param(self, fname, pname):
        """返回函数 fname 的参数 pname 的默认值节点；不是"有默认值的参数"就失败。

        用 AST 查而不是正则 —— 正则会因为"后面又加了个参数"这种正常改动而变红
        （2026-09-21 加 gripper_mask 时就把它搞红过一次，属于测试自己太脆）。
        """
        fn = next(n for n in ast.walk(ast.parse(self.src))
                  if isinstance(n, ast.FunctionDef) and n.name == fname)
        args = [a.arg for a in fn.args.args]
        self.assertIn(pname, args, "%s 没有参数 %s" % (fname, pname))
        first_default = len(args) - len(fn.args.defaults)
        idx = args.index(pname)
        self.assertGreaterEqual(idx, first_default,
                                "%s 的 %s 不是有默认值的参数" % (fname, pname))
        return fn.args.defaults[idx - first_default]

    def test_62_trace_is_optional_so_the_live_path_is_untouched(self):
        """trace 必须是默认 None 的关键字参数：不传就等于没有这段代码。"""
        d = self._optional_param("analyze", "trace")
        self.assertIsInstance(d, ast.Constant)
        self.assertIsNone(d.value, "trace 的默认值必须是 None")

    def test_65_gripper_mask_is_optional_and_guarded(self):
        """gripper_mask 不传时必须完全不生效 —— 否则线上没标定就会被改行为。"""
        d = self._optional_param("analyze", "gripper_mask")
        self.assertIsInstance(d, ast.Constant)
        self.assertIsNone(d.value, "gripper_mask 的默认值必须是 None")
        # 判据必须带 None 守卫，且必须只对 black 生效
        self.assertIn('if _gm is not None and color == "black":', self.src)
        self.assertIn('_bump("c9_gripper_mask", color)', self.src)

    def test_63_mark_is_a_noop_without_trace(self):
        v6 = self.v6
        v6._mark(None, "c1_area")                    # 不抛异常即为通过
        v6._mark(None, gate="c1_area", edge=3)
        d = {}
        v6._mark(d, "c2_border", edge=2)
        self.assertEqual(d, {"gate": "c2_border", "edge": 2})

    def test_64_forensic_has_no_second_copy_of_the_gates(self):
        """⑤ 回归：取证脚本不许再有 analyze() 副本，且必须走 trace。"""
        fsrc = (DEPLOY_DIR / "forensic_v6_frame.py").read_text(encoding="utf-8")
        self.assertNotIn("def analyze_instrumented(", fsrc)
        self.assertIn("trace=tr", fsrc)


def _metrics_table():
    """打印合成图度量表 —— 现场查因时把这张表和真实日志对照。"""
    if v6 is None:
        print("[skip] 未安装 cv2，跳过合成图度量表")
        return
    pal = _palette()
    print("=" * 80)
    print("合成图度量表（320 帧；area 已由 analyze() 换算回 320 帧像素²）")
    print("%-16s %-11s %4s %9s %8s %7s %18s" % ("shape", "palette", "bin", "area", "frac",
                                                "color", "bbox"))
    print("-" * 80)
    for shape in ("square", "disc", "tri0", "tri15", "tri30", "tri45"):
        for pname in ("red", "blue", "green", "cyan", "orange", "black",
                      "blue_dark", "red_dark", "green_dark", "shadow_deep", "shadow_light"):
            img = SyntheticPoseTest.canvas()
            color = pal[pname]
            if shape == "square":
                SyntheticPoseTest.square(img, 160, 160, 82, color)
            elif shape == "disc":
                SyntheticPoseTest.disc(img, 160, 160, 41, color)
            else:
                SyntheticPoseTest.tri(img, 160, 160, 82, color, rot=float(shape[3:]))
            results, _ = v6.analyze(img, input_rgb=False)
            if not results:
                print("%-16s %-11s %4s %9s %8s %7s %18s"
                      % (shape, pname, "-", "-", "-", "-", "DROPPED"))
            for r in results:
                print("%-16s %-11s %4d %9.0f %8.3f %7s %18s"
                      % (shape, pname, r["bin"], r["area"], r["color_fraction"],
                         r["color"], r["bbox"]))
    print("=" * 80)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):        # Windows 控制台 GBK
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:                       # noqa: BLE001
            pass
    if v6 is None:
        print("[warn] %s\n       几何/线格式断言仍会运行。" % NEEDS_CV2)
    else:
        _metrics_table()
    unittest.main(verbosity=2)
