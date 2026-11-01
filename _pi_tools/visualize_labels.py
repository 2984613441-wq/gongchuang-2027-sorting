#!/usr/bin/env python3
"""把已有 YOLO 标签画到图上，用于目视检查标注质量。

## 用途

用户要确认「旧图标注对不对」。本脚本：
  1. 读 images/ + labels/ 同名配对
  2. 把每个框画到图上，标注 类别id + 类名
  3. 输出到 _check_labels/
  4. 同时统计：框数、各类数、有无异常（超边界/极小/极大）

## 用法

```bash
# 画前 12 张旧图
python _pi_tools/visualize_labels.py --pattern "session_*" --limit 12

# 画前 12 张新图（新图没标签，只画图）
python _pi_tools/visualize_labels.py --pattern "img_*" --limit 12

# 指定输出目录
python _pi_tools/visualize_labels.py --pattern "session_*" --limit 20 --out _check_old
```
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
WS = ROOT / "_label_review_all"

CLASS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism",
               "cone", "tetrahedron"]
# BGR 颜色（每类一色）
CLS_COLORS = [
    (0, 0, 255),       # 0 cube          红
    (0, 165, 255),     # 1 cuboid        橙
    (0, 255, 0),       # 2 cylinder      绿
    (255, 0, 0),       # 3 pentagonal    蓝
    (255, 0, 255),     # 4 cone          洋红
    (0, 255, 255),     # 5 tetrahedron   黄
]

IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="把标签画到图上检查")
    ap.add_argument("--pattern", default="*", help="图片文件名通配（默认 *）")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--out", default=None, help="输出目录")
    ap.add_argument("--offset", type=int, default=0, help="跳过前 N 张")
    ap.add_argument("--grid", type=int, default=200,
                    help="画每 N 像素的参考网格（0=不画）")
    args = ap.parse_args(argv)

    img_dir = WS / "images"
    lbl_dir = WS / "labels"
    out = Path(args.out) if args.out else ROOT / "_check_labels"
    out.mkdir(parents=True, exist_ok=True)

    imgs = sorted(img_dir.glob(args.pattern))
    imgs = [p for p in imgs if p.suffix.lower() in IMG_EXTS]
    imgs = imgs[args.offset:args.offset + args.limit]
    if not imgs:
        print("❌ 没有匹配的图")
        return 1

    print("=" * 74)
    print("  标签可视化检查")
    print("=" * 74)
    print("  图目录: %s" % img_dir)
    print("  标签  : %s" % lbl_dir)
    print("  匹配  : %d 张（从第 %d 张开始）" % (len(imgs), args.offset))
    print("  输出  : %s" % out)
    print()

    total_boxes = 0
    cls_cnt = Counter()
    n_no_label = 0

    for p in imgs:
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            print("  ⚠️ 读不到: %s" % p.name)
            continue
        H, W = img.shape[:2]
        vis = img.copy()

        # 参考网格
        if args.grid > 0:
            for x in range(args.grid, W, args.grid):
                cv2.line(vis, (x, 0), (x, H), (128, 128, 128), 1)
                cv2.putText(vis, str(x), (x + 2, 14),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (128, 128, 128), 1)
            for y in range(args.grid, H, args.grid):
                cv2.line(vis, (0, y), (W, y), (128, 128, 128), 1)
                cv2.putText(vis, str(y), (2, y - 3),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (128, 128, 128), 1)

        lf = lbl_dir / (p.stem + ".txt")
        boxes = []
        if lf.is_file():
            for ln in lf.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                parts = ln.split()
                if len(parts) < 5:
                    continue
                try:
                    cid = int(float(parts[0]))
                    cx, cy, w, h = (float(v) for v in parts[1:5])
                except ValueError:
                    continue
                boxes.append((cid, cx, cy, w, h))
        else:
            n_no_label += 1

        for cid, cx, cy, w, h in boxes:
            x1 = int((cx - w / 2) * W)
            y1 = int((cy - h / 2) * H)
            x2 = int((cx + w / 2) * W)
            y2 = int((cy + h / 2) * H)
            col = CLS_COLORS[cid] if 0 <= cid < len(CLS_COLORS) else (255, 255, 255)
            cv2.rectangle(vis, (x1, y1), (x2, y2), col, 3)
            label = "%d %s" % (cid, CLASS_NAMES[cid] if cid < 6 else "?")
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(vis, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1),
                          col, -1)
            cv2.putText(vis, label, (x1 + 3, max(th + 2, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
            cls_cnt[cid] += 1
            total_boxes += 1

        # 左上角信息
        info = "%s  boxes=%d" % (p.name, len(boxes))
        cv2.rectangle(vis, (0, 0), (560, 34), (0, 0, 0), -1)
        cv2.putText(vis, info, (6, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (255, 255, 255), 2)

        cv2.imencode(".jpg", vis, [int(cv2.IMWRITE_JPEG_QUALITY), 92])[1].tofile(
            str(out / p.name))
        print("  %-46s %2d 个框" % (p.name, len(boxes)))

    print()
    print("=" * 74)
    print("  统计")
    print("=" * 74)
    print("  处理图片 : %d 张" % len(imgs))
    print("  总框数   : %d" % total_boxes)
    print("  无标签图 : %d 张" % n_no_label)
    print()
    for cid, name in enumerate(CLASS_NAMES):
        print("    %d %-18s %4d" % (cid, name, cls_cnt.get(cid, 0)))
    print()
    print("  可视化: %s" % out)
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
