#!/usr/bin/env python3
"""离线验证：**全分辨率裁剪图上的几何特征**能不能分开 cylinder / pentagonal_prism / cone。

## 为什么做这个

YOLO 输入只有 448×448，50mm 物件只占 64 像素 ⇒ 五边形和圆形在输入里几乎一样，
这就是 `cylinder` mAP50=0.86（11% 误判成五棱柱）的可能原因。

但**原始帧是 1280×720**，同样的物件有 **184 像素** —— 如果在那里能数出顶点数，
就可以「YOLO 粗检 → 全分辨率裁剪 → 几何细化」，把 cylinder 的准确率拉上去。

## 方法

对 `_label_review_all` 里每张图的每个真值框：
  1. 按 YOLO 归一化坐标裁出**全分辨率** ROI
  2. 灰度 → Otsu 二值化（物件是深色/彩色，托盘是白）
  3. 取最大轮廓
  4. `approxPolyDP` 数顶点（epsilon = 1.5% / 3% / 5% 周长，三个口径都记）
  5. 再算 circularity / solidity / 最小外接矩形长宽比
  6. 按真值类别分组统计

## 判据

如果 `cylinder` 的顶点数明显 ≥7 而 `pentagonal_prism` 稳定 =5，就说明特征可用。

## 用法

```bash
python _pi_tools/test_vertex_features.py
python _pi_tools/test_vertex_features.py --max-per-class 80
```
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "_label_review_all" / "images"
LBL = ROOT / "_label_review_all" / "labels"

CLASS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism",
               "cone", "tetrahedron"]
IMG_EXTS = (".jpg", ".jpeg", ".png")


def analyze_roi(roi: np.ndarray) -> dict | None:
    """对一个裁剪 ROI 提取几何特征。"""
    if roi.size == 0 or roi.shape[0] < 12 or roi.shape[1] < 12:
        return None

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    # 稍微放大让边缘更干净（最近邻，避免引入新的模糊）
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0,
                      interpolation=cv2.INTER_LINEAR)

    # 物件相对白托盘是暗的：Otsu 后取「暗」的那一侧
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _t, binary = cv2.threshold(blur, 0, 255,
                               cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k, 2)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k, 1)

    cs, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL,
                             cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    area = cv2.contourArea(c)
    if area < 200:
        return None

    peri = cv2.arcLength(c, True)
    if peri <= 0:
        return None

    verts = {}
    for tag, frac in (("e15", 0.015), ("e30", 0.030), ("e50", 0.050)):
        ap = cv2.approxPolyDP(c, frac * peri, True)
        verts[tag] = len(ap)

    circ = 4.0 * np.pi * area / (peri * peri)

    hull = cv2.convexHull(c)
    hull_area = cv2.contourArea(hull)
    solidity = area / hull_area if hull_area > 0 else 0.0

    rect = cv2.minAreaRect(c)
    (rw, rh) = rect[1]
    if rw < 1 or rh < 1:
        return None
    aspect = max(rw, rh) / min(rw, rh)

    return {
        "verts15": verts["e15"], "verts30": verts["e30"], "verts50": verts["e50"],
        "circ": circ, "solidity": solidity, "aspect": aspect,
        "area": area, "rect_short": min(rw, rh), "rect_long": max(rw, rh),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-per-class", type=int, default=120)
    args = ap.parse_args(argv)

    per_cls: dict[int, list[dict]] = defaultdict(list)
    n_img = 0

    for lf in sorted(LBL.glob("*.txt")):
        if lf.stem == "classes":
            continue
        imgf = None
        for ext in IMG_EXTS:
            p = IMG / (lf.stem + ext)
            if p.is_file():
                imgf = p
                break
        if imgf is None:
            continue
        img = cv2.imdecode(np.fromfile(str(imgf), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            continue
        n_img += 1
        H, W = img.shape[:2]

        for ln in lf.read_text(encoding="utf-8").splitlines():
            parts = ln.strip().split()
            if len(parts) != 5:
                continue
            try:
                cid = int(float(parts[0]))
                cx, cy, bw, bh = (float(v) for v in parts[1:5])
            except ValueError:
                continue
            if not (0 <= cid < 6):
                continue
            if len(per_cls[cid]) >= args.max_per_class:
                continue

            x1 = int((cx - bw / 2) * W)
            x2 = int((cx + bw / 2) * W)
            y1 = int((cy - bh / 2) * H)
            y2 = int((cy + bh / 2) * H)
            x1 = max(0, x1); y1 = max(0, y1)
            x2 = min(W, x2); y2 = min(H, y2)
            if x2 - x1 < 12 or y2 - y1 < 12:
                continue

            roi = img[y1:y2, x1:x2]
            feats = analyze_roi(roi)
            if feats is not None:
                per_cls[cid].append(feats)

    print("=" * 78)
    print("  全分辨率 ROI 几何特征 离线验证")
    print("=" * 78)
    print("  扫描图片: %d 张" % n_img)
    print("  有效样本: %d 个框" % sum(len(v) for v in per_cls.values()))
    print()

    def stat(vals):
        a = np.array(vals, dtype=np.float64)
        return a.mean(), np.median(a), a.std()

    print("  %-18s %5s | %-22s | %-22s | %-9s | %-9s" %
          ("类别", "n", "顶点数 e=1.5%(均/中/σ)", "顶点数 e=3%(均/中/σ)",
           "circ", "solid"))
    print("  " + "-" * 96)
    for cid, name in enumerate(CLASS_NAMES):
        rows = per_cls.get(cid, [])
        if not rows:
            print("  %-18s %5d |  （无样本）" % (name, 0))
            continue
        v15 = stat([r["verts15"] for r in rows])
        v30 = stat([r["verts30"] for r in rows])
        circ = stat([r["circ"] for r in rows])
        sol = stat([r["solidity"] for r in rows])
        print("  %-18s %5d | %5.1f /%5.1f /%5.2f | %5.1f /%5.1f /%5.2f "
              "| %5.3f   | %5.3f" %
              (name, len(rows), v15[0], v15[1], v15[2],
               v30[0], v30[1], v30[2], circ[0], sol[0]))
    print()

    # ── 关键对比：cylinder vs pentagonal_prism ──────────────────
    print("=" * 78)
    print("  关键对比：cylinder(2) vs pentagonal_prism(3)")
    print("=" * 78)
    for cid in (2, 3):
        rows = per_cls.get(cid, [])
        if not rows:
            continue
        name = CLASS_NAMES[cid]
        for key, label in (("verts15", "顶点数 e=1.5%"),
                           ("verts30", "顶点数 e=3%"),
                           ("verts50", "顶点数 e=5%"),
                           ("circ", "圆度"),
                           ("solidity", "实心度"),
                           ("aspect", "长宽比")):
            vals = [r[key] for r in rows]
            cnt = Counter(vals) if key.startswith("verts") else None
            if cnt is not None:
                top = ", ".join("%s:%d" % (k, v)
                                for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])[:6])
                print("  %-18s %-14s 分布 %s" % (name, label, top))
            else:
                a = np.array(vals)
                print("  %-18s %-14s 均 %.3f  中 %.3f  σ %.3f"
                      % (name, label, a.mean(), np.median(a), a.std()))
        print()

    # ── 单特征可分性评估 ───────────────────────────────────────
    print("=" * 78)
    print("  可分性评估（用中位数绝对差 / 合并标准差 粗判）")
    print("=" * 78)
    a_rows = per_cls.get(2, [])
    b_rows = per_cls.get(3, [])
    if a_rows and b_rows:
        for key, label in (("verts15", "顶点数 1.5%"), ("verts30", "顶点数 3%"),
                           ("verts50", "顶点数 5%"), ("circ", "圆度"),
                           ("solidity", "实心度"), ("aspect", "长宽比")):
            a = np.array([r[key] for r in a_rows], dtype=float)
            b = np.array([r[key] for r in b_rows], dtype=float)
            pooled = np.sqrt((a.var() + b.var()) / 2.0)
            d = abs(a.mean() - b.mean()) / pooled if pooled > 1e-9 else 0.0
            verdict = ("★★★ 强" if d >= 1.2 else
                       ("★★ 中" if d >= 0.8 else
                        ("★ 弱" if d >= 0.4 else "✗ 无效")))
            print("  %-14s  圆柱 %.3f vs 五棱柱 %.3f   Cohen's d=%.2f  %s"
                  % (label, a.mean(), b.mean(), d, verdict))
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
