#!/usr/bin/env python3
"""用 round3 的 best.pt 在工作区 64 张图上自评，直接量化"域迁移是否修复"。

原理：把 workspace_label 里 64 张非空标注图临时拼成 val 数据集，用
ultralytics 的 val() 按标准 mAP 对比工作区标签。

⚠️ 注意：这 64 张已经进过 round3 的 train（ws_ 前缀），所以这是"训练集内
自评"，分数会偏乐观。它的作用是 sanity check——模型现在到底能不能在工作区
风格场景里检出这些料块。要无偏评估需额外留出工作区验证集（当前只有 64 张，
舍不得留）。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# 让本地 ultralytics（8.3.163 源码）可导入，无论从哪个 cwd 跑
ULTRALYTICS_SRC = r"D:\AAAdesktop1\shijue\ultralytics-8.3.163"
if ULTRALYTICS_SRC not in sys.path:
    sys.path.insert(0, ULTRALYTICS_SRC)

CLASSES = (
    "cube", "cuboid", "cylinder", "hexagonal_prism",
    "pentagonal_prism", "square_pyramid", "triangular_prism",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", type=Path,
        default=Path(ULTRALYTICS_SRC) / "runs" / "block_detector"
        / "block_yolo11n_e100_round3" / "weights" / "best.pt")
    ap.add_argument("--workspace", type=Path,
        default=Path(r"C:\Users\29845\Desktop\工创赛\workspace_label"))
    ap.add_argument("--imgsz", type=int, default=448)
    ap.add_argument("--conf", type=float, default=0.25)
    args = ap.parse_args()

    from ultralytics import YOLO

    if not args.weights.is_file():
        raise SystemExit(f"找不到权重：{args.weights}")

    # 1) 收集非空标注的图
    pairs = []
    for jpg in sorted(args.workspace.glob("img_*.jpg")):
        txt = jpg.with_suffix(".txt")
        if txt.is_file() and txt.stat().st_size > 0:
            pairs.append((jpg, txt))
    if not pairs:
        raise SystemExit(f"工作区里没有非空标注的图：{args.workspace}")

    # 2) 临时拼 val 数据集（eval 完可删）
    tmp = args.workspace / "_eval"
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "images" / "val").mkdir(parents=True)
    (tmp / "labels" / "val").mkdir(parents=True)
    for jpg, txt in pairs:
        shutil.copy2(jpg, tmp / "images" / "val" / jpg.name)
        shutil.copy2(txt, tmp / "labels" / "val" / txt.name)
    (tmp / "data.yaml").write_text(
        f'path: "{tmp.as_posix()}"\n'
        "train: images/val\n"  # check_det_dataset 要求 train 键必须存在；实际只用 val
        "val: images/val\n"
        "names:\n" + "".join(f'  {i}: "{c}"\n' for i, c in enumerate(CLASSES)),
        encoding="utf-8",
    )

    # 3) 验证
    model = YOLO(str(args.weights))
    metrics = model.val(
        data=str(tmp / "data.yaml"),
        imgsz=args.imgsz,
        conf=args.conf,
        split="val",
        verbose=True,
    )

    ap50 = metrics.box.ap50
    print("\n===== 工作区自评结果 =====")
    print(f"images   : {len(pairs)}")
    print(f"mAP50    : {metrics.box.map50:.4f}")
    print(f"mAP50-95 : {metrics.box.map:.4f}")
    for i, c in enumerate(CLASSES):
        v = float(ap50[i]) if ap50 is not None and i < len(ap50) else float("nan")
        print(f"  {i} {c:<18} AP50={v:.4f}")
    print(f"\n临时数据集保留在: {tmp}（可手动删除）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
