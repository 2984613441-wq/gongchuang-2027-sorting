#!/usr/bin/env python3
"""主相机 / 副相机**分开训练**（2026-10-30 复核版数据集）。

## 两个模型互不影响

| | 主相机 | 副相机 |
|---|---|---|
| 数据 | `_train_main_20261030`（109 train / 27 val）| `_train_cam2_20261030`（45 / 11）|
| 初始化 | `_runs/yolo11n_6c_v11/weights/best.pt`（同域同一套类）| 同样从 v11 微调 |
| 输出 | `_runs/main_6c_20261030/` | `_runs/cam2_6c_20261030/` |

两套数据域不同（MaixCAM 俯视 vs DF200 斜侧视），**绝不可混训**。

## 用法

    python _train_two_models.py            # 顺次训练两个
    python _train_two_models.py --only main
"""

from __future__ import annotations

import argparse
import json
import os

_ultra_patch_ok = False
try:
    import _ultra_patch
    _ultra_patch_ok = _ultra_patch.apply()
except Exception as _e:
    print("[warn] ultra_patch 未生效：%r" % _e)

from ultralytics import YOLO

JOBS = [
    dict(tag="main", data="_train_main_20261030/data.yaml",
         init=r"_runs\yolo11n_6c_v11\weights\best.pt", name="main_6c_20261030",
         epochs=120, patience=40),
    dict(tag="cam2", data="_train_cam2_20261030/data.yaml",
         init=r"_runs\yolo11n_6c_v11\weights\best.pt", name="cam2_6c_20261030",
         epochs=150, patience=50),
]


def train(job, device, imgsz, batch, lr0):
    print("=" * 70, flush=True)
    print("开始训练 [%s]  init=%s" % (job["tag"], job["init"]), flush=True)
    print("  data=%s epochs=%d imgsz=%d batch=%d device=%s lr0=%s"
          % (job["data"], job["epochs"], imgsz, batch, device, lr0), flush=True)
    print("=" * 70, flush=True)
    model = YOLO(job["init"])
    res = model.train(
        data=job["data"],
        epochs=job["epochs"],
        imgsz=imgsz,
        batch=batch,
        device=device,
        project="_runs",
        name=job["name"],
        exist_ok=True,
        seed=0,
        lr0=lr0, lrf=0.01,
        patience=job["patience"],
        cos_lr=True,
        cache=False,   # 沙箱下 cache_images 会用 ThreadPool
        workers=0,   # 沙箱禁止子进程/命名管道
        # 小数据加强增强
        mosaic=1.0, close_mosaic=15,
        degrees=10.0, translate=0.10, scale=0.40,
        fliplr=0.5, flipud=0.0,
        hsv_h=0.015, hsv_s=0.5, hsv_v=0.3,
        verbose=True,
    )
    best = os.path.join("_runs", job["name"], "weights", "best.pt")
    metrics = {}
    try:
        m = model.val(data=job["data"], split="val", imgsz=imgsz, device=device, verbose=False)
        metrics = {"mAP50": float(m.box.map50), "mAP50_95": float(m.box.map),
                   "precision": float(m.box.mp), "recall": float(m.box.mr)}
    except Exception as e:
        print("val 失败: %r" % e, flush=True)
    print("[%s] 训练完成 best=%s  %s" % (job["tag"], best, metrics), flush=True)
    return dict(tag=job["tag"], best=best, exists=os.path.exists(best), metrics=metrics,
                epochs=job["epochs"], data=job["data"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", choices=["", "main", "cam2"])
    ap.add_argument("--device", default="0")
    ap.add_argument("--imgsz", type=int, default=448)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lr0", type=float, default=0.002)
    args = ap.parse_args()

    out = []
    for job in JOBS:
        if args.only and job["tag"] != args.only:
            continue
        out.append(train(job, args.device, args.imgsz, args.batch, args.lr0))
    json.dump(out, open("_train_results_20261030.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("=" * 70)
    for r in out:
        print("%-5s best=%s exists=%s metrics=%s"
              % (r["tag"], r["best"], r["exists"], r["metrics"]))
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
