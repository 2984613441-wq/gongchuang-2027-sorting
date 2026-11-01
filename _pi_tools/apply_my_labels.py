#!/usr/bin/env python3
"""把「我的判形结果」写成 YOLO 标签。

## 分工

· **坐标**：`detect_tray_boxes.py` 用 HSV 在托盘 ROI 内检测，像素级精确
· **形状**：我（AI）逐图目视判定，写进 `my_shapes.json`

## my_shapes.json 格式

```json
{
  "img_00000.jpg": {"1": 3, "2": 4, "3": 0, "4": 5, "5": 2},
  "img_00022.jpg": {"1": 3, "2": 4, "3": 0, "4": 1, "5": 2}
}
```
键 = 文件名；值 = {框编号(str): class_id}

## 特殊标记

· `"DELETE"` —— 这帧要删（有手/模糊/烂图）
· `"SKIP"`   —— 这帧不标也不删（比如空托盘）

## 用法

```bash
python _pi_tools/apply_my_labels.py            # 写标签
python _pi_tools/apply_my_labels.py --dry-run  # 只看统计
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
SHEETS = WS / "_sheets"
IMG_DIR = WS / "images"
LBL_DIR = WS / "labels"

CLASS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism",
               "cone", "tetrahedron"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="写我判定的 YOLO 标签")
    ap.add_argument("--boxes", default=str(SHEETS / "boxes_all.json"))
    ap.add_argument("--shapes", default=str(SHEETS / "my_shapes.json"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    bfile = Path(args.boxes)
    sfile = Path(args.shapes)
    if not bfile.is_file():
        print("❌ 缺 %s（先跑检测脚本）" % bfile)
        return 1
    if not sfile.is_file():
        print("❌ 缺 %s（先写判形结果）" % sfile)
        return 1

    boxes_all = json.loads(bfile.read_text(encoding="utf-8"))
    shapes = json.loads(sfile.read_text(encoding="utf-8"))

    LBL_DIR.mkdir(parents=True, exist_ok=True)
    cls_cnt = Counter()
    n_written = 0
    n_delete = 0
    n_skip = 0
    n_missing_box = 0
    problems = []

    for fname, assign in sorted(shapes.items()):
        if assign == "DELETE":
            n_delete += 1
            continue
        if assign == "SKIP":
            n_skip += 1
            continue
        if fname not in boxes_all:
            problems.append("%s: 检测结果里没有" % fname)
            continue

        info = boxes_all[fname]
        W, H = info["W"], info["H"]
        by_id = {str(b["id"]): b for b in info["boxes"]}

        lines = []
        for bid, cid in assign.items():
            b = by_id.get(str(bid))
            if b is None:
                n_missing_box += 1
                problems.append("%s: 没有框 %s" % (fname, bid))
                continue
            cx = (b["x"] + b["w"] / 2.0) / W
            cy = (b["y"] + b["h"] / 2.0) / H
            nw = b["w"] / float(W)
            nh = b["h"] / float(H)
            lines.append("%d %.6f %.6f %.6f %.6f" % (cid, cx, cy, nw, nh))
            cls_cnt[cid] += 1

        if not lines:
            problems.append("%s: 没有任何有效框" % fname)
            continue

        if not args.dry_run:
            (LBL_DIR / (Path(fname).stem + ".txt")).write_text(
                "\n".join(lines) + "\n", encoding="utf-8")
        n_written += 1

    print("=" * 74)
    print("  写标签结果%s" % ("（DRY-RUN）" if args.dry_run else ""))
    print("=" * 74)
    print("  判定条目  : %d" % len(shapes))
    print("  写入标签  : %d 个文件" % n_written)
    print("  标记删除  : %d 帧" % n_delete)
    print("  标记跳过  : %d 帧" % n_skip)
    print("  缺框/异常 : %d 处" % n_missing_box)
    print()
    print("  各类实例数:")
    total = 0
    for cid, name in enumerate(CLASS_NAMES):
        n = cls_cnt.get(cid, 0)
        total += n
        print("    %d %-18s %4d" % (cid, name, n))
    print("    %-20s %4d" % ("合计", total))
    print()
    if problems:
        print("  ⚠️ 问题（前 10）:")
        for p in problems[:10]:
            print("    %s" % p)
        print()
    print("  标签目录: %s" % LBL_DIR)
    print("=" * 74)

    # 还剩多少没判
    done = set(shapes)
    allf = {p.name for p in IMG_DIR.glob("img_*.jpg")}
    left = sorted(allf - done)
    print()
    print("  进度: %d / %d 已判，剩 %d 帧" %
          (len(done & allf), len(allf), len(left)))
    if left:
        print("  下一批: %s" % left[:8])
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
