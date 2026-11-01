#!/usr/bin/env python3
"""分析 tilt30 采集帧之间的相似度距离分布，用来选一个合理的去重阈值。

用法：
    python _pi_tools/analyze_dedupe_thresh.py
    python _pi_tools/analyze_dedupe_thresh.py --sample 120
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
ALL_DIR = ROOT / "_new_capture_tilt30" / "all"


def sig_gray(p: Path, w=48, h=27) -> np.ndarray | None:
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    g = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    return g.astype(np.float32) / 255.0


def sig_hist(p: Path) -> np.ndarray | None:
    """颜色直方图签名（对光照变化更鲁棒）。"""
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # 只取托盘中部区域
    H, W = hsv.shape[:2]
    roi = hsv[H // 6: 5 * H // 6, W // 6: 5 * W // 6]
    h = cv2.calcHist([roi], [0, 1], None, [32, 32], [0, 180, 0, 256])
    cv2.normalize(h, h, 0, 1, cv2.NORM_MINMAX)
    return h.flatten().astype(np.float32)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=150,
                    help="最多分析多少帧（默认 150，按顺序均匀取样）")
    args = ap.parse_args(argv)

    files = sorted(ALL_DIR.glob("*.jpg"))
    if not files:
        print("❌ %s 里没有图" % ALL_DIR)
        return 1
    print("总帧数 %d" % len(files))

    # 均匀取样
    n = min(args.sample, len(files))
    idx = np.linspace(0, len(files) - 1, n).astype(int)
    sel = [files[i] for i in idx]
    print("取样 %d 帧" % len(sel))
    print()

    # ── 灰度签名 ───────────────────────────────────────────────
    gs = [sig_gray(f) for f in sel]
    gs = [g for g in gs if g is not None]
    print("=" * 72)
    print("  灰度 48x27 签名的距离分布（相邻帧 / 全部配对）")
    print("=" * 72)
    adj = [float(np.abs(gs[i] - gs[i + 1]).mean()) for i in range(len(gs) - 1)]
    adj = np.array(adj)
    print("  相邻帧距离:  min %.5f  中位 %.5f  均 %.5f  max %.5f"
          % (adj.min(), np.median(adj), adj.mean(), adj.max()))
    for q in (10, 25, 50, 75, 90, 95):
        print("    P%-3d = %.5f" % (q, np.percentile(adj, q)))
    print()

    # 全部配对（对称矩阵上三角）
    m = len(gs)
    pairs = []
    for i in range(m):
        for j in range(i + 1, m):
            pairs.append(float(np.abs(gs[i] - gs[j]).mean()))
    pairs = np.array(pairs)
    print("  全部配对 (%d 对): 中位 %.5f  均 %.5f" % (len(pairs), np.median(pairs), pairs.mean()))
    for q in (1, 5, 10, 25, 50):
        print("    P%-3d = %.5f" % (q, np.percentile(pairs, q)))
    print()

    print("  ⇒ 建议阈值（灰度）:")
    for q in (5, 10, 25, 50):
        th = float(np.percentile(pairs, q))
        # 估算：用该阈值做单链聚类，看能分成多少组
        used = [False] * m
        ng = 0
        for i in range(m):
            if used[i]:
                continue
            used[i] = True
            ng += 1
            for j in range(i + 1, m):
                if not used[j] and float(np.abs(gs[i] - gs[j]).mean()) < th:
                    used[j] = True
        print("     P%-3d = %.5f  →  约 %d 组（取样 %d 帧，折算全量约 %d 组）"
              % (q, th, ng, m, int(round(ng / m * len(files)))))
    print()

    # ── 颜色直方图签名 ─────────────────────────────────────────
    hs = [sig_hist(f) for f in sel]
    hs = [h for h in hs if h is not None]
    if len(hs) >= 2:
        print("=" * 72)
        print("  HSV 直方图签名的距离分布（对光照更鲁棒）")
        print("=" * 72)
        hp = []
        for i in range(len(hs)):
            for j in range(i + 1, len(hs)):
                hp.append(float(np.abs(hs[i] - hs[j]).mean()))
        hp = np.array(hp)
        print("  全部配对: 中位 %.6f  均 %.6f" % (np.median(hp), hp.mean()))
        for q in (5, 10, 25, 50):
            th = float(np.percentile(hp, q))
            used = [False] * len(hs)
            ng = 0
            for i in range(len(hs)):
                if used[i]:
                    continue
                used[i] = True
                ng += 1
                for j in range(i + 1, len(hs)):
                    if not used[j] and float(np.abs(hs[i] - hs[j]).mean()) < th:
                        used[j] = True
            print("     P%-3d = %.6f  →  约 %d 组（折算全量约 %d 组）"
                  % (q, th, ng, int(round(ng / len(hs) * len(files)))))
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
