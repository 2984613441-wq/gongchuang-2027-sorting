#!/usr/bin/env python3
"""用**用户复核后的标签**重建数据集 v7，并删除无标签的帧。

## 规则（用户确立）

**没有标签 / 所有框被删光 = 这张图不想要 ⇒ 删掉。**

## 与 v6 构建的区别

    v6: 用我的判形结果（_pi_tools/label_overrides.py）
    v7: 用**用户复核后的标签**（_review_v6/labels/*.txt）

复核实测修正量：合计框数 271 → 368（+36%），
cuboid 0 → 51，pentagonal_prism 14 → 68，cube 138 → 99。
⇒ 我的判形在「方块类」上错得多，必须用用户版本。

## 输出

    _dataset_yolo_6c_v7/        新数据集（直接喂 YOLO）
    _deleted_from_review_v6/    被删的 21 张（保留可回滚）

## 用法

    python _pi_tools/build_v7_from_review.py
    python _pi_tools/build_v7_from_review.py --val-ratio 0.2
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
REVIEW = ROOT / "_review_v6"
IMGS = REVIEW / "images"
LBL = REVIEW / "labels"
OUT = ROOT / "_dataset_yolo_6c_v7"
TRASH = ROOT / "_deleted_from_review_v6"

CLASS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism",
               "cone", "tetrahedron"]


def read_labels(p: Path) -> list[str]:
    """读标签，返回归一化后的行（过滤非法行）。"""
    if not p.is_file():
        return []
    lines = []
    for line in p.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        try:
            cid = int(float(parts[0]))
            x, y, w, h = (float(v) for v in parts[1:])
        except ValueError:
            continue
        if not (0 <= cid < 6):
            continue
        if w <= 0 or h <= 0 or w > 1 or h > 1:
            continue
        lines.append("%d %.6f %.6f %.6f %.6f" % (cid, x, y, w, h))
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--val-ratio", type=float, default=0.2)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not IMGS.is_dir() or not LBL.is_dir():
        print("❌ 缺 %s 或 %s" % (IMGS, LBL))
        return 1

    stems = sorted(p.stem for p in IMGS.glob("*.jpg"))
    print("=" * 78)
    print("  用复核后的标签重建数据集 v7")
    print("=" * 78)
    print("  复核工作区: %s" % REVIEW)
    print("  图片: %d 张" % len(stems))
    print()

    kept: list[tuple[str, list[str]]] = []
    empty: list[str] = []
    for s in stems:
        lab = read_labels(LBL / (s + ".txt"))
        if not lab:
            empty.append(s)
        else:
            kept.append((s, lab))

    print("  🔴 无标签（按规则删）: %d 张" % len(empty))
    print("  ✅ 保留: %d 张" % len(kept))
    print()

    # 类别统计
    cnt = Counter()
    for _, lab in kept:
        for line in lab:
            cnt[int(line.split()[0])] += 1
    print("  类别分布:")
    for cid in range(6):
        n = cnt.get(cid, 0)
        flag = "  ⚠️ 无样本" if n == 0 else ""
        print("    %d %-20s %4d%s" % (cid, CLASS_NAMES[cid], n, flag))
    print("    合计 %d 框" % sum(cnt.values()))
    print()

    # 划分
    train, val = [], []
    for s, lab in kept:
        h = int(hashlib.md5(s.encode()).hexdigest()[:8], 16)
        if (h % 1000) / 1000.0 < args.val_ratio:
            val.append((s, lab))
        else:
            train.append((s, lab))
    if len(val) < 10:
        step = max(2, int(1 / max(args.val_ratio, 0.05)))
        val = kept[::step]
        vs = {s for s, _ in val}
        train = [(s, l) for s, l in kept if s not in vs]
    print("  划分: train %d 帧 (%d 框) / val %d 帧 (%d 框)"
          % (len(train), sum(len(l) for _, l in train),
             len(val), sum(len(l) for _, l in val)))
    print()

    if args.dry_run:
        print("  [dry-run] 不写盘")
        return 0

    # 清理旧输出
    if OUT.exists():
        shutil.rmtree(OUT)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)

    def emit(items, split: str) -> int:
        n = 0
        for s, lab in items:
            src = IMGS / (s + ".jpg")
            if not src.is_file():
                continue
            shutil.copy2(src, OUT / "images" / split / (s + ".jpg"))
            (OUT / "labels" / split / (s + ".txt")).write_text(
                "\n".join(lab) + "\n", encoding="utf-8")
            n += 1
        return n

    print("  写 train ...")
    n_tr = emit(train, "train")
    print("  写 val ...")
    n_va = emit(val, "val")

    # data.yaml
    (OUT / "data.yaml").write_text(
        "# 6 类 · 30° 斜视 · 用户复核标签 · 20261028\n"
        "path: %s\n"
        "train: images/train\n"
        "val: images/val\n"
        "nc: 6\n"
        "names:\n" % str(OUT).replace("\\", "/")
        + "".join("  %d: %s\n" % (i, nm) for i, nm in enumerate(CLASS_NAMES)),
        encoding="utf-8")

    # 删除的帧移到隔离区（可回滚）
    if empty:
        if TRASH.exists():
            shutil.rmtree(TRASH)
        (TRASH / "images").mkdir(parents=True, exist_ok=True)
        (TRASH / "labels").mkdir(parents=True, exist_ok=True)
        for s in empty:
            for src, sub, ext in ((IMGS / (s + ".jpg"), "images", ".jpg"),
                                  (LBL / (s + ".txt"), "labels", ".txt")):
                if src.is_file():
                    shutil.copy2(src, TRASH / sub / (s + ext))
        (TRASH / "说明.txt").write_text(
            "这 %d 张图在复核时标签被删空，按用户规则「无标签=不想要」移出数据集。\n"
            "如需恢复：把 images 和 labels 拷回 _review_v6 对应目录。\n" % len(empty),
            encoding="utf-8")

    # 记录
    (OUT / "build_info.json").write_text(json.dumps({
        "source": str(REVIEW),
        "n_images_input": len(stems),
        "n_deleted_empty": len(empty),
        "n_kept": len(kept),
        "n_train": n_tr,
        "n_val": n_va,
        "class_counts": {CLASS_NAMES[c]: cnt.get(c, 0) for c in range(6)},
        "deleted_frames": empty,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print()
    print("=" * 78)
    print("  ✅ v7 数据集完成: %s" % OUT)
    print("     train %d / val %d 张" % (n_tr, n_va))
    print("     删除 %d 张（隔离到 %s，可回滚）" % (len(empty), TRASH))
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
