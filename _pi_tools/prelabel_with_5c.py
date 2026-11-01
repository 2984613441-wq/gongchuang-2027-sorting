#!/usr/bin/env python3
"""半自动预标注：用现有 5 类模型给新图片打草稿框，你只需改错。

## 为什么要这个

新采的白托盘数据如果**纯手工标注**，400 张要几小时。
用现有 5 类模型（mAP50 0.9155）预标，**你只需要修错的框**，能省 70~80% 时间。

## 🔴 关键：类别映射必须显式做

现有 5 类模型的类别顺序：
```
0=cube  1=cuboid  2=cylinder  3=pentagonal_prism  4=tetrahedron
```
6 类数据集（`_dataset_yolo_6c`）的顺序：
```
0=cube  1=cuboid  2=cylinder  3=pentagonal_prism  4=cone  5=tetrahedron
```
**⇒ 5 类的 `4` 必须映射成 6 类的 `5`。不映射 = 正四面体被当圆锥 = 灾难。**

## 它不会做什么

- **不会标 cone**（模型没见过圆锥，0 数据）⇒ cone 必须**手工标**
- **不保证 100% 正确** ⇒ 必须人工复核
- **不动原图**，只生成 `.txt`

## 用法

```bash
# 1) 先 dry-run 看会标出什么（不写文件）
python _pi_tools/prelabel_with_5c.py --src captured_images/ --dry-run

# 2) 正式预标（写 .txt 到 labels/ 目录）
python _pi_tools/prelabel_with_5c.py --src captured_images/ --out labels/

# 3) 调置信度（默认 0.35，宁低勿高 —— 漏框比错框好补）
python _pi_tools/prelabel_with_5c.py --src captured_images/ --out labels/ --conf 0.25
```

## 输出

每个 `xxx.jpg` 生成一个 `xxx.txt`，YOLO 格式：
```
class_id cx cy w h      # 全部归一化到 0~1
```

导出的同时会打印统计（各类标出多少框、平均置信度）。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 5 类模型的类别顺序（训练时用的）
MODEL_5C_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism", "tetrahedron"]

#: 6 类数据集的类别顺序（目标）
DATASET_6C_NAMES = [
    "cube", "cuboid", "cylinder", "pentagonal_prism", "cone", "tetrahedron"]

#: 5 类 class_id → 6 类 class_id
#: 前 4 个不变，tetrahedron 从 4 移到 5
ID_MAP_5C_TO_6C = {0: 0, 1: 1, 2: 2, 3: 3, 4: 5}

#: 默认权重
DEFAULT_WEIGHT = ROOT / "_runs" / "yolo11n_5c_448" / "weights" / "best.pt"

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def find_images(src: Path) -> list[Path]:
    if src.is_file():
        return [src] if src.suffix.lower() in IMG_EXTS else []
    return sorted(p for p in src.rglob("*")
                  if p.is_file() and p.suffix.lower() in IMG_EXTS)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="用 5 类模型预标注，输出 6 类 YOLO 标签")
    ap.add_argument("--src", required=True, help="图片目录（或单个图片）")
    ap.add_argument("--out", default=None,
                    help="标签输出目录（默认与图片同目录）")
    ap.add_argument("--weight", default=str(DEFAULT_WEIGHT),
                    help="5 类模型权重（默认 _runs/yolo11n_5c_448/weights/best.pt）")
    ap.add_argument("--conf", type=float, default=0.35,
                    help="置信度阈值（默认 0.35，宁低勿高）")
    ap.add_argument("--imgsz", type=int, default=448)
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    ap.add_argument("--overwrite", action="store_true",
                    help="覆盖已存在的 .txt（默认跳过）")
    args = ap.parse_args(argv)

    src = Path(args.src)
    out_dir = Path(args.out) if args.out else None

    if not src.exists():
        print("❌ 源不存在: %s" % src)
        return 1

    weight = Path(args.weight)
    if not weight.is_file():
        print("❌ 权重不存在: %s" % weight)
        print("   可用:")
        for p in (ROOT / "_runs").glob("*/weights/best.pt"):
            print("     " + str(p.relative_to(ROOT)))
        return 1

    images = find_images(src)
    if not images:
        print("❌ 在 %s 下没找到图片" % src)
        return 1

    print("=" * 72)
    print("  半自动预标注（5 类模型 → 6 类标签）")
    print("=" * 72)
    print("  源       : %s" % src)
    print("  图片数   : %d" % len(images))
    print("  权重     : %s" % weight)
    print("  置信度   : %.2f" % args.conf)
    print("  输出到   : %s" % (out_dir if out_dir else "（与图片同目录）"))
    print("  模式     : %s" % ("DRY-RUN（不写文件）" if args.dry_run else "写入"))
    print()
    print("  类别映射（5 类 → 6 类）:")
    for old, new in sorted(ID_MAP_5C_TO_6C.items()):
        print("    %d %-18s → %d %-18s"
              % (old, MODEL_5C_NAMES[old], new, DATASET_6C_NAMES[new]))
    print()
    print("  ⚠️ 模型没见过的 cone 不会被标出来 —— 圆锥必须手工补")
    print()

    try:
        from ultralytics import YOLO
    except Exception as exc:
        print("❌ 导入 ultralytics 失败:", exc)
        return 1

    print("  加载模型…")
    model = YOLO(str(weight))
    print("  ✅ 已加载")
    print()

    # 统计
    n_written = 0
    n_skipped = 0
    n_empty = 0
    n_boxes_total = 0
    cls_counter = Counter()          # 6 类 id → 框数
    conf_by_cls = defaultdict(list)  # 6 类 id → 置信度列表
    n_dropped = 0                    # 因为未知类别被丢弃的框

    for i, img in enumerate(images, 1):
        out_path = (out_dir / (img.stem + ".txt")) if out_dir else \
                   (img.parent / (img.stem + ".txt"))

        if out_path.exists() and not args.overwrite and not args.dry_run:
            n_skipped += 1
            continue

        try:
            results = model.predict(
                source=str(img), imgsz=args.imgsz, conf=args.conf,
                verbose=False, device="0",
            )
        except Exception as exc:
            print("  [%d/%d] %s 推理失败: %s" % (i, len(images), img.name, exc))
            continue

        lines = []
        for r in results:
            boxes = getattr(r, "boxes", None)
            if boxes is None:
                continue
            for b in boxes:
                try:
                    old_id = int(b.cls.item())
                    conf = float(b.conf.item())
                except Exception:
                    continue
                new_id = ID_MAP_5C_TO_6C.get(old_id)
                if new_id is None:
                    n_dropped += 1
                    continue
                xywhn = b.xywhn[0].tolist()   # 归一化 cx cy w h
                lines.append("%d %.6f %.6f %.6f %.6f"
                             % (new_id, xywhn[0], xywhn[1], xywhn[2], xywhn[3]))
                cls_counter[new_id] += 1
                conf_by_cls[new_id].append(conf)
                n_boxes_total += 1

        if not lines:
            n_empty += 1

        if not args.dry_run:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        n_written += 1

        if i % 20 == 0 or i == len(images):
            print("  [%d/%d] 已处理…" % (i, len(images)))

    # ── 汇总 ────────────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("  汇总")
    print("=" * 72)
    print("  处理图片 : %d" % n_written)
    print("  跳过（已存在）: %d" % n_skipped)
    print("  无任何框 : %d  （要么真空图，要么漏检 —— 需人工看）" % n_empty)
    print("  总框数   : %d" % n_boxes_total)
    if n_dropped:
        print("  ⚠️ 丢弃了 %d 个未知类别的框（映射表里没有的 class_id）" % n_dropped)
    print()
    print("  各类标出的框数 + 平均置信度:")
    for cid, name in enumerate(DATASET_6C_NAMES):
        n = cls_counter.get(cid, 0)
        if n:
            avg = sum(conf_by_cls[cid]) / len(conf_by_cls[cid])
            print("    %d %-18s %5d 框  平均 conf %.3f" % (cid, name, n, avg))
        else:
            mark = "  ❌ 模型没见过（必须手工标）" if name == "cone" else "  ⚠️ 0 框"
            print("    %d %-18s %5d 框%s" % (cid, name, 0, mark))
    print()
    print("=" * 72)
    print("  下一步")
    print("=" * 72)
    print("  1. 用标注工具（labelImg / Label Studio / MaixHub）打开图片 + 这些 .txt")
    print("  2. **逐张复核**：删错框、补漏框、改错类、**手工补圆锥**")
    print("  3. 复核完把 images/ + labels/ 放进 _dataset_yolo_6c/")
    print("  4. 跑 python _pi_tools/train_6class.py --check 确认类别分布")
    print("  5. 再跑训练")
    return 0


if __name__ == "__main__":
    sys.exit(main())
