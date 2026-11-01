#!/usr/bin/env python3
"""6 类 YOLO 训练脚本（省赛表1）。

## 类别顺序（**必须严格照这个来，不能改**）

```
0 = cube             正方体
1 = cuboid           长方体
2 = cylinder         圆柱
3 = pentagonal_prism 五棱柱
4 = cone             圆锥        ← 目前零数据，采到后才有
5 = tetrahedron      正四面体
```

⚠️ 这个顺序必须与 `_screen_assets/colored/manifest.json` 里的 `shape_id` 对齐：
   `shape_id = 类别索引 + 1`
   即 shape_id 1..6 ↔ 类别 0..5

## 用法

```bash
# 1) 先看数据集状态（不训练）
python _pi_tools/train_6class.py --check

# 2) 快速验证流水线（5 epoch，约 10 分钟）
python _pi_tools/train_6class.py --epochs 5 --name yolo11n_6c_smoke

# 3) 正式训练
python _pi_tools/train_6class.py --epochs 120 --name yolo11n_6c_448

# 4) 从已有权重继续
python _pi_tools/train_6class.py --epochs 60 --resume _runs/yolo11n_6c_448/weights/last.pt
```

## 数据集要求

```
_dataset_yolo_6c/
  data.yaml            ← 本脚本会检查 nc 和 names
  images/train/*.jpg
  images/val/*.jpg
  labels/train/*.txt   ← YOLO 格式：class cx cy w h（归一化 0~1）
  labels/val/*.txt
```

**缺失的类别**（比如 cone）允许，但 `--check` 会告警，训练时会少一类。
**建议：cone 至少 150 个实例再训**，否则那一类的召回会很差。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 与 manifest.json 的 shape_id 对齐（shape_id = 索引 + 1）
CLASS_NAMES = (
    "cube",              # 0  正方体
    "cuboid",            # 1  长方体
    "cylinder",          # 2  圆柱
    "pentagonal_prism",  # 3  五棱柱
    "cone",              # 4  圆锥（目前零数据）
    "tetrahedron",       # 5  正四面体
)

CLASS_NAMES_ZH = (
    "正方体", "长方体", "圆柱", "五棱柱", "圆锥", "正四面体")

#: 每类建议的最少实例数（低于它召回会明显下降）
MIN_INSTANCES_RECOMMENDED = {
    "cube": 200, "cuboid": 200, "cylinder": 200,
    "pentagonal_prism": 200, "cone": 150, "tetrahedron": 200,
}


def scan_dataset(ds: Path) -> dict:
    """扫数据集，返回统计信息。"""
    info = {
        "root": ds,
        "exists": ds.is_dir(),
        "train_images": 0, "train_labels": 0,
        "val_images": 0, "val_labels": 0,
        "class_counts": Counter(),   # 训练集里各类的实例数
        "empty_labels": 0,           # 没有框的标注文件（负样本）
        "bad_lines": 0,
        "has_data_yaml": (ds / "data.yaml").is_file(),
    }
    if not info["exists"]:
        return info

    for split, img_key, lbl_key in (
            ("train", "train_images", "train_labels"),
            ("val", "val_images", "val_labels")):
        idir = ds / "images" / split
        ldir = ds / "labels" / split
        if idir.is_dir():
            info[img_key] = sum(
                1 for p in idir.iterdir()
                if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".webp"))
        if ldir.is_dir():
            files = list(ldir.glob("*.txt"))
            info[lbl_key] = len(files)
            if split == "train":
                for f in files:
                    try:
                        lines = [ln.strip() for ln in
                                 f.read_text(encoding="utf-8").splitlines()
                                 if ln.strip()]
                    except Exception:
                        continue
                    if not lines:
                        info["empty_labels"] += 1
                        continue
                    for ln in lines:
                        parts = ln.split()
                        if len(parts) < 5:
                            info["bad_lines"] += 1
                            continue
                        try:
                            cid = int(parts[0])
                        except ValueError:
                            info["bad_lines"] += 1
                            continue
                        if 0 <= cid < len(CLASS_NAMES):
                            info["class_counts"][CLASS_NAMES[cid]] += 1
                        else:
                            info["bad_lines"] += 1
    return info


def print_report(info: dict) -> bool:
    """打印数据集报告。返回 True = 可以训练。"""
    print("=" * 72)
    print("  6 类数据集报告")
    print("=" * 72)
    print("  根目录: %s" % info["root"])
    if not info["exists"]:
        print()
        print("  ❌ 数据集目录不存在")
        print()
        print("  需要先构建 _dataset_yolo_6c/。可以：")
        print("    · 从 _dataset_yolo_5c 复制并补 cone 数据")
        print("    · 或用 _pi_tools/build_6c_dataset.py（如果存在）")
        return False

    print()
    print("  文件数:")
    print("    train  images=%d  labels=%d"
          % (info["train_images"], info["train_labels"]))
    print("    val    images=%d  labels=%d"
          % (info["val_images"], info["val_labels"]))
    print("    空标注（负样本）=%d" % info["empty_labels"])

    issues = []
    if info["train_images"] != info["train_labels"]:
        issues.append("train 图/标数量不一致 (%d vs %d)"
                      % (info["train_images"], info["train_labels"]))
    if info["val_images"] != info["val_labels"]:
        issues.append("val 图/标数量不一致 (%d vs %d)"
                      % (info["val_images"], info["val_labels"]))
    if info["bad_lines"]:
        issues.append("有 %d 行标注格式不对（应为 'class cx cy w h' 归一化）"
                      % info["bad_lines"])
    if not info["has_data_yaml"]:
        issues.append("缺 data.yaml")

    print()
    print("  各类实例数（训练集）:")
    total = 0
    for i, name in enumerate(CLASS_NAMES):
        n = info["class_counts"].get(name, 0)
        total += n
        need = MIN_INSTANCES_RECOMMENDED[name]
        if n == 0:
            flag = "❌ 零数据"
        elif n < need:
            flag = "⚠️ 少 (%d/%d)" % (n, need)
        else:
            flag = "✅"
        print("    %d  %-18s %-8s %5d 实例  %s"
              % (i, name, CLASS_NAMES_ZH[i], n, flag))
    print("    %-20s %-8s %5d 实例" % ("合计", "", total))

    # 零数据/少数据的类 → 记为问题但不阻塞（允许先训）
    empty = [CLASS_NAMES[i] for i in range(len(CLASS_NAMES))
             if info["class_counts"].get(CLASS_NAMES[i], 0) == 0]
    if empty:
        issues.append("这些类没有训练数据（训练后会完全检不出）: %s" % empty)

    print()
    if issues:
        print("  问题:")
        for s in issues:
            print("    ⚠️ " + s)
        print()
        print("  ⇒ 仍然可以训练，但上面这些问题会影响效果。")
        print("    建议先用现有数据跑 smoke test 验证流水线。")
    else:
        print("  ✅ 数据集看起来 OK")

    ok = (info["train_images"] > 0 and info["train_labels"] > 0)
    print()
    print("  结论: %s" % ("可以训练" if ok else "❌ 训练集为空，不能训练"))
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="6 类 YOLO 训练")
    ap.add_argument("--dataset", default=str(ROOT / "_dataset_yolo_6c"),
                    help="数据集根目录（含 data.yaml + images/ + labels/）")
    ap.add_argument("--check", action="store_true", help="只检查数据集，不训练")
    ap.add_argument("--epochs", type=int, default=120)
    ap.add_argument("--imgsz", type=int, default=448)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--patience", type=int, default=30)
    ap.add_argument("--device", default="0")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--model", default="yolo11n.pt",
                    help="起点权重（yolo11n.pt / yolo11s.pt / 或某个 .pt 路径）")
    ap.add_argument("--name", default="yolo11n_6c_448",
                    help="输出 run 名（在 _runs/ 下）")
    ap.add_argument("--resume", default=None, help="从某权重继续")
    args = ap.parse_args(argv)

    ds = Path(args.dataset)
    info = scan_dataset(ds)
    can_train = print_report(info)
    if args.check or not can_train:
        return 0 if args.check else 1

    # ── 真正开始训练 ────────────────────────────────────────────────────
    try:
        from ultralytics import YOLO
    except Exception as exc:
        print()
        print("❌ 导入 ultralytics 失败:", exc)
        print("   请用带 ultralytics 的解释器：")
        print("   C:\\Users\\29845\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\"
              "dependencies\\python\\python.exe")
        return 1

    # 校验 data.yaml 的 names 必须与 CLASS_NAMES 完全一致
    yaml_path = ds / "data.yaml"
    try:
        import yaml
        meta = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print("❌ 读 data.yaml 失败:", exc)
        return 1

    names = meta.get("names")
    if isinstance(names, dict):
        names_list = [names[k] for k in sorted(names, key=lambda x: int(x))]
    else:
        names_list = list(names or [])
    if names_list != list(CLASS_NAMES):
        print()
        print("🔴 data.yaml 的 names 与约定不符，拒绝训练（否则类别会错位）")
        print("   约定:", list(CLASS_NAMES))
        print("   实际:", names_list)
        return 1
    print("  ✅ data.yaml 的 names 与约定一致")

    runs_dir = ROOT / "_runs"
    print()
    print("=" * 72)
    print("  开始训练")
    print("=" * 72)
    print("  起点权重 : %s" % (args.resume or args.model))
    print("  数据集   : %s" % ds)
    print("  imgsz    : %d" % args.imgsz)
    print("  batch    : %d" % args.batch)
    print("  epochs   : %d" % args.epochs)
    print("  patience : %d" % args.patience)
    print("  输出     : %s" % (runs_dir / args.name))
    print("=" * 72)
    print()

    model = YOLO(args.resume or args.model)
    results = model.train(
        data=str(yaml_path),
        imgsz=args.imgsz,
        batch=args.batch,
        epochs=args.epochs,
        patience=args.patience,
        device=args.device,
        workers=args.workers,
        project=str(runs_dir),
        name=args.name,
        exist_ok=True,
        # 与 5 类模型一致的数据增强（便于对比）
        hsv_h=0.015, hsv_s=0.7, hsv_v=0.4,
        degrees=10.0, translate=0.1, scale=0.3,
        fliplr=0.5, mosaic=1.0,
    )

    # ── 汇总 ────────────────────────────────────────────────────────────
    out_dir = runs_dir / args.name
    print()
    print("=" * 72)
    print("  训练完成")
    print("=" * 72)
    print("  输出目录: %s" % out_dir)
    print("  最好权重: %s" % (out_dir / "weights" / "best.pt"))
    print("  最后权重: %s" % (out_dir / "weights" / "last.pt"))
    print("  训练曲线: %s" % (out_dir / "results.csv"))
    print("  混淆矩阵: %s" % (out_dir / "confusion_matrix_normalized.png"))
    print()
    # 打印关键指标（如果 results 里有）
    try:
        m = getattr(results, "results_dict", None) or {}
        for k in ("metrics/mAP50(B)", "metrics/mAP50-95(B)",
                  "metrics/precision(B)", "metrics/recall(B)"):
            if k in m:
                print("  %-26s %.4f" % (k.split("/")[1], m[k]))
    except Exception:
        pass
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
