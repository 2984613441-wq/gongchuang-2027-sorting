#!/usr/bin/env python3
"""用最简单的轮廓特征自动标注（不依赖 shape_geometry 的复杂阈值）。

## 判据（俯视轮廓）

| 轮廓 | 形状 | 判据 |
|---|---|---|
| 三角形（3 顶点）| 正四面体 | approxPolyDP 顶点数 == 3 |
| 五边形（5 顶点）| 五棱柱 | 顶点数 == 5 |
| 四边形（4 顶点）| 正方体 / 长方体 | 顶点数 == 4，靠长宽比分 |
| 圆形（>6 顶点且圆形度高）| 圆柱 / 圆锥 | 圆形度 > 0.85 |

## 两处歧义怎么分

**① 正方体 vs 长方体**
   俯视都是正方形/长方形。用长宽比：
     ratio < 1.20 ⇒ cube（正方形）
     ratio >= 1.20 ⇒ cuboid（长方形）
   ⚠️ 正方体俯视是正方形；长方体如果是 3:1:1 则俯视是 3:1 ⇒ 很好分。

**② 圆柱 vs 圆锥**
   俯视都是圆。用**内部亮度梯度**：
     圆柱：顶面是平的 ⇒ 亮度均匀（标准差小）
     圆锥：有锥面 ⇒ 中心亮、边缘暗，呈径向渐变（标准差大）
   做法：取轮廓内部，算「距中心距离」与该点亮度的相关性。
     圆锥：距离越远越暗 ⇒ 相关系数强负
     圆柱：无明显相关

## 输出
  · 可视化图（框 + 判定 + 置信）
  · 可选写 YOLO 标签
  · 统计（各类数量、歧义未决数）
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

# 6 类
CLS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism", "cone",
             "tetrahedron"]

# 5 色 HSV（OpenCV H 0~179）
COLOR_HSV = {
    "red": [((165, 70, 40), (179, 255, 255)), ((0, 70, 40), (10, 255, 255))],
    "yellow": [((15, 70, 40), (32, 255, 255))],
    "green": [((55, 60, 30), (90, 255, 255))],
    "blue": [((95, 70, 30), (130, 255, 255))],
    "white": [((0, 0, 180), (179, 40, 255))],
}

MIN_AREA_FRAC = 0.0012
MAX_AREA_FRAC = 0.22

# 顶点数判定的多边形近似精度（相对周长）
APPROX_EPS_RATIO = 0.025

# 圆形度阈值
CIRCULARITY_MIN = 0.82

# 正方体/长方体长宽比阈值
CUBE_RATIO_MAX = 1.20

# 圆柱/圆锥：径向亮度梯度相关系数阈值（越负越像圆锥）
CONE_CORR_MAX = -0.35


def poly_vertices(contour) -> int:
    peri = cv2.arcLength(contour, True)
    eps = APPROX_EPS_RATIO * peri
    ap = cv2.approxPolyDP(contour, eps, True)
    return len(ap)


def circularity(contour) -> float:
    a = cv2.contourArea(contour)
    p = cv2.arcLength(contour, True)
    if p <= 0:
        return 0.0
    return 4.0 * np.pi * a / (p * p)


def radial_brightness_corr(gray, contour):
    """算「距中心距离」与「亮度」的相关系数。

    圆锥：中心亮边缘暗 ⇒ 距离-亮度 强负相关
    圆柱：平面 ⇒ 弱相关
    """
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


def classify_contour(contour, gray) -> tuple[int | None, str, str]:
    """返回 (class_id 或 None, 理由, 备注)。"""
    a = cv2.contourArea(contour)
    x, y, w, h = cv2.boundingRect(contour)
    if w == 0 or h == 0:
        return None, "zero-size", ""
    ratio = max(w, h) / float(min(w, h))
    circ = circularity(contour)
    nv = poly_vertices(contour)
    fill = a / float(w * h)

    # ── 圆形（圆柱 / 圆锥）────────────────────────────────────────
    # 🔴 2026-10-26 修 bug：原来写成 `circ >= 0.82 and nv >= 6`，
    #    但 approxPolyDP 经常把圆近似成 4~5 个顶点 ⇒ 圆形掉进 `nv == 5`
    #    被判成五棱柱（实测 115 个 pentagonal_prism、只有 4 个 cylinder）。
    #    ⇒ 圆形度够高就直接判圆，**不看顶点数**（圆形度是更强的信号）。
    if circ >= CIRCULARITY_MIN:
        corr = radial_brightness_corr(gray, contour)
        if corr <= CONE_CORR_MAX:
            return 4, "circle+radial_grad corr=%.2f" % corr, "cone"
        return 2, "circle+flat corr=%.2f" % corr, "cylinder"

    # ── 三角形（正四面体）────────────────────────────────────────
    if nv == 3:
        return 5, "3 vertices fill=%.2f" % fill, "tetrahedron"

    # ── 五边形（五棱柱）──────────────────────────────────────────
    if nv == 5:
        return 3, "5 vertices", "pentagonal_prism"

    # ── 四边形（正方体 / 长方体）────────────────────────────────
    if nv == 4:
        if ratio < CUBE_RATIO_MAX:
            return 0, "4 vertices ratio=%.2f" % ratio, "cube"
        return 1, "4 vertices ratio=%.2f" % ratio, "cuboid"

    # ── 顶点数不在 3/4/5 但也不是圆 ───────────────────────────────
    # 退一步：按顶点数近似
    if nv <= 3:
        return 5, "nv=%d->tetra" % nv, "tetrahedron?"
    if nv == 4:
        return (0 if ratio < CUBE_RATIO_MAX else 1), "nv=4 fallback", "?"
    if nv <= 6:
        return 3, "nv=%d->prism" % nv, "pentagonal_prism?"
    return None, "nv=%d circ=%.2f undecided" % (nv, circ), "?"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="简单轮廓特征自动标注")
    ap.add_argument("--src", required=True)
    ap.add_argument("--vis-dir", default=None)
    ap.add_argument("--write-labels", action="store_true")
    ap.add_argument("--include-white", action="store_true",
                    help="也处理白色（默认跳过，因为白托盘会混）")
    args = ap.parse_args(argv)

    src = Path(args.src)
    frames = sorted(src.glob("*.jpg"))
    if not frames:
        print("❌ 没有 .jpg")
        return 1
    vis_dir = Path(args.vis_dir) if args.vis_dir else src / "_auto2_vis"
    vis_dir.mkdir(parents=True, exist_ok=True)

    colors = ("red", "yellow", "green", "blue")
    if args.include_white:
        colors = colors + ("white",)

    print("=" * 76)
    print("  简单轮廓特征自动标注")
    print("=" * 76)
    print("  目录: %s" % src)
    print("  帧数: %d" % len(frames))
    print("  颜色: %s" % (colors,))
    print()

    cls_counter = Counter()
    n_undecided = 0
    per_frame = []

    for i, p in enumerate(frames, 1):
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            continue
        H, W = img.shape[:2]
        img_area = W * H
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        vis = img.copy()

        lines = []
        cnt_this = 0

        for color in colors:
            mask = None
            for lo, hi in COLOR_HSV[color]:
                m = cv2.inRange(hsv, np.array(lo, np.uint8),
                                np.array(hi, np.uint8))
                mask = m if mask is None else cv2.bitwise_or(mask, m)
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, 2)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, 1)
            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
            for c in cnts:
                a = cv2.contourArea(c)
                if a < img_area * MIN_AREA_FRAC or a > img_area * MAX_AREA_FRAC:
                    continue
                cid, why, note = classify_contour(c, gray)
                x, y, w2, h2 = cv2.boundingRect(c)
                if cid is None:
                    n_undecided += 1
                    cv2.rectangle(vis, (x, y), (x + w2, y + h2), (0, 165, 255), 2)
                    cv2.putText(vis, "%s? %s" % (color[:2], why[:14]),
                                (x, max(13, y - 4)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 165, 255), 1)
                    continue
                cls_counter[cid] += 1
                cnt_this += 1
                cx = (x + w2 / 2.0) / W
                cy = (y + h2 / 2.0) / H
                nw = w2 / float(W)
                nh = h2 / float(H)
                lines.append("%d %.6f %.6f %.6f %.6f" % (cid, cx, cy, nw, nh))

                cv2.rectangle(vis, (x, y), (x + w2, y + h2), (0, 255, 0), 2)
                cv2.putText(vis, "%d %s" % (cid, CLS_NAMES[cid][:10]),
                            (x, max(13, y - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)

        per_frame.append(cnt_this)
        if args.write_labels:
            p.with_suffix(".txt").write_text(
                "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

        cv2.imencode(".jpg", vis, [int(cv2.IMWRITE_JPEG_QUALITY), 90])[1].tofile(
            str(vis_dir / p.name))

        if i % 10 == 0 or i == len(frames):
            print("  [%d/%d] 已处理（累计判定 %d）"
                  % (i, len(frames), sum(per_frame)))

    print()
    print("=" * 76)
    print("  统计")
    print("=" * 76)
    print("  每帧判定数 : 平均 %.1f" % (sum(per_frame) / max(1, len(per_frame))))
    print("  未定       : %d" % n_undecided)
    print()
    print("  各类:")
    for cid, name in enumerate(CLS_NAMES):
        print("    %d %-18s %4d" % (cid, name, cls_counter.get(cid, 0)))
    print()
    print("  可视化: %s" % vis_dir)
    if args.write_labels:
        print("  ✅ 已写 .txt（**必须人工复核**）")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
