#!/usr/bin/env python3
"""筛选采集帧 v3 —— 基于「托盘内最大连通域」判手，实测可分。

## 为什么 v1/v2 失败（记录教训）

**v1**：用「肤色像素占 ROI 比例」
  ❌ ROI 只取托盘内部 ⇒ 手在托盘外，看不到
  ❌ 又因为是全图肤色，木桌（棕色）被当成手
  ❌ 判据方向反了（保留空托盘、剔除有物料）

**v2**：改成全图找「大面积肤色块 + 触边」
  ❌ 木桌本身就在画面边缘且是棕色 ⇒ 113/161 帧被误判为"有手"

**v3**：只用「托盘内最大连通域大小」
  ✅ 实测数据（`_pi_tools/find_hand_feature.py`）：
       有手     max_blob_frac = 0.089~0.432（5/6 > 0.20）
       有物料   max_blob_frac = 0.102~0.121
       空托盘   max_blob_frac = 0.055~0.118
     ⇒ 阈值 0.15 能抓住 5/6 有手帧，物料帧全保留
  ✅ 再叠加 `white_frac` 判空托盘（空托盘 > 0.90，有物料 ≈ 0.65）

  ⚠️ 已知漏网：手张得很开但没形成大连通域时会漏（6 帧里漏 1 帧）。
     漏网的帧会带手进训练集 —— 这是可接受的噪声（YOLO 对少量噪声鲁棒）。

## 用法

```bash
# 只看统计
python _pi_tools/filter_capture_v3.py --src _new_capture/whitetray_1793028347

# 实际复制通过的帧
python _pi_tools/filter_capture_v3.py --src _new_capture/whitetray_1793028347 --copy

# 把通过的帧裁到托盘区域（推荐：去背景 + 手在托盘外的自动消失）
python _pi_tools/filter_capture_v3.py --src ... --copy --crop
```
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

# ── 内层托盘 ROI（相对比例，从 img_00000 目测 + measure_tray_bbox 校正）──
INNER_ROI = (0.3008, 0.0486, 0.7852, 0.9514)

# ── 判据阈值（在 find_hand_feature.py 的实测数据上标定）────────────────
# 空托盘：托盘白占比 > 0.90；有物料 ≈ 0.65；有手 0.38~0.71
EMPTY_WHITE_MIN = 0.80

# 有手：最大连通域占托盘比 > 0.20（物料最大 0.12，手最小 0.089 但多数 > 0.20）
HAND_MAX_BLOB_MIN = 0.15

# 静态：帧间差均值上限
MOTION_MAX = 12.0
MOTION_WINDOW = 2

# 形态学核
MORPH_K = 7


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="筛出「有物料且无手」的帧")
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default=None, help="输出目录（默认 <src>/_clean3）")
    ap.add_argument("--copy", action="store_true", help="实际复制（默认只统计）")
    ap.add_argument("--crop", action="store_true",
                    help="同时裁剪到托盘区域（去掉背景）")
    ap.add_argument("--no-motion", action="store_true",
                    help="不做静止检查（若采集时很慢、帧间差都接近 0 可选）")
    args = ap.parse_args(argv)

    src = Path(args.src)
    if not src.is_dir():
        print("❌ 源目录不存在: %s" % src)
        return 1
    out = Path(args.out) if args.out else src / "_clean3"

    frames = sorted(src.glob("*.jpg"))
    if not frames:
        print("❌ 没有 .jpg")
        return 1

    print("=" * 78)
    print("  帧筛选 v3（有物料 + 无手 + 静止）")
    print("=" * 78)
    print("  源目录: %s" % src)
    print("  帧数  : %d" % len(frames))
    print("  输出  : %s" % out)
    print("  裁剪  : %s" % ("是" if args.crop else "否"))
    print("  模式  : %s" % ("复制" if args.copy else "DRY-RUN（只统计）"))
    print()

    # 预读灰度
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
    rej = {"empty": 0, "hand": 0, "motion": 0, "unreadable": 0}
    crop_box = None   # 第一次算出来就固定（保证所有帧裁同一个框）

    for i, p in enumerate(frames):
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            rows.append([p.name, "REJECT", "unreadable", 0, "", "", ""])
            rej["unreadable"] += 1
            continue

        H, W = img.shape[:2]
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        x1 = int(W * INNER_ROI[0]); y1 = int(H * INNER_ROI[1])
        x2 = int(W * INNER_ROI[2]); y2 = int(H * INNER_ROI[3])
        roi = hsv[y1:y2, x1:x2]
        area = roi.shape[0] * roi.shape[1]

        # ── 托盘白占比 ────────────────────────────────────────────
        white = cv2.inRange(roi, np.array((0, 0, 150), np.uint8),
                            np.array((179, 50, 255), np.uint8))
        white_frac = np.count_nonzero(white) / area

        # ── "非托盘白"区域（物料 + 手 + 阴影）─────────────────────
        not_tray = cv2.inRange(roi, np.array((0, 55, 0), np.uint8),
                               np.array((179, 255, 255), np.uint8))
        dark = cv2.inRange(roi, np.array((0, 0, 0), np.uint8),
                           np.array((179, 255, 165), np.uint8))
        not_tray = cv2.bitwise_or(not_tray, dark)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (MORPH_K, MORPH_K))
        not_tray = cv2.morphologyEx(not_tray, cv2.MORPH_CLOSE, k, 2)
        not_tray = cv2.morphologyEx(not_tray, cv2.MORPH_OPEN, k, 1)
        cnts, _ = cv2.findContours(not_tray, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        min_a = area * 0.0015
        areas = sorted((cv2.contourArea(c) for c in cnts), reverse=True)
        n_blob = sum(1 for a in areas if a >= min_a)
        max_blob_frac = (areas[0] / area) if areas else 0.0

        # ── 帧间差 ────────────────────────────────────────────────
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
        if white_frac > EMPTY_WHITE_MIN:
            verdict, why = "REJECT", "empty"
            rej["empty"] += 1
        elif max_blob_frac > HAND_MAX_BLOB_MIN:
            verdict, why = "REJECT", "hand"
            rej["hand"] += 1
        elif (not args.no_motion) and motion > MOTION_MAX:
            verdict, why = "REJECT", "motion"
            rej["motion"] += 1
        else:
            n_pass += 1

        rows.append([p.name, verdict, why, n_blob,
                     "%.4f" % white_frac, "%.4f" % max_blob_frac,
                     "%.2f" % motion])

        if verdict == "PASS" and crop_box is None and args.crop:
            crop_box = (x1, y1, x2, y2)

        if (i + 1) % 40 == 0 or i == len(frames) - 1:
            print("  判定 %d/%d…（通过 %d）" % (i + 1, len(frames), n_pass))

    # ── 输出 ──────────────────────────────────────────────────────
    print()
    if args.copy:
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for r in rows:
            if r[1] != "PASS":
                continue
            img = cv2.imdecode(np.fromfile(str(src / r[0]), dtype=np.uint8),
                               cv2.IMREAD_COLOR)
            if img is None:
                continue
            if args.crop and crop_box is not None:
                cx1, cy1, cx2, cy2 = crop_box
                img = img[cy1:cy2, cx1:cx2]
            dst = out / r[0]
            cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])[1].tofile(str(dst))
            n += 1
        rep = out / "report.csv"
        print("  ✅ 已复制 %d 张到 %s" % (n, out))
        if args.crop and crop_box:
            print("     裁剪框: x %d~%d, y %d~%d  (%dx%d)"
                  % (crop_box[0], crop_box[2], crop_box[1], crop_box[3],
                     crop_box[2] - crop_box[0], crop_box[3] - crop_box[1]))
    else:
        rep = src / "_filter_report_v3.csv"
    with open(rep, "w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["file", "verdict", "reason", "n_blob",
                     "white_frac", "max_blob_frac", "motion"])
        wr.writerows(rows)
    print("  报告: %s" % rep)

    print()
    print("=" * 78)
    print("  汇总")
    print("=" * 78)
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
        print("     可试：--no-motion（去掉静止检查）")
    else:
        print("  ✅ 可用 %d 帧" % n_pass)
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
