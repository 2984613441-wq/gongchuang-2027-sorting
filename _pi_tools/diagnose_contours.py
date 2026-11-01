#!/usr/bin/env python3
"""诊断：img_00026 里 5 个物件的真实轮廓指标。

已知这帧内容：
  左上   黄色长方体     → 期望 cuboid (1)
  中右   红色五棱柱     → 期望 pentagonal_prism (3)
  左中   绿色正四面体   → 期望 tetrahedron (5)
  下中   红色圆锥       → 期望 cone (4)
  右下   黄色正方体     → 期望 cube (0)

打印每个轮廓的：面积、bbox、长宽比、圆形度、approxPolyDP 顶点数、
填充率、径向亮度相关系数。
"""

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FRAME = (ROOT / "_new_capture" / "whitetray_1793028347" / "_clean3"
         / "img_00026.jpg")

COLOR_HSV = {
    "red": [((165, 70, 40), (179, 255, 255)), ((0, 70, 40), (10, 255, 255))],
    "yellow": [((15, 70, 40), (32, 255, 255))],
    "green": [((55, 60, 30), (90, 255, 255))],
    "blue": [((95, 70, 30), (130, 255, 255))],
}


def radial_corr(gray, contour):
    mask = np.zeros(gray.shape, np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    ys, xs = np.nonzero(mask)
    if len(xs) < 50:
        return 0.0
    M = cv2.moments(contour)
    if M["m00"] <= 0:
        return 0.0
    cx, cy = M["m10"] / M["m00"], M["m01"] / M["m00"]
    d = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
    v = gray[ys, xs].astype(np.float32)
    if d.std() < 1e-6 or v.std() < 1e-6:
        return 0.0
    return float(np.corrcoef(d, v)[0, 1])


def main():
    img = cv2.imdecode(np.fromfile(str(FRAME), dtype=np.uint8),
                       cv2.IMREAD_COLOR)
    if img is None:
        print("❌ 读不到图")
        return 1
    H, W = img.shape[:2]
    ia = W * H
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    print("=" * 100)
    print("  img_00026 轮廓指标诊断  (%dx%d)" % (W, H))
    print("=" * 100)
    print("  %-7s %-6s %-5s %-5s %-6s %-6s %-6s %-7s %-6s %s"
          % ("颜色", "x", "y", "w", "h", "ratio", "circ", "nv", "fill", "radial"))
    print("-" * 100)

    objects = []
    for color, ranges in COLOR_HSV.items():
        mask = None
        for lo, hi in ranges:
            m = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
            mask = m if mask is None else cv2.bitwise_or(mask, m)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, 2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, 1)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            a = cv2.contourArea(c)
            if a < ia * 0.0012 or a > ia * 0.22:
                continue
            x, y, w, h = cv2.boundingRect(c)
            if w == 0 or h == 0:
                continue
            ratio = max(w, h) / float(min(w, h))
            peri = cv2.arcLength(c, True)
            circ = 4 * np.pi * a / (peri * peri) if peri > 0 else 0.0
            fill = a / float(w * h)
            # 多个 eps 采样
            nvs = {}
            for epsr in (0.010, 0.020, 0.030, 0.050):
                ap = cv2.approxPolyDP(c, epsr * peri, True)
                nvs[epsr] = len(ap)
            rc = radial_corr(gray, c)
            objects.append((color, x, y, w, h, ratio, circ, nvs, fill, rc, c))
            print("  %-7s %-6d %-5d %-5d %-5d %-6.2f %-6.3f %-6s %-7.2f %+.3f"
                  % (color, x, y, w, h, ratio, circ,
                     "/".join(str(nvs[e]) for e in (0.010, 0.020, 0.030, 0.050)),
                     fill, rc))

    print()
    print("=" * 100)
    print("  分析")
    print("=" * 100)
    print("  nv 列 = eps 为 0.010/0.020/0.030/0.050 时的顶点数")
    print("  期望：三角形≈3、四边形≈4、五边形≈5、圆>6（但 eps 大时会退化成 4~5）")
    print()
    # 按 y 排序对应物件
    print("  按位置对应物件（y 升序）:")
    for o in sorted(objects, key=lambda t: t[2]):
        color, x, y, w, h, ratio, circ, nvs, fill, rc, _ = o
        print("    (%3d,%3d) %-6s  w=%d h=%d ratio=%.2f circ=%.3f nv=%s fill=%.2f radial=%+.3f"
              % (x, y, color, w, h, ratio, circ,
                 "/".join(str(nvs[e]) for e in (0.010, 0.020, 0.030, 0.050)),
                 fill, rc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
