"""训练 5 类 YOLO11n（对齐省赛表1，暂缺圆锥）。

类别：0 cube 正方体 / 1 cuboid 长方体 / 2 cylinder 圆柱 /
      3 pentagonal_prism 五棱柱 / 4 tetrahedron 正四面体
（六棱柱、三棱柱已按表1 剔除；圆锥数据待补，后面再训 6 类）

## 参数依据（全部来自上次成功训练 `_runs/yolo11n_7c_448/args.yaml`）

| 参数 | 值 | 理由 |
|---|---|---|
| model | yolo11n.pt | 与上次一致，n 版最小最快，适合 MaixCAM NPU |
| imgsz | 448 | 与上次一致（训练/推理尺寸一致，避免精度漂移） |
| batch | 32 | 12.8 GB 显存够 |
| epochs | 120 | 上次用 120，patience 30 |
| device | 0 | RTX 5070 Ti |
| workers | 0 | Windows 上多 worker 易崩（上次也是 0） |
| patience | 30 | 连续 30 epoch 无提升就早停 |
| seed | 0 | 可复现 |
| project/name | _runs / yolo11n_5c_448 | 与上次命名风格一致 |

## 用法

    python _pi_tools/train_5class.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "_dataset_yolo_5c" / "data.yaml"
PROJ = ROOT / "_runs"
NAME = "yolo11n_5c_448"

if not DATA.exists():
    print("❌ 数据集不存在: %s" % DATA)
    print("   先跑: python _pi_tools/remap_to_5class.py --apply")
    sys.exit(1)


def main() -> int:
    from ultralytics import YOLO

    print("=" * 74)
    print("训练 5 类 YOLO11n")
    print("  data   = %s" % DATA)
    print("  imgsz  = 448   batch = 32   epochs = 120   device = 0")
    print("  输出   = %s / %s" % (PROJ, NAME))
    print("=" * 74)

    model = YOLO("yolo11n.pt")
    results = model.train(
        data=str(DATA),
        imgsz=448,
        epochs=120,
        batch=32,
        patience=30,
        device=0,
        workers=0,
        seed=0,
        project=str(PROJ),
        name=NAME,
        exist_ok=True,
        plots=True,
        verbose=True,
    )
    print("\n=== 训练结束 ===")
    try:
        print("  best:  %s" % (results.save_dir / "weights" / "best.pt"))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
