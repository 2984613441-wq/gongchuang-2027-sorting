#!/usr/bin/env python3
"""验证：只在内层托盘 ROI 内做「物料 + 手」检测，看能否分开有手/干净帧。

内层托盘 ROI（从 img_00000 目测）：x 385~1005, y 35~685
换成相对比例：x 0.3008~0.7852, y 0.0486~0.9514

对照：
  · 有手帧（我目视确认）：img_00080, 81, 82, 83
  · 干净有物料：img_00000, 26, 78
  · 空托盘：img_00087, 88, 89, 117, 118
"""

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "_new_capture" / "whitetray_1793028347"

# 内层托盘 ROI（相对比例）
INNER_ROI = (0.3008, 0.0486, 0.7852, 0.9514)

# 肤色（更严格：真正的人手在补光灯下 S 不会太高，V 很高）
SKIN_HSV = [((0, 25, 90), (20, 130, 255))]

# 物料：高饱和
OBJ_HSV = ((0, 70, 40), (179, 255, 255))


def analyze(idx):
    p = SRC / ("img_%05d.jpg" % idx)
    if not p.is_file():
        return None
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    x1 = int(W * INNER_ROI[0]); y1 = int(H * INNER_ROI[1])
    x2 = int(W * INNER_ROI[2]); y2 = int(H * INNER_ROI[3])
    roi = hsv[y1:y2, x1:x2]
    area = roi.shape[0] * roi.shape[1]

    # 物料
    obj = cv2.inRange(roi, np.array(OBJ_HSV[0], np.uint8),
                      np.array(OBJ_HSV[1], np.uint8))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    obj = cv2.morphologyEx(obj, cv2.MORPH_CLOSE, k, 2)
    obj = cv2.morphologyEx(obj, cv2.MORPH_OPEN, k, 1)
    oc, _ = cv2.findContours(obj, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_a = area * 0.0015
    n_obj = sum(1 for c in oc if cv2.contourArea(c) >= min_a)
    obj_frac = sum(cv2.contourArea(c) for c in oc
                   if cv2.contourArea(c) >= min_a) / area

    # 肤色（ROI 内）
    skin = None
    for lo, hi in SKIN_HSV:
        m = cv2.inRange(roi, np.array(lo, np.uint8), np.array(hi, np.uint8))
        skin = m if skin is None else cv2.bitwise_or(skin, m)
    k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    skin = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, k2, 2)
    sc, _ = cv2.findContours(skin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    skin_frac = np.count_nonzero(skin) / area
    skin_max = max((cv2.contourArea(c) for c in sc), default=0.0) / area

    return {
        "n_obj": n_obj, "obj_frac": obj_frac,
        "skin_frac": skin_frac, "skin_max": skin_max,
    }


def main():
    print("=" * 76)
    print("  只在内层托盘 ROI 内检测 —— 能否分开有手/干净？")
    print("=" * 76)
    print("  INNER_ROI = %s" % (INNER_ROI,))
    print()

    groups = {
        "有手（目视确认）": [80, 81, 82, 83],
        "干净 + 有物料": [0, 26, 78],
        "空托盘": [87, 88, 89, 117, 118],
    }

    all_vals = {}
    for gname, idxs in groups.items():
        print("── %s ──" % gname)
        vals = []
        for i in idxs:
            r = analyze(i)
            if r is None:
                continue
            vals.append(r)
            print("  %3d  n_obj=%-2d obj=%.4f skin=%.4f skinMax=%.4f"
                  % (i, r["n_obj"], r["obj_frac"],
                     r["skin_frac"], r["skin_max"]))
        all_vals[gname] = vals
        print()

    print("=" * 76)
    print("  区间对比")
    print("=" * 76)
    for key in ("n_obj", "obj_frac", "skin_frac", "skin_max"):
        print("  %-12s" % key)
        for gname, vals in all_vals.items():
            if not vals:
                continue
            v = [r[key] for r in vals]
            print("    %-14s %.4f ~ %.4f" % (gname, min(v), max(v)))
        print()
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
