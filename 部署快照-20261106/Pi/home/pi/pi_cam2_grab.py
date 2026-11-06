#!/usr/bin/env python3
"""副相机（DF200 / UVC）对焦与取景辅助 —— 在树莓派上跑。

## 用途

对焦环是手动的，靠"看着清楚"会来回试。本脚本**连拍 N 帧并逐帧打印清晰度**，
你一边转对焦环一边看数字往上走，到峰值后点胶锁死。

同时在每帧上算「白块占宽 / 白块占高 / 网格主方向」，与 `cam_verdict.py` 同口径，
便于现场判断"是否已经对到托盘上"。

## 用法（在 Pi 上）

    python3 pi_cam2_grab.py                     # 720p，连拍 5 帧，逐帧打印
    python3 pi_cam2_grab.py --n 10 --interval 0.5
    python3 pi_cam2_grab.py --w 1920 --h 1080   # 1080p（Pi 软解约 16 fps）
    python3 pi_cam2_grab.py --save /home/pi/cam2_focus   # 同时存图，供 PC 侧 cam_verdict 复核

## 说明

* DF200 **只有 MJPG**（v4l2 枚举实测），必须显式设 FOURCC=MJPG，否则拿不到高分辨率。
* 720p 实测 30.5 fps；1080p 实测 16.5 fps（Pi 4 软解上限，不是相机问题）。
* 清晰度用 Laplacian 方差：**只能同场景相对比较**（训练帧 115 也可能合格、失焦帧 218 也可能不合格）。
"""

from __future__ import annotations

import argparse
import os
import time

import cv2
import numpy as np


def white_metrics(frame):
    """白块 bbox 占比（与 cam_verdict.py 同口径：V>100 且 S<60，取最大连通域）。"""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
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
    return {"w_frac": bw / w, "h_frac": bh / h,
            "touch": (x <= 3, y <= 3, (x + bw) >= w - 3, (y + bh) >= h - 3)}


def roll_deg(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=60,
                            minLineLength=max(40, int(0.1 * min(frame.shape[:2]))),
                            maxLineGap=12)
    if lines is None:
        return None, 0
    angs, lens = [], []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        dx, dy = float(x2 - x1), float(y2 - y1)
        L = float(np.hypot(dx, dy))
        a = float(np.degrees(np.arctan2(dy, dx))) % 90.0
        if a > 45.0:
            a -= 90.0
        angs.append(a)
        lens.append(L)
    if not angs:
        return None, 0
    angs, lens = np.array(angs), np.array(lens)
    order = np.argsort(angs)
    cum = np.cumsum(lens[order]) / lens.sum()
    return float(angs[order][np.searchsorted(cum, 0.5)]), len(angs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", type=int, default=0)
    ap.add_argument("--w", type=int, default=1280)
    ap.add_argument("--h", type=int, default=720)
    ap.add_argument("--n", type=int, default=5, help="连拍帧数")
    ap.add_argument("--interval", type=float, default=0.4, help="帧间隔秒")
    ap.add_argument("--save", help="存图前缀（会给每帧存 jpg）")
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.dev, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.h)
    if not cap.isOpened():
        print("❌ 打不开 /dev/video%d" % args.dev)
        return 1

    real_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    real_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print("=" * 70)
    print("  副相机对焦辅助  /dev/video%d  %dx%d（请求 %dx%d）"
          % (args.dev, real_w, real_h, args.w, args.h))
    print("  转动对焦环 → 看 sharp 数字上升 → 峰值处点胶锁死")
    print("=" * 70)

    # 预热：丢掉开头几帧（AE/AWB 未稳）
    for _ in range(6):
        cap.read()

    best = -1.0
    for i in range(args.n):
        ok, frame = cap.read()
        if not ok or frame is None:
            print("  第 %d 帧读取失败" % (i + 1))
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        tray = white_metrics(frame)
        roll, nlines = roll_deg(frame)
        tag = ""
        if sharp > best:
            best = sharp
            tag = "  ← 目前最清晰"
        print("[%2d] sharp=%7.1f  白块占宽=%s  占高=%s  主方向=%s  长线=%d%s"
              % (i + 1, sharp,
                 "%.1f%%" % (tray["w_frac"] * 100) if tray else "  --  ",
                 "%.1f%%" % (tray["h_frac"] * 100) if tray else "  --  ",
                 "%+.1f°" % roll if roll is not None else " -- ",
                 nlines, tag))
        if args.save:
            os.makedirs(os.path.dirname(args.save) or ".", exist_ok=True)
            p = "%s_%02d.jpg" % (args.save, i + 1)
            cv2.imwrite(p, frame)
        time.sleep(args.interval)

    cap.release()
    print("-" * 70)
    print("本组最高 sharp = %.1f（同一场景下越高越清晰；跨场景不可比）" % best)
    print("判据（到 PC 上用 _pi_tools/cam_verdict.py 复核）：占宽 78~87%、占高 ≥90%、|主方向| ≤5°")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
