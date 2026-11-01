#!/usr/bin/env python3
"""合并「旧 6 类数据集」+「新图标注」→ 训练集 `_dataset_yolo_6c_v3`。

## 来源

· 旧：`_dataset_yolo_6c`（471 张，已转 6 类）
· 新：`_label_ws_6c/images` + `_label_ws_6c/labels`（72 张有标签）

**没有 .txt 的图直接跳过**（按用户约定：没标签 = 要删的图）。

## 用法

```bash
python _pi_tools/build_6c_v3.py --dry-run
python _pi_tools/build_6c_v3.py --overwrite
```
"""

from __future__ import annotations

import argparse
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD = ROOT / "_dataset_yolo_6c"
NEW_IMG = ROOT / "_label_ws_6c" / "images"
NEW_LBL = ROOT / "_label_ws_6c" / "labels"
OUT = ROOT / "_dataset_yolo_6c_v3"

CLASS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism",
               "cone", "tetrahedron"]
IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

DATA_YAML = """# 6 类数据集 v3 = 旧 471 张 + 新拍白托盘标注
# 生成: _pi_tools/build_6c_v3.py
# 新图来源: _label_ws_6c（AI 目视判形，HSV 仅用于定位）

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


def valid_label(p: Path) -> list[str]:
    out = []
    try:
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            parts = ln.split()
            if len(parts) != 5:
                continue
            try:
                cid = int(float(parts[0]))
                vals = [float(v) for v in parts[1:5]]
            except ValueError:
                continue
            if not (0 <= cid < 6):
                continue
            if not all(0.0 <= v <= 1.0 for v in vals):
                continue
            out.append("%d %.6f %.6f %.6f %.6f" % (cid, *vals))
    except Exception:
        return []
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--val-ratio", type=float, default=0.0,
                    help="新图抽多少进 val（默认 0 = 全进 train）")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    if OUT.is_dir() and not args.overwrite and not args.dry_run:
        print("⚠️ 输出已存在: %s（加 --overwrite）" % OUT)
        return 1

    print("=" * 74)
    print("  合并 6 类数据集 v3")
    print("=" * 74)

    plan: list[tuple[Path, Path, Path, Path]] = []   # (img, lbl, out_img_dir, out_lbl_dir)

    # ── 旧数据集 ──────────────────────────────────────────────────
    for split in ("train", "val"):
        idir = OLD / "images" / split
        ldir = OLD / "labels" / split
        if not idir.is_dir():
            continue
        n = 0
        for img in sorted(idir.iterdir()):
            if img.suffix.lower() not in IMG_EXTS:
                continue
            lf = ldir / (img.stem + ".txt")
            if not lf.is_file():
                continue
            if not valid_label(lf):
                continue
            plan.append((img, lf, OUT / "images" / split, OUT / "labels" / split))
            n += 1
        print("  旧 %-6s : %d 张" % (split, n))

    # ── 新图（只收有标签的）──────────────────────────────────────
    new_items = []
    for img in sorted(NEW_IMG.iterdir()):
        if img.suffix.lower() not in IMG_EXTS:
            continue
        lf = NEW_LBL / (img.stem + ".txt")
        if not lf.is_file():
            continue
        if not valid_label(lf):
            continue
        new_items.append((img, lf))
    print("  新图        : %d 张有标签" % len(new_items))

    rng = random.Random(args.seed)
    rng.shuffle(new_items)
    n_val = max(0, int(len(new_items) * args.val_ratio))
    for i, (img, lf) in enumerate(new_items):
        split = "val" if i < n_val else "train"
        plan.append((img, lf, OUT / "images" / split, OUT / "labels" / split))
    print("  新图分配    : train %d / val %d" % (len(new_items) - n_val, n_val))
    print()

    if args.dry_run:
        print("  （DRY-RUN，不写文件）总计划 %d 张" % len(plan))
        return 0

    # ── 写盘 ──────────────────────────────────────────────────────
    if OUT.is_dir():
        shutil.rmtree(OUT)
    copied = 0
    cls_cnt = Counter()
    for img, lf, odir, ldir in plan:
        odir.mkdir(parents=True, exist_ok=True)
        ldir.mkdir(parents=True, exist_ok=True)
        dst = odir / img.name
        if dst.exists():
            print("  ⚠️ 重名跳过: %s" % img.name)
            continue
        shutil.copy2(img, dst)
        lines = valid_label(lf)
        (ldir / (img.stem + ".txt")).write_text("\n".join(lines) + "\n",
                                                encoding="utf-8")
        for ln in lines:
            cls_cnt[int(ln.split()[0])] += 1
        copied += 1

    (OUT / "data.yaml").write_text(
        DATA_YAML.format(path=str(OUT).replace("\\", "/")), encoding="utf-8")

    print()
    print("=" * 74)
    print("  ✅ 已生成 %s" % OUT)
    print("=" * 74)
    for split in ("train", "val"):
        ni = len(list((OUT / "images" / split).glob("*"))) if (OUT / "images" / split).is_dir() else 0
        nl = len(list((OUT / "labels" / split).glob("*.txt"))) if (OUT / "labels" / split).is_dir() else 0
        print("  %-6s : %4d 图 / %4d 标签" % (split, ni, nl))
    print()
    print("  各类实例数:")
    tot = 0
    for cid, nm in enumerate(CLASS_NAMES):
        n = cls_cnt.get(cid, 0)
        tot += n
        print("    %d %-18s %5d" % (cid, nm, n))
    print("    %-20s %5d" % ("合计", tot))
    print()
    print("  下一步（重训）：")
    print("    python _pi_tools/train_6class.py --dataset _dataset_yolo_6c_v3 "
          "--epochs 120 --name yolo11n_6c_v3 --batch 32 --imgsz 448")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
