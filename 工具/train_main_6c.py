# -*- coding: utf-8 -*-
"""主相机 6 类模型训练（2026-11-05，合并数据集 + 从 main_v2 热启动）。

用法（必须用带 CUDA 的环境：D:\\Anaconda\\envs\\yolo\\python.exe）：
    python 工具/train_main_6c.py                       # 默认 100 epochs
    python 工具/train_main_6c.py --epochs 150 --name v14
    python 工具/train_main_6c.py --init yolo11n.pt     # 从预训练权重开始（不热启动）

产物：`_runs/<name>/weights/best.pt` 与 `results.csv`（Ultralytics 会放在 runs/detect 下）。
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="_train_6c_merged_20261105/data.yaml")
    ap.add_argument("--init", default="_runs/main_6c_v2/weights/best.pt",
                    help="初始权重：main_v2 best.pt（热启动）或 yolo11n.pt")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=448)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--name", default="yolo11n_6c_merged13_20261105")
    ap.add_argument("--project", default="_runs")
    ap.add_argument("--device", default="0")
    args = ap.parse_args()

    from ultralytics import YOLO

    init = ROOT / args.init if not args.init.startswith("yolo") else args.init
    print("初始权重：", init)
    model = YOLO(str(init))
    results = model.train(
        data=str(ROOT / args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=0,
        cache=True,
        patience=30,
        cos_lr=True,
        lr0=0.001,            # 热启动用较小的初始学习率
        project=str(ROOT / args.project),
        name=args.name,
        exist_ok=True,
        plots=False,
        verbose=False,
    )
    print("TRAIN_DONE", results.save_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
