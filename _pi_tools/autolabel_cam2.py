#!/usr/bin/env python3
"""副相机（DF200）数据集的**标注初稿**生成（给用户复核用，不训练）。

## 为什么不用 v11 预标

实测：v11 是**主相机俯视**模型，在副相机斜侧视图上**类别判错**
（把圆柱判成 cone、五棱柱判成 cylinder，见交接文档 §19/本轮记录），
所以这里改用「颜色连通域 + 轮廓几何」生成**建议框 + 建议类别**，
由用户复核修正后再转成 YOLO 标签。

## 输出

    <out>/labels/<帧名>.txt      YOLO 格式（class cx cy w h，归一化）
    <out>/annotated/<帧名>.jpg   画了框和建议类别的可视化图
    <out>/suggest.json           每帧每件的几何证据（circularity/extent/verts/颜色）
    <out>/review_sheet_*.jpg     每 4 帧拼一张的复核大图

## 用法

    python autolabel_cam2.py _dataset_cam2/cam2_20261030-124653_curated \
        --out _labels_cam2/cam2_20261030-124653
"""

from __future__ import annotations

import argparse
import glob
import json
import os

import cv2
import numpy as np

CLASSES = ["cube", "cuboid", "cylinder", "pentagonal_prism", "cone", "tetrahedron"]
# 颜色模式（推荐给副相机）：类别 = 颜色，不猜形状。
# 依据：副相机在生产链里只做"存在性 + 颜色"确证（见交接文档 §13/§17），形状由主相机负责。
COLOR_CLASSES = ["red", "yellow", "green", "blue", "white"]
COLORS = {
    "red": [((0, 90, 40), (8, 255, 255)), ((170, 90, 40), (179, 255, 255))],
    "orange": [((9, 90, 60), (22, 255, 255))],
    "yellow": [((23, 90, 60), (35, 255, 255))],
    "green": [((36, 70, 35), (88, 255, 255))],
    "blue": [((95, 70, 30), (140, 255, 255))],
    "white": [((0, 0, 190), (179, 45, 255))],
}

# 托盘在画面的这个区域（避开左右分格框与上方工作台）
ROI = (0.20, 0.42, 0.88, 1.00)      # x1,y1,x2,y2 (比例)
TRAY_V_MIN, TRAY_S_MAX = 150, 70     # 白托盘：亮(V高)且低饱和(S低)
TRAY_V_MIN, TRAY_S_MAX = 150, 70     # 白托盘：亮且低饱和
MIN_AREA_FRAC = 0.004                # 相对 ROI 面积（抬高，压掉碎块）
BOX_COLORS = {"cube": (60, 230, 60), "cuboid": (60, 200, 255), "cylinder": (80, 80, 255),
              "pentagonal_prism": (235, 80, 235), "cone": (255, 210, 40),
              "tetrahedron": (40, 255, 255)}


def guess_class(circ: float, extent: float, verts: int, aspect: float) -> str:
    """几何 → 类别的**建议**（一定会在复核时被修正，别当真理）。"""
    if circ > 0.80 and extent > 0.68:
        return "cylinder"                      # 俯视能见到圆/椭圆面
    if verts <= 4 and extent < 0.62:
        return "cone"                          # 侧视近似三角形
    if verts <= 4:
        return "cuboid" if aspect > 1.55 else "cube"
    if verts == 5:
        return "pentagonal_prism"
    if verts >= 6 and circ > 0.55:
        return "cylinder"
    return "tetrahedron"


def tray_mask(img):
    """白托盘掩膜：亮(V高)且低饱和(S低)的最大连通域，再腐蚀避开边缘阴影。

    背景（木桌/绿垫/线缆）都不满足"亮且低饱和"，因此能有效排除桌面杂物。
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, np.array((0, 0, TRAY_V_MIN), np.uint8),
                    np.array((179, TRAY_S_MAX, 255), np.uint8))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k, 2)
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    m2 = np.zeros_like(m)
    cv2.drawContours(m2, [c], -1, 255, -1)
    return cv2.erode(m2, np.ones((25, 25), np.uint8))


def detect(img, roi_mask_scale=True):
    h, w = img.shape[:2]
    x1, y1 = int(w * ROI[0]), int(h * ROI[1])
    x2, y2 = int(w * ROI[2]), int(h * ROI[3])
    sub = img[y1:y2, x1:x2]
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    tm = tray_mask(img)
    tray_sub = tm[y1:y2, x1:x2] if tm is not None else None

    out = []
    for name, ranges in COLORS.items():
        if name == "white":
            continue                      # 白件与白托盘同行，本阶段不自动建议
        mask = None
        for lo, hi in ranges:
            m = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
            mask = m if mask is None else cv2.bitwise_or(mask, m)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
        if tray_sub is not None:
            mask = cv2.bitwise_and(mask, tray_sub)     # 只在托盘内找件
        cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        area_roi = sub.shape[0] * sub.shape[1]
        for c in cs:
            A = float(cv2.contourArea(c))
            if A < MIN_AREA_FRAC * area_roi:
                continue
            bx, by, bw, bh = cv2.boundingRect(c)
            peri = cv2.arcLength(c, True)
            circ = 4.0 * np.pi * A / (peri * peri) if peri > 1 else 0.0
            extent = A / float(bw * bh) if bw and bh else 0.0
            approx = cv2.approxPolyDP(c, 0.04 * peri, True)
            verts = len(approx)
            cls = guess_class(circ, extent, verts, bw / float(bh) if bh else 1.0)
            # geom_conf：可解释的几何置信度（不是模型置信度）
            #   · 形状明确（圆形度很高 → 圆柱；正四边形 → 立方/长方体）给高分
            #   · 三角形（cone/tetra 难分）给低分，交给人工
            geom_conf = 0.0
            if cls == "cylinder" and circ > 0.80:
                geom_conf = 0.80
            elif verts == 4 and extent > 0.65:
                geom_conf = 0.70
            elif verts == 5:
                geom_conf = 0.60
            elif verts <= 3:
                geom_conf = 0.35          # 三角形分不清 cone / tetra
            else:
                geom_conf = 0.45
            if 0 < bw and 0 < bh:
                geom_conf *= 1.0 if min(bw, bh) >= 40 else 0.7   # 太小打折
            out.append(dict(
                color=name, cls=cls, bx=bx + x1, by=by + y1, bw=bw, bh=bh,
                area=A, circ=round(circ, 3), extent=round(extent, 3), verts=verts,
                aspect=round(bw / float(bh), 2) if bh else 0.0,
                geom_conf=round(geom_conf, 2)))
    # 去重：同色框 IoU>0.6 只留大的
    out.sort(key=lambda r: -r["area"])
    kept = []
    for r in out:
        dup = False
        for k in kept:
            ix1 = max(r["bx"], k["bx"]); iy1 = max(r["by"], k["by"])
            ix2 = min(r["bx"] + r["bw"], k["bx"] + k["bw"]); iy2 = min(r["by"] + r["bh"], k["by"] + k["bh"])
            if ix2 > ix1 and iy2 > iy1:
                inter = (ix2 - ix1) * (iy2 - iy1)
                union = r["area"] + k["area"] - inter
                if inter / max(1e-9, union) > 0.6:
                    dup = True
                    break
        if not dup:
            kept.append(r)
    return kept


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-sheet", type=int, default=4)
    ap.add_argument("--mode", choices=["shape", "color"], default="color",
                    help="color=只标件+颜色（副相机推荐）；shape=几何猜 6 类")
    args = ap.parse_args(argv)

    files = sorted(glob.glob(os.path.join(args.session, "*.jpg")))
    if not files:
        print("❌ 没有 jpg：%s" % args.session)
        return 1
    lab_dir = os.path.join(args.out, "labels")
    ann_dir = os.path.join(args.out, "annotated")
    os.makedirs(lab_dir, exist_ok=True)
    os.makedirs(ann_dir, exist_ok=True)

    suggest = {}
    uncertain = {}
    n_obj = {c: 0 for c in (COLOR_CLASSES if args.mode == "color" else CLASSES)}
    total = 0
    for p in files:
        img = cv2.imread(p)
        if img is None:
            continue
        h, w = img.shape[:2]
        objs = detect(img)
        suggest[os.path.basename(p)] = objs
        lines = []
        low = []
        vis = img.copy()
        for r in objs:
            if args.mode == "color":
                pass
            elif r["geom_conf"] < 0.55:
                low.append(r)
                # 低置信也画出来，但用灰色虚线框，便于人工判断
                cv2.rectangle(vis, (r["bx"], r["by"]),
                              (r["bx"] + r["bw"], r["by"] + r["bh"]), (160, 160, 160), 1)
                cv2.putText(vis, "?%s" % r["color"], (r["bx"], max(14, r["by"] - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 160), 1, cv2.LINE_AA)
                continue
            cx = (r["bx"] + r["bw"] / 2) / w
            cy = (r["by"] + r["bh"] / 2) / h
            if args.mode == "color":
                cname = "yellow" if r["color"] == "orange" else r["color"]
                if cname not in COLOR_CLASSES:
                    continue
                lines.append("%d %.6f %.6f %.6f %.6f" % (COLOR_CLASSES.index(cname), cx, cy,
                                                         r["bw"] / w, r["bh"] / h))
                key = cname
            else:
                lines.append("%d %.6f %.6f %.6f %.6f" % (CLASSES.index(r["cls"]), cx, cy,
                                                         r["bw"] / w, r["bh"] / h))
                key = r["cls"]
            n_obj[key] = n_obj.get(key, 0) + 1
            total += 1
            col = BOX_COLORS.get(r["cls"], (0, 255, 0))
            cv2.rectangle(vis, (r["bx"], r["by"]), (r["bx"] + r["bw"], r["by"] + r["bh"]), col, 2)
            _tag = r["color"] if args.mode == "color" else "%s/%s" % (r["color"], r["cls"])
            cv2.putText(vis, _tag, (r["bx"], max(14, r["by"] - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 2, cv2.LINE_AA)
        with open(os.path.join(lab_dir, os.path.splitext(os.path.basename(p))[0] + ".txt"),
                  "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        if low:
            uncertain[os.path.basename(p)] = low
        cv2.imwrite(os.path.join(ann_dir, os.path.basename(p)), vis)

    with open(os.path.join(args.out, "suggest.json"), "w", encoding="utf-8") as f:
        json.dump(suggest, f, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, "uncertain.json"), "w", encoding="utf-8") as f:
        json.dump(uncertain, f, ensure_ascii=False, indent=1)

    # 复核大图：每 N 张拼一张
    per = max(1, args.per_sheet)
    for si in range(0, len(files), per):
        chunk = files[si:si + per]
        tiles = []
        for p in chunk:
            v = cv2.imread(os.path.join(ann_dir, os.path.basename(p)))
            if v is None:
                continue
            v = cv2.resize(v, (640, 360), interpolation=cv2.INTER_AREA)
            tiles.append(v)
        if not tiles:
            continue
        while len(tiles) < per:
            tiles.append(np.zeros_like(tiles[0]))
        row = np.hstack(tiles)
        sheet = os.path.join(args.out, "review_sheet_%03d.jpg" % (si // per + 1))
        cv2.imwrite(sheet, row)

    print("=" * 70)
    print("标注初稿生成：%s" % args.out)
    print("  帧数 %d｜建议框 %d 个" % (len(files), total))
    _cls = COLOR_CLASSES if args.mode == "color" else CLASSES
    print("  类别分布：" + "  ".join("%s=%d" % (c, n_obj[c]) for c in _cls if n_obj.get(c)))
    print("  标注口径：%s" % ("颜色（副相机只做存在性+颜色确证）" if args.mode == "color"
                            else "几何形状（易错，需人工核对）"))
    print("  labels/   %d 个 txt（YOLO 格式，class 按 %s）" % (len(files), CLASSES))
    print("  annotated/ 可视化；review_sheet_*.jpg 每 %d 帧一张复核图" % per)
    print("  ⚠️ 类别是**几何建议**，务必人工复核后再训练")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
