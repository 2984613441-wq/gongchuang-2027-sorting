#!/usr/bin/env python3
"""筛选采集到的原始帧：剔除「有手 / 正在移动」的帧，只留干净样本。

## 为什么要筛

`capture_dataset.py` / `cap_1s.py` 是**定时或无差别采集**，会在
用户放置物料的瞬间抓拍到**手**。这类帧用于训练会有两个问题：
  1. 手会被模型当成"物料"（肤色块类似某些形状）
  2. 不是比赛场景（比赛时画面里只有托盘 + 物料）

## 判据（三重）

**A. 肤色检测（主判据）**
   在托盘 ROI 内找肤色像素。人手在补光灯下通常是粉色/橙色。
   HSV 肤色范围（宽松，宁严勿松）：H[0,25] S[30,180] V[60,255]
   若肤色像素占 ROI 比例 > SKIN_FRAC_MAX ⇒ 判为"有手"，剔除。

**B. 帧间差（辅助）**
   与前后 N 帧的平均差。正在移动时差异大。
   若差 > MOTION_MAX ⇒ 剔除。

**C. 托盘区域完整性**
   托盘是白色高亮区。若 ROI 内"亮且低饱和"像素比例过低
   ⇒ 说明托盘被手/物体大面积遮挡 ⇒ 剔除。

## 用法

```bash
python _pi_tools/filter_capture.py --src _new_capture/whitetray_1793028347
```

默认输出到 `<src>/_clean/`（只复制通过的图），并打印统计。
加 `--dry-run` 只看统计不复制。
加 `--copy` 实际复制（默认 dry-run）。

## 输出

```
_clean/
  img_00012.jpg
  ...
report.csv        ← 每帧的判定依据（方便你抽查）
```
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── 判据阈值 ────────────────────────────────────────────────────────────

#: 托盘 ROI（相对比例）。默认取画面中心区域，避开四周的台面/线缆
#: 格式 (left, top, right, bottom)，都是 0~1 的比例
ROI = (0.28, 0.03, 0.80, 0.96)

#: 肤色像素占 ROI 的最大比例。超过 ⇒ 判为"有手"
SKIN_FRAC_MAX = 0.030

#: 托盘"亮且低饱和"像素占 ROI 的最小比例。低于 ⇒ 托盘被大面积遮挡
TRAY_WHITE_FRAC_MIN = 0.45

#: 帧间差（与相邻帧灰度差的均值）上限。超过 ⇒ 判为"正在移动"
MOTION_MAX = 18.0

# ── HSV 范围 ────────────────────────────────────────────────────────────

#: 肤色（OpenCV H 范围 0~179）。宽松取，因为补光灯会让肤色偏亮偏白
SKIN_HSV = [
    ((0, 30, 60), (25, 180, 255)),
]

#: 托盘白：低饱和 + 高亮度
WHITE_HSV = [((0, 0, 150), (179, 45, 255))]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="筛掉有手/移动的帧")
    ap.add_argument("--src", required=True, help="原始帧目录")
    ap.add_argument("--out", default=None,
                    help="输出目录（默认 <src>/_clean）")
    ap.add_argument("--copy", action="store_true",
                    help="实际复制通过的图（默认只统计）")
    ap.add_argument("--motion-window", type=int, default=2,
                    help="帧间差比较的相邻帧数（默认 2）")
    args = ap.parse_args(argv)

    src = Path(args.src)
    if not src.is_dir():
        print("❌ 源目录不存在: %s" % src)
        return 1
    out = Path(args.out) if args.out else src / "_clean"

    frames = sorted(src.glob("*.jpg"))
    if not frames:
        print("❌ %s 下没有 .jpg" % src)
        return 1

    try:
        import cv2
        import numpy as np
    except Exception as exc:
        print("❌ 需要 opencv + numpy: %s" % exc)
        return 1

    print("=" * 72)
    print("  采集帧筛选")
    print("=" * 72)
    print("  源目录   : %s" % src)
    print("  帧数     : %d" % len(frames))
    print("  ROI      : %s" % (ROI,))
    print("  肤色上限 : %.1f%%" % (SKIN_FRAC_MAX * 100))
    print("  托盘白下限: %.0f%%" % (TRAY_WHITE_FRAC_MIN * 100))
    print("  运动上限 : %.1f" % MOTION_MAX)
    print("  模式     : %s" % ("复制" if args.copy else "DRY-RUN（只统计）"))
    print()

    # ── 1. 逐帧读灰度（用于帧间差）+ 原始（用于 HSV）────────────────
    grays = []
    metas = []
    for i, p in enumerate(frames):
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            grays.append(None)
            metas.append(None)
            continue
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # 帧间差用缩略图，快
        g_small = cv2.resize(g, (160, 90))
        grays.append(g_small.astype(np.int16))
        metas.append(img)
        if (i + 1) % 20 == 0 or i == len(frames) - 1:
            print("  读取 %d/%d…" % (i + 1, len(frames)))

    print()

    h, w = metas[0].shape[:2] if metas[0] is not None else (720, 1280)
    x1 = int(w * ROI[0])
    y1 = int(h * ROI[1])
    x2 = int(w * ROI[2])
    y2 = int(h * ROI[3])

    rows = []
    n_pass = 0
    reasons = {"skin": 0, "white_low": 0, "motion": 0, "unreadable": 0}

    for i, (p, img, g) in enumerate(zip(frames, metas, grays)):
        if img is None or g is None:
            rows.append((p.name, "REJECT", "unreadable", "", "", ""))
            reasons["unreadable"] += 1
            continue

        # ── A. 肤色 ─────────────────────────────────────────────────
        roi = img[y1:y2, x1:x2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        skin_mask = None
        for lo, hi in SKIN_HSV:
            m = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
            skin_mask = m if skin_mask is None else cv2.bitwise_or(skin_mask, m)
        skin_frac = float(np.count_nonzero(skin_mask)) / max(1, roi.shape[0] * roi.shape[1])

        # ── C. 托盘白覆盖 ───────────────────────────────────────────
        white_mask = None
        for lo, hi in WHITE_HSV:
            m = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
            white_mask = m if white_mask is None else cv2.bitwise_or(white_mask, m)
        white_frac = float(np.count_nonzero(white_mask)) / max(
            1, roi.shape[0] * roi.shape[1])

        # ── B. 帧间差 ───────────────────────────────────────────────
        motion = 0.0
        cnt = 0
        for d in range(1, args.motion_window + 1):
            for j in (i - d, i + d):
                if 0 <= j < len(grays) and grays[j] is not None:
                    motion += float(np.abs(g - grays[j]).mean())
                    cnt += 1
        if cnt:
            motion /= cnt

        # ── 判定 ────────────────────────────────────────────────────
        verdict = "PASS"
        why = ""
        if skin_frac > SKIN_FRAC_MAX:
            verdict, why = "REJECT", "skin"
            reasons["skin"] += 1
        elif white_frac < TRAY_WHITE_FRAC_MIN:
            verdict, why = "REJECT", "white_low"
            reasons["white_low"] += 1
        elif motion > MOTION_MAX:
            verdict, why = "REJECT", "motion"
            reasons["motion"] += 1
        else:
            n_pass += 1

        rows.append((p.name, verdict, why,
                     "%.4f" % skin_frac, "%.4f" % white_frac, "%.2f" % motion))

        if (i + 1) % 20 == 0 or i == len(frames) - 1:
            print("  判定 %d/%d…（通过 %d）" % (i + 1, len(frames), n_pass))

    # ── 复制通过的 ─────────────────────────────────────────────────
    print()
    if args.copy:
        out.mkdir(parents=True, exist_ok=True)
        n_copied = 0
        for name, verdict, *_ in rows:
            if verdict == "PASS":
                shutil.copy2(src / name, out / name)
                n_copied += 1
        print("  ✅ 已复制 %d 张到 %s" % (n_copied, out))
        # 写报告
        rep = out / "report.csv"
        with open(rep, "w", encoding="utf-8", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["file", "verdict", "reason",
                         "skin_frac", "white_frac", "motion"])
            wr.writerows(rows)
        print("  报告: %s" % rep)
    else:
        # dry-run 也写一份报告到源目录
        rep = src / "_filter_report.csv"
        with open(rep, "w", encoding="utf-8", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["file", "verdict", "reason",
                         "skin_frac", "white_frac", "motion"])
            wr.writerows(rows)
        print("  报告: %s" % rep)

    # ── 汇总 ───────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("  汇总")
    print("=" * 72)
    print("  总帧数   : %d" % len(frames))
    print("  通过     : %d  (%.1f%%)" % (n_pass, 100.0 * n_pass / len(frames)))
    print()
    print("  剔除原因分布:")
    for k, v in reasons.items():
        if v:
            print("    %-12s %d" % (k, v))
    print()
    if n_pass < 50:
        print("  ⚠️ 通过帧少于 50 —— 可能阈值太严，或者采集时手一直在画面里。")
        print("     建议：调大 SKIN_FRAC_MAX、或重新采集（放完再启动采集）。")
    else:
        print("  ✅ 干净帧够用（%d 张）" % n_pass)
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
