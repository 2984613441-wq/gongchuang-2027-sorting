#!/usr/bin/env python3
"""测试现有 v4 模型在**新 30° 视角**下的检出能力 —— 决定标注策略。

## 为什么要测

新采集了 480 帧（全是不同布局，无法去重）。
如果 v4 在新视角下检出率够高（比如每帧能检到 4~6 个），
就可以「v4 自动预标 → 人工只修错的」，比从零标注快 5~10 倍。

如果 v4 检出率很低，就只能纯人工标，或者换更省事的策略。

## 用法

    python _pi_tools/test_v4_on_newview.py
    python _pi_tools/test_v4_on_newview.py --sample 30 --conf 0.25
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
ALL_DIR = ROOT / "_new_capture_tilt30" / "all"
WEIGHTS = ROOT / "_runs" / "yolo11n_6c_v4" / "weights" / "best.pt"

CLASS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism",
               "cone", "tetrahedron"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=30)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=448)
    args = ap.parse_args(argv)

    files = sorted(ALL_DIR.glob("*.jpg"))
    if not files:
        print("❌ %s 里没图" % ALL_DIR)
        return 1

    n = min(args.sample, len(files))
    idx = np.linspace(0, len(files) - 1, n).astype(int)
    sel = [files[i] for i in idx]

    from ultralytics import YOLO
    model = YOLO(str(WEIGHTS))

    print("=" * 76)
    print("  v4 模型在新 30° 视角下的检出能力测试")
    print("=" * 76)
    print("  权重   : %s" % WEIGHTS.name)
    print("  取样   : %d 帧（从 %d 帧里均匀抽）" % (n, len(files)))
    print("  conf   : %.2f   imgsz: %d" % (args.conf, args.imgsz))
    print()

    per_frame = []
    cls_cnt = Counter()
    conf_all = []

    for f in sel:
        img = cv2.imdecode(np.fromfile(str(f), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            continue
        res = model(img, imgsz=args.imgsz, conf=args.conf, iou=0.45,
                    verbose=False)[0]
        nb = len(res.boxes)
        per_frame.append(nb)
        for b in res.boxes:
            cls_cnt[int(b.cls)] += 1
            conf_all.append(float(b.conf))

    if not per_frame:
        print("❌ 没有有效结果")
        return 1

    pf = np.array(per_frame)
    print("  每帧检出数:  min %d  中位 %.0f  均 %.2f  max %d"
          % (pf.min(), np.median(pf), pf.mean(), pf.max()))
    dist = Counter(per_frame)
    print("  分布:")
    for k in sorted(dist):
        print("    %d 个框: %3d 帧 (%.0f%%)"
              % (k, dist[k], dist[k] / len(per_frame) * 100))
    print()

    if conf_all:
        ca = np.array(conf_all)
        print("  置信度:  min %.2f  中位 %.2f  均 %.2f  max %.2f"
              % (ca.min(), np.median(ca), ca.mean(), ca.max()))
        for th in (0.3, 0.5, 0.7, 0.85):
            print("    conf >= %.2f 占 %.0f%%" % (th, (ca >= th).mean() * 100))
    print()

    print("  各类检出数:")
    tot = 0
    for cid in range(6):
        k = cls_cnt.get(cid, 0)
        tot += k
        print("    %d %-18s %4d" % (cid, CLASS_NAMES[cid], k))
    print("    %-20s %4d" % ("合计", tot))
    print()

    # ── 判据 ──────────────────────────────────────────────────
    print("=" * 76)
    print("  判据")
    print("=" * 76)
    med = np.median(pf)
    if med >= 4:
        print("  ✅ 中位 %.0f 个/帧 ⇒ v4 在新视角上**基本可用**" % med)
        print("     ⇒ 采用「v4 自动预标 → 人工只修错」策略，快 5~10 倍")
    elif med >= 2:
        print("  ⚠️ 中位 %.0f 个/帧 ⇒ v4 只能检到一部分" % med)
        print("     ⇒ 可做「预标 + 大量人工补漏」，仍比从零快")
    else:
        print("  ❌ 中位 %.0f 个/帧 ⇒ v4 在新视角上基本失效" % med)
        print("     ⇒ 只能纯人工标注，或先把相机调回旧取景")
    hi_conf = (np.array(conf_all) >= 0.7).mean() * 100 if conf_all else 0
    print()
    print("  conf>=0.7 占比 %.0f%%（越高说明检出的越可信）" % hi_conf)
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
