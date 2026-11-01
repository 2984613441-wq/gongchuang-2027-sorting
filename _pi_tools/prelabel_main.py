#!/usr/bin/env python3
"""主相机（MaixCAM 俯视）新数据的**预标注初稿** + 逐帧质检（先标不训）。

主相机域与 v11 训练域一致，所以这里可以直接用 v11 预标（与副相机不同）。

## 逐帧质检（不合格的帧不标注，单独列清单）

| 判据 | 阈值 | 说明 |
|---|---|---|
| v11 检出数（conf≥0.35） | ≥ 1 | 0 件 ⇒ 空台/手挡/位姿不对 |
| 清晰度 laplacian | ≥ 120 | 手贴镜头/运动模糊会被刷掉 |
| 白托盘占宽 | 25% ~ 100% | 太低 ⇒ 托盘没进画面 |
| 亮度均值 | 40 ~ 250 | 全黑/过曝 |

## 产物

    <out>/labels/<帧>.txt       YOLO（class 顺序 = cube,cuboid,cylinder,pentagonal_prism,cone,tetrahedron）
    <out>/annotated/<帧>.jpg    可视化
    <out>/review_sheet_*.jpg    每 4 帧一张复核图
    <out>/rejected.txt          被刷掉的帧 + 原因
    <out>/curated/              通过质检的原始帧副本（可选）

## 用法

    python prelabel_main.py _dataset_main_20261030 --out _labels_main/20261030 [--copy-curated]
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil

import cv2
import numpy as np

CLASSES = ["cube", "cuboid", "cylinder", "pentagonal_prism", "cone", "tetrahedron"]
BOX_COLORS = {"cube": (60, 230, 60), "cuboid": (60, 200, 255), "cylinder": (80, 80, 255),
              "pentagonal_prism": (235, 80, 235), "cone": (255, 210, 40),
              "tetrahedron": (40, 255, 255)}
CONF_KEEP = 0.35
SHARP_MIN = 120.0
W_MIN = 0.25
MEAN_RANGE = (40.0, 250.0)


def tray_width(img):
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, np.array((0, 0, 150), np.uint8), np.array((179, 60, 255), np.uint8))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k, 2)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k, 1)
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.02 * w * h:
        return None
    x, y, bw, bh = cv2.boundingRect(c)
    return bw / w


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="会话根目录（含多个 tilt30_* 子目录）或单个会话目录")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=r"_runs\yolo11n_6c_v11\weights\best.pt")
    ap.add_argument("--conf", type=float, default=CONF_KEEP)
    ap.add_argument("--copy-curated", action="store_true")
    ap.add_argument("--per-sheet", type=int, default=4)
    args = ap.parse_args(argv)

    if os.path.isdir(os.path.join(args.root, "tilt30_20261030-120935")):
        sessions = sorted(d for d in glob.glob(os.path.join(args.root, "*")) if os.path.isdir(d))
    elif glob.glob(os.path.join(args.root, "*.jpg")):
        sessions = [args.root]
    else:
        sessions = sorted(d for d in glob.glob(os.path.join(args.root, "*")) if os.path.isdir(d))
    files = []
    for s in sessions:
        files.extend(sorted(glob.glob(os.path.join(s, "*.jpg"))))
    if not files:
        print("❌ 没找到 jpg：%s" % args.root)
        return 1

    from ultralytics import YOLO
    model = YOLO(args.model)

    lab = os.path.join(args.out, "labels")
    ann = os.path.join(args.out, "annotated")
    cur = os.path.join(args.out, "curated")
    for d in (lab, ann):
        os.makedirs(d, exist_ok=True)
    if args.copy_curated:
        os.makedirs(cur, exist_ok=True)

    rejected = []
    kept = []
    stat = {c: 0 for c in CLASSES}
    for p in files:
        img = cv2.imread(p)
        if img is None:
            rejected.append((p, "读不出"))
            continue
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        mean = float(gray.mean())
        tw = tray_width(img)
        r = model.predict(img, imgsz=448, conf=args.conf, verbose=False)[0]
        boxes = [(model.names[int(b.cls)], float(b.conf), [float(v) for v in b.xyxy[0]])
                 for b in r.boxes]

        why = []
        if not boxes:
            why.append("无检出")
        if sharp < SHARP_MIN:
            why.append("模糊(%.0f)" % sharp)
        if tw is None:
            why.append("无托盘")
        elif tw < W_MIN:
            why.append("托盘过小(%.0f%%)" % (tw * 100))
        if not (MEAN_RANGE[0] <= mean <= MEAN_RANGE[1]):
            why.append("亮度异常(%.0f)" % mean)
        base = os.path.basename(os.path.dirname(p)) + "__" + os.path.basename(p)
        vis = img.copy()
        lines = []
        for cls, conf, (x1, y1, x2, y2) in boxes:
            cx, cy = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h
            lines.append("%d %.6f %.6f %.6f %.6f" % (CLASSES.index(cls), cx, cy,
                                                     (x2 - x1) / w, (y2 - y1) / h))
            stat[cls] += 1
            col = BOX_COLORS.get(cls, (255, 255, 255))
            cv2.rectangle(vis, (int(x1), int(y1)), (int(x2), int(y2)), col, 2)
            cv2.putText(vis, "%s %.2f" % (cls, conf), (int(x1), max(14, int(y1) - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 2, cv2.LINE_AA)
        if why:
            rejected.append((p, " / ".join(why)))
            continue
        kept.append(p)
        with open(os.path.join(lab, os.path.splitext(base)[0] + ".txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        cv2.imwrite(os.path.join(ann, base), vis)
        if args.copy_curated:
            shutil.copy2(p, os.path.join(cur, base))

    with open(os.path.join(args.out, "rejected.txt"), "w", encoding="utf-8") as f:
        for p, why in rejected:
            f.write("%s\t%s\n" % (p, why))

    # 复核表
    per = max(1, args.per_sheet)
    sheets = 0
    for si in range(0, len(kept), per):
        tiles = []
        for p in kept[si:si + per]:
            _base = os.path.basename(os.path.dirname(p)) + "__" + os.path.basename(p)
            v = cv2.imread(os.path.join(ann, _base))
            if v is None:
                continue
            tiles.append(cv2.resize(v, (640, 360), interpolation=cv2.INTER_AREA))
        while 0 < len(tiles) < per:
            tiles.append(np.zeros_like(tiles[0]))
        if tiles:
            cv2.imwrite(os.path.join(args.out, "review_sheet_%03d.jpg" % (sheets + 1)),
                        np.hstack(tiles))
            sheets += 1

    print("=" * 72)
    print("主相机预标注：%s" % args.out)
    print("  扫描 %d 帧（%d 个会话）" % (len(files), len(sessions)))
    print("  通过质检 **%d** 帧 / 剔除 %d 帧" % (len(kept), len(rejected)))
    print("  标注框总数 %d｜类别分布：%s"
          % (sum(stat.values()), "  ".join("%s=%d" % (c, stat[c]) for c in CLASSES if stat[c])))
    print("  复核表 %d 张（每 %d 帧一张）" % (sheets, per))
    print("  剔除清单：%s" % os.path.join(args.out, "rejected.txt"))
    if args.copy_curated:
        print("  通过帧副本：%s" % cur)
    print("  ⚠️ 先标不训：等用户复核后再合并训练")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
