#!/usr/bin/env python3
"""构建 v10 数据集 = v9 数据集 + 20261028b 批次（用户补的弱项数据）。

## 为什么加这批

v9 验证暴露三个弱项：
    cuboid 召回 0.702 / pentagonal_prism 0.727 / tetrahedron 仅 22 框
用户据此采集 100 帧，经 v9 预标 + 我逐格判读（200px 拼图）：
    cuboid 162 / pentagonal_prism 75 / tetrahedron 20 / cone 2  （共 259 可用）

## 输出

    _dataset_yolo_6c_v10/
        images/train, images/val
        labels/train, labels/val
        data.yaml
        build_info.json

## 用法

    python _pi_tools/build_v10_dataset.py
    python _pi_tools/build_v10_dataset.py --val-ratio 0.2
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
V9 = ROOT / "_dataset_yolo_6c_v9"
NEW = ROOT / "_new_capture_20261028b"
OUT = ROOT / "_dataset_yolo_6c_v10"

sys.path.insert(0, str(ROOT / "_pi_tools"))
from label_overrides_20261028b import build_class_map  # noqa: E402

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
        if 0 <= c < 6 and 0 < w <= 1 and 0 < h <= 1:
            out.append("%d %.6f %.6f %.6f %.6f" % (c, x, y, w, h))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--val-ratio", type=float, default=0.2)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    print("=" * 78)
    print("  构建 v10 数据集")
    print("=" * 78)

    # ── ① v9 作为基底 ──
    items = []
    for split in ("train", "val"):
        idir, ldir = V9 / "images" / split, V9 / "labels" / split
        if not idir.is_dir():
            continue
        n = 0
        for img in sorted(idir.glob("*.jpg")):
            lab = read_yolo(ldir / (img.stem + ".txt"))
            if lab:
                items.append((img, img.stem, lab))
                n += 1
        print("  v9 %-5s : %d 帧" % (split, n))
    n_v9 = len(items)
    print("  v9 合计 : %d 帧 / %d 框"
          % (n_v9, sum(len(l) for _, _, l in items)))
    print()

    # ── ② 新批次 ──
    idx_path = NEW / "_crops" / "index.json"
    if not idx_path.is_file():
        print("❌ 缺 %s" % idx_path)
        return 1
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    gid2cls = build_class_map()
    print("  新批次裁片: %d，可用（非 X）: %d" % (len(idx), len(gid2cls)))

    per_frame: dict[str, list] = defaultdict(list)
    n_skip = 0
    for it in idx:
        g = int(it["gid"])
        if g not in gid2cls:
            n_skip += 1
            continue
        per_frame[it["frame"]].append(
            (gid2cls[g], int(it["x"]), int(it["y"]), int(it["w"]), int(it["h"])))

    W, H = 1280.0, 720.0
    n_new_f = n_new_b = 0
    for fname, boxes in sorted(per_frame.items()):
        img = NEW / "all" / fname
        if not img.is_file():
            print("  ⚠️ 缺图: %s" % fname)
            continue
        lines = []
        for cls, x, y, w, h in boxes:
            cx = (x + w / 2.0) / W
            cy = (y + h / 2.0) / H
            bw, bh = w / W, h / H
            if not (0 <= cx <= 1 and 0 <= cy <= 1 and 0 < bw <= 1 and 0 < bh <= 1):
                continue
            lines.append("%d %.6f %.6f %.6f %.6f" % (cls, cx, cy, bw, bh))
        if lines:
            items.append((img, "b_" + img.stem, lines))
            n_new_f += 1
            n_new_b += len(lines)
    print("  新批次可用: %d 帧 / %d 框（跳过 %d）" % (n_new_f, n_new_b, n_skip))
    print()

    all_cnt = Counter()
    for _, _, lab in items:
        for line in lab:
            all_cnt[int(line.split()[0])] += 1
    print("  合并合计: %d 帧 / %d 框" % (len(items), sum(all_cnt.values())))
    print()
    print("  类别分布:")
    for c in range(6):
        v = all_cnt.get(c, 0)
        flag = "  ⚠️ 无样本" if v == 0 else ("  ⚠️ 偏少" if v < 20 else "")
        print("    %d %-18s %4d%s" % (c, CLASS_NAMES[c], v, flag))
    print("    合计 %d 框" % sum(all_cnt.values()))
    print()

    if args.dry_run:
        print("  [dry-run] 不写盘")
        return 0

    # ── ③ 划分 + 写盘 ──
    train, val = [], []
    for img, stem, lab in items:
        h = int(hashlib.md5(stem.encode()).hexdigest()[:8], 16)
        (val if (h % 1000) / 1000.0 < args.val_ratio else train).append(
            (img, stem, lab))
    print("  划分: train %d 帧 (%d 框) / val %d 帧 (%d 框)"
          % (len(train), sum(len(l) for _, _, l in train),
             len(val), sum(len(l) for _, _, l in val)))

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
        "# 6 类 · 30° 斜视 · v9 数据 + 20261028b 弱项补充数据\n"
        "path: %s\n"
        "train: images/train\n"
        "val: images/val\n"
        "nc: 6\n"
        "names:\n" % str(OUT).replace("\\", "/")
        + "".join("  %d: %s\n" % (i, nm) for i, nm in enumerate(CLASS_NAMES)),
        encoding="utf-8")

    (OUT / "build_info.json").write_text(json.dumps({
        "v9_frames": n_v9,
        "new_frames": n_new_f,
        "new_boxes": n_new_b,
        "n_train": n_tr,
        "n_val": n_va,
        "class_counts": {CLASS_NAMES[c]: all_cnt.get(c, 0) for c in range(6)},
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print()
    print("=" * 78)
    print("  ✅ v10 数据集完成: %s" % OUT)
    print("     train %d / val %d,  合计 %d 框" % (n_tr, n_va, sum(all_cnt.values())))
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
