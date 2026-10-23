# -*- coding: utf-8 -*-
"""量出各形状的 rect_fill / rect_aspect / circularity / n_vertices 实际值。

用途：**为阈值提供实测依据**，而不是拍脑袋。
运行：python _pi_tools/measure_shape_features.py
"""
import math
import sys
from pathlib import Path

import cv2
import numpy as np

SRC = Path(__file__).resolve().parent.parent / "视觉" / "src"
sys.path.insert(0, str(SRC))

from sorting_vision.shape_geometry import classify_contour_shape  # noqa: E402


def poly(n, r, cx=200.0, cy=200.0, start=0.0):
    pts = []
    for i in range(n):
        a = math.radians(start + 360.0 * i / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return np.array(pts, np.float32).reshape(-1, 1, 2).astype(np.int32)


def rect(w, h, cx=200.0, cy=200.0, ang=0.0):
    hw, hh = w / 2.0, h / 2.0
    base = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    a = math.radians(ang)
    ca, sa = math.cos(a), math.sin(a)
    pts = [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in base]
    return np.array(pts, np.float32).reshape(-1, 1, 2).astype(np.int32)


cases = [
    ("正方形 100x100",          rect(100, 100)),
    ("正方形 100x100 @8deg",    rect(100, 100, ang=8.0)),
    ("正方形 100x100 @45deg",   rect(100, 100, ang=45.0)),
    ("长方形 160x80",           rect(160, 80)),
    ("长方形 160x80 @30deg",    rect(160, 80, ang=30.0)),
    ("长方形 200x60 (3.33:1)",  rect(200, 60)),
    ("三角形 r=90",             poly(3, 90)),
    ("三角形 r=90 @25deg",      poly(3, 90, start=25.0)),
    ("五边形 r=90",             poly(5, 90)),
    ("五边形 r=90 @36deg",      poly(5, 90, start=36.0)),
    ("六边形 r=90",             poly(6, 90)),
    ("圆 r=90 (120点)",         poly(120, 90)),
    ("圆 r=50 (120点)",         poly(120, 50)),
]

print(f"{'形状':<26} {'n_vert':>6} {'rect_fill':>10} {'rect_asp':>9} "
      f"{'circ':>7} {'aabb_ext':>9}  {'判定':<18} {'置信'}")
print("-" * 106)
for name, c in cases:
    r = classify_contour_shape(c)
    e = r.evidence
    if "rect_fill" not in e:
        print(f"{name:<26} {'--':>6}  (degenerate: {e})")
        continue
    print(f"{name:<26} {e['n_vertices']:>6} {e['rect_fill']:>10.4f} "
          f"{e['rect_aspect']:>9.4f} {e['circularity']:>7.4f} "
          f"{e['aabb_extent']:>9.4f}  {r.shape:<18} {r.confidence}")

print()
print("理论值参考：")
print("  四边形 rect_fill = 1.000")
print("  五边形 rect_fill ≈ ?  ← 以实测为准")
print("  圆盘   rect_fill = π/4 = 0.7854")
print("  三角形 rect_fill = 0.500")
