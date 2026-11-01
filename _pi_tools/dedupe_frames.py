#!/usr/bin/env python3
"""去重：找出「干净帧」里有多少个**不同摆放**（场景）。

## 为什么需要

`cap_1s.py` 每 1 秒拍一张。摆一次物料不动 3 秒 ⇒ 存 3 张几乎一样的图。
⇒ 40 张"干净帧"可能只代表 5~10 个不同摆放。
⇒ 直接拿去训练会让数据集**严重偏向少数场景**。

## 做法

对每帧算一个"场景签名"：缩到 32x32 灰度 + 归一化，然后按汉明/欧氏距离聚类。
距离 < 阈值的归为同一场景，只保留第一帧。

用法：
  python _pi_tools/dedupe_frames.py --src _new_capture/.../_clean3
  python _pi_tools/dedupe_frames.py --src _new_capture/.../_clean3 --copy
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

SIG_SIZE = 32


def signature(img) -> np.ndarray:
    """32x32 灰度签名，归一化到 0~1。"""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (SIG_SIZE, SIG_SIZE), interpolation=cv2.INTER_AREA)
    return g.astype(np.float32) / 255.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="按场景去重")
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default=None, help="输出目录（默认 <src>/_dedup）")
    ap.add_argument("--thresh", type=float, default=0.06,
                    help="签名差阈值（0~1，越小越严格；默认 0.06）")
    ap.add_argument("--copy", action="store_true", help="实际复制代表帧")
    args = ap.parse_args(argv)

    src = Path(args.src)
    frames = sorted(src.glob("*.jpg"))
    if not frames:
        print("❌ 没有 .jpg")
        return 1

    print("=" * 72)
    print("  按场景去重")
    print("=" * 72)
    print("  源目录: %s" % src)
    print("  帧数  : %d" % len(frames))
    print("  阈值  : %.3f" % args.thresh)
    print()

    sigs = []
    names = []
    for p in frames:
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            continue
        sigs.append(signature(img))
        names.append(p.name)

    # 贪心聚类：与已选代表帧的最小距离 < thresh ⇒ 同场景，丢弃
    reps = []          # [(idx, name)]
    groups = []        # 每组包含哪些帧
    for i, s in enumerate(sigs):
        best_d = 1e9
        best_j = -1
        for j, (ri, _) in enumerate(reps):
            d = float(np.abs(s - sigs[ri]).mean())
            if d < best_d:
                best_d = d
                best_j = j
        if best_d < args.thresh:
            groups[best_j].append(names[i])
        else:
            reps.append((i, names[i]))
            groups.append([names[i]])

    print("=" * 72)
    print("  结果")
    print("=" * 72)
    print("  总帧数     : %d" % len(names))
    print("  不同场景   : %d" % len(reps))
    print("  平均每场景 : %.1f 帧" % (len(names) / max(1, len(reps))))
    print()
    print("  各场景（代表帧 + 重复帧数）:")
    for j, (ri, rname) in enumerate(reps):
        g = groups[j]
        print("    [%2d] %-14s  重复 %2d 帧" % (j + 1, rname, len(g)))

    print()
    if args.copy:
        out = Path(args.out) if args.out else src / "_dedup"
        out.mkdir(parents=True, exist_ok=True)
        for ri, rname in reps:
            shutil.copy2(src / rname, out / rname)
        print("  ✅ 已复制 %d 张代表帧到 %s" % (len(reps), out))
    else:
        print("  （未复制。加 --copy 实际输出代表帧）")

    print()
    print("  说明:")
    print("    不同场景数 = 这批数据的**真实多样性**。")
    print("    < 15 个场景 ⇒ 数据量不足，训练会过拟合。")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
