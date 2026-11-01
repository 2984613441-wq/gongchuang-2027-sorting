#!/usr/bin/env python3
"""从「统一复核工作区」构建训练集 —— 直接反映用户在 labelImg 里的改动。

## 用户约定（2026-10-27 明确）

> 我将不想要的照片的标签框全部删掉，那张图就是不想要的，到时候你删掉就可以了

⇒ **判定规则**：
```
有 .txt 且至少 1 个有效框  → 保留该图
无 .txt（被删掉）           → 丢弃该图
有 .txt 但 0 个有效框（框全删）→ 丢弃该图
```

## 单一数据源

`_label_review_all/`（712 张图 = 551 旧 + 161 新）
  · images/  ← 全部图
  · labels/  ← 471 旧标签（已转 7→6 类）+ 72 新标签

用户在 labelImg 里改完后，跑本脚本重建训练集。

## 划分规则

· 文件名以 `session_` 或 `np__` 开头 = 旧图 ⇒ 按 `_dataset_yolo_6c` 里原有的 train/val 归属
· 文件名以 `img_` 开头 = 新图 ⇒ 全部进 train

## 用法

```bash
python _pi_tools/build_from_review.py --dry-run
python _pi_tools/build_from_review.py --overwrite
```
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REVIEW = ROOT / "_label_review_all"
REVIEW_IMG = REVIEW / "images"
REVIEW_LBL = REVIEW / "labels"
OLD_DS = ROOT / "_dataset_yolo_6c"
OUT = ROOT / "_dataset_yolo_6c_v4"

CLASS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism",
               "cone", "tetrahedron"]
IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
SKIP_TXT = {"classes", "obj", "labels"}

DATA_YAML = """# 6 类数据集 v4 —— 从「统一复核工作区」重建
# 生成: _pi_tools/build_from_review.py
#
# 判定规则：无 .txt / 框全删 ⇒ 该图丢弃（用户标记为不要）
# 旧图按原 train/val 归属；新图全部进 train

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


def read_valid(lf: Path) -> list[str]:
    """读标签，返回合法行。文件不存在或全无效 ⇒ 空列表。"""
    if not lf.is_file():
        return []
    out = []
    try:
        for ln in lf.read_text(encoding="utf-8").splitlines():
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
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--new-val", type=int, default=0,
                    help="从新图（img_*）里抽 N 张进 val，用于衡量白托盘域性能；"
                         "默认 0 = 新图全进 train（此时 val 只有旧域）")
    args = ap.parse_args(argv)

    out_root = Path(args.out)

    for p, desc in ((REVIEW_IMG, "复核图目录"), (REVIEW_LBL, "复核标签目录"),
                    (OLD_DS, "旧数据集")):
        if not p.is_dir():
            print("❌ %s 不存在: %s" % (desc, p))
            return 1

    if out_root.is_dir() and not args.overwrite and not args.dry_run:
        print("⚠️ 输出已存在: %s（加 --overwrite）" % out_root)
        return 1

    # 旧图的 train/val 归属
    old_split: dict[str, str] = {}
    for split in ("train", "val"):
        d = OLD_DS / "images" / split
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.suffix.lower() in IMG_EXTS:
                old_split[f.stem] = split

    print("=" * 76)
    print("  从统一复核工作区构建训练集")
    print("=" * 76)
    print("  图目录 : %s" % REVIEW_IMG)
    print("  标签   : %s" % REVIEW_LBL)
    print("  旧图归属映射: %d 条" % len(old_split))
    print()

    kept: list[tuple[Path, Path, str]] = []
    dropped_missing = 0
    dropped_empty = 0
    dropped_unknown_split = 0
    cls_cnt = Counter()

    for img in sorted(REVIEW_IMG.iterdir()):
        if img.suffix.lower() not in IMG_EXTS:
            continue
        lf = REVIEW_LBL / (img.stem + ".txt")
        if not lf.is_file():
            dropped_missing += 1
            continue
        lines = read_valid(lf)
        if not lines:
            dropped_empty += 1
            continue

        stem = img.stem
        if stem in old_split:
            split = old_split[stem]
        elif stem.startswith("img_"):
            split = "train"
        else:
            dropped_unknown_split += 1
            continue

        kept.append((img, lf, split))
        for ln in lines:
            cls_cnt[int(ln.split()[0])] += 1

    # ── 可选：抽 N 张新图进 val（衡量白托盘域性能）──────────────────
    if args.new_val > 0:
        news = [i for i, (img, _, s) in enumerate(kept)
                if img.stem.startswith("img_") and s == "train"]
        for idx in news[:args.new_val]:
            img, lf, _ = kept[idx]
            kept[idx] = (img, lf, "val")
        print("  ⇒ 已把 %d 张新图移入 val（白托盘域评估）" % min(args.new_val, len(news)))
        print()

    n_train = sum(1 for _, _, s in kept if s == "train")
    n_val = sum(1 for _, _, s in kept if s == "val")

    print("  保留 : %d 张（train %d / val %d）" % (len(kept), n_train, n_val))
    print("  丢弃 : 无标签 %d 张 / 框全删 %d 张 / 归属未知 %d 张"
          % (dropped_missing, dropped_empty, dropped_unknown_split))
    print()
    print("  各类实例数:")
    tot = 0
    for cid, nm in enumerate(CLASS_NAMES):
        n = cls_cnt.get(cid, 0)
        tot += n
        print("    %d %-18s %5d" % (cid, nm, n))
    print("    %-20s %5d" % ("合计", tot))
    print()

    if args.dry_run:
        print("  （DRY-RUN，不写文件）")
        print("=" * 76)
        return 0

    if out_root.is_dir():
        shutil.rmtree(out_root)

    for img, lf, split in kept:
        idir = out_root / "images" / split
        ldir = out_root / "labels" / split
        idir.mkdir(parents=True, exist_ok=True)
        ldir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(img, idir / img.name)
        (ldir / (img.stem + ".txt")).write_text(
            "\n".join(read_valid(lf)) + "\n", encoding="utf-8")

    (out_root / "data.yaml").write_text(
        DATA_YAML.format(path=str(out_root).replace("\\", "/")),
        encoding="utf-8")

    print("=" * 76)
    print("  ✅ 已生成 %s" % out_root)
    print("=" * 76)
    for split in ("train", "val"):
        ni = len(list((out_root / "images" / split).glob("*"))) \
            if (out_root / "images" / split).is_dir() else 0
        nl = len(list((out_root / "labels" / split).glob("*.txt"))) \
            if (out_root / "labels" / split).is_dir() else 0
        print("  %-6s : %4d 图 / %4d 标签" % (split, ni, nl))
    print()
    print("  重训命令：")
    print("    python _pi_tools/train_6class.py --dataset %s "
          "--epochs 120 --name yolo11n_6c_v4 --batch 32 --imgsz 448"
          % out_root.relative_to(ROOT))
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
