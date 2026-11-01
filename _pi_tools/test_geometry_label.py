#!/usr/bin/env python3
"""测试：用 HSV 分色 + 几何判形 给新帧自动打标签，不依赖任何模型。

流程：
  1. 对每种颜色做 HSV 分割（5 色窗口）
  2. 每种颜色里找连通域
  3. 每个连通域用 shape_geometry.classify_contour_shape() 判形状
  4. 输出：可视化 + 统计（看判对了多少）

⚠️ 已知难点：圆柱 vs 圆锥俯视都是圆 ⇒ 几何可能返回"未定"。
   这类会单独标出，需要人工或用明暗梯度进一步区分。
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "视觉" / "src"))

import cv2
import numpy as np

from sorting_vision.shape_geometry import (
    SHAPE_CONE,
    SHAPE_CUBE,
    SHAPE_CUBOID,
    SHAPE_CYLINDER,
    SHAPE_PENTAGONAL_PRISM,
    SHAPE_TETRAHEDRON,
    classify_contour_shape,
)

# 6 类 → class_id（与 _dataset_yolo_6c 对齐）
SHAPE_TO_CLS = {
    SHAPE_CUBE: 0,
    SHAPE_CUBOID: 1,
    SHAPE_CYLINDER: 2,
    SHAPE_PENTAGONAL_PRISM: 3,
    SHAPE_CONE: 4,
    SHAPE_TETRAHEDRON: 5,
}
CLS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism", "cone",
             "tetrahedron"]

# 5 色 HSV（OpenCV H 0~179）—— 基于实测：红 171~173、黄 20~22、绿 69~75、蓝 107~112
COLOR_HSV = {
    "red": [((165, 70, 40), (179, 255, 255)), ((0, 70, 40), (10, 255, 255))],
    "yellow": [((15, 70, 40), (30, 255, 255))],
    "green": [((55, 60, 30), (90, 255, 255))],
    "blue": [((95, 70, 30), (130, 255, 255))],
    # 白：低饱和高亮。⚠️ 白托盘也是白的 ⇒ 白件最难，可能分不开
    "white": [((0, 0, 175), (179, 45, 255))],
}

MIN_AREA_FRAC = 0.0012      # 最小面积（占全图）
MAX_AREA_FRAC = 0.25        # 最大面积（防把托盘当下物料）


def segment_color(hsv, color):
    mask = None
    for lo, hi in COLOR_HSV[color]:
        m = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
        mask = m if mask is None else cv2.bitwise_or(mask, m)
    return mask


def main():
    src = ROOT / "_new_capture" / "whitetray_1793028347" / "_clean3"
    vis_dir = src / "_auto_vis"
    vis_dir.mkdir(exist_ok=True)

    frames = sorted(src.glob("*.jpg"))
    print("=" * 76)
    print("  几何 + HSV 自动打标测试")
    print("=" * 76)
    print("  目录: %s" % src)
    print("  帧数: %d" % len(frames))
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
        vis = img.copy()

        found = []
        for color in ("red", "yellow", "green", "blue"):   # white 先跳过（最难）
            cmask = segment_color(hsv, color)
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
            cmask = cv2.morphologyEx(cmask, cv2.MORPH_CLOSE, k, 2)
            cmask = cv2.morphologyEx(cmask, cv2.MORPH_OPEN, k, 1)
            cnts, _ = cv2.findContours(cmask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
            for c in cnts:
                a = cv2.contourArea(c)
                if a < img_area * MIN_AREA_FRAC or a > img_area * MAX_AREA_FRAC:
                    continue
                gs = classify_contour_shape(c)
                shape = getattr(gs, "shape", None)
                decided = getattr(gs, "is_decided", False)
                if not decided or shape not in SHAPE_TO_CLS:
                    n_undecided += 1
                    x, y, w2, h2 = cv2.boundingRect(c)
                    cv2.rectangle(vis, (x, y), (x + w2, y + h2),
                                  (0, 165, 255), 2)
                    cv2.putText(vis, "%s?%s" % (color[:1], shape or "?"),
                                (x, max(14, y - 4)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 165, 255), 1)
                    continue
                cid = SHAPE_TO_CLS[shape]
                cls_counter[cid] += 1
                found.append((cid, c, shape, color))

                x, y, w2, h2 = cv2.boundingRect(c)
                cv2.rectangle(vis, (x, y), (x + w2, y + h2), (0, 255, 0), 2)
                label = "%d %s" % (cid, CLS_NAMES[cid])
                cv2.putText(vis, label, (x, max(14, y - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)

        per_frame.append(len(found))
        cv2.imencode(".jpg", vis, [int(cv2.IMWRITE_JPEG_QUALITY), 90])[1].tofile(
            str(vis_dir / p.name))

        if i % 10 == 0 or i == len(frames):
            print("  [%d/%d] 已处理" % (i, len(frames)))

    print()
    print("=" * 76)
    print("  统计")
    print("=" * 76)
    print("  每帧判定成功 : 平均 %.1f 个" % (sum(per_frame) / max(1, len(per_frame))))
    print("  未定/失败    : %d 个" % n_undecided)
    print()
    print("  各类判定数:")
    for cid, name in enumerate(CLS_NAMES):
        n = cls_counter.get(cid, 0)
        print("    %d %-18s %4d" % (cid, name, n))
    print()
    print("  可视化: %s" % vis_dir)
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
