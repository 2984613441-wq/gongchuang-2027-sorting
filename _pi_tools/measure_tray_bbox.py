#!/usr/bin/env python3
"""精确测出白托盘在画面里的边界（像素坐标）。

思路：托盘是画面里**最大的一块高亮低饱和区域**。
用 HSV 阈值 + 形态学 + 最大轮廓的外接矩形，得到托盘 bbox。

输出：
  · 托盘 bbox（像素）
  · 相对比例（0~1，方便换分辨率后复用）
  · 建议的 mm/px（若告知托盘物理尺寸）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="测白托盘边界")
    ap.add_argument("--src", required=True, help="图片目录")
    ap.add_argument("--n", type=int, default=12, help="取样帧数（均匀抽）")
    ap.add_argument("--tray-w-mm", type=float, default=185.0,
                    help="托盘物理宽度（mm），用于算 mm/px")
    ap.add_argument("--tray-h-mm", type=float, default=190.0,
                    help="托盘物理高度（mm）")
    args = ap.parse_args(argv)

    src = Path(args.src)
    frames = sorted(src.glob("*.jpg"))
    if not frames:
        print("❌ 没有 .jpg")
        return 1

    # 均匀抽样，避开开头可能正在放置的帧
    step = max(1, len(frames) // args.n)
    sample = frames[::step][:args.n]

    print("=" * 72)
    print("  白托盘边界测量")
    print("=" * 72)
    print("  目录: %s" % src)
    print("  抽样: %d / %d 帧" % (len(sample), len(frames)))
    print()

    boxes = []
    for p in sample:
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            continue
        H, W = img.shape[:2]
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # 托盘：高亮 + 低饱和
        mask = cv2.inRange(hsv,
                           np.array((0, 0, 140), np.uint8),
                           np.array((179, 60, 255), np.uint8))
        # 形态学：填补物料造成的洞
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=3)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, iterations=2)

        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        big = max(cnts, key=cv2.contourArea)
        if cv2.contourArea(big) < W * H * 0.04:
            continue
        x, y, w, h = cv2.boundingRect(big)
        boxes.append((x, y, w, h, p.name))

    if not boxes:
        print("❌ 一帧都没测到托盘")
        return 1

    xs = [b[0] for b in boxes]
    ys = [b[1] for b in boxes]
    ws = [b[2] for b in boxes]
    hs = [b[3] for b in boxes]

    def med(v):
        return sorted(v)[len(v) // 2]

    x0, y0, bw, bh = med(xs), med(ys), med(ws), med(hs)
    W = 1280
    H = 720

    print("  逐帧 bbox（x, y, w, h）:")
    for b in boxes:
        print("    %-14s  (%4d, %3d, %4d, %4d)" % (b[4], b[0], b[1], b[2], b[3]))
    print()
    print("  中位数 bbox: x=%d  y=%d  w=%d  h=%d" % (x0, y0, bw, bh))
    print()
    print("  相对比例（换分辨率也能用）:")
    print("    TRAY_ROI = (%.4f, %.4f, %.4f, %.4f)"
          % (x0 / W, y0 / H, (x0 + bw) / W, (y0 + bh) / H))
    print()
    print("  mm/px 估算（托盘物理 %.0f x %.0f mm）:"
          % (args.tray_w_mm, args.tray_h_mm))
    print("    水平: %.0f / %d = %.4f mm/px" % (args.tray_w_mm, bw, args.tray_w_mm / bw))
    print("    竖直: %.0f / %d = %.4f mm/px" % (args.tray_h_mm, bh, args.tray_h_mm / bh))
    print()
    print("  ⚠️ 若两者差异大（>5%），说明有透视/畸变，需要重新标定相机")
    print()

    # 画出来验证
    out_dir = src / "_tray_bbox_check"
    out_dir.mkdir(exist_ok=True)
    for i, p in enumerate(sample[:6]):
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            continue
        cv2.rectangle(img, (x0, y0), (x0 + bw, y0 + bh), (0, 255, 0), 3)
        cv2.putText(img, "TRAY %dx%d" % (bw, bh), (x0 + 6, y0 + 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
        out = out_dir / ("check_%02d.jpg" % i)
        cv2.imencode(".jpg", img)[1].tofile(str(out))
    print("  验证图: %s" % out_dir)
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
