#!/usr/bin/env python3
"""在 PC 上分析 MaixCAM 抓回来的图 —— 定位「远端识别不到」的原因。

用法：
    python _pi_tools/analyze_grab.py _pi_tools/grab1.jpg
    python _pi_tools/analyze_grab.py _pi_tools/grab1.jpg --conf 0.10

输出：
  · 每个检出框的类别/置信度/像素框/宽高
  · 按 Y 位置分「远端/中段/近端」统计框宽与置信度
  · 一张画好框的对比图（*_det.jpg），并标出托盘实际可见范围

判据：
  远端框明显更小、置信度更低 ⇒ 透视 + 画面未对准（不是模型问题）
  远端完全无检出且物件可见 ⇒ 物件被裁切/太小
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
WEIGHTS = ROOT / "_runs" / "yolo11n_6c_v4" / "weights" / "best.pt"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--conf", type=float, default=0.15,
                    help="故意放低，便于看漏检（默认 0.15）")
    ap.add_argument("--imgsz", type=int, default=448)
    ap.add_argument("--weights", default=str(WEIGHTS))
    args = ap.parse_args(argv)

    imf = Path(args.image)
    if not imf.is_file():
        print("文件不存在: %s" % imf)
        return 1
    wf = Path(args.weights)
    if not wf.is_file():
        print("权重不存在: %s" % wf)
        return 1

    img = cv2.imdecode(np.fromfile(str(imf), dtype=np.uint8),
                       cv2.IMREAD_COLOR)
    if img is None:
        print("读图失败: %s" % imf)
        return 1
    H, W = img.shape[:2]

    from ultralytics import YOLO
    model = YOLO(str(wf))
    res = model(img, imgsz=args.imgsz, conf=args.conf, iou=0.45,
                verbose=False)[0]
    names = res.names

    rows = []
    for b in res.boxes:
        cid = int(b.cls)
        conf = float(b.conf)
        x1, y1, x2, y2 = [int(v) for v in b.xyxy[0]]
        rows.append({
            "cls": names[cid], "conf": conf,
            "x1": x1, "y1": y1, "w": x2 - x1, "h": y2 - y1,
        })
    rows.sort(key=lambda r: r["y1"])

    print("=" * 78)
    print("  分析: %s   (%dx%d)   conf>=%.2f  imgsz=%d"
          % (imf.name, W, H, args.conf, args.imgsz))
    print("=" * 78)
    print("  检出 %d 个物件" % len(rows))
    print()
    if rows:
        print("  %-18s %6s  %-24s %6s %6s %7s %7s"
              % ("类别", "conf", "框(x,y,w,h)", "宽px", "高px", "占宽%", "Y中心"))
        print("  " + "-" * 74)
        for r in rows:
            yc = r["y1"] + r["h"] / 2.0
            pct = r["w"] / W * 100.0
            print(
                f'  {r["cls"]:<18} {r["conf"]:>6.2f}  '
                f'({r["x1"]:>4},{r["y1"]:>4},{r["w"]:>4},{r["h"]:>4}) '
                f'{r["w"]:>6} {r["h"]:>6} {pct:>6.1f}% {yc:>7.0f}'
            )
    print()

    # ── 按 Y 分三段统计 ──────────────────────────────────────────
    print("=" * 78)
    print("  按 Y 位置分段（Y 小 = 远端 / 画面上方）")
    print("=" * 78)
    zones = [("远端 0~1/3", 0, H // 3),
             ("中段 1/3~2/3", H // 3, 2 * H // 3),
             ("近端 2/3~H", 2 * H // 3, H)]
    for name, y0, y1 in zones:
        sel = [r for r in rows if y0 <= (r["y1"] + r["h"] / 2.0) < y1]
        if not sel:
            print("  %-14s 检出 0 个" % name)
            continue
        ws = [r["w"] for r in sel]
        hh = [r["h"] for r in sel]
        cfs = [r["conf"] for r in sel]
        print("  %-14s 检出 %d 个 | 框宽 %.0f~%.0f(均%.0f) | "
              "框高 %.0f~%.0f | conf %.2f~%.2f"
              % (name, len(sel), min(ws), max(ws), np.mean(ws),
                 min(hh), max(hh), min(cfs), max(cfs)))
    print()

    # ── 诊断结论 ────────────────────────────────────────────────
    print("=" * 78)
    print("  自动诊断")
    print("=" * 78)
    if len(rows) >= 2:
        far = [r for r in rows if (r["y1"] + r["h"] / 2.0) < H / 3]
        near = [r for r in rows if (r["y1"] + r["h"] / 2.0) >= 2 * H / 3]
        if far and near:
            wf_ = np.mean([r["w"] for r in far])
            wn_ = np.mean([r["w"] for r in near])
            ratio = wf_ / wn_ if wn_ > 0 else 0.0
            print("  远端平均框宽 %.0f px vs 近端 %.0f px  ⇒  远端只有近端的 %.0f%%"
                  % (wf_, wn_, ratio * 100))
            if ratio < 0.7:
                print("  ⇒ 🔴 透视压缩明显：相机倾斜过大，远端物件过小")
            elif ratio < 0.85:
                print("  ⇒ ⚠️ 有一定透视压缩，远端偏小")
            else:
                print("  ⇒ ✅ 远近端尺寸接近")
        # 是否贴边被裁
        edge = [r for r in rows if r["y1"] <= 2]
        if edge:
            print("  ⇒ 🔴 有 %d 个物件贴着画面顶边（y1<=2），远端可能已被裁切"
                  % len(edge))
    # 托盘占画面比例（按白色像素粗估）
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    white = (gray > 200)
    ys = np.where(white.any(axis=1))[0]
    if len(ys) > 0:
        ymin, ymax = int(ys.min()), int(ys.max())
        print("  白色托盘纵向范围: y=%d ~ %d  （占画面 %.0f%%）"
              % (ymin, ymax, (ymax - ymin) / H * 100))
        if ymin <= 2:
            print("  ⇒ 🔴 托盘远端已顶到画面顶边（y=0），远端被裁切！")
        below = H - ymax
        if below > H * 0.35:
            print("  ⇒ ⚠️ 托盘下方有 %d px（%.0f%%）是无关区域，视野浪费"
                  % (below, below / H * 100))
    print()

    # ── 画图 ────────────────────────────────────────────────────
    vis = img.copy()
    for r in rows:
        cv2.rectangle(vis, (r["x1"], r["y1"]),
                      (r["x1"] + r["w"], r["y1"] + r["h"]), (0, 255, 0), 3)
        cv2.putText(vis, "%s %.2f" % (r["cls"], r["conf"]),
                    (r["x1"], max(22, r["y1"] - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)
    for name, y0, y1 in zones:
        cv2.line(vis, (0, y1), (W, y1), (255, 160, 0), 2)
        cv2.putText(vis, name, (8, max(20, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 160, 0), 2)
    out = imf.with_name(imf.stem + "_det.jpg")
    ok, buf = cv2.imencode(".jpg", vis, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if ok:
        buf.tofile(str(out))
        print("  已画: %s" % out)
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
