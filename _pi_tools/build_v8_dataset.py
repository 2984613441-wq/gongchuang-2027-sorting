#!/usr/bin/env python3
"""构建 v8 数据集 = 现有 v7 数据 + 20261028 新批次的人工标注。

## 数据来源

    ① _dataset_yolo_6c_v7/           上一轮（用户复核过的 216 张 → 154/41 划分）
    ② _new_capture_20261028/          今天新拍 179 帧
       · all/*.jpg                    合并后的帧
       · _crops/index.json            430 个裁片 → (frame, box)
       · label_overrides_20261028.py  我判的 430 个字母（24 个 X 跳过）

## 输出

    _dataset_yolo_6c_v8/
        images/train, images/val
        labels/train, labels/val
        data.yaml
        build_info.json

## 用法

    python _pi_tools/build_v8_dataset.py
    python _pi_tools/build_v8_dataset.py --val-ratio 0.2
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
V7 = ROOT / "_dataset_yolo_6c_v7"
NEW = ROOT / "_new_capture_20261028"
OUT = ROOT / "_dataset_yolo_6c_v8"

sys.path.insert(0, str(ROOT / "_pi_tools"))
from label_overrides_20261028 import build_class_map  # noqa: E402

CLASS_NAMES = ["cube", "cuboid", "cylinder",
               "pentagonal_prism", "cone", "tetrahedron"]


def read_yolo(p: Path) -> list[str]:
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        try:
            c = int(float(parts[0]))
            x, y, w, h = (float(v) for v in parts[1:])
        except ValueError:
            continue
        if 0 <= c < 6 and w > 0 and h > 0:
            out.append("%d %.6f %.6f %.6f %.6f" % (c, x, y, w, h))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--val-ratio", type=float, default=0.2)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    print("=" * 78)
    print("  构建 v8 数据集")
    print("=" * 78)

    # ── ① 读 v7 现有数据 ──
    items: list[tuple[Path, str, list[str]]] = []   # (img, stem, label_lines)
    for split in ("train", "val"):
        idir = V7 / "images" / split
        ldir = V7 / "labels" / split
        if not idir.is_dir():
            continue
        n = 0
        for img in sorted(idir.glob("*.jpg")):
            lab = read_yolo(ldir / (img.stem + ".txt"))
            if lab:
                items.append((img, img.stem, lab))
                n += 1
        print("  v7 %-5s : %d 帧有标签" % (split, n))
    n_v7 = len(items)
    print("  v7 合计 : %d 帧" % n_v7)
    print()

    # ── ② 读新批次标注 ──
    idx = json.loads((NEW / "_crops" / "index.json").read_text(encoding="utf-8"))
    gid2cls = build_class_map()
    print("  新批次裁片: %d 个，其中可用（非 X）: %d"
          % (len(idx), len(gid2cls)))

    # frame -> [(cls, x,y,w,h)]
    per_frame: dict[str, list[tuple[int, int, int, int, int]]] = defaultdict(list)
    n_skip = 0
    for it in idx:
        g = int(it["gid"])
        if g not in gid2cls:
            n_skip += 1
            continue
        per_frame[it["frame"]].append(
            (gid2cls[g], int(it["x"]), int(it["y"]), int(it["w"]), int(it["h"])))
    print("  跳过(X) : %d" % n_skip)
    print("  涉及帧  : %d" % len(per_frame))
    print()

    # 转 YOLO 归一化（1280x720）
    W, H = 1280.0, 720.0
    n_new_frames = 0
    n_new_boxes = 0
    for fname, boxes in sorted(per_frame.items()):
        img = NEW / "all" / fname
        if not img.is_file():
            print("  ⚠️ 缺图: %s" % fname)
            continue
        lines = []
        for cls, x, y, w, h in boxes:
            cx = (x + w / 2.0) / W
            cy = (y + h / 2.0) / H
            bw = w / W
            bh = h / H
            if not (0 <= cx <= 1 and 0 <= cy <= 1 and 0 < bw <= 1 and 0 < bh <= 1):
                continue
            lines.append("%d %.6f %.6f %.6f %.6f" % (cls, cx, cy, bw, bh))
        if lines:
            # stem 加前缀避免和 v7 重名
            items.append((img, "n_" + img.stem, lines))
            n_new_frames += 1
            n_new_boxes += len(lines)
    print("  新批次可用: %d 帧 / %d 框" % (n_new_frames, n_new_boxes))
    print()
    print("  合并合计: %d 帧 / %d 框"
          % (len(items), sum(len(l) for _, _, l in items)))
    print()

    if args.dry_run:
        print("  [dry-run] 不写盘")
        return 0

    # ── ③ 划分 ──
    train, val = [], []
    for img, stem, lab in items:
        h = int(hashlib.md5(stem.encode()).hexdigest()[:8], 16)
        (val if (h % 1000) / 1000.0 < args.val_ratio else train).append(
            (img, stem, lab))
    print("  划分: train %d 帧 (%d 框) / val %d 帧 (%d 框)"
          % (len(train), sum(len(l) for _, _, l in train),
             len(val), sum(len(l) for _, _, l in val)))

    # ── ④ 写盘 ──
    if OUT.exists():
        shutil.rmtree(OUT)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)

    def emit(group, split: str) -> int:
        n = 0
        for img, stem, lab in group:
            try:
                shutil.copy2(img, OUT / "images" / split / (stem + ".jpg"))
            except Exception as e:
                print("  ⚠️ 复制失败 %s: %s" % (img.name, e))
                continue
            (OUT / "labels" / split / (stem + ".txt")).write_text(
                "\n".join(lab) + "\n", encoding="utf-8")
            n += 1
        return n

    print("  写 train ...")
    n_tr = emit(train, "train")
    print("  写 val ...")
    n_va = emit(val, "val")

    (OUT / "data.yaml").write_text(
        "# 6 类 · 30° 斜视 · v7 用户复核数据 + 20261028 新批次\n"
        "path: %s\n"
        "train: images/train\n"
        "val: images/val\n"
        "nc: 6\n"
        "names:\n" % str(OUT).replace("\\", "/")
        + "".join("  %d: %s\n" % (i, nm) for i, nm in enumerate(CLASS_NAMES)),
        encoding="utf-8")

    cnt = Counter()
    for _, _, lab in items:
        for line in lab:
            cnt[int(line.split()[0])] += 1
    (OUT / "build_info.json").write_text(json.dumps({
        "v7_frames": n_v7,
        "new_frames_used": n_new_frames,
        "new_boxes_used": n_new_boxes,
        "new_boxes_skipped_X": n_skip,
        "n_train": n_tr,
        "n_val": n_va,
        "class_counts": {CLASS_NAMES[c]: cnt.get(c, 0) for c in range(6)},
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print()
    print("=" * 78)
    print("  ✅ v8 数据集完成: %s" % OUT)
    print("     train %d / val %d" % (n_tr, n_va))
    print()
    print("  类别分布:")
    for c in range(6):
        v = cnt.get(c, 0)
        print("    %d %-18s %4d%s" % (c, CLASS_NAMES[c], v,
                                      "  ⚠️ 偏少" if v < 20 else ""))
    print("    合计 %d 框" % sum(cnt.values()))
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
