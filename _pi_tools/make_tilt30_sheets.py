#!/usr/bin/env python3
"""为 tilt30 新采集帧生成「带大号编号框」的 2×2 拼版，供人工判形状。

## 背景

- 新采集 480 帧，实测**全是不同布局**（无法按像素去重）
- v4 模型在新 30° 视角下几乎失效（中位 0 个/帧）⇒ 不能自动预标
- ⇒ 采取「**抽样 120 帧 + 人工判形**」策略（约 720 个框，够训 6 类）

## 与上一批的差异

**用户明确要求：有手的照片也要标注**（摆件时手必须入画）。
⇒ 所以本脚本**不按"是否有手"跳帧**，手造成的多余色块由人工判形时丢弃。

## 关键参数（实测得出）

托盘实心面 ROI：x 330~1050, y 60~471
  ⚠️ 托盘左右是条纹镂空边框，透过缝隙能看到桌上红色电线，
     如果 ROI 包住镂空区，HSV 会把电线当物件（每帧虚检 8~12 个）。

色块尺寸上下限（占 ROI 面积）：
  MIN 0.002  滤噪点
  MAX 0.20   宽容放行（手会超限被排除，但物件也可能偏大）
  → 宁可多检，人工判形时丢多余的

## 输出

    _new_capture_tilt30/_sheets/num_XXX.jpg   2×2 拼版
    _new_capture_tilt30/_sheets/boxes_all.json 每帧的像素框

## 用法

    python _pi_tools/make_tilt30_sheets.py
    python _pi_tools/make_tilt30_sheets.py --stride 4 --min-obj 3
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
ALL_DIR = ROOT / "_new_capture_tilt30" / "all"
SHEETS = ROOT / "_new_capture_tilt30" / "_sheets"

# 🔴 托盘「实心面」ROI —— 实测多次纠正后的值
#
# 2026-10-27 教训链：
#   ① 先用 x 120~1270, y 40~500 ⇒ 每帧检出 8~16 个"物件"：
#      左右条纹镂空边框外能看到桌上红色电线，全被 HSV 当物件
#   ② 改 x 330~1050, y 60~471 ⇒ 仍有 9~13 个：
#      托盘实心面只到 y≈240，y>240 是桌面 + 电线（30° 斜视下托盘被压缩）
#   ③ 最终 x 170~1040, y 44~245（只包白色实心面）⇒ 应回到 3~6 个
TX1, TY1, TX2, TY2 = 170, 44, 1040, 245

HSV = {
    "red":    [((160, 90, 45), (179, 255, 255)), ((0, 90, 45), (12, 255, 255))],
    "yellow": [((16, 90, 55), (32, 255, 255))],
    "green":  [((52, 85, 40), (92, 255, 255))],
    "blue":   [((95, 90, 40), (132, 255, 255))],
}
ORDER = ["red", "yellow", "green", "blue"]
DRAW = {"red": (0, 0, 255), "yellow": (0, 200, 255),
        "green": (0, 220, 0), "blue": (255, 120, 0)}

# 🔴 面积上下限（占 ROI 比例）—— 实测标定
#
# 2026-10-27 实测该 ROI 下的真实数据：
#   真物件（绿方块 126×168）面积占 ROI 11.03%
#   假框（条纹缝隙/反光碎块）面积只占 0.31~0.38%，尺寸仅 20~48 px
#   ⇒ 旧值 MIN=0.002(0.2%) 太松，把碎块全放行，导致每帧虚检 3~5 个
#   ⇒ 改成 MIN=0.02(2%)：物件(5~15%)通过，碎块(<0.5%)全部剔除
#   手在 ROI 内可能占 20~40% ⇒ MAX 放到 0.30 容忍大物件、排除整只手
MIN_FRAC = 0.020
MAX_FRAC = 0.300


def detect(img: np.ndarray) -> list[dict]:
    roi = img[TY1:TY2, TX1:TX2]
    if roi.size == 0:
        return []
    rh, rw = roi.shape[:2]
    roi_area = float(rh * rw)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    res = []
    for color, ranges in HSV.items():
        m = None
        for lo, hi in ranges:
            part = cv2.inRange(hsv, np.array(lo, np.uint8),
                               np.array(hi, np.uint8))
            m = part if m is None else cv2.bitwise_or(m, part)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k, 2)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k, 1)
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL,
                                 cv2.CHAIN_APPROX_SIMPLE)
        for c in cs:
            a = cv2.contourArea(c)
            if a < roi_area * MIN_FRAC or a > roi_area * MAX_FRAC:
                continue
            x, y, w, h = cv2.boundingRect(c)
            if w < 20 or h < 20:
                continue
            res.append({"color": color,
                        "x": int(TX1 + x), "y": int(TY1 + y),
                        "w": int(w), "h": int(h),
                        "area_pct": round(a / roi_area * 100.0, 2)})
    res.sort(key=lambda r: (ORDER.index(r["color"]), r["y"], r["x"]))
    for i, r in enumerate(res, 1):
        r["id"] = i
    return res


def tile(img: np.ndarray, boxes: list[dict], name: str,
         scale: float = 0.5) -> np.ndarray:
    h, w = img.shape[:2]
    vis = img.copy()
    cv2.rectangle(vis, (TX1, TY1), (TX2, TY2), (255, 255, 0), 2)
    for b in boxes:
        col = DRAW[b["color"]]
        cv2.rectangle(vis, (b["x"], b["y"]),
                      (b["x"] + b["w"], b["y"] + b["h"]), col, 4)
        txt = str(b["id"])
        ox, oy = b["x"] + 6, b["y"] + 46
        cv2.putText(vis, txt, (ox, oy), cv2.FONT_HERSHEY_SIMPLEX, 1.6,
                    (0, 0, 0), 7)
        cv2.putText(vis, txt, (ox, oy), cv2.FONT_HERSHEY_SIMPLEX, 1.6,
                    (255, 255, 255), 3)
    vis = cv2.resize(vis, (int(w * scale), int(h * scale)),
                     interpolation=cv2.INTER_AREA)
    cv2.rectangle(vis, (0, 0), (int(w * scale), 26), (0, 0, 0), -1)
    cv2.putText(vis, "%s  n=%d" % (name, len(boxes)), (5, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 255), 2)
    return vis


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stride", type=int, default=4,
                    help="每 N 帧取 1 帧（默认 4 ⇒ 480→120）")
    ap.add_argument("--min-obj", type=int, default=3,
                    help="少于 N 个物件的帧跳过（默认 3）")
    ap.add_argument("--out", default=str(SHEETS))
    args = ap.parse_args(argv)

    files = sorted(ALL_DIR.glob("*.jpg"))
    if not files:
        print("❌ %s 里没图" % ALL_DIR)
        return 1

    picked = files[::args.stride]
    print("=" * 74)
    print("  生成 tilt30 判形拼版")
    print("=" * 74)
    print("  总帧 %d，步长 %d ⇒ 抽样 %d 帧" % (len(files), args.stride, len(picked)))
    print("  ROI  x %d~%d, y %d~%d" % (TX1, TX2, TY1, TY2))
    print("  跳过条件：物件数 < %d" % args.min_obj)
    print()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_boxes: dict[str, dict] = {}
    usable = []
    skipped = 0
    for f in picked:
        img = cv2.imdecode(np.fromfile(str(f), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            continue
        bs = detect(img)
        if len(bs) < args.min_obj:
            skipped += 1
            continue
        all_boxes[f.name] = {"W": img.shape[1], "H": img.shape[0], "boxes": bs}
        usable.append(f)

    print("  可用 %d 帧（跳过 %d 帧，物件太少）" % (len(usable), skipped))
    cnt = Counter(len(all_boxes[f.name]["boxes"]) for f in usable)
    print("  每帧物件数分布:")
    for k in sorted(cnt):
        print("    %d 个: %3d 帧" % (k, cnt[k]))
    print()

    n_sheet = 0
    for bi in range(0, len(usable), 4):
        batch = usable[bi:bi + 4]
        tiles = []
        for f in batch:
            img = cv2.imdecode(np.fromfile(str(f), dtype=np.uint8),
                               cv2.IMREAD_COLOR)
            if img is None:
                continue
            tiles.append(tile(img, all_boxes[f.name]["boxes"], f.name))
        while len(tiles) < 4:
            tiles.append(np.zeros((360, 640, 3), np.uint8))
        sheet = np.vstack([np.hstack(tiles[0:2]), np.hstack(tiles[2:4])])
        p = out_dir / ("num_%03d.jpg" % bi)
        ok, buf = cv2.imencode(".jpg", sheet,
                               [int(cv2.IMWRITE_JPEG_QUALITY), 93])
        if ok:
            buf.tofile(str(p))
            print("  %-14s <- %s" % (p.name, ", ".join(f.name for f in batch)))
            n_sheet += 1

    (out_dir / "boxes_all.json").write_text(
        json.dumps(all_boxes, ensure_ascii=False, indent=1), encoding="utf-8")

    print()
    print("=" * 74)
    print("  ✅ 生成 %d 张拼版，%d 帧框坐标已存" % (n_sheet, len(all_boxes)))
    print("     拼版: %s" % out_dir)
    print("     坐标: %s" % (out_dir / "boxes_all.json"))
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
