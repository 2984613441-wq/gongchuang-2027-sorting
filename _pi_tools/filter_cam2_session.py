#!/usr/bin/env python3
"""副相机（DF200）采集会话筛选（PC 侧）：把空台 / 偏糊 / 重复帧挑出来。

## 为什么需要

`pi_cam2_capture.py` 是按固定间隔自动拍的，摆件过程中必然混进：
  · **空台帧**（换布局时把件拿空了）
  · **偏糊帧**（手/件还在动）
  · **重复帧**（没换布局，几乎相同）

这些直接进训练集只会污染，必须先筛。

## 判据（依据 2026-10-30 实测标定）

| 类别 | 判据 | 实测依据 |
|---|---|---|
| 空台 EMPTY | 中央托盘区饱和像素 < 6% **且** v11 检出 0 | 空台帧：饱和 4.81% / v11=0；三件帧：10.02% / v11=3 |
| 偏糊 BLUR | 清晰度 < max(绝对下限, 0.55×本会话中位) | 本批中位 ~195，糊帧低至 21 |
| 重复 DUP | 与上一张差异 < 0.30% 像素 | — |
| 暗 DARK | 亮度均值 < 60 | — |

> ⚠️ v11 是**主相机**模型，在副相机视角下**类别会判错**（实测把圆柱判成 cone 等），
> 所以这里只用它的「有没有检出」来辅助判空台，**不要**拿它当副相机数据的预标注。

## 用法

    # 只看统计
    python filter_cam2_session.py _dataset_cam2/cam2_20261030-124920

    # 把可用帧复制到一个 _curated 目录（不改原图）
    python filter_cam2_session.py <dir> --copy-curated

输出：终端表格 + `<dir>/../<session>_curated/`（可选）+ `<dir>/keep_list.txt`
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil

import cv2
import numpy as np

CENTRAL_Y = (0.45, 0.98)     # 托盘在画面下半部
CENTRAL_X = (0.22, 0.85)     # 避开左右分格框
SAT_S_MIN, SAT_V_MIN = 90, 40
EMPTY_SAT = 6.0              # 中央饱和像素 < 6% 视为"没件"
BLUR_RATIO = 0.55
DUP_RATIO = 0.003
DARK_MEAN = 60.0


def analyse(path, model, conf):
    img = cv2.imread(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean = float(gray.mean())
    roi = img[int(h * CENTRAL_Y[0]):int(h * CENTRAL_Y[1]),
              int(w * CENTRAL_X[0]):int(w * CENTRAL_X[1])]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    sat = float(((hsv[:, :, 1] > SAT_S_MIN) & (hsv[:, :, 2] > SAT_V_MIN)).mean() * 100)
    nd = None
    if model is not None:
        r = model.predict(img, imgsz=448, conf=conf, verbose=False)[0]
        nd = len(r.boxes)
    return dict(gray=gray, sharp=sharp, mean=mean, sat=sat, nd=nd)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--model", default="_runs/yolo11n_6c_v11/weights/best.pt")
    ap.add_argument("--conf", type=float, default=0.15)
    ap.add_argument("--copy-curated", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    files = sorted(glob.glob(os.path.join(args.session, "*.jpg")))
    if not files:
        print("❌ 没有 jpg：%s" % args.session)
        return 1

    model = None
    if args.model and os.path.exists(args.model):
        try:
            from ultralytics import YOLO
            model = YOLO(args.model)
        except Exception as e:
            print("⚠️ 模型加载失败（只用几何判据）：%s" % e)

    rows = []
    prev = None
    for i, p in enumerate(files):
        a = analyse(p, model, args.conf)
        if a is None:
            rows.append(dict(idx=i, name=os.path.basename(p), tag="BAD"))
            continue
        tag = "KEEP"
        if a["mean"] < DARK_MEAN:
            tag = "DARK"
        elif prev is not None and float((cv2.absdiff(a["gray"], prev) > 8).mean()) < DUP_RATIO:
            tag = "DUP"
        elif a["sat"] < EMPTY_SAT and (a["nd"] == 0 or a["nd"] is None):
            tag = "EMPTY"
        rows.append(dict(idx=i, name=os.path.basename(p), tag=tag, sharp=a["sharp"],
                         mean=a["mean"], sat=a["sat"], nd=a["nd"]))
        prev = a["gray"]

    # 偏糊：相对本会话中位
    mid = float(np.median([r["sharp"] for r in rows if "sharp" in r])) if rows else 0.0
    thr = max(60.0, mid * BLUR_RATIO)
    for r in rows:
        if r.get("tag") == "KEEP" and r.get("sharp", 1e9) < thr:
            r["tag"] = "BLUR"

    if not args.quiet:
        print("=" * 78)
        print("副相机会话筛选：%s  共 %d 张（清晰度中位 %.0f，糊阈值 %.0f）"
              % (os.path.basename(args.session.rstrip("/\\")), len(files), mid, thr))
        print("=" * 78)
        print("%-6s %-14s %7s %7s %7s %6s  %s"
              % ("帧", "文件", "清晰度", "亮度", "中央饱和%", "检出", "判定"))
        for r in rows:
            print("%-6d %-14s %7s %7s %7s %6s  %s"
                  % (r["idx"], r["name"],
                     "%.0f" % r["sharp"] if "sharp" in r else "-",
                     "%.0f" % r["mean"] if "mean" in r else "-",
                     "%.2f" % r["sat"] if "sat" in r else "-",
                     r["nd"] if r.get("nd") is not None else "-",
                     r["tag"]))

    keep = [r for r in rows if r["tag"] == "KEEP"]
    stat = {}
    for r in rows:
        stat[r["tag"]] = stat.get(r["tag"], 0) + 1
    print("-" * 78)
    print("统计：" + "  ".join("%s=%d" % (k, v) for k, v in sorted(stat.items())))
    print("可用 %d 张（保留率 %.0f%%）" % (len(keep), 100.0 * len(keep) / max(1, len(rows))))
    drop = [r for r in rows if r["tag"] != "KEEP"]
    if drop:
        print("剔除清单：")
        for r in drop:
            print("   %s  ← %s" % (r["name"], r["tag"]))

    list_path = os.path.join(args.session, "keep_list.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        f.write("\n".join(r["name"] for r in keep) + "\n")
    print("保留清单：%s" % list_path)

    if args.copy_curated:
        out = args.session.rstrip("/\\") + "_curated"
        os.makedirs(out, exist_ok=True)
        for r in keep:
            shutil.copy2(os.path.join(args.session, r["name"]), os.path.join(out, r["name"]))
        print("已复制可用帧到：%s（%d 张，原图未动）" % (out, len(keep)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
