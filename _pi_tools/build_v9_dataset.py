#!/usr/bin/env python3
"""构建 v9 数据集 = 现有 v7 数据 + 20261028 **用户复核后**的标签。

## 与 v8 的区别

    v8 = v7 + 我判的 406 框（未经复核，方块类判得糙）
    v9 = v7 + 用户复核后的 273 框（高质量，含 37 帧补的漏框）

## 删除规则（用户确立）

    **没标签 = 不要的图** ⇒ 空标签帧移出数据集，隔离到 `_deleted_20261028/`（可回滚）

## 输出

    _dataset_yolo_6c_v9/        新数据集
    _deleted_20261028/          被删的空标签帧（image + 空 label，可回滚）
    _review_20261028/review_diff.json  复核差异记录

## 用法

    python _pi_tools/build_v9_dataset.py
    python _pi_tools/build_v9_dataset.py --val-ratio 0.2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V7 = ROOT / "_dataset_yolo_6c_v7"
REVIEW = ROOT / "_review_20261028"
OUT = ROOT / "_dataset_yolo_6c_v9"
TRASH = ROOT / "_deleted_20261028"

CLASS_NAMES = ["cube", "cuboid", "cylinder",
               "pentagonal_prism", "cone", "tetrahedron"]


def read_yolo(p: Path) -> list[str]:
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        try:
            c = int(float(parts[0]))
            x, y, w, h = (float(v) for v in parts[1:])
        except ValueError:
            continue
        if 0 <= c < 6 and 0 < w <= 1 and 0 < h <= 1:
            out.append("%d %.6f %.6f %.6f %.6f" % (c, x, y, w, h))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--val-ratio", type=float, default=0.2)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    print("=" * 78)
    print("  构建 v9 数据集（含用户复核标签）")
    print("=" * 78)

    # ── ① v7 数据 ──
    items = []
    for split in ("train", "val"):
        idir, ldir = V7 / "images" / split, V7 / "labels" / split
        if not idir.is_dir():
            continue
        n = 0
        for img in sorted(idir.glob("*.jpg")):
            lab = read_yolo(ldir / (img.stem + ".txt"))
            if lab:
                items.append((img, img.stem, lab))
                n += 1
        print("  v7 %-5s : %d 帧" % (split, n))
    n_v7 = len(items)
    print("  v7 合计 : %d 帧 / %d 框"
          % (n_v7, sum(len(l) for _, _, l in items)))
    print()

    # ── ② 复核后的新批次 ──
    rimg, rlbl = REVIEW / "images", REVIEW / "labels"
    if not rimg.is_dir():
        print("❌ 缺 %s" % rimg)
        return 1

    kept, empty = [], []
    cnt = Counter()
    for lp in sorted(rlbl.glob("*.txt")):
        if lp.name == "classes.txt":
            continue
        lab = read_yolo(lp)
        ip = rimg / (lp.stem + ".jpg")
        if not ip.is_file():
            continue
        if lab:
            kept.append((ip, "n_" + lp.stem, lab))
            for line in lab:
                cnt[int(line.split()[0])] += 1
        else:
            empty.append((ip, lp))
    n_new = len(kept)
    n_new_box = sum(len(l) for _, _, l in kept)
    print("  新批次 保留 : %d 帧 / %d 框" % (n_new, n_new_box))
    print("  🔴 删除(空标签): %d 帧" % len(empty))
    print()

    items += kept
    total_box = sum(len(l) for _, _, l in items)
    print("  合并合计: %d 帧 / %d 框" % (len(items), total_box))

    # 类别分布
    all_cnt = Counter()
    for _, _, lab in items:
        for line in lab:
            all_cnt[int(line.split()[0])] += 1
    print()
    print("  类别分布:")
    for c in range(6):
        v = all_cnt.get(c, 0)
        flag = "  ⚠️ 无样本" if v == 0 else ("  ⚠️ 偏少" if v < 20 else "")
        print("    %d %-18s %4d%s" % (c, CLASS_NAMES[c], v, flag))
    print("    合计 %d 框" % sum(all_cnt.values()))
    print()

    if args.dry_run:
        print("  [dry-run] 不写盘")
        return 0

    # ── ③ 隔离被删的帧 ──
    if empty:
        if TRASH.exists():
            shutil.rmtree(TRASH)
        (TRASH / "images").mkdir(parents=True, exist_ok=True)
        (TRASH / "labels").mkdir(parents=True, exist_ok=True)
        for ip, lp in empty:
            shutil.copy2(ip, TRASH / "images" / ip.name)
            shutil.copy2(lp, TRASH / "labels" / lp.name)
        (TRASH / "说明.txt").write_text(
            "这 %d 帧在复核时标签被删空，按用户规则「无标签=不想要」移出数据集。\n"
            "如需恢复：把 images/labels 拷回 _review_20261028 对应目录。\n\n"
            "⚠️ 其中有若干帧原本标了 3~7 个物件，属于大面积删除，\n"
            "   若发现是误删可从本目录恢复。\n" % len(empty),
            encoding="utf-8")
        print("  ✅ %d 帧已隔离到 %s（可回滚）" % (len(empty), TRASH))
        print()

    # ── ④ 划分 + 写盘 ──
    train, val = [], []
    for img, stem, lab in items:
        h = int(hashlib.md5(stem.encode()).hexdigest()[:8], 16)
        (val if (h % 1000) / 1000.0 < args.val_ratio else train).append(
            (img, stem, lab))
    print("  划分: train %d 帧 (%d 框) / val %d 帧 (%d 框)"
          % (len(train), sum(len(l) for _, _, l in train),
             len(val), sum(len(l) for _, _, l in val)))

    if OUT.exists():
        shutil.rmtree(OUT)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)

    def emit(group, split: str) -> int:
        n = 0
        for img, stem, lab in group:
            try:
                shutil.copy2(img, OUT / "images" / split / (stem + ".jpg"))
            except Exception as e:
                print("  ⚠️ 复制失败 %s: %s" % (img.name, e))
                continue
            (OUT / "labels" / split / (stem + ".txt")).write_text(
                "\n".join(lab) + "\n", encoding="utf-8")
            n += 1
        return n

    print("  写 train ...")
    n_tr = emit(train, "train")
    print("  写 val ...")
    n_va = emit(val, "val")

    (OUT / "data.yaml").write_text(
        "# 6 类 · 30° 斜视 · v7 数据 + 20261028 用户复核数据\n"
        "path: %s\n"
        "train: images/train\n"
        "val: images/val\n"
        "nc: 6\n"
        "names:\n" % str(OUT).replace("\\", "/")
        + "".join("  %d: %s\n" % (i, nm) for i, nm in enumerate(CLASS_NAMES)),
        encoding="utf-8")

    (OUT / "build_info.json").write_text(json.dumps({
        "v7_frames": n_v7,
        "new_frames_kept": n_new,
        "new_boxes_kept": n_new_box,
        "new_frames_deleted_empty": len(empty),
        "n_train": n_tr,
        "n_val": n_va,
        "class_counts": {CLASS_NAMES[c]: all_cnt.get(c, 0) for c in range(6)},
        "deleted_frames": [ip.stem for ip, _ in empty],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print()
    print("=" * 78)
    print("  ✅ v9 数据集完成: %s" % OUT)
    print("     train %d / val %d,  合计 %d 框" % (n_tr, n_va, total_box))
    print("     删除 %d 帧（隔离到 %s，可回滚）" % (len(empty), TRASH))
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
