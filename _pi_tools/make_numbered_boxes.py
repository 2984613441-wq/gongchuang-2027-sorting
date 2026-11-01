#!/usr/bin/env python3
"""给代表帧生成「带编号的候选框」图，供 AI/人工逐个指定形状。

## 为什么这么做

YOLO 标签需要【像素级精确】的 bbox，但人可以看图判断形状却量不准像素。
所以拆成两步：
  1. HSV 分割 ⇒ 像素级精确的 bbox（脚本负责）
  2. 看图 + 编号 ⇒ 指定每个框的形状（人/AI 负责）

编号是稳定的：框按 (颜色优先序, y, x) 排序，编号写进 JSON，
后续 assign 脚本按编号对应形状即可。

## 用法

```bash
python _pi_tools/make_numbered_boxes.py --src _new_capture/.../_clean3
```

输出：
  <src>/_numbered/
    img_00000_boxed.jpg      ← 带编号的框图
    boxes.json               ← 每个编号的 bbox（像素 + 归一化）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

# 5 色 HSV（OpenCV H 0~179）
COLOR_HSV = {
    "red": [((165, 70, 40), (179, 255, 255)), ((0, 70, 40), (10, 255, 255))],
    "yellow": [((15, 70, 40), (32, 255, 255))],
    "green": [((55, 60, 30), (90, 255, 255))],
    "blue": [((95, 70, 30), (130, 255, 255))],
    "white": [((0, 0, 185), (179, 38, 255))],
}

# 颜色判定顺序（先红黄绿蓝，白最后 —— 白托盘容易误检）
COLOR_ORDER = ["red", "yellow", "green", "blue", "white"]

MIN_AREA_FRAC = 0.0012
MAX_AREA_FRAC = 0.22

# BGR 画框颜色（便于人眼区分）
COLOR_DRAW = {
    "red": (0, 0, 255),
    "yellow": (0, 215, 255),
    "green": (0, 200, 0),
    "blue": (255, 128, 0),
    "white": (200, 200, 200),
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成带编号的候选框图")
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--frames", default="",
                    help="只处理这些帧（逗号分隔文件名），默认全部")
    ap.add_argument("--include-white", action="store_true",
                    help="也处理白色（默认跳过，白托盘易误检）")
    args = ap.parse_args(argv)

    src = Path(args.src)
    out = Path(args.out) if args.out else src / "_numbered"
    out.mkdir(parents=True, exist_ok=True)

    if args.frames:
        want = set(args.frames.split(","))
        frames = [p for p in sorted(src.glob("*.jpg")) if p.name in want]
    else:
        frames = sorted(src.glob("*.jpg"))
    if not frames:
        print("❌ 没有匹配的帧")
        return 1

    colors = COLOR_ORDER if args.include_white else COLOR_ORDER[:-1]

    print("=" * 74)
    print("  生成带编号的候选框图")
    print("=" * 74)
    print("  源目录: %s" % src)
    print("  帧数  : %d" % len(frames))
    print("  颜色  : %s" % (colors,))
    print("  输出  : %s" % out)
    print()

    all_boxes = {}

    for p in frames:
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            continue
        H, W = img.shape[:2]
        ia = W * H
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        cands = []      # (color, x, y, w, h)
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
                if a < ia * MIN_AREA_FRAC or a > ia * MAX_AREA_FRAC:
                    continue
                x, y, w, h = cv2.boundingRect(c)
                if w < 12 or h < 12:
                    continue
                cands.append((color, x, y, w, h))

        # 排序：颜色优先序 → y 升序 → x 升序（编号稳定）
        cands.sort(key=lambda t: (colors.index(t[0]), t[2], t[1]))

        vis = img.copy()
        boxes = []
        for i, (color, x, y, w, h) in enumerate(cands, 1):
            col = COLOR_DRAW[color]
            cv2.rectangle(vis, (x, y), (x + w, y + h), col, 2)
            # 编号（黑底白字，确保可读）
            label = "%d.%s" % (i, color)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX,
                                          0.55, 2)
            cv2.rectangle(vis, (x, max(0, y - th - 6)),
                          (x + tw + 6, y), (0, 0, 0), -1)
            cv2.putText(vis, label, (x + 3, max(th + 2, y - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
            boxes.append({
                "id": i,
                "color": color,
                "px": [int(x), int(y), int(w), int(h)],
                "norm": [
                    round((x + w / 2.0) / W, 6),
                    round((y + h / 2.0) / H, 6),
                    round(w / float(W), 6),
                    round(h / float(H), 6),
                ],
                "area_frac": round(float(w * h) / ia, 5),
            })

        dst = out / p.name
        cv2.imencode(".jpg", vis, [int(cv2.IMWRITE_JPEG_QUALITY), 92])[1].tofile(
            str(dst))
        all_boxes[p.name] = {"w": W, "h": H, "boxes": boxes}
        print("  %-14s  候选 %d 个" % (p.name, len(boxes)))

    with open(out / "boxes.json", "w", encoding="utf-8") as f:
        json.dump(all_boxes, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 74)
    print("  ✅ 已输出 %d 张框图 + boxes.json" % len(all_boxes))
    print("  下一步：看框图，给每个编号指定形状")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
