#!/usr/bin/env python3
"""建「统一复查工作区」—— 把旧标注 + 昨天新拍的照片放一起，一遍过完。

## 解决的问题

用户要的是**复查**（不是重标）：
  · 旧数据集 551 张（train 441 + val 110）已经有标注
  · 昨天新拍 161 张没有标注
  ⇒ 放同一个工作区里，一次看完全部 712 张

## 🔴 关键：旧标注是 7 类，必须转成 6 类

旧 `_dataset_yolo` 的类序：
```
0 cube  1 cuboid  2 cylinder  3 hexagonal_prism
4 pentagonal_prism  5 triangular_prism  6 square_pyramid
```
我们的 6 类：
```
0 cube  1 cuboid  2 cylinder  3 pentagonal_prism  4 cone  5 tetrahedron
```
映射：
```
0→0  1→1  2→2  3→丢  4→3  5→丢  6→5
```
⚠️ 丢掉的 `hexagonal_prism` / `triangular_prism` 是表1 没有的类。
   含这两类的框会被删掉，图上那些物件就变成"未标注" 状态 —— 这是预期的，
   你要复查时能看到它们但不需要管。

## 用法

```bash
python _pi_tools/build_review_workspace.py
python _pi_tools/build_review_workspace.py --overwrite
```

输出：
```
_label_review_all/
  images/       712 张（551 旧 + 161 新）
  labels/       551 个转换后的 .txt
  classes_6c.txt
```
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OLD_DS = ROOT / "_dataset_yolo"
NEW_IMG = ROOT / "_label_ws_6c" / "images"
OUT = ROOT / "_label_review_all"

#: 7 类 → 6 类；None = 丢弃
MAP_7_TO_6 = {0: 0, 1: 1, 2: 2, 3: None, 4: 3, 5: None, 6: 5}

CLASS_NAMES_6 = ["cube", "cuboid", "cylinder", "pentagonal_prism",
                 "cone", "tetrahedron"]

IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="建统一复查工作区")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)

    for p, desc in ((OLD_DS, "旧数据集"), (NEW_IMG, "新照片目录")):
        if not p.is_dir():
            print("❌ %s 不存在: %s" % (desc, p))
            return 1

    if OUT.is_dir() and not args.overwrite:
        print("⚠️ 输出已存在: %s" % OUT)
        print("   加 --overwrite 覆盖")
        return 1
    if OUT.is_dir():
        shutil.rmtree(OUT)

    img_dir = OUT / "images"
    lbl_dir = OUT / "labels"
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 76)
    print("  建统一复查工作区")
    print("=" * 76)
    print()

    # ── 1. 复制旧数据集（图 + 转换后的标签）────────────────────────
    n_old_img = 0
    n_old_lbl = 0
    n_boxes_kept = 0
    n_boxes_dropped = 0
    n_became_empty = 0
    old_cls = Counter()

    for split in ("train", "val"):
        idir = OLD_DS / "images" / split
        ldir = OLD_DS / "labels" / split
        if not idir.is_dir():
            continue
        print("  ── 旧 %s ──" % split)

        for img in sorted(idir.iterdir()):
            if img.suffix.lower() not in IMG_EXTS:
                continue
            shutil.copy2(img, img_dir / img.name)
            n_old_img += 1

            lf = ldir / (img.stem + ".txt")
            if not lf.is_file():
                continue

            out_lines = []
            try:
                raw = lf.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for ln in raw:
                ln = ln.strip()
                if not ln:
                    continue
                parts = ln.split()
                if len(parts) < 5:
                    continue
                try:
                    old_id = int(float(parts[0]))
                except ValueError:
                    continue
                new_id = MAP_7_TO_6.get(old_id)
                if new_id is None:
                    n_boxes_dropped += 1
                    continue
                out_lines.append("%d %s" % (new_id, " ".join(parts[1:5])))
                n_boxes_kept += 1
                old_cls[new_id] += 1

            if out_lines:
                (lbl_dir / (img.stem + ".txt")).write_text(
                    "\n".join(out_lines) + "\n", encoding="utf-8")
                n_old_lbl += 1
            else:
                n_became_empty += 1

        print("     图 %d / 标签 %d" % (n_old_img, n_old_lbl))

    # ── 2. 复制新照片（无标签）──────────────────────────────────────
    n_new = 0
    for img in sorted(NEW_IMG.iterdir()):
        if img.suffix.lower() not in IMG_EXTS:
            continue
        dst = img_dir / img.name
        if dst.exists():
            print("  ⚠️ 重名跳过: %s" % img.name)
            continue
        shutil.copy2(img, dst)
        n_new += 1

    # ── 3. classes.txt ────────────────────────────────────────────
    (OUT / "classes_6c.txt").write_text(
        "\n".join(CLASS_NAMES_6) + "\n", encoding="utf-8")
    # labelImg 要求 SAVE 目录里有 classes.txt
    shutil.copy2(OUT / "classes_6c.txt", lbl_dir / "classes.txt")

    # ── 4. 汇总 ───────────────────────────────────────────────────
    total_img = len([p for p in img_dir.iterdir()
                     if p.suffix.lower() in IMG_EXTS])
    print()
    print("=" * 76)
    print("  ✅ 完成")
    print("=" * 76)
    print("  旧图      : %d 张（含标签 %d 个）" % (n_old_img, n_old_lbl))
    print("  新图      : %d 张（无标签，待你标）" % n_new)
    print("  合计图    : %d 张" % total_img)
    print()
    print("  旧标注转换:")
    print("    保留框  : %d 个" % n_boxes_kept)
    print("    丢弃框  : %d 个（hexagonal_prism / triangular_prism）"
          % n_boxes_dropped)
    print("    变空标注: %d 张图（原本只有被丢的两类）" % n_became_empty)
    print()
    print("  转换后各类实例数:")
    for cid, name in enumerate(CLASS_NAMES_6):
        print("    %d %-18s %5d" % (cid, name, old_cls.get(cid, 0)))
    print()
    print("  输出:")
    print("    %s" % (img_dir))
    print("    %s" % (lbl_dir))
    print()
    print("  ⚠️ 含 hexagonal_prism / triangular_prism 的物件在图上会是"
          "『未标注』状态 —— 表1 没这两类，不用管")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
