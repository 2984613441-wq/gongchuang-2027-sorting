# -*- coding: utf-8 -*-
"""副相机（DF200）6 类模型训练 —— 2026-11-05。

数据来源：`_dataset_cam2_复核后`（**用户人工复核版**，56 张 / 61 个标签 / 263 个框）
—— 按项目纪律「以用户复核结果为准」，**不混入未复核的 `_labels_cam2` 预标注**。

做法：
  1) 按 80/20 固定划分（用图片内容 sha1，可复现）生成 `_train_cam2_20261105/{images,labels}/{train,val}`
  2) 写 data.yaml
  3) 用 yolo11n 训练（默认 300 epochs —— 数据少，需要多轮 + 强增广）
     可选从旧 cam2 权重热启动（`--init _runs/cam2_6c_20261030/weights/best.pt`）

用法（CUDA 环境：D:\\Anaconda\\envs\\yolo\\python.exe）：
    python 工具/train_cam2_6c.py                 # 默认 300 epochs
    python 工具/train_cam2_6c.py --init _runs/cam2_6c_20261030/weights/best.pt
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "_dataset_cam2_复核后"
DEFAULT_OUT = ROOT / "_train_cam2_20261105"
CLASS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism", "cone", "tetrahedron"]


def _sha1(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare(out: Path, val_ratio: float = 0.2) -> tuple[int, int]:
    if out.exists():
        shutil.rmtree(out)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    n_tr = n_va = 0
    for img in sorted((SRC / "images").iterdir()):
        if img.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        label = SRC / "labels" / (img.stem + ".txt")
        if not label.exists():
            continue
        bucket = "val" if (int(_sha1(img)[:8], 16) % 100) < int(val_ratio * 100) else "train"
        shutil.copy2(img, out / "images" / bucket / img.name)
        shutil.copy2(label, out / "labels" / bucket / label.name)
        if bucket == "train":
            n_tr += 1
        else:
            n_va += 1
    lines = ["# 副相机 6 类（用户复核版 56 张），工具/train_cam2_6c.py 生成",
             "path: %s" % out.as_posix(),
             "train: images/train", "val: images/val", "nc: 6", "names:"]
    lines += ["  %d: %s" % (i, n) for i, n in enumerate(CLASS_NAMES)]
    (out / "data.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return n_tr, n_va


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=300)
    ap.add_argument("--imgsz", type=int, default=448)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--init", default="yolo11n.pt")
    ap.add_argument("--name", default="cam2_6c_v2_20261105")
    ap.add_argument("--project", default="_runs")
    ap.add_argument("--device", default="0")
    ap.add_argument("--val-ratio", type=float, default=0.2)
    args = ap.parse_args()

    n_tr, n_va = prepare(DEFAULT_OUT, args.val_ratio)
    print("数据划分：train %d / val %d（源：用户复核版 %s）" % (n_tr, n_va, SRC.name))
    if n_tr < 10:
        print("数据太少，拒绝训练（先补采/复核）")
        return 2

    from ultralytics import YOLO
    init = args.init if args.init.startswith("yolo") else str(ROOT / args.init)
    model = YOLO(init)
    print("初始权重：", init)
    results = model.train(
        data=str(DEFAULT_OUT / "data.yaml"),
        epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
        device=args.device, workers=0, cache=True,
        patience=80, cos_lr=True, lr0=0.01,
        # 小数据强增广（默认已开 mosaic/HSV/翻转；这里再显式声明关键项）
        mosaic=1.0, close_mosaic=30, degrees=10.0, scale=0.5, fliplr=0.5,
        hsv_h=0.02, hsv_s=0.7, hsv_v=0.4,
        project=str(ROOT / args.project), name=args.name, exist_ok=True,
        plots=False, verbose=False,
    )
    print("TRAIN_DONE", results.save_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
