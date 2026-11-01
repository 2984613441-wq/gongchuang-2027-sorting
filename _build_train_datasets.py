#!/usr/bin/env python3
"""把两套复核版数据集转成 ultralytics 可训练的目录（主/副相机**分开**）。

输出：
    _train_main_20261030\\   images/train images/val labels/train labels/val data.yaml
    _train_cam2_20261030\\   同上

划分：随机 80/20（seed 固定），并保证 val 里至少有一个框。
"""

from __future__ import annotations

import glob
import json
import os
import random
import shutil

CLASSES = ["cube", "cuboid", "cylinder", "pentagonal_prism", "cone", "tetrahedron"]
JOBS = [
    ("main", r"_dataset_main_20261030_复核后", r"_train_main_20261030", 0.20),
    ("cam2", r"_dataset_cam2_复核后", r"_train_cam2_20261030", 0.20),
]


def n_boxes(p):
    return sum(1 for ln in open(p, encoding="utf-8") if len(ln.split()) == 5)


def build(tag, src, dst, val_ratio, seed=0):
    imgs = sorted(glob.glob(os.path.join(src, "images", "*.jpg")))
    pairs = []
    for p in imgs:
        stem = os.path.splitext(os.path.basename(p))[0]
        lp = os.path.join(src, "labels", stem + ".txt")
        if os.path.exists(lp) and n_boxes(lp) > 0:
            pairs.append((p, lp))
    random.Random(seed).shuffle(pairs)
    n_val = max(1, int(round(len(pairs) * val_ratio)))
    val, train = pairs[:n_val], pairs[n_val:]

    shutil.rmtree(dst, ignore_errors=True)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        os.makedirs(os.path.join(dst, sub))

    for split, items in (("train", train), ("val", val)):
        for p, lp in items:
            shutil.copy2(p, os.path.join(dst, "images", split, os.path.basename(p)))
            shutil.copy2(lp, os.path.join(dst, "labels", split, os.path.basename(lp)))

    yaml_path = os.path.join(dst, "data.yaml")
    with open(yaml_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("path: %s\n" % os.path.abspath(dst).replace("\\", "/"))
        f.write("train: images/train\nval: images/val\n")
        f.write("nc: %d\nnames:\n" % len(CLASSES))
        for i, c in enumerate(CLASSES):
            f.write("  %d: %s\n" % (i, c))

    print("[%s] 总 %d 张 → train %d / val %d" % (tag, len(pairs), len(train), len(val)))
    print("      data.yaml: %s" % yaml_path)
    return dict(tag=tag, src=src, dst=dst, total=len(pairs), train=len(train), val=len(val),
                yaml=yaml_path)


def main() -> int:
    out = [build(*j) for j in JOBS]
    json.dump(out, open("_train_datasets_20261030.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
