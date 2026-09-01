#!/usr/bin/env python3
"""把 64 张工作区标注数据并入 round2 数据集，生成 round3（合并训练用）。

结构：round3 = round2（638 张实验室数据，train/val/test=510/64/64）
       + 64 张工作区数据（全部进 train，文件名加 ws_ 前缀）。

数据集目录结构（ultralytics 约定）：
    round3/images/{train,val,test}/  +  round3/labels/{train,val,test}/

工作区数据已重映射为正确 0-6 类别编号（见 remap_labels.py），与 round2 的
classes.txt / data.yaml 的 names 完全一致。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROUND2 = Path(r"D:\AAAdesktop1\shijue\ultralytics-8.3.163\datasets\block_dataset_v1_7class_round2")
ROUND3 = Path(r"D:\AAAdesktop1\shijue\ultralytics-8.3.163\datasets\block_dataset_v1_7class_round3")
WORKSPACE = Path(r"C:\Users\29845\Desktop\工创赛\workspace_label")

CLASSES = (
    "cube", "cuboid", "cylinder", "hexagonal_prism",
    "pentagonal_prism", "square_pyramid", "triangular_prism",
)

SPLITS = ("train", "val", "test")


def copy_split(dst: Path, split: str) -> None:
    """把 round2 的一个 split（images + labels）复制到 round3。"""
    for kind in ("images", "labels"):
        src_dir = ROUND2 / kind / split
        if not src_dir.is_dir():
            raise SystemExit(f"缺失源目录：{src_dir}")
        dst_dir = dst / kind / split
        dst_dir.mkdir(parents=True, exist_ok=True)
        for f in src_dir.iterdir():
            if f.suffix == ".cache":
                continue
            shutil.copy2(f, dst_dir / f.name)


def main() -> int:
    if ROUND3.exists():
        raise SystemExit(f"目标已存在，先手动处理：{ROUND3}")

    ROUND3.mkdir(parents=True)
    for split in SPLITS:
        copy_split(ROUND3, split)

    shutil.copy2(ROUND2 / "classes.txt", ROUND3 / "classes.txt")

    # 工作区 64 张（非空标签）并入 train
    n_ws = 0
    for jpg in sorted(WORKSPACE.glob("img_*.jpg")):
        txt = jpg.with_suffix(".txt")
        if not txt.is_file() or txt.stat().st_size == 0:
            continue
        stem = jpg.stem  # 例如 img_00003
        shutil.copy2(jpg, ROUND3 / "images" / "train" / f"ws_{stem}.jpg")
        shutil.copy2(txt, ROUND3 / "labels" / "train" / f"ws_{stem}.txt")
        n_ws += 1

    # data.yaml（path 指向 round3，其余不变）
    data_yaml = (
        f'path: "{ROUND3.as_posix()}"\n'
        "train: images/train\n"
        "val: images/val\n"
        "test: images/test\n"
        "names:\n"
        + "".join(f'  {i}: "{c}"\n' for i, c in enumerate(CLASSES))
    )
    (ROUND3 / "data.yaml").write_text(data_yaml, encoding="utf-8")

    # manifest.json 记录合并来源
    manifest = {
        "schema_version": "voc-to-yolo-dataset-v1",
        "merged": True,
        "base": "block_dataset_v1_7class_round2",
        "workspace_added": n_ws,
        "workspace_source": str(WORKSPACE),
        "classes": list(CLASSES),
    }
    (ROUND3 / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 校验
    for split in SPLITS:
        n_img = len(list((ROUND3 / "images" / split).glob("*.jpg")))
        n_lbl = len(list((ROUND3 / "labels" / split).glob("*.txt")))
        print(f"{split:5s}: images={n_img:4d}  labels={n_lbl:4d}")

    print(f"\n工作区并入 train 的数量: {n_ws}")
    print(f"输出目录: {ROUND3}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
