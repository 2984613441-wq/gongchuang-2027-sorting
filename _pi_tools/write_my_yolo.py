#!/usr/bin/env python3
"""把我的「目视框」写成 YOLO 标签。

## 分工（这是重点）

· **形状 class**：我（AI）看图判定 —— cube/cuboid/cylinder/pentagonal_prism/cone/tetrahedron
· **框坐标**：我（AI）看图估算 —— 1280×720 像素坐标，误差约 ±20px（1.6% 宽，YOLO 可接受）
· **不用 HSV、不用任何颜色信息** —— 纯视觉判形

## 输入格式 my_boxes_manual.json

```json
{
  "img_00000.jpg": [[5,510,128,640,250], [3,798,105,978,278], ...],
  "img_00001.jpg": "COPY:img_00000.jpg",
  "img_00002.jpg": "DELETE",
  "img_00003.jpg": "SKIP"
}
```

· 列表元素 = `[class_id, x1, y1, x2, y2]`（像素，左上/右下）
· `"COPY:<参考帧>"` = 与参考帧同一布局，直接复制标签
· `"DELETE"` = 有手/模糊/烂图，要删
· `"SKIP"` = 不标也不删

## 类名对照

```
0 cube              正方体
1 cuboid            长方体
2 cylinder          圆柱
3 pentagonal_prism  五棱柱
4 cone              圆锥
5 tetrahedron       正四面体
```

## 用法

```bash
python _pi_tools/write_my_yolo.py            # 写标签 + 出删除清单
python _pi_tools/write_my_yolo.py --dry-run
```
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WS = ROOT / "_label_ws_6c"
IMG_DIR = WS / "images"
LBL_DIR = WS / "labels"
MANUAL = WS / "_sheets" / "my_boxes_manual.json"

CLASS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism",
               "cone", "tetrahedron"]


def get_size(p: Path) -> tuple[int, int] | None:
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            return None
        return img.shape[1], img.shape[0]
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="写目视 YOLO 标签")
    ap.add_argument("--manual", default=str(MANUAL))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    mf = Path(args.manual)
    if not mf.is_file():
        print("❌ 缺 %s" % mf)
        return 1
    manual = json.loads(mf.read_text(encoding="utf-8"))

    LBL_DIR.mkdir(parents=True, exist_ok=True)

    cls_cnt = Counter()
    n_written = 0
    n_copied = 0
    n_delete = []
    n_skip = 0
    problems = []
    sizes = {}

    def size_of(fname):
        if fname not in sizes:
            sizes[fname] = get_size(IMG_DIR / fname)
        return sizes[fname]

    def emit(fname, boxes, src_note=""):
        sz = size_of(fname)
        if sz is None:
            problems.append("%s: 读不到图" % fname)
            return False
        W, H = sz
        lines = []
        for item in boxes:
            if len(item) != 5:
                problems.append("%s: 框元素长度=%d" % (fname, len(item)))
                continue
            cid, x1, y1, x2, y2 = item
            if not (0 <= cid < 6):
                problems.append("%s: class_id=%s 越界" % (fname, cid))
                continue
            x1, x2 = min(x1, x2), max(x1, x2)
            y1, y2 = min(y1, y2), max(y1, y2)
            x1 = max(0, min(W - 1, x1)); x2 = max(0, min(W - 1, x2))
            y1 = max(0, min(H - 1, y1)); y2 = max(0, min(H - 1, y2))
            w = x2 - x1
            h = y2 - y1
            if w < 8 or h < 8:
                problems.append("%s: 框太小 %dx%d" % (fname, w, h))
                continue
            cx = (x1 + x2) / 2.0 / W
            cy = (y1 + y2) / 2.0 / H
            nw = w / float(W)
            nh = h / float(H)
            lines.append("%d %.6f %.6f %.6f %.6f" % (cid, cx, cy, nw, nh))
            cls_cnt[cid] += 1
        if not lines:
            problems.append("%s: 无有效框" % fname)
            return False
        if not args.dry_run:
            (LBL_DIR / (Path(fname).stem + ".txt")).write_text(
                "\n".join(lines) + "\n", encoding="utf-8")
        return True

    for fname in sorted(manual):
        val = manual[fname]
        if val == "DELETE":
            n_delete.append(fname)
            continue
        if val == "SKIP":
            n_skip += 1
            continue
        if isinstance(val, str) and val.startswith("COPY:"):
            ref = val[5:]
            if ref in manual and isinstance(manual[ref], list):
                if emit(fname, manual[ref], "copy from %s" % ref):
                    n_copied += 1
            else:
                problems.append("%s: COPY 参考 %s 不可用" % (fname, ref))
            continue
        if isinstance(val, list):
            if emit(fname, val):
                n_written += 1
            continue
        problems.append("%s: 无法识别的值类型 %s" % (fname, type(val).__name__))

    # ── 报告 ──────────────────────────────────────────────────────
    print("=" * 74)
    print("  写目视 YOLO 标签%s" % ("（DRY-RUN）" if args.dry_run else ""))
    print("=" * 74)
    print("  判定条目 : %d" % len(manual))
    print("  手写框   : %d 帧" % n_written)
    print("  复制     : %d 帧" % n_copied)
    print("  标记删除 : %d 帧" % len(n_delete))
    print("  标记跳过 : %d 帧" % n_skip)
    print()
    print("  各类实例数:")
    total = 0
    for cid, name in enumerate(CLASS_NAMES):
        n = cls_cnt.get(cid, 0)
        total += n
        print("    %d %-18s %4d" % (cid, name, n))
    print("    %-20s %4d" % ("合计", total))
    print()

    if n_delete:
        del_file = WS / "_sheets" / "to_delete.txt"
        if not args.dry_run:
            del_file.write_text("\n".join(n_delete) + "\n", encoding="utf-8")
        print("  删除清单: %s（%d 帧）" % (del_file, len(n_delete)))
    if problems:
        print()
        print("  ⚠️ 问题（前 12）:")
        for p in problems[:12]:
            print("    %s" % p)

    allf = {p.name for p in IMG_DIR.glob("img_*.jpg")}
    done = set(manual)
    left = sorted(allf - done)
    print()
    print("  进度: %d / %d 已判，剩 %d 帧" % (len(done & allf), len(allf), len(left)))
    if left:
        print("  下一批: %s" % ", ".join(left[:6]))
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
