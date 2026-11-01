#!/usr/bin/env python3
"""合并多个 tilt30 采集 session，并按像素级相似度去重。

## 为什么需要

`cap_tilt30.py` 每秒一张，同一个摆放会连拍好几张（几乎一模一样）。
480 张里真正"不同布局"可能只有 60~100 个。

去重后每个布局留 1 张代表作，我只需要判这些代表帧的形状，
其余帧自动继承标签 —— 和上一批一样的流水线。

## 与上一批的区别

**上一批有手的帧被 SKIP 了**（用户要求删）。
**这一批用户明确要求：有手的照片也要标注**（因为摆件时手必须入画）。

⇒ 所以本脚本**不按"是否有手"过滤**，只按像素相似度去重。

## 输出

    _new_capture_tilt30/all/         合并后的全部图（session 前缀防重名）
    _new_capture_tilt30/_dedupe/     去重结果
        reps/        每个不同布局的代表帧
        groups.json  分组信息（代表帧 -> 同组其他帧）

## 用法

    python _pi_tools/consolidate_tilt30.py
    python _pi_tools/consolidate_tilt30.py --thresh 0.004
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "_new_capture_tilt30"
ALL_DIR = SRC_ROOT / "all"
DD_DIR = SRC_ROOT / "_dedupe"
REPS_DIR = DD_DIR / "reps"

# 相似度阈值：48x27 灰度的平均绝对差
# 0.004 ≈ 像素级几乎相同；0.010 允许轻微噪声
DEFAULT_THRESH = 0.004


def signature(path: Path) -> np.ndarray | None:
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8),
                       cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    g = cv2.resize(img, (48, 27), interpolation=cv2.INTER_AREA)
    return g.astype(np.float32) / 255.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--thresh", type=float, default=DEFAULT_THRESH,
                    help="相似度阈值（越小越严格，默认 %.3f）" % DEFAULT_THRESH)
    ap.add_argument("--keep", type=int, default=2,
                    help="每个布局最多保留几张（默认 2，留一点多样性）")
    args = ap.parse_args(argv)

    if not SRC_ROOT.is_dir():
        print("❌ 找不到 %s" % SRC_ROOT)
        return 1

    sessions = sorted([d for d in SRC_ROOT.iterdir()
                       if d.is_dir() and d.name.startswith("tilt30_")])
    if not sessions:
        print("❌ %s 下没有 tilt30_* 目录" % SRC_ROOT)
        return 1

    print("=" * 76)
    print("  合并 tilt30 采集 session")
    print("=" * 76)
    print("  找到 %d 个 session" % len(sessions))
    total_src = 0
    for d in sessions:
        n = len(list(d.glob("*.jpg")))
        total_src += n
        print("    %-28s %4d 张" % (d.name, n))
    print("  ─────────────────────────────────────────")
    print("  原始合计 %d 张" % total_src)
    print()

    # ── 1) 合并（加 session 前缀防重名）───────────────────────
    ALL_DIR.mkdir(parents=True, exist_ok=True)
    merged = 0
    for d in sessions:
        tag = d.name.replace("tilt30_", "")
        for f in sorted(d.glob("*.jpg")):
            dst = ALL_DIR / ("%s__%s" % (tag, f.name))
            if dst.exists():
                continue
            shutil.copy2(f, dst)
            merged += 1
    print("  ✅ 合并 %d 张到 %s" % (merged, ALL_DIR))
    print()

    # ── 2) 去重 ────────────────────────────────────────────────
    files = sorted(ALL_DIR.glob("*.jpg"))
    print("  去重（阈值 %.3f，每布局最多留 %d 张）..." % (args.thresh, args.keep))
    sigs = []
    for f in files:
        s = signature(f)
        if s is not None:
            sigs.append((f, s))
    print("  可读 %d / %d 张" % (len(sigs), len(files)))

    used = [False] * len(sigs)
    groups = []
    for i in range(len(sigs)):
        if used[i]:
            continue
        members = [i]
        used[i] = True
        for j in range(i + 1, len(sigs)):
            if used[j]:
                continue
            d = float(np.abs(sigs[i][1] - sigs[j][1]).mean())
            if d < args.thresh:
                members.append(j)
                used[j] = True
        groups.append(members)

    n_groups = len(groups)
    kept_plan = []
    for g in groups:
        keep_n = min(args.keep, len(g))
        for k in range(keep_n):
            kept_plan.append(sigs[g[k]][0])

    print("  ✅ %d 张 → %d 个不同布局" % (len(sigs), n_groups))
    print("  ✅ 保留 %d 张代表作（每布局 %d 张）" % (len(kept_plan), args.keep))
    print()

    # 分组大小分布
    from collections import Counter
    dist = Counter(len(g) for g in groups)
    print("  分组大小分布:")
    for k in sorted(dist):
        print("    %d 张的组: %3d 个" % (k, dist[k]))
    print()

    if not args.dry_run if hasattr(args, "dry_run") else True:
        pass

    # ── 3) 写盘 ────────────────────────────────────────────────
    if REPS_DIR.is_dir():
        shutil.rmtree(REPS_DIR)
    REPS_DIR.mkdir(parents=True, exist_ok=True)
    for f in kept_plan:
        shutil.copy2(f, REPS_DIR / f.name)

    info = []
    for gi, g in enumerate(groups):
        info.append({
            "group": gi,
            "n_frames": len(g),
            "rep": sigs[g[0]][0].name,
            "kept": [sigs[k][0].name for k in g[:args.keep]],
            "all": [sigs[k][0].name for k in g],
        })
    (DD_DIR / "groups.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")

    print("=" * 76)
    print("  ✅ 完成")
    print("=" * 76)
    print("  合并全部 : %s" % ALL_DIR)
    print("  代表作   : %s  (%d 张)" % (REPS_DIR, len(kept_plan)))
    print("  分组信息 : %s" % (DD_DIR / "groups.json"))
    print()
    print("  ⇒ 下一步：对 reps/ 做形状标注")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
