#!/usr/bin/env python3
"""用 v4 模型直接对「单个物件裁片」做分类，替代人工逐个判形。

## 为什么可行

v4 在新 30° 视角下**检测**失效（中位 0 个/帧），因为检测依赖完整场景上下文
和 bbox 回归。但**分类**只需要「这张小图里是什么形状」——
裁片已经把物件裁紧了，尺寸归一化后形状特征是保留的。

⇒ 先跑一遍看准确率，如果可用就「v4 自动分类 + 人工只改错的」。

## 输出

    _new_capture_tilt30/_crops/pred.json          每个 gid 的预测类别+置信度
    _new_capture_tilt30/_crops/montage_pred_XX.jpg 带预测标签的网格（供人工核对）

## 用法

    python _pi_tools/classify_crops_v4.py
    python _pi_tools/classify_crops_v4.py --imgsz 224 --conf 0.5
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "_new_capture_tilt30"
ALL_DIR = BASE / "all"
CROPS = BASE / "_crops"
WEIGHTS = ROOT / "_runs" / "yolo11n_6c_v4" / "weights" / "best.pt"

CLASS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism",
               "cone", "tetrahedron"]
ZH = {"cube": "正方体", "cuboid": "长方体", "cylinder": "圆柱",
      "pentagonal_prism": "五棱柱", "cone": "圆锥", "tetrahedron": "正四面体"}
SHORT = {"cube": "立", "cuboid": "长", "cylinder": "柱",
         "pentagonal_prism": "五", "cone": "锥", "tetrahedron": "四"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--imgsz", type=int, default=224)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--cols", type=int, default=8)
    ap.add_argument("--rows", type=int, default=6)
    ap.add_argument("--cell", type=int, default=130)
    args = ap.parse_args(argv)

    idx_f = CROPS / "index.json"
    if not idx_f.is_file():
        print("❌ 缺 %s（先跑 make_object_montages.py）" % idx_f)
        return 1
    index = json.loads(idx_f.read_text(encoding="utf-8"))
    if not WEIGHTS.is_file():
        print("❌ 缺权重 %s" % WEIGHTS)
        return 1

    from ultralytics import YOLO
    model = YOLO(str(WEIGHTS))

    print("=" * 76)
    print("  v4 对裁片做分类")
    print("=" * 76)
    print("  裁片 %d 个   imgsz=%d" % (len(index), args.imgsz))
    print()

    preds = []
    frames_cache: dict[str, np.ndarray] = {}
    for it in index:
        fname = it["frame"]
        if fname not in frames_cache:
            img = cv2.imdecode(np.fromfile(str(ALL_DIR / fname),
                                           dtype=np.uint8),
                              cv2.IMREAD_COLOR)
            frames_cache[fname] = img
        img = frames_cache[fname]
        if img is None:
            continue
        H, W = img.shape[:2]
        x, y, w, h = it["x"], it["y"], it["w"], it["h"]
        pad = int(max(w, h) * 0.10)
        x1 = max(0, x - pad); y1 = max(0, y - pad)
        x2 = min(W, x + w + pad); y2 = min(H, y + h + pad)
        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        # 分类：把裁片居中放在方形画布上再送模型
        side = max(crop.shape[:2])
        canvas = np.full((side, side, 3), 128, np.uint8)
        oy = (side - crop.shape[0]) // 2
        ox = (side - crop.shape[1]) // 2
        canvas[oy:oy + crop.shape[0], ox:ox + crop.shape[1]] = crop
        res = model(canvas, imgsz=args.imgsz, verbose=False)[0]
        top = None
        if len(res.boxes) > 0:
            b = max(res.boxes, key=lambda z: float(z.conf))
            top = (int(b.cls), float(b.conf))
        preds.append({
            "gid": it["gid"],
            "color": it["color"],
            "w": w, "h": h,
            "pred_cls": top[0] if top else -1,
            "pred_name": CLASS_NAMES[top[0]] if top else "UNKNOWN",
            "pred_conf": round(top[1], 3) if top else 0.0,
            "crop": crop,
        })

    # 统计
    print("  预测类别分布:")
    cnt = Counter(p["pred_name"] for p in preds)
    for n, c in cnt.most_common():
        print("    %-18s %4d" % (n, c))
    confs = [p["pred_conf"] for p in preds if p["pred_conf"] > 0]
    if confs:
        ca = np.array(confs)
        print()
        print("  置信度: 中位 %.2f  均值 %.2f" % (np.median(ca), ca.mean()))
        for th in (0.4, 0.6, 0.8):
            print("    >= %.1f 占 %.0f%%" % (th, (ca >= th).mean() * 100))
    print()

    # 存 pred.json
    out = [{"gid": p["gid"], "color": p["color"], "w": p["w"], "h": p["h"],
            "pred_cls": p["pred_cls"], "pred_name": p["pred_name"],
            "pred_conf": p["pred_conf"]} for p in preds]
    (CROPS / "pred.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # 画带预测的网格，供人工核对
    per = args.cols * args.rows
    for si in range(0, len(preds), per):
        batch = preds[si:si + per]
        cell = args.cell
        grid = np.full((args.rows * cell, args.cols * cell, 3), 32, np.uint8)
        for k, p in enumerate(batch):
            r, c = divmod(k, args.cols)
            crop = p["crop"]
            ch, cw = crop.shape[:2]
            scale = min((cell - 4) / cw, (cell - 4) / ch)
            nw, nh = max(1, int(cw * scale)), max(1, int(ch * scale))
            rs = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
            yo = r * cell + (cell - nh) // 2
            xo = c * cell + (cell - nw) // 2
            grid[yo:yo + nh, xo:xo + nw] = rs
            # 预测标签（大字，颜色区分置信度）
            col = ((0, 255, 0) if p["pred_conf"] >= 0.6 else
                   (0, 200, 255) if p["pred_conf"] >= 0.3 else (0, 0, 255))
            txt = "%s" % SHORT.get(p["pred_name"], "?")
            cv2.putText(grid, txt, (c * cell + cell - 34, r * cell + cell - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5)
            cv2.putText(grid, txt, (c * cell + cell - 34, r * cell + cell - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, col, 2)
            cv2.putText(grid, "%02d" % p["gid"], (c * cell + 3, r * cell + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
            cv2.putText(grid, "%02d" % p["gid"], (c * cell + 3, r * cell + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.rectangle(grid, (c * cell, r * cell),
                          (c * cell + cell - 1, r * cell + cell - 1),
                          (70, 70, 70), 1)
        pf = CROPS / ("montage_pred_%03d.jpg" % (si // per))
        ok, buf = cv2.imencode(".jpg", grid,
                               [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        if ok:
            buf.tofile(str(pf))
            print("  %-22s gid %d~%d" % (pf.name, si, si + len(batch) - 1))

    print()
    print("=" * 76)
    print("  图例：立=正方体 长=长方体 柱=圆柱 五=五棱柱 锥=圆锥 四=正四面体")
    print("  颜色：绿=conf>=0.6  黄=0.3~0.6  红=<0.3（需人工改）")
    print("  预测已存: %s" % (CROPS / "pred.json"))
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
