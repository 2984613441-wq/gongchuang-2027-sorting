#!/usr/bin/env python3
"""把被清空（0 字节）的 YOLO 标签恢复成第一次的 v11 预标。

## 为什么单独做这个

2026-10-30 21:43~21:50 在 labelImg 里复核时，**21 个标签文件被清成 0 字节**（0 个框）。
其余 52 个文件的修改是有效的，不能整体回滚 —— 所以本脚本**只处理"当前 0 字节"的文件**，
把它们的框从原始预标副本里拿回来，其它文件一概不动。

## 数据来源（都已存在）

    _labels_main\\20261030\\labels\\<同名>.txt    ← 第一次 v11 预标（161 个，519 框）
    _review_20261030b\\labels\\<同名>.txt         ← 你复核后的现状

## 用法

    # 只看看哪些会被恢复
    python _restore_empty_labels.py --list

    # 真正恢复（先自动备份当前 labels 到 labels_备份_<时间>）
    python _restore_empty_labels.py

    # 干跑，不写
    python _restore_empty_labels.py --dry-run
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import time

CUR = r"_review_20261030b\labels"
SRC = r"_labels_main\20261030\labels"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cur", default=CUR)
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--list", action="store_true", help="只列出将被恢复的文件")
    ap.add_argument("--dry-run", action="store_true", help="不写文件")
    args = ap.parse_args()

    if not os.path.isdir(args.cur):
        print("❌ 当前标签目录不存在：%s" % args.cur)
        return 1
    if not os.path.isdir(args.src):
        print("❌ 原始预标目录不存在：%s" % args.src)
        return 1

    empties = [p for p in sorted(glob.glob(os.path.join(args.cur, "*.txt")))
               if os.path.basename(p) != "classes.txt" and os.path.getsize(p) == 0]
    if not empties:
        print("没有 0 字节的标签文件，无需恢复。")
        return 0

    print("当前 0 字节（0 框）文件 %d 个：" % len(empties))
    rows = []
    for p in empties:
        n = os.path.basename(p)
        q = os.path.join(args.src, n)
        if os.path.exists(q):
            nbox = sum(1 for ln in open(q, encoding="utf-8") if len(ln.split()) == 5)
            rows.append((n, nbox, True))
            print("  ✓ %-46s 可从预标恢复 %d 框" % (n, nbox))
        else:
            rows.append((n, 0, False))
            print("  ✗ %-46s 原始预标里也没有这个文件" % n)

    ok = [r for r in rows if r[2]]
    print("-" * 70)
    print("可恢复 %d 个文件，共 %d 框；不可恢复 %d 个"
          % (len(ok), sum(r[1] for r in ok), len(rows) - len(ok)))
    if args.list:
        return 0
    if args.dry_run:
        print("（--dry-run：未写入）")
        return 0

    bak = args.cur.rstrip("\\/") + "_备份_%s" % time.strftime("%H%M%S")
    shutil.copytree(args.cur, bak)
    print("当前 labels 已备份 → %s" % bak)

    done = 0
    for n, nbox, okk in ok:
        shutil.copy2(os.path.join(args.src, n), os.path.join(args.cur, n))
        print("  恢复 %-46s %d 框" % (n, nbox))
        done += 1
    print("=" * 70)
    print("完成：恢复 %d 个文件（其余文件未改动）" % done)
    print("提示：若你确认这些帧就是「不要框」，删掉恢复结果即可（备份里有 0 字节版本）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
