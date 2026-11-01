#!/usr/bin/env python3
"""筛选采集帧 v2 —— 保留「有物料且无手」的帧。

## 上一版（v1）的两个致命错误

1. **ROI 只取托盘内部 ⇒ 手在托盘外，肤色检测看不到手**
   （img_00080 明确有手，但 skin_frac 只有 0.005）
2. **判据方向错了 ⇒ 保留了空托盘帧、剔除了有物料的帧**
   （空托盘 white=0.93、matMax=0.004，反而"更干净"）

## v2 的正确判据（三个都要满足才保留）

**① 必须有物料**（MUST_HAVE_OBJECTS）
   托盘 ROI 内，颜色饱和度高的连通域，面积 ≥ MIN_OBJ_FRAC 的数量 ≥ 1
   ⇒ 剔除空托盘帧

**② 不能有手**（NO_HANDS）
   **全图**（不是托盘 ROI）检测「大面积肤色块」，且该块**触及图像边缘**
   （手一定从画面边缘进入）
   ⇒ 面积占全图 > HAND_FRAC_MAX 且 触及边缘 ⇒ 有手，剔除

**③ 必须静止**（STATIC）
   与前后帧的灰度差均值 < MOTION_MAX
   ⇒ 剔除正在移动（手在动）的帧

## 用法

```bash
# 只看统计
python _pi_tools/filter_capture_v2.py --src _new_capture/whitetray_1793028347

# 实际复制通过的帧
python _pi_tools/filter_capture_v2.py --src _new_capture/whitetray_1793028347 --copy
```
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

# ── 托盘 ROI（相对比例，只用于「找物料」，不用于找手）──────────────────
# 从 img_00000 观测：托盘约 x 390~1000, y 5~715
TRAY_ROI = (0.305, 0.010, 0.780, 0.990)

# ── 判据 ①：必须有物料 ────────────────────────────────────────────────
# 饱和度高 = 有颜色 = 物料（托盘是低饱和白）
OBJ_S_MIN = 70          # OpenCV S 范围 0~255
OBJ_V_MIN = 40
OBJ_AREA_FRAC_MIN = 0.0015   # 单个物料至少占托盘面积 0.15%
OBJ_COUNT_MIN = 1            # 至少检出 1 个物料

# ── 判据 ②：不能有手（全图检测 + 触边）────────────────────────────────
# 肤色：OpenCV H 0~179。补光灯下人手偏亮偏粉
SKIN_HSV = [((0, 25, 70), (22, 150, 255))]
HAND_FRAC_MAX = 0.045        # 单个肤色块占全图 > 4.5% ⇒ 疑似手
HAND_TOUCH_BORDER = True     # 且必须触及画面边缘（手从边缘进入）

# ── 判据 ③：必须静止 ──────────────────────────────────────────────────
MOTION_MAX = 9.0
MOTION_WINDOW = 2


def _touches_border(x: int, y: int, w: int, h: int,
                    W: int, H: int, margin: int = 6) -> bool:
    return (x <= margin or y <= margin
            or x + w >= W - margin or y + h >= H - margin)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="筛出「有物料且无手」的帧")
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default=None,
                    help="输出目录（默认 <src>/_clean2）")
    ap.add_argument("--copy", action="store_true", help="实际复制（默认只统计）")
    args = ap.parse_args(argv)

    src = Path(args.src)
    if not src.is_dir():
        print("❌ 源目录不存在: %s" % src)
        return 1
    out = Path(args.out) if args.out else src / "_clean2"

    frames = sorted(src.glob("*.jpg"))
    if not frames:
        print("❌ 没有 .jpg")
        return 1

    try:
        import cv2
        import numpy as np
    except Exception as exc:
        print("❌ 需要 opencv + numpy: %s" % exc)
        return 1

    print("=" * 76)
    print("  帧筛选 v2（有物料 + 无手 + 静止）")
    print("=" * 76)
    print("  源目录: %s" % src)
    print("  帧数  : %d" % len(frames))
    print("  模式  : %s" % ("复制" if args.copy else "DRY-RUN（只统计）"))
    print()

    # ── 预读灰度（算帧间差）────────────────────────────────────────
    grays = []
    for i, p in enumerate(frames):
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            grays.append(None)
            continue
        grays.append(cv2.resize(
            cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (160, 90)).astype(np.int16))
        if (i + 1) % 40 == 0:
            print("  预读 %d/%d…" % (i + 1, len(frames)))
    print()

    rows = []
    n_pass = 0
    rej = {"no_object": 0, "hand": 0, "motion": 0, "unreadable": 0}

    for i, p in enumerate(frames):
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            rows.append([p.name, "REJECT", "unreadable", "", "", "", ""])
            rej["unreadable"] += 1
            continue

        H, W = img.shape[:2]
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # ── ① 找物料（托盘 ROI 内，高饱和连通域）─────────────────
        tx1 = int(W * TRAY_ROI[0]); ty1 = int(H * TRAY_ROI[1])
        tx2 = int(W * TRAY_ROI[2]); ty2 = int(H * TRAY_ROI[3])
        tray_hsv = hsv[ty1:ty2, tx1:tx2]
        tray_area = (ty2 - ty1) * (tx2 - tx1)

        obj_mask = cv2.inRange(
            tray_hsv,
            np.array((0, OBJ_S_MIN, OBJ_V_MIN), np.uint8),
            np.array((179, 255, 255), np.uint8))
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        obj_mask = cv2.morphologyEx(obj_mask, cv2.MORPH_CLOSE, k, iterations=2)
        obj_mask = cv2.morphologyEx(obj_mask, cv2.MORPH_OPEN, k, iterations=1)
        cnts, _ = cv2.findContours(obj_mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        min_area = tray_area * OBJ_AREA_FRAC_MIN
        n_obj = sum(1 for c in cnts if cv2.contourArea(c) >= min_area)
        obj_area_frac = sum(cv2.contourArea(c) for c in cnts
                            if cv2.contourArea(c) >= min_area) / tray_area

        # ── ② 找手（全图肤色块 + 触边）────────────────────────────
        skin_mask = None
        for lo, hi in SKIN_HSV:
            m = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
            skin_mask = m if skin_mask is None else cv2.bitwise_or(skin_mask, m)
        k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_CLOSE, k2, iterations=2)
        scnts, _ = cv2.findContours(skin_mask, cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_SIMPLE)
        hand_frac = 0.0
        n_hand = 0
        img_area = W * H
        for c in scnts:
            a = cv2.contourArea(c)
            f = a / img_area
            if f <= HAND_FRAC_MAX:
                continue
            if HAND_TOUCH_BORDER:
                x, y, w2, h2 = cv2.boundingRect(c)
                if not _touches_border(x, y, w2, h2, W, H):
                    continue
            n_hand += 1
            hand_frac = max(hand_frac, f)

        # ── ③ 帧间差 ──────────────────────────────────────────────
        motion = 0.0
        cnt = 0
        g = grays[i]
        if g is not None:
            for d in range(1, MOTION_WINDOW + 1):
                for j in (i - d, i + d):
                    if 0 <= j < len(grays) and grays[j] is not None:
                        motion += float(abs(g - grays[j]).mean())
                        cnt += 1
        if cnt:
            motion /= cnt

        # ── 判定 ──────────────────────────────────────────────────
        verdict, why = "PASS", ""
        if n_obj < OBJ_COUNT_MIN:
            verdict, why = "REJECT", "no_object"
            rej["no_object"] += 1
        elif n_hand >= 1:
            verdict, why = "REJECT", "hand"
            rej["hand"] += 1
        elif motion > MOTION_MAX:
            verdict, why = "REJECT", "motion"
            rej["motion"] += 1
        else:
            n_pass += 1

        rows.append([p.name, verdict, why, n_obj,
                     "%.4f" % obj_area_frac, "%.4f" % hand_frac,
                     "%.2f" % motion])

        if (i + 1) % 40 == 0 or i == len(frames) - 1:
            print("  判定 %d/%d…（通过 %d）" % (i + 1, len(frames), n_pass))

    # ── 输出 ──────────────────────────────────────────────────────
    print()
    hdr = ["file", "verdict", "reason", "n_obj", "obj_frac", "hand_frac", "motion"]
    if args.copy:
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for r in rows:
            if r[1] == "PASS":
                shutil.copy2(src / r[0], out / r[0])
                n += 1
        rep = out / "report.csv"
        print("  ✅ 已复制 %d 张到 %s" % (n, out))
    else:
        rep = src / "_filter_report_v2.csv"
    with open(rep, "w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(hdr)
        wr.writerows(rows)
    print("  报告: %s" % rep)

    print()
    print("=" * 76)
    print("  汇总")
    print("=" * 76)
    print("  总帧数 : %d" % len(frames))
    print("  通过   : %d  (%.1f%%)" % (n_pass, 100.0 * n_pass / len(frames)))
    print()
    print("  剔除原因:")
    for k, v in rej.items():
        if v:
            print("    %-12s %d" % (k, v))
    print()
    if n_pass < 20:
        print("  ⚠️ 通过少于 20 帧 —— 阈值可能太严，或采集时手停留太久")
    else:
        print("  ✅ 可用 %d 帧" % n_pass)
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
