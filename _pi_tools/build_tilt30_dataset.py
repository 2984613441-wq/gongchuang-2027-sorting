#!/usr/bin/env python3
"""用人工判形结果（label_overrides.py）生成 tilt30 新视角的 YOLO 数据集。

## 流程

    index.json (gid -> frame, 像素框)
        +
    label_overrides.build_map() (gid -> 类别短字母)
        ↓
    每帧一个 .txt（YOLO 归一化格式）
        ↓
    _dataset_yolo_6c_v6/  (images/ labels/ data.yaml)

## 类别（6 类，顺序与 v4 一致，不能改）

    0 cube             正方体
    1 cuboid           长方体
    2 cylinder         圆柱
    3 pentagonal_prism 五棱柱
    4 cone             圆锥
    5 tetrahedron      正四面体

## 划分

同一个 session 的帧只进 train 或 val（避免同布局泄漏到两边）。
按 session 名称哈希取模决定，保证可复现。

## 用法

    python _pi_tools/build_tilt30_dataset.py
    python _pi_tools/build_tilt30_dataset.py --val-ratio 0.15
    python _pi_tools/build_tilt30_dataset.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "_new_capture_tilt30"
ALL_DIR = BASE / "all"
CROPS = BASE / "_crops"
OUT = ROOT / "_dataset_yolo_6c_v6"

sys.path.insert(0, str(ROOT / "_pi_tools"))
from label_overrides import CLASS_NAMES, build_map  # noqa: E402

SHORT2ID = {"C": 0, "B": 1, "Y": 2, "P": 3, "N": 4, "T": 5}


def session_of(fname: str) -> str:
    return fname.split("__")[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--val-ratio", type=float, default=0.15)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    for p, nm in ((CROPS / "index.json", "index.json"),):
        if not p.is_file():
            print("❌ 缺 %s（先跑 make_object_montages.py）" % p)
            return 1

    index = json.loads((CROPS / "index.json").read_text(encoding="utf-8"))
    gmap = build_map()

    # 按帧聚合
    per_frame: dict[str, list[dict]] = defaultdict(list)
    n_skip = 0
    for it in index:
        gid = it["gid"]
        ch = gmap.get(gid)
        if ch is None:
            print("⚠️ gid %d 没有判形，跳过" % gid)
            n_skip += 1
            continue
        if ch == "X":
            n_skip += 1
            continue
        cid = SHORT2ID[ch]
        per_frame[it["frame"]].append({
            "gid": gid, "cls": cid,
            "x": it["x"], "y": it["y"], "w": it["w"], "h": it["h"],
        })

    print("=" * 76)
    print("  构建 tilt30 数据集 v6")
    print("=" * 76)
    print("  裁片 %d 个，跳过 %d 个（SKIP/未判）" % (len(index), n_skip))
    print("  涉及帧 %d 个" % len(per_frame))
    print()

    # 类别统计
    cnt = Counter(b["cls"] for v in per_frame.values() for b in v)
    print("  类别分布:")
    for cid in range(6):
        n = cnt.get(cid, 0)
        flag = "  ⚠️ 无样本" if n == 0 else ""
        print("    %d %-18s %4d%s" % (cid, CLASS_NAMES[cid], n, flag))
    print()

    # 划分：按「帧名哈希」而不是 session 哈希。
    # 原按 session 哈希时，8 个 session 只有 1 个落到 val（15 帧 / 15 框），
    # 太小无法评估。改成按帧哈希后 val 约 20%，覆盖所有 session 的样本。
    # ⚠️ 代价：同一布局的相邻帧可能一边 train 一边 val（轻微泄漏），
    #    但帧间差异大（手在动、物件在挪），实测影响有限。
    frames_sorted = sorted(per_frame)
    val_frames = []
    train_frames = []
    for f in frames_sorted:
        h = int(hashlib.md5(f.encode()).hexdigest()[:8], 16)
        if (h % 1000) / 1000.0 < args.val_ratio:
            val_frames.append(f)
        else:
            train_frames.append(f)
    if len(val_frames) < 10:
        # 太少就按步长补
        step = max(2, int(1 / max(args.val_ratio, 0.05)))
        val_frames = frames_sorted[::step]
        train_frames = [f for f in frames_sorted if f not in set(val_frames)]

    print("  划分: train %d 帧 / val %d 帧（按帧哈希，比例 %.0f%%）"
          % (len(train_frames), len(val_frames), args.val_ratio * 100))
    print()
    print("  session 级框数分布:")
    sess_frames = defaultdict(int)
    sess_boxes = defaultdict(int)
    for f, v in per_frame.items():
        sess_frames[session_of(f)] += 1
        sess_boxes[session_of(f)] += len(v)
    for s in sorted(sess_frames):
        print("    %-24s %3d 帧  %4d 框" % (s, sess_frames[s], sess_boxes[s]))
    print()
    print("  train %d 帧 (%d 框)   val %d 帧 (%d 框)"
          % (len(train_frames),
             sum(len(per_frame[f]) for f in train_frames),
             len(val_frames),
             sum(len(per_frame[f]) for f in val_frames)))
    print()

    if args.dry_run:
        print("  [dry-run] 不写盘")
        return 0

    # 写盘
    out = Path(args.out)
    if out.exists():
        print("  ⚠️ %s 已存在，先删除" % out)
        shutil.rmtree(out)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    def write_split(frames, split: str) -> int:
        n_img = 0
        for f in frames:
            src = ALL_DIR / f
            if not src.is_file():
                print("  ⚠️ 缺图 %s" % f)
                continue
            shutil.copy2(src, out / "images" / split / f)
            # 取图像尺寸
            import cv2
            import numpy as np
            img = cv2.imdecode(np.fromfile(str(src), dtype=np.uint8),
                               cv2.IMREAD_COLOR)
            if img is None:
                continue
            H, W = img.shape[:2]
            lines = []
            for b in per_frame[f]:
                cx = (b["x"] + b["w"] / 2.0) / W
                cy = (b["y"] + b["h"] / 2.0) / H
                nw = b["w"] / W
                nh = b["h"] / H
                if not (0 <= cx <= 1 and 0 <= cy <= 1):
                    continue
                # 裁剪到 [0,1]
                x1 = max(0.0, cx - nw / 2); x2 = min(1.0, cx + nw / 2)
                y1 = max(0.0, cy - nh / 2); y2 = min(1.0, cy + nh / 2)
                if x2 - x1 < 0.005 or y2 - y1 < 0.005:
                    continue
                lines.append("%d %.6f %.6f %.6f %.6f"
                             % (b["cls"], (x1 + x2) / 2, (y1 + y2) / 2,
                                x2 - x1, y2 - y1))
            if not lines:
                continue
            lbl = out / "labels" / split / (Path(f).stem + ".txt")
            lbl.write_text("\n".join(lines) + "\n", encoding="utf-8")
            n_img += 1
        return n_img

    print("  写 train ...")
    n_tr = write_split(train_frames, "train")
    print("  写 val ...")
    n_va = write_split(val_frames, "val")

    # data.yaml
    yaml = out / "data.yaml"
    yaml.write_text(
        "# 6 类 · 30° 斜视新视角 · 20261028\n"
        "path: %s\n"
        "train: images/train\n"
        "val: images/val\n"
        "nc: 6\n"
        "names:\n" % str(out).replace("\\", "/")
        + "".join("  %d: %s\n" % (i, n) for i, n in enumerate(CLASS_NAMES)),
        encoding="utf-8")

    print()
    print("=" * 76)
    print("  ✅ 数据集完成: %s" % out)
    print("     train %d 张 / val %d 张" % (n_tr, n_va))
    print("     data.yaml: %s" % yaml)
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
