#!/usr/bin/env python3
"""按「物件位置」去重 —— 解决 480 帧全被当成不同布局的问题。

## 为什么整幅图像签名不行

实测：相邻帧的 48x27 灰度距离中位 **0.123**（几乎完全不同）。
原因是**手在画面里不停移动**（用户摆件时手必须入画），
整幅图的差异主要来自手，而不是物件布局。

## 正确做法

用 **HSV 在托盘 ROI 内检出彩色物件的中心位置**做签名：
  · 同一布局、手不同的帧 ⇒ 物件位置相同 ⇒ 签名相同 ⇒ 合到一组
  · 不同布局 ⇒ 物件位置不同 ⇒ 签名不同

签名格式：`tuple(sorted((颜色, cx//GRID, cy//GRID)))`
  GRID=30px 的粗化，容忍轻微抖动。

## 输出

    _new_capture_tilt30/_dedupe_pos/groups.json
    _new_capture_tilt30/_dedupe_pos/reps/        代表帧（每布局 1~2 张）

## 用法

    python _pi_tools/dedupe_by_position.py
    python _pi_tools/dedupe_by_position.py --grid 40 --keep 2
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
ALL_DIR = ROOT / "_new_capture_tilt30" / "all"
OUT_DIR = ROOT / "_new_capture_tilt30" / "_dedupe_pos"
REPS = OUT_DIR / "reps"

# 默认 ROI = 托盘「实心面」区域。
# ⚠️ 2026-10-27 实测教训：托盘左右是**条纹镂空边框**，透过缝隙能看到桌上的
#    红色/橙色电线，如果 ROI 包住镂空区，HSV 会把电线当成物件
#    （实测每帧检出 8~12 个"物件"，远超真实的 5~6 个）。
#    ⇒ ROI 必须收窄到白色实心面：x≈330~1050, y≈60~471
DEFAULT_ROI = "330,60,1050,471"
TX1, TY1, TX2, TY2 = 330, 60, 1050, 471

HSV = {
    "red":    [((160, 90, 45), (179, 255, 255)), ((0, 90, 45), (12, 255, 255))],
    "yellow": [((16, 90, 55), (32, 255, 255))],
    "green":  [((52, 85, 40), (92, 255, 255))],
    "blue":   [((95, 90, 40), (132, 255, 255))],
}
ORDER = ["red", "yellow", "green", "blue"]

# 手/手臂会被红窗当大块检出 ⇒ 用面积上限排除
MAX_BLOB_FRAC = 0.030      # 占 ROI 比例上限（手通常 >3%）
MIN_BLOB_FRAC = 0.0035     # 下限（滤噪点）


def detect_objects(img: np.ndarray) -> list[tuple[str, int, int]]:
    """返回 [(颜色, cx, cy), ...]，已排除手/噪点。"""
    roi = img[TY1:TY2, TX1:TX2]
    if roi.size == 0:
        return []
    rh, rw = roi.shape[:2]
    roi_area = float(rh * rw)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    out = []
    for color, ranges in HSV.items():
        m = None
        for lo, hi in ranges:
            part = cv2.inRange(hsv, np.array(lo, np.uint8),
                               np.array(hi, np.uint8))
            m = part if m is None else cv2.bitwise_or(m, part)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k, 2)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k, 1)
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL,
                                 cv2.CHAIN_APPROX_SIMPLE)
        for c in cs:
            a = cv2.contourArea(c)
            if a < roi_area * MIN_BLOB_FRAC or a > roi_area * MAX_BLOB_FRAC:
                continue
            x, y, w, h = cv2.boundingRect(c)
            if w < 18 or h < 18:
                continue
            cx = TX1 + x + w // 2
            cy = TY1 + y + h // 2
            out.append((color, int(cx), int(cy)))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", type=int, default=30,
                    help="位置粗化格（像素，默认 30）")
    ap.add_argument("--keep", type=int, default=2,
                    help="每个布局最多保留几张（默认 2）")
    ap.add_argument("--min-n", type=int, default=1,
                    help="只保留至少含 N 个物件的布局（默认 1）")
    ap.add_argument("--roi", default=DEFAULT_ROI,
                    help="托盘实心面 ROI: x1,y1,x2,y2（默认 %(default)s）")
    args = ap.parse_args(argv)

    global TX1, TY1, TX2, TY2
    TX1, TY1, TX2, TY2 = [int(v) for v in args.roi.split(",")]

    files = sorted(ALL_DIR.glob("*.jpg"))
    if not files:
        print("❌ %s 里没图" % ALL_DIR)
        return 1

    print("=" * 76)
    print("  按物件位置去重")
    print("=" * 76)
    print("  输入 : %d 帧" % len(files))
    print("  ROI  : x %d~%d, y %d~%d" % (TX1, TX2, TY1, TY2))
    print("  格   : %d px   每布局留 %d 张" % (args.grid, args.keep))
    print()

    per_frame = []
    for f in files:
        img = cv2.imdecode(np.fromfile(str(f), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            continue
        objs = detect_objects(img)
        sig = tuple(sorted((c, x // args.grid, y // args.grid)
                           for c, x, y in objs))
        per_frame.append((f, objs, sig))

    print("  检出物件数分布:")
    dist = Counter(len(o) for _, o, _ in per_frame)
    for k in sorted(dist):
        print("    %d 个物件: %3d 帧 (%.0f%%)"
              % (k, dist[k], dist[k] / len(per_frame) * 100))
    print()

    # 聚类
    groups: dict[tuple, list] = {}
    for f, objs, sig in per_frame:
        if len(objs) < args.min_n:
            continue
        groups.setdefault(sig, []).append((f, objs))

    print("  ✅ %d 帧 → %d 个不同布局（要求每布局 ≥%d 个物件）"
          % (len(per_frame), len(groups), args.min_n))
    print()
    gs = Counter(len(v) for v in groups.values())
    print("  布局帧数分布:")
    for k in sorted(gs, reverse=True)[:12]:
        print("    %d 帧的布局: %3d 个" % (k, gs[k]))
    print()

    # 写盘
    if REPS.is_dir():
        shutil.rmtree(REPS)
    REPS.mkdir(parents=True, exist_ok=True)
    info = []
    kept = 0
    for gi, (sig, members) in enumerate(
            sorted(groups.items(), key=lambda kv: -len(kv[1]))):
        keep = members[:args.keep]
        for f, _ in keep:
            shutil.copy2(f, REPS / f.name)
            kept += 1
        info.append({
            "group": gi,
            "n_frames": len(members),
            "n_objects": len(sig),
            "kept": [f.name for f, _ in keep],
            "all": [f.name for f, _ in members],
            "objects": [[c, x * args.grid, y * args.grid]
                        for c, x, y in sig],
        })
    (OUT_DIR / "groups.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")

    print("=" * 76)
    print("  ✅ 完成")
    print("=" * 76)
    print("  唯一布局 : %d 个" % len(groups))
    print("  代表帧   : %s  (%d 张)" % (REPS, kept))
    print("  分组信息 : %s" % (OUT_DIR / "groups.json"))
    print()
    print("  ⇒ 这是真正需要我判形状的帧数")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
