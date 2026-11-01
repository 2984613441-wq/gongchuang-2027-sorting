#!/usr/bin/env python3
"""从原始 7 类数据集构建「6 类增强版」—— 救回被丢掉但含有效类的图。

## 问题背景

`_dataset_yolo`（原始 7 类）有 551 张图，但 `_dataset_yolo_6c` 只有 471 张。
少了 80 张 —— 因为映射到 6 类时，**含「六棱柱 / 三棱柱」的图被整张丢掉**。

但其中有 155 张是**混合图**：既有表1 的 5 个有效类，也有表1 没有的 2 个类。
这些图**去掉无效类标注后仍然可用** ⇒ 能救回来。

## 实测可救回量

```
train: 全有效 260 / 混合 120（351 个有效框）/ 只有无效 61（弃）
val:   全有效  56 / 混合  35（124 个有效框）/ 只有无效 19（弃）
⇒ 共救回 155 张图 + 475 个有效框
```

## 类别映射（7 类 → 6 类）

```
7类 id  含义              →  6类 id
  0     cube              →  0
  1     cuboid            →  1
  2     cylinder          →  2
  3     hexagonal_prism   →  ✗ 丢弃（表1 没有）
  4     pentagonal_prism  →  3
  5     triangular_prism  →  ✗ 丢弃（表1 没有）
  6     tetrahedron       →  5
（6 类 id=4 的 cone 保持空，等后续数据）
```

⚠️ 注意：原始 `_dataset_yolo/data.yaml` 里把 class 6 写成 `square_pyramid`，
   但**实际标注是 tetrahedron**（236 个实例，与 5c 的 tetrahedron 数量一致）。
   本脚本按真实语义映射（6 → tetrahedron → 6类 id 5）。

## 用法

```bash
python _pi_tools/build_6c_plus.py
python _pi_tools/build_6c_plus.py --overwrite
```

输出：`_dataset_yolo_6c_plus/`
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SRC = ROOT / "_dataset_yolo"
DST = ROOT / "_dataset_yolo_6c_plus"

#: 7 类 id → 6 类 id；不在表里的映射到 None（丢弃该框）
MAP_7_TO_6 = {
    0: 0,      # cube             → cube
    1: 1,      # cuboid           → cuboid
    2: 2,      # cylinder         → cylinder
    3: None,   # hexagonal_prism  → 丢弃
    4: 3,      # pentagonal_prism → pentagonal_prism
    5: None,   # triangular_prism → 丢弃
    6: 5,      # tetrahedron      → tetrahedron
}

CLASS_NAMES_6 = [
    "cube", "cuboid", "cylinder", "pentagonal_prism", "cone", "tetrahedron"]

DATA_YAML = """# 6 类 YOLO 数据集（增强版）
# 从 _dataset_yolo（原始 7 类）映射，**保留了「混合图」中有效的框**
# 丢弃的两个类: hexagonal_prism(六棱柱) / triangular_prism(三棱柱) —— 赛规表1 无
# 生成: _pi_tools/build_6c_plus.py
#
# ⚠️ cone(class 4) 目前仍为 0 实例，等后续采集

path: {path}
train: images/train
val: images/val

nc: 6
names:
  0: cube
  1: cuboid
  2: cylinder
  3: pentagonal_prism
  4: cone
  5: tetrahedron
"""

IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def find_image(labels_dir: Path, stem: str) -> Path | None:
    """在 labels 同级 images 目录里找同名图片。"""
    # labels/train/xxx.txt → images/train/xxx.<ext>
    img_dir = labels_dir.parent.parent / "images" / labels_dir.name
    for ext in IMG_EXTS:
        p = img_dir / (stem + ext)
        if p.is_file():
            return p
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="构建 6 类增强版数据集")
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("--dst", default=str(DST))
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)

    src = Path(args.src)
    dst = Path(args.dst)

    if not src.is_dir():
        print("❌ 源数据集不存在: %s" % src)
        return 1
    if dst.is_dir() and not args.overwrite:
        print("⚠️ 输出已存在: %s" % dst)
        print("   加 --overwrite 覆盖（会先删掉旧目录）")
        return 1
    if dst.is_dir():
        shutil.rmtree(dst)

    print("=" * 74)
    print("  构建 6 类增强版数据集")
    print("=" * 74)
    print("  源: %s" % src)
    print("  输出: %s" % dst)
    print()

    total_stats = {}

    for split in ("train", "val"):
        ldir = src / "labels" / split
        if not ldir.is_dir():
            print("  ⚠️ 跳过 %s（无 labels 目录）" % split)
            continue

        out_img = dst / "images" / split
        out_lbl = dst / "labels" / split
        out_img.mkdir(parents=True, exist_ok=True)
        out_lbl.mkdir(parents=True, exist_ok=True)

        n_kept = 0
        n_dropped_no_valid = 0
        n_missing_img = 0
        n_boxes = 0
        cls_cnt = Counter()
        n_invalid_dropped = 0

        for lf in sorted(ldir.glob("*.txt")):
            stem = lf.stem
            lines_out = []
            try:
                raw_lines = lf.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue

            for ln in raw_lines:
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
                    n_invalid_dropped += 1
                    continue
                lines_out.append("%d %s" % (new_id, " ".join(parts[1:5])))
                cls_cnt[new_id] += 1

            if not lines_out:
                # 这张图没有有效框 ⇒ 丢弃
                n_dropped_no_valid += 1
                continue

            img = find_image(ldir, stem)
            if img is None:
                n_missing_img += 1
                continue

            shutil.copy2(img, out_img / img.name)
            (out_lbl / (stem + ".txt")).write_text(
                "\n".join(lines_out) + "\n", encoding="utf-8")
            n_kept += 1
            n_boxes += len(lines_out)

        total_stats[split] = {
            "kept": n_kept,
            "dropped": n_dropped_no_valid,
            "missing": n_missing_img,
            "boxes": n_boxes,
            "cls": dict(sorted(cls_cnt.items())),
            "invalid_boxes_dropped": n_invalid_dropped,
        }
        print("  ── %s ──" % split)
        print("    保留图片     : %d" % n_kept)
        print("    丢弃（无有效框）: %d" % n_dropped_no_valid)
        print("    缺图         : %d" % n_missing_img)
        print("    有效框       : %d" % n_boxes)
        print("    丢掉的无效框 : %d" % n_invalid_dropped)
        print("    各类实例     : %s" % dict(sorted(cls_cnt.items())))
        print()

    # data.yaml
    (dst / "data.yaml").write_text(
        DATA_YAML.format(path=str(dst).replace("\\", "/")), encoding="utf-8")
    print("  ✅ 已写 data.yaml")

    # 汇总
    print()
    print("=" * 74)
    print("  汇总对比")
    print("=" * 74)
    for split in ("train", "val"):
        s = total_stats.get(split)
        if s:
            print("  %-6s : %4d 张 / %4d 框" % (split, s["kept"], s["boxes"]))
    print()
    tot_img = sum(s["kept"] for s in total_stats.values())
    tot_box = sum(s["boxes"] for s in total_stats.values())
    print("  总图片 : %d" % tot_img)
    print("  总框数 : %d" % tot_box)
    print()
    print("  对比 _dataset_yolo_6c: 471 张 ⇒ 提升 %+d 张（%+.1f%%）"
          % (tot_img - 471, 100.0 * (tot_img - 471) / 471))
    print()
    print("  下一步：")
    print("    python _pi_tools/train_6class.py "
          "--dataset %s --epochs 120 --name yolo11n_6c_plus"
          % dst.relative_to(ROOT))
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
