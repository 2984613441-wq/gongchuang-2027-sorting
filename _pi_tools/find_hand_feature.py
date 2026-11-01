#!/usr/bin/env python3
"""找能真正分开「手」和「物料」的判据。

已知：
  · 肤色比例不行（手在补光灯下苍白，反而更低）
  · 物料 vs 手的大小差很大：物料 ≈ 170px 见方，手 ≈ 340×508px

候选判据：
  A. 最大单个连通域占托盘比例（物料小、手大）
  B. "非白且非肤色"区域的最大连通域（即"物料样"物体）
  C. 长宽比（手细长，物料接近方形）
  D. 边缘密度（手有褶皱，边缘多）
  E. 与托盘的亮度差（手比托盘暗一点）
"""

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "_new_capture" / "whitetray_1793028347"

INNER_ROI = (0.3008, 0.0486, 0.7852, 0.9514)

GROUPS = {
    "有手": [80, 81, 82, 83, 8, 9],
    "有物料": [0, 26, 30, 71],
    "空托盘": [87, 88, 89, 117, 118],
}


def analyze(idx):
    p = SRC / ("img_%05d.jpg" % idx)
    if not p.is_file():
        return None
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    x1 = int(W * INNER_ROI[0]); y1 = int(H * INNER_ROI[1])
    x2 = int(W * INNER_ROI[2]); y2 = int(H * INNER_ROI[3])
    roi_hsv = hsv[y1:y2, x1:x2]
    roi_gray = gray[y1:y2, x1:x2]
    area = roi_hsv.shape[0] * roi_hsv.shape[1]

    out = {}

    # ── 候选 A：所有"非托盘白"区域的连通域（= 一切挡在托盘上的东西）
    #    托盘白 = 低饱和 + 高亮度
    not_tray = cv2.inRange(roi_hsv,
                           np.array((0, 55, 0), np.uint8),      # 饱和 > 55
                           np.array((179, 255, 255), np.uint8))
    # 再加"暗"的（手/阴影）
    dark = cv2.inRange(roi_hsv, np.array((0, 0, 0), np.uint8),
                       np.array((179, 255, 165), np.uint8))
    not_tray = cv2.bitwise_or(not_tray, dark)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    not_tray = cv2.morphologyEx(not_tray, cv2.MORPH_CLOSE, k, 2)
    not_tray = cv2.morphologyEx(not_tray, cv2.MORPH_OPEN, k, 1)
    cnts, _ = cv2.findContours(not_tray, cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_SIMPLE)
    areas = sorted((cv2.contourArea(c) for c in cnts), reverse=True)

    out["n_blobs"] = sum(1 for a in areas if a > area * 0.0015)
    out["total_frac"] = sum(a for a in areas if a > area * 0.0015) / area
    out["max_blob_frac"] = (areas[0] / area) if areas else 0.0
    out["p90_blob_frac"] = (areas[len(areas) // 10] / area) if areas else 0.0

    # ── 候选 C：最大 blob 的长宽比与填充率 ────────────────────────
    if cnts:
        big = max(cnts, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(big)
        out["max_aspect"] = (max(w, h) / max(1, min(w, h)))
        out["max_fill"] = cv2.contourArea(big) / max(1, w * h)
        out["max_bbox_frac"] = (w * h) / area
    else:
        out["max_aspect"] = 0.0
        out["max_fill"] = 0.0
        out["max_bbox_frac"] = 0.0

    # ── 候选 D：边缘密度 ──────────────────────────────────────────
    edges = cv2.Canny(roi_gray, 50, 150)
    out["edge_density"] = np.count_nonzero(edges) / area

    # ── 候选 E：托盘白占比（手/物料都占掉白）──────────────────────
    white = cv2.inRange(roi_hsv, np.array((0, 0, 150), np.uint8),
                        np.array((179, 50, 255), np.uint8))
    out["white_frac"] = np.count_nonzero(white) / area

    return out


def main():
    print("=" * 84)
    print("  找区分「手」vs「物料」的判据")
    print("=" * 84)
    print()

    data = {}
    for gname, idxs in GROUPS.items():
        print("── %s ──" % gname)
        rows = []
        for i in idxs:
            r = analyze(i)
            if r is None:
                continue
            rows.append((i, r))
            print("  %3d  nBlob=%-2d total=%.3f maxBlob=%.3f aspect=%.2f "
                  "fill=%.2f bboxFrac=%.3f edge=%.4f white=%.3f"
                  % (i, r["n_blobs"], r["total_frac"], r["max_blob_frac"],
                     r["max_aspect"], r["max_fill"], r["max_bbox_frac"],
                     r["edge_density"], r["white_frac"]))
        data[gname] = rows
        print()

    print("=" * 84)
    print("  区间对比（看有无重叠）")
    print("=" * 84)
    keys = ["n_blobs", "total_frac", "max_blob_frac", "max_aspect",
            "max_fill", "max_bbox_frac", "edge_density", "white_frac"]
    print("  %-16s %-20s %-20s %-20s %s"
          % ("判据", "有手", "有物料", "空托盘", "手/物料 可分?"))
    for k in keys:
        parts = []
        for g in ("有手", "有物料", "空托盘"):
            v = [r[k] for _, r in data.get(g, [])]
            parts.append("%.4f~%.4f" % (min(v), max(v)) if v else "n/a")
        hv = [r[k] for _, r in data.get("有手", [])]
        ov = [r[k] for _, r in data.get("有物料", [])]
        sep = "?"
        if hv and ov:
            # 手全部 > 物料最大值，或手全部 < 物料最小值
            if min(hv) > max(ov) or max(hv) < min(ov):
                sep = "✅ 可分"
            else:
                sep = "❌ 重叠"
        print("  %-16s %-20s %-20s %-20s %s"
              % (k, parts[0], parts[1], parts[2], sep))
    print("=" * 84)
    return 0


if __name__ == "__main__":
    sys.exit(main())
