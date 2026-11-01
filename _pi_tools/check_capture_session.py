#!/usr/bin/env python3
"""采集会话质检（PC 侧）—— 一边拍一边看，别等 140 张拍完才发现废了。

## 检查什么

| 指标 | 判据 | 说明 |
|---|---|---|
| 托盘占宽 | 78~87% | 与 v11 训练口径一致（`cam_verdict.py` 同款白块口径）|
| 托盘占高 | ≥90% | 训练帧托盘纵贯画面 |
| 网格主方向 | \|角\| ≤ 5° | 相机滚转 |
| 清晰度 laplacian | 记录，**不作判据** | 跨场景不可比，只看同场景相对变化 |
| v11 检出 | ≥1 件 | 0 件 ⇒ 布局没摆好/太暗/糊 |
| 与上一帧差异 | >0.3% 像素 | 太小 ⇒ 你没换布局，等于重复样本 |
| 过曝/过暗 | 过曝(≥250)占比 ≤5%，均值 ≥40 | 补光灯 255 满亮时容易过曝 |

## 用法

    # 本地目录（scp 回来以后）
    python check_capture_session.py _dataset_tilt30/tilt30_20261030-200000

    # 只看汇总，不打逐帧表
    python check_capture_session.py <dir> --quiet

    # 抽检：只看前 20 张
    python check_capture_session.py <dir> --limit 20

退出码：0 = 无致命问题；1 = 有问题（会列出来）。
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

import cv2
import numpy as np

W_MIN, W_MAX = 0.78, 0.87
H_MIN = 0.90
ROLL_MAX = 5.0
DIFF_MIN = 0.003          # 与上一帧的最小变化占比


def white_bbox(img):
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, np.array((0, 0, 100), np.uint8), np.array((179, 60, 255), np.uint8))
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
    return x, y, x + bw, y + bh, bw / w, bh / h


def roll_deg(img, box):
    x1, y1, x2, y2 = box[:4]
    roi = img[max(0, y1):y2, max(0, x1):x2]
    if roi.size == 0:
        return None, 0
    edges = cv2.Canny(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=60,
                            minLineLength=max(40, int(0.15 * min(roi.shape[:2]))),
                            maxLineGap=12)
    if lines is None:
        return None, 0
    angs, lens = [], []
    for a1, b1, a2, b2 in lines.reshape(-1, 4):
        dx, dy = float(a2 - a1), float(b2 - b1)
        L = float(np.hypot(dx, dy))
        a = float(np.degrees(np.arctan2(dy, dx))) % 90.0
        if a > 45:
            a -= 90
        angs.append(a)
        lens.append(L)
    angs, lens = np.array(angs), np.array(lens)
    order = np.argsort(angs)
    cum = np.cumsum(lens[order]) / lens.sum()
    return float(angs[order][np.searchsorted(cum, 0.5)]), len(angs)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--limit", type=int, default=0, help="只检查前 N 张")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--model", default="_runs/yolo11n_6c_v11/weights/best.pt")
    ap.add_argument("--conf", type=float, default=0.25)
    args = ap.parse_args(argv)

    files = sorted(glob.glob(os.path.join(args.session, "*.jpg")))
    if not files:
        print("❌ 目录里没有 jpg：%s" % args.session)
        return 1
    if args.limit:
        files = files[:args.limit]

    model = None
    if args.model and os.path.exists(args.model):
        try:
            from ultralytics import YOLO
            model = YOLO(args.model)
        except Exception as e:
            print("⚠️ 模型加载失败，跳过检出统计：%s" % e)

    print("=" * 96)
    print("会话质检：%s  共 %d 张%s" % (os.path.basename(args.session), len(files),
                                        "（抽检前 %d）" % len(files) if args.limit else ""))
    print("=" * 96)
    if not args.quiet:
        print("%-6s %7s %7s %7s %7s %7s %6s  %s"
              % ("帧", "占宽%", "占高%", "主方向°", "清晰度", "过曝%", "检出", "提示"))

    prev_gray = None
    rows = []
    bad = []
    for i, p in enumerate(files):
        img = cv2.imread(p)
        if img is None:
            bad.append((os.path.basename(p), "读不出"))
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        over = float((gray >= 250).mean() * 100)
        mean = float(gray.mean())
        bb = white_bbox(img)
        w = h = None
        roll = None
        nlines = 0
        if bb:
            w, h = bb[4], bb[5]
            roll, nlines = roll_deg(img, bb)
        nd = None
        if model is not None:
            r = model.predict(img, imgsz=448, conf=args.conf, verbose=False)[0]
            nd = len(r.boxes)
        diff = 1.0
        if prev_gray is not None:
            d = cv2.absdiff(gray, prev_gray)
            diff = float((d > 8).mean())
        prev_gray = gray

        tips = []
        if bb is None:
            tips.append("无托盘")
        else:
            if not (W_MIN <= w <= W_MAX):
                tips.append("占宽%.0f%%" % (w * 100))
            if h < H_MIN:
                tips.append("占高%.0f%%" % (h * 100))
            if roll is not None and abs(roll) > ROLL_MAX:
                tips.append("主方向%+.0f°" % roll)
        if nd == 0:
            tips.append("无检出")
        if over > 5:
            tips.append("过曝")
        if mean < 40:
            tips.append("过暗")
        if prev_gray is not None and diff < DIFF_MIN:
            tips.append("与上帧几乎相同")
        if tips:
            bad.append((os.path.basename(p), " / ".join(tips)))

        rows.append(dict(name=os.path.basename(p), w=w, h=h, roll=roll, sharp=sharp,
                         over=over, mean=mean, nd=nd, diff=diff))
        if not args.quiet:
            print("%-6d %7s %7s %7s %7.0f %7.1f %6s  %s"
                  % (i, "%.0f" % (w * 100) if w else "-",
                     "%.0f" % (h * 100) if h else "-",
                     "%+.1f" % roll if roll is not None else "-",
                     sharp, over, nd if nd is not None else "-",
                     " / ".join(tips)))

    ok = [r for r in rows if r["w"] and W_MIN <= r["w"] <= W_MAX and r["h"] >= H_MIN]
    print("-" * 96)
    print("张数 %d｜占宽落在 78~87%% 且占高≥90%% 的：%d 张（%.0f%%）"
          % (len(rows), len(ok), 100.0 * len(ok) / max(1, len(rows))))
    if rows:
        ws = [r["w"] * 100 for r in rows if r["w"]]
        if ws:
            print("占宽分布：%.0f%%~%.0f%%（均 %.1f%%）" % (min(ws), max(ws), sum(ws) / len(ws)))
        sh = [r["sharp"] for r in rows]
        print("清晰度：均 %.0f（%.0f~%.0f）" % (sum(sh) / len(sh), min(sh), max(sh)))
        if model is not None:
            n0 = sum(1 for r in rows if r["nd"] == 0)
            print("无检出帧：%d 张" % n0)
            tot = sum(r["nd"] for r in rows if r["nd"] is not None)
            print("检出总数：%d（均 %.1f 件/帧）" % (tot, tot / max(1, len(rows))))
    if bad:
        print()
        print("⚠️ 需要注意的 %d 张：" % len(bad))
        for name, why in bad[:30]:
            print("   %s  ←  %s" % (name, why))
        if len(bad) > 30:
            print("   ...（共 %d 条）" % len(bad))
    print("=" * 96)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
