# -*- coding: utf-8 -*-
"""把多个 6 类主相机数据集合并成一个（去重 + 固定划分），2026-11-05。

背景：现有数据集按批次分散（v7/v9/v10/v11 + main_6c_v2），类别映射一致
（0=cube 1=cuboid 2=cylinder 3=pentagonal_prism 4=cone 5=tetrahedron）。
训练新模型前先把它们并成一个超集，避免"只用某一批"导致召回下降。

做法：
  * 按图片内容 sha1 去重（不同批次常有重复帧）
  * 用 sha1 决定 train/val（85/15，可复现，不随来源变化）
  * 缺标签的图片跳过并计数
  * 输出 `_train_6c_merged_<日期>/`（images/train、images/val、labels/...、data.yaml）

用法：
    python 工具/merge_6c_datasets.py --out _train_6c_merged_20261105
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLASS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism", "cone", "tetrahedron"]
DEFAULT_SOURCES = [
    "_dataset_yolo_6c_v7",
    "_dataset_yolo_6c_v9",
    "_dataset_yolo_6c_v10",
    "_dataset_yolo_6c_v11",
    "_train_main_6c_v2",
]
IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp"}


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_train_6c_merged_20261105")
    ap.add_argument("--sources", default="")
    ap.add_argument("--val-ratio", type=float, default=0.15)
    args = ap.parse_args()

    out = ROOT / args.out
    if out.exists():
        print("输出目录已存在，先确认是否要覆盖：%s" % out)
        return 1
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    sources = ([s.strip() for s in args.sources.split(",") if s.strip()]
               if args.sources else DEFAULT_SOURCES)
    seen: set[str] = set()
    stats = {"total": 0, "dup": 0, "no_label": 0, "train": 0, "val": 0,
             "per_class": {i: 0 for i in range(6)}, "per_source": {}}

    for src_name in sources:
        src = ROOT / src_name
        if not src.exists():
            print("跳过（不存在）：%s" % src_name)
            continue
        n_add = 0
        for split in ("train", "val"):
            img_dir = src / "images" / split
            if not img_dir.exists():
                continue
            for img in sorted(img_dir.iterdir()):
                if not img.is_file() or img.suffix.lower() not in IMG_EXT:
                    continue
                label = src / "labels" / split / (img.stem + ".txt")
                if not label.exists():
                    stats["no_label"] += 1
                    continue
                digest = sha1_file(img)
                if digest in seen:
                    stats["dup"] += 1
                    continue
                seen.add(digest)
                bucket = "val" if (int(digest[:8], 16) % 100) < int(args.val_ratio * 100) else "train"
                dst_img = out / "images" / bucket / img.name
                dst_lbl = out / "labels" / bucket / (img.stem + ".txt")
                if dst_img.exists():                       # 同名不同图：加后缀
                    dst_img = dst_img.with_name("%s_%s%s" % (img.stem, digest[:6], img.suffix))
                    dst_lbl = dst_lbl.with_name("%s_%s.txt" % (img.stem, digest[:6]))
                shutil.copy2(img, dst_img)
                shutil.copy2(label, dst_lbl)
                for line in label.read_text(encoding="utf-8", errors="ignore").splitlines():
                    parts = line.split()
                    if parts:
                        cid = int(float(parts[0]))
                        if cid in stats["per_class"]:
                            stats["per_class"][cid] += 1
                stats["total"] += 1
                stats[bucket] += 1
                n_add += 1
        stats["per_source"][src_name] = n_add
        print("%-28s +%d" % (src_name, n_add))

    yaml = out / "data.yaml"
    lines = ["# 合并 6 类数据集（工具/merge_6c_datasets.py 生成，2026-11-05）",
             "path: %s" % out.as_posix(),
             "train: images/train",
             "val: images/val",
             "nc: 6",
             "names:"]
    lines += ["  %d: %s" % (i, n) for i, n in enumerate(CLASS_NAMES)]
    yaml.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n合计 %d 张（train %d / val %d），去重 %d，缺标签 %d" % (
        stats["total"], stats["train"], stats["val"], stats["dup"], stats["no_label"]))
    print("每类实例数：" + ", ".join("%s=%d" % (CLASS_NAMES[i], c)
                                    for i, c in stats["per_class"].items()))
    print("data.yaml →", yaml)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
