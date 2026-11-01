#!/usr/bin/env python3
"""用 v7 模型为新一批数据生成候选框，输出与 make_tilt30_sheets.py 相同格式。

## 为什么不再用 HSV 候选

2026-10-28 新一批数据（`_new_capture_20261028`）的构图与昨晚不同：
    · 托盘 bbox (256,17)-(1257,406)，实心面板约 x 390~930 / y 60~470
    · 昨晚用的 ROI（x 170~1040, y 44~245）**完全对不上**
    · 试过「自动找白色面板」⇒ 阈值把下方亮桌面也算进去，bbox 一直延伸到 y=720，失败

而 v7 模型正是在昨晚的 tilt30 数据上训练的，在本视角下已经可用：
    · img_00063 上 v7 给 5 个框，肉眼也是 5 个物件，位置吻合
⇒ 直接拿 v7 的输出当候选框，比重新调 ROI 稳得多。

## 输出

    <base>/all/*.jpg                     合并后的帧（session 前缀防重名）
    <base>/_sheets/boxes_all.json        与 make_tilt30_sheets.py 同格式
    <base>/_sheets/v7_pred.json          v7 原始预测（含类别和置信度，供参考）

## 用法

    python _pi_tools/make_boxes_v7.py --base _new_capture_20261028
    python _pi_tools/make_boxes_v7.py --base _new_capture_20261028 --conf 0.15
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
WEIGHTS = ROOT / "_runs/yolo11n_6c_v7/weights/best.pt"

CLASS_NAMES = ["cube", "cuboid", "cylinder",
               "pentagonal_prism", "cone", "tetrahedron"]


def dominant_color(bgr: np.ndarray) -> str:
    """框内主导颜色名（给 make_object_montages.py 的 b['color'] 用）。

    旧格式的 color 来自 HSV 检测阶段；这里改成从裁片里现算，
    既满足下游字段要求，也方便人工判读。
    """
    if bgr.size == 0:
        return "other"
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    m = (s > 90) & (v > 45)
    if m.sum() < 20:
        return "other"
    hm = float(np.median(h[m]))
    if hm < 13 or hm >= 160:
        return "red"
    if hm < 33:
        return "yellow"
    if hm < 92:
        return "green"
    if hm < 132:
        return "blue"
    return "other"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True,
                    help="数据根目录（相对仓库根或绝对），下面应有 session 子目录")
    ap.add_argument("--conf", type=float, default=0.15,
                    help="候选框置信度下限（低一点，宁可多给候选）")
    ap.add_argument("--iou", type=float, default=0.45)
    ap.add_argument("--imgsz", type=int, default=448)
    ap.add_argument("--weights", default=str(WEIGHTS))
    ap.add_argument("--no-consolidate", action="store_true",
                    help="跳过合并帧（all/ 已存在时用）")
    args = ap.parse_args(argv)

    base = Path(args.base)
    if not base.is_absolute():
        base = ROOT / base
    all_dir = base / "all"
    sheets = base / "_sheets"
    sheets.mkdir(parents=True, exist_ok=True)

    # ── ① 合并帧（session 前缀防重名，如 085045__img_00063.jpg）──
    if not args.no_consolidate:
        sessions = sorted(d for d in base.iterdir()
                          if d.is_dir() and d.name.startswith("tilt30_"))
        if not sessions:
            print("❌ %s 下没有 tilt30_* session 目录" % base)
            return 1
        all_dir.mkdir(parents=True, exist_ok=True)
        n_copy = 0
        for s in sessions:
            tag = s.name[-6:]           # 例 085045
            for f in sorted(s.glob("*.jpg")):
                dst = all_dir / ("%s__%s" % (tag, f.name))
                if not dst.exists():
                    shutil.copy2(f, dst)
                    n_copy += 1
        print("合并帧: %d 个 session → %d 张（新增 %d）"
              % (len(sessions), len(list(all_dir.glob('*.jpg'))), n_copy))

    files = sorted(all_dir.glob("*.jpg"))
    if not files:
        print("❌ all/ 里没图")
        return 1
    print("待处理: %d 张" % len(files))

    # ── ② 跑 v7 ──
    from ultralytics import YOLO
    model = YOLO(args.weights)
    print("模型: %s" % Path(args.weights).name)
    print()

    boxes_all = {}
    v7_pred = {}
    n_obj = 0
    n_empty = 0
    cls_cnt = {n: 0 for n in CLASS_NAMES}
    for i, f in enumerate(files, 1):
        img = cv2.imdecode(np.fromfile(str(f), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        r = model(img, imgsz=args.imgsz, conf=args.conf, iou=args.iou,
                  verbose=False)[0]
        boxes = []
        preds = []
        for b in r.boxes:
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
            c = int(b.cls)
            cf = float(b.conf)
            bx, by = int(x1), int(y1)
            bw, bh = int(x2 - x1), int(y2 - y1)
            # color：从裁片现算（下游 make_object_montages.py 需要这个字段）
            crop = img[max(0, by):max(0, by + bh), max(0, bx):max(0, bx + bw)]
            col = dominant_color(crop)
            boxes.append({"x": bx, "y": by, "w": bw, "h": bh,
                          "color": col, "id": n_obj})
            n_obj += 1
            name = CLASS_NAMES[c] if 0 <= c < 6 else str(c)
            preds.append({"cls": name, "conf": round(cf, 3),
                          "box": [bx, by, bw, bh]})
            cls_cnt[name] = cls_cnt.get(name, 0) + 1
        boxes_all[f.name] = {"boxes": boxes}
        v7_pred[f.name] = preds
        if not boxes:
            n_empty += 1
        if i % 30 == 0 or i == len(files):
            print("  %d/%d ..." % (i, len(files)))

    (sheets / "boxes_all.json").write_text(
        json.dumps(boxes_all, ensure_ascii=False, indent=1), encoding="utf-8")
    (sheets / "v7_pred.json").write_text(
        json.dumps(v7_pred, ensure_ascii=False, indent=1), encoding="utf-8")

    print()
    print("=" * 74)
    print("  候选框生成完成")
    print("=" * 74)
    print("  帧数        : %d" % len(boxes_all))
    print("  空帧        : %d (%.0f%%)" % (n_empty, 100.0 * n_empty / max(1, len(boxes_all))))
    print("  候选框总数  : %d" % n_obj)
    print("  平均每帧    : %.1f" % (n_obj / max(1, len(boxes_all))))
    print()
    print("  v7 预测的类别分布（仅供参考，需人工复核）:")
    for k, v in cls_cnt.items():
        if v:
            print("    %-18s %d" % (k, v))
    print()
    print("  输出: %s" % (sheets / "boxes_all.json"))
    print("        %s" % (sheets / "v7_pred.json"))
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
