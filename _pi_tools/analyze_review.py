#!/usr/bin/env python3
"""分析用户复核后的标签：找出无标签照片（要删）+ 统计修正情况。

## 规则（用户确立）

**没有标签 / 所有框被删光 = 这张图不想要 ⇒ 删掉。**

## 用途

1. 列出被删空的帧（用户判定"不想要"）
2. 对比复核前后类别分布，看用户改了什么
3. 输出 `_review_v6/review_diff.json` 供后续重建数据集

## 用法

    python _pi_tools/analyze_review.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / "_review_v6"
IMGS = REVIEW / "images"
LBL = REVIEW / "labels"
ORIG = ROOT / "_dataset_yolo_6c_v6"

CLASS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism",
               "cone", "tetrahedron"]


def read_labels(p: Path) -> list[tuple[int, float, float, float, float]]:
    out = []
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        try:
            out.append((int(float(parts[0])), float(parts[1]),
                        float(parts[2]), float(parts[3]), float(parts[4])))
        except ValueError:
            continue
    return out


def main() -> int:
    if not IMGS.is_dir() or not LBL.is_dir():
        print("❌ 缺 %s 或 %s" % (IMGS, LBL))
        return 1

    imgs = sorted(p.stem for p in IMGS.glob("*.jpg"))
    print("=" * 78)
    print("  复核结果分析")
    print("=" * 78)
    print("  图片总数: %d" % len(imgs))
    print()

    empty: list[str] = []
    kept: list[str] = []
    cnt_now = Counter()
    cnt_orig = Counter()
    per_frame: dict[str, list] = {}

    for stem in imgs:
        now = read_labels(LBL / (stem + ".txt"))
        orig = read_labels(ORIG / "labels" / "train" / (stem + ".txt")) or \
            read_labels(ORIG / "labels" / "val" / (stem + ".txt"))
        if not now:
            empty.append(stem)
            continue
        kept.append(stem)
        per_frame[stem] = now
        for b in now:
            cnt_now[b[0]] += 1
        for b in orig:
            cnt_orig[b[0]] += 1

    print("  🔴 无标签（用户判定不想要）: %d 张" % len(empty))
    print("  ✅ 保留: %d 张" % len(kept))
    print()

    if empty:
        print("  要删的帧（前 20 个）:")
        for s in empty[:20]:
            print("    %s" % s)
        if len(empty) > 20:
            print("    ... 共 %d 个" % len(empty))
        print()

    print("  类别分布（保留的帧）:")
    print("    %-20s %8s %8s %8s" % ("类别", "复核前", "复核后", "变化"))
    print("    " + "-" * 50)
    tot_o = tot_n = 0
    for cid in range(6):
        o, n = cnt_orig.get(cid, 0), cnt_now.get(cid, 0)
        tot_o += o
        tot_n += n
        d = n - o
        print("    %-20s %8d %8d %+8d" % (CLASS_NAMES[cid], o, n, d))
    print("    " + "-" * 50)
    print("    %-20s %8d %8d %+8d" % ("合计", tot_o, tot_n, tot_n - tot_o))
    print()

    # 帧级变化
    changed_cls = 0
    changed_n = 0
    for stem in kept:
        orig = read_labels(ORIG / "labels" / "train" / (stem + ".txt")) or \
            read_labels(ORIG / "labels" / "val" / (stem + ".txt"))
        now = per_frame[stem]
        if len(orig) != len(now):
            changed_n += 1
        elif sorted(b[0] for b in orig) != sorted(b[0] for b in now):
            changed_cls += 1
    print("  帧级修正:")
    print("    框数变化: %d 张" % changed_n)
    print("    类别改判: %d 张" % changed_cls)
    print()

    # 存 diff
    out = {
        "n_images": len(imgs),
        "n_empty_deleted": len(empty),
        "n_kept": len(kept),
        "empty_frames": empty,
        "kept_frames": kept,
        "class_counts_now": {CLASS_NAMES[c]: cnt_now.get(c, 0) for c in range(6)},
        "class_counts_orig": {CLASS_NAMES[c]: cnt_orig.get(c, 0) for c in range(6)},
    }
    (REVIEW / "review_diff.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("  已存: %s" % (REVIEW / "review_diff.json"))
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
