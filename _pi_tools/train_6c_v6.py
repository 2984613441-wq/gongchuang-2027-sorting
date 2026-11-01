#!/usr/bin/env python3
"""训练 6 类 v6 模型（30° 斜视新视角数据集）。

## 与 v4 的区别

    v4: 405 图 / 1089 框 / 近正顶视（相机旧位置）
    v6: 180 图 /  257 框 / 30° 斜视（相机新位置，与现场一致）

**v6 框数少得多，但视角与现场一致** —— 这是关键。

## 已知缺口

- **cuboid（长方体）零样本** ⇒ 这个类别学不到
- **pentagonal_prism 只有 14 框** ⇒ 样本偏少
- 总框数 257，约为 v4 的 1/4

## 用法

    python _pi_tools/train_6c_v6.py
    python _pi_tools/train_6c_v6.py --epochs 200 --imgsz 448
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "_dataset_yolo_6c_v6" / "data.yaml"))
    ap.add_argument("--base", default="yolo11n.pt")
    ap.add_argument("--imgsz", type=int, default=448)
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--name", default="yolo11n_6c_v6")
    ap.add_argument("--patience", type=int, default=50)
    args = ap.parse_args(argv)

    data = Path(args.data)
    if not data.is_file():
        print("❌ 缺 data.yaml: %s" % data)
        return 1

    from ultralytics import YOLO

    print("=" * 70)
    print("  训练 6 类 v6（30° 斜视新视角）")
    print("=" * 70)
    print("  data   : %s" % data)
    print("  base   : %s" % args.base)
    print("  imgsz  : %d   epochs: %d   batch: %d" % (args.imgsz, args.epochs, args.batch))
    print("  ⚠️ cuboid 零样本；pentagonal_prism 仅 14 框")
    print("=" * 70)

    model = YOLO(args.base)
    model.train(
        data=str(data),
        imgsz=args.imgsz,
        epochs=args.epochs,
        batch=args.batch,
        patience=args.patience,
        project=str(ROOT / "_runs"),
        name=args.name,
        exist_ok=True,
        # 小数据集 ⇒ 加强增强，防过拟合
        degrees=180.0,        # 全角度旋转：物件朝向随机，必须要
        translate=0.15,
        scale=0.5,
        shear=5.0,
        perspective=0.0005,   # 轻微透视，模拟 30° 斜视下的位置差异
        flipud=0.5,
        fliplr=0.5,
        hsv_h=0.015,
        hsv_s=0.5,
        hsv_v=0.5,            # 光照不均（实测横向 0.636）⇒ 加强亮度增强
        mosaic=1.0,
        mixup=0.1,
        close_mosaic=20,
        cache=False,
        workers=4,
        verbose=True,
    )

    print()
    print("=" * 70)
    print("  ✅ 训练完成: %s" % (ROOT / "_runs" / args.name))
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
