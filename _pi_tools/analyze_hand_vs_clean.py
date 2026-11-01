#!/usr/bin/env python3
"""对比「有手帧」和「干净帧」的特征，找出可靠判据。

问题：基于肤色比例的判据误判严重（干净帧也有 11% "肤色"），
      因为 ROI 含托盘外木桌 + 红橙物料本身在肤色 HSV 范围内。

本脚本对一组已知帧提取多个候选特征，看哪个能真正分开两类。
"""

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "_new_capture" / "whitetray_1793028347"

# 已知有几帧有手（我看过 img_00080 明确有手）
HAND_CANDIDATES = [78, 79, 80, 81, 82, 83]
# 已知干净
CLEAN_CANDIDATES = [0, 1, 87, 88, 89, 117, 118]


def load(idx):
    p = SRC / ("img_%05d.jpg" % idx)
    if not p.is_file():
        return None
    return cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)


def features(img):
    """提取多个候选判据。"""
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # ── 托盘区域（收紧，只取托盘内部）────────────────────────────
    # 从 img_00000 看，托盘大约 x 390~1000, y 5~715
    x1, y1, x2, y2 = 400, 20, 990, 700
    roi_hsv = hsv[y1:y2, x1:x2]
    roi_gray = gray[y1:y2, x1:x2]
    roi_area = (y2 - y1) * (x2 - x1)

    out = {}

    # ── F1: 托盘白覆盖 ────────────────────────────────────────────
    white = cv2.inRange(roi_hsv, np.array((0, 0, 150), np.uint8),
                        np.array((179, 45, 255), np.uint8))
    out["white_frac"] = np.count_nonzero(white) / roi_area

    # ── F2: 肤色（宽松）比例 ──────────────────────────────────────
    skin = cv2.inRange(roi_hsv, np.array((0, 25, 80), np.uint8),
                       np.array((25, 140, 255), np.uint8))
    out["skin_frac"] = np.count_nonzero(skin) / roi_area

    # ── F3: 最大的"肤色样"连通域面积（占 ROI 比例）────────────────
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    skin_m = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, k, iterations=2)
    cnts, _ = cv2.findContours(skin_m, cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_SIMPLE)
    biggest = max((cv2.contourArea(c) for c in cnts), default=0.0)
    out["skin_max_blob_frac"] = biggest / roi_area

    # ── F4: 最大的非白、非肤色连通域（= 物料）面积 ────────────────
    colored = cv2.inRange(roi_hsv, np.array((0, 60, 40), np.uint8),
                          np.array((179, 255, 255), np.uint8))
    # 排除肤色区
    colored = cv2.bitwise_and(colored, cv2.bitwise_not(skin))
    # 排除白区
    colored = cv2.bitwise_and(colored, cv2.bitwise_not(white))
    colored = cv2.morphologyEx(colored, cv2.MORPH_CLOSE, k, iterations=2)
    cnts2, _ = cv2.findContours(colored, cv2.RETR_EXTERNAL,
                                cv2.CHAIN_APPROX_SIMPLE)
    areas = sorted((cv2.contourArea(c) for c in cnts2), reverse=True)
    out["n_material_blobs"] = sum(1 for a in areas if a > roi_area * 0.002)
    out["material_max_frac"] = (areas[0] / roi_area) if areas else 0.0

    # ── F5: 边缘密度（手有大量褶皱边缘）──────────────────────────
    edges = cv2.Canny(roi_gray, 60, 160)
    out["edge_density"] = np.count_nonzero(edges) / roi_area

    # ── F6: 画面下 1/4 的"皮肤样"比例（手通常从下方进入）─────────
    lower = roi_hsv[roi_hsv.shape[0] * 3 // 4:, :]
    skin_l = cv2.inRange(lower, np.array((0, 25, 80), np.uint8),
                         np.array((25, 140, 255), np.uint8))
    out["skin_lower_frac"] = np.count_nonzero(skin_l) / max(1, lower.size // 3)

    # ── F7: 亮度分布（手比托盘暗）────────────────────────────────
    out["mean_v"] = float(roi_hsv[:, :, 2].mean())
    out["dark_frac"] = np.count_nonzero(roi_hsv[:, :, 2] < 110) / roi_area

    return out


def main():
    print("=" * 78)
    print("  手 vs 干净 帧特征对比")
    print("=" * 78)

    hand_f = []
    clean_f = []

    print()
    print("── 疑似有手的帧 ──")
    for i in HAND_CANDIDATES:
        img = load(i)
        if img is None:
            continue
        f = features(img)
        hand_f.append((i, f))
        print("  %3d  white=%.3f skin=%.3f skinBlob=%.3f nMat=%d matMax=%.3f "
              "edge=%.4f skinLow=%.3f dark=%.3f"
              % (i, f["white_frac"], f["skin_frac"], f["skin_max_blob_frac"],
                 f["n_material_blobs"], f["material_max_frac"],
                 f["edge_density"], f["skin_lower_frac"], f["dark_frac"]))

    print()
    print("── 干净帧 ──")
    for i in CLEAN_CANDIDATES:
        img = load(i)
        if img is None:
            continue
        f = features(img)
        clean_f.append((i, f))
        print("  %3d  white=%.3f skin=%.3f skinBlob=%.3f nMat=%d matMax=%.3f "
              "edge=%.4f skinLow=%.3f dark=%.3f"
              % (i, f["white_frac"], f["skin_frac"], f["skin_max_blob_frac"],
                 f["n_material_blobs"], f["material_max_frac"],
                 f["edge_density"], f["skin_lower_frac"], f["dark_frac"]))

    if not hand_f or not clean_f:
        print("\n⚠️ 样本不够，无法对比")
        return

    print()
    print("=" * 78)
    print("  哪个特征能分开两类？（看两组的 min/max 是否重叠）")
    print("=" * 78)
    keys = list(hand_f[0][1].keys())
    print("  %-22s %-24s %-24s %s" % ("特征", "有手(min~max)",
                                      "干净(min~max)", "可分?"))
    for k in keys:
        hv = [f[k] for _, f in hand_f]
        cv_ = [f[k] for _, f in clean_f]
        hmin, hmax = min(hv), max(hv)
        cmin, cmax = min(cv_), max(cv_)
        # 可分 = 两组区间完全不重叠
        separable = (hmin > cmax) or (hmax < cmin)
        print("  %-22s %-24s %-24s %s"
              % (k, "%.4f~%.4f" % (hmin, hmax),
                 "%.4f~%.4f" % (cmin, cmax),
                 "✅ 可分" if separable else "❌ 重叠"))

    print()
    print("=" * 78)
    print("  结论：选「可分」的特征做判据；全重叠说明这条路走不通")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
