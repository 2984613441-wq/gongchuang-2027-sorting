#!/usr/bin/env python3
"""主相机重训（合并到 471 张 ≥ 300 张要求）。

数据：`_train_main_6c_v2`（复核 136 + v11 历史 335，去重后 471；train 377 / val 94）
初始化：`_models_20261030/main_best.pt`（= v11 + 今天 136 张微调后的权重）
输出：`_runs\\main_6c_v2`（绝对 project，避免落到 runs/detect 下）
"""

from __future__ import annotations

import json
import os

import _ultra_patch

_ultra_patch.apply()

from ultralytics import YOLO

HERE = os.path.abspath(".")
DATA = os.path.join(HERE, "_train_main_6c_v2", "data.yaml")
INIT = os.path.join(HERE, "_models_20261030", "main_best.pt")
PROJECT = os.path.join(HERE, "_runs")
NAME = "main_6c_v2"


def main() -> int:
    print("=" * 70, flush=True)
    print("主相机重训：data=%s" % DATA, flush=True)
    print("init=%s" % INIT, flush=True)
    print("=" * 70, flush=True)
    model = YOLO(INIT)
    model.train(
        data=DATA,
        epochs=150,
        imgsz=448,
        batch=16,
        device="0",
        project=PROJECT,
        name=NAME,
        exist_ok=True,
        seed=0,
        lr0=0.0015, lrf=0.01, cos_lr=True,
        patience=50,
        cache=False, workers=0,
        mosaic=1.0, close_mosaic=20,
        degrees=10.0, translate=0.10, scale=0.40,
        fliplr=0.5, flipud=0.0,
        hsv_h=0.015, hsv_s=0.5, hsv_v=0.3,
        verbose=True,
    )
    run_dir = os.path.join(PROJECT, NAME)
    best = os.path.join(run_dir, "weights", "best.pt")
    metrics = {}
    try:
        m = YOLO(best).val(data=DATA, split="val", imgsz=448, device="0", workers=0, verbose=False)
        metrics = {"mAP50": float(m.box.map50), "mAP50_95": float(m.box.map),
                   "P": float(m.box.mp), "R": float(m.box.mr)}
        per = {}
        try:
            for i, c in enumerate(m.names.values() if isinstance(m.names, dict) else m.names):
                per[str(c)] = {"mAP50": float(m.box.ap50[i]), "mAP50_95": float(m.box.ap[i])}
        except Exception as e:
            print("逐类指标提取失败: %r" % e, flush=True)
        metrics["per_class"] = per
    except Exception as e:
        print("val 失败: %r" % e, flush=True)
    out = dict(best=best, run_dir=run_dir, metrics=metrics, data=DATA,
               images={"train": 377, "val": 94})
    json.dump(out, open(os.path.join(HERE, "_train_main_v2_result.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("=" * 70)
    print("完成：%s" % best)
    print("指标：%s" % json.dumps(metrics, ensure_ascii=False))
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
