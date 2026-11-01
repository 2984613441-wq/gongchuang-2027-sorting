#!/usr/bin/env python3
"""用 v7 预标注生成 labelImg 复核工作区。

## 为什么这么做（而不是我人眼从拼图判）

2026-10-27 的教训：我从 130px 拼图格子里判形状，用户复核时改了 97 个框
（cube 138→99、cuboid 0→51、五棱柱 14→68）。
⇒ 方块类（正方体/长方体/五棱柱）在 30° 斜视 + 小拼图下人工判不清。

而 v7 模型六类 mAP50 全部 ≥0.924、形状判别准确率约 92%。
⇒ 用 v7 预标注 + 人工修正，比重头标注快 5~10 倍，
   而且是在"修正 8%"而不是"从零标 100%"。

## 输出

    <out>/images/*.jpg      帧（session 前缀命名）
    <out>/labels/*.txt      YOLO 格式预标注（cls cx cy w h，归一化）
    <out>/classes.txt       六类（**无 BOM**，否则 labelImg 显示乱码）
    <out>/predefined_classes.txt  同上
    <out>/pred_info.json    每框的 v7 置信度（供参考）
    <out>/复核说明.txt       给用户看的说明

## 用法

    python _pi_tools/make_review_v7.py --base _new_capture_20261028 --out _review_20261028
    python _pi_tools/make_review_v7.py --base _new_capture_20261028 --out _review_20261028 --conf 0.25
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
WEIGHTS = ROOT / "_runs/yolo11n_6c_v7/weights/best.pt"

# 顺序必须与 data.yaml / 模型一致，不能改
CLASS_NAMES = ["cube", "cuboid", "cylinder",
               "pentagonal_prism", "cone", "tetrahedron"]
ZH = {"cube": "正方体", "cuboid": "长方体", "cylinder": "圆柱",
      "pentagonal_prism": "五棱柱", "cone": "圆锥",
      "tetrahedron": "正四面体"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--conf", type=float, default=0.25,
                    help="预标注置信度下限（低于此不预标，留给你补）")
    ap.add_argument("--iou", type=float, default=0.45)
    ap.add_argument("--imgsz", type=int, default=448)
    ap.add_argument("--weights", default=str(WEIGHTS))
    args = ap.parse_args(argv)

    base = Path(args.base)
    if not base.is_absolute():
        base = ROOT / base
    all_dir = base / "all"
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out

    files = sorted(all_dir.glob("*.jpg"))
    if not files:
        print("❌ %s 里没图（先跑 make_boxes_v7.py 合并帧）" % all_dir)
        return 1

    img_dir = out / "images"
    lbl_dir = out / "labels"
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)

    from ultralytics import YOLO
    model = YOLO(args.weights)
    print("模型: %s" % Path(args.weights).name)
    print("帧数: %d   预标注阈值: conf >= %.2f" % (len(files), args.conf))
    print()

    pred_info = {}
    n_box = 0
    n_empty = 0
    cls_cnt = {n: 0 for n in CLASS_NAMES}
    for i, f in enumerate(files, 1):
        img = cv2.imdecode(np.fromfile(str(f), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        H, W = img.shape[:2]
        r = model(img, imgsz=args.imgsz, conf=args.conf, iou=args.iou,
                  verbose=False)[0]
        lines = []
        infos = []
        for b in r.boxes:
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
            c = int(b.cls)
            cf = float(b.conf)
            cx = (x1 + x2) / 2.0 / W
            cy = (y1 + y2) / 2.0 / H
            bw = (x2 - x1) / W
            bh = (y2 - y1) / H
            cx = min(max(cx, 0.0), 1.0)
            cy = min(max(cy, 0.0), 1.0)
            bw = min(max(bw, 0.0), 1.0)
            bh = min(max(bh, 0.0), 1.0)
            lines.append("%d %.6f %.6f %.6f %.6f" % (c, cx, cy, bw, bh))
            name = CLASS_NAMES[c] if 0 <= c < 6 else str(c)
            infos.append({"cls": name, "zh": ZH.get(name, name),
                          "conf": round(cf, 3)})
            cls_cnt[name] = cls_cnt.get(name, 0) + 1
        # 复制图片
        dst = img_dir / f.name
        if not dst.exists():
            dst.write_bytes(f.read_bytes())
        # 写标签（空帧也写空文件 ⇒ labelImg 里显示"无框"，你确认是否是废帧）
        (lbl_dir / (f.stem + ".txt")).write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        pred_info[f.name] = infos
        n_box += len(lines)
        if not lines:
            n_empty += 1
        if i % 30 == 0 or i == len(files):
            print("  %d/%d ..." % (i, len(files)))

    # classes.txt（**必须无 BOM**，否则 labelImg 把 UTF-8 BOM 当字符，显示 "锘縞ube"）

    def write_no_bom(p: Path, text: str) -> None:
        p.write_bytes(text.encode("utf-8"))   # 不用 write_text，避免平台加 BOM

    cls_text = "\n".join(CLASS_NAMES) + "\n"
    write_no_bom(out / "classes.txt", cls_text)
    write_no_bom(out / "predefined_classes.txt", cls_text)
    write_no_bom(lbl_dir / "classes.txt", cls_text)
    (out / "pred_info.json").write_text(
        json.dumps(pred_info, ensure_ascii=False, indent=1), encoding="utf-8")

    (out / "复核说明.txt").write_text(
        "v7 预标注复核工作区\n"
        "=" * 50 + "\n\n"
        "这些框是 v7 模型（mAP50 0.976、形状判别约92%）自动标的，\n"
        "不是从零标注 —— 你只需要：\n\n"
        "  1) 改错的类别（双击框，或删了重画）\n"
        "  2) 补 v7 漏掉的物件\n"
        "  3) 删掉误检的框（手、电线、反光）\n"
        "  4) 空标签的帧 = v7 什么都没找到；如果确实没物件，它就是废帧\n\n"
        "类别（6 类，顺序不能改）：\n" +
        "".join("  %d  %-18s %s\n" % (i, n, ZH[n])
                for i, n in enumerate(CLASS_NAMES)) +
        "\n判类要点：\n"
        "  正方体 vs 长方体 = 顶面是否为正方形（长方形 => 长方体）\n"
        "  正方体 vs 五棱柱 = 顶面 4 条边还是 5 条边\n"
        "  圆柱   = 平顶 + 圆形，侧面光滑\n"
        "  圆锥   = 尖顶\n"
        "  正四面体 = 三角形面，尖端\n",
        encoding="utf-8")

    print()
    print("=" * 74)
    print("  ✅ 复核工作区已生成: %s" % out)
    print("=" * 74)
    print("  图片   : %d 张" % len(list(img_dir.glob('*.jpg'))))
    print("  预标注 : %d 个框（平均 %.1f/帧，其中空帧 %d）"
          % (n_box, n_box / max(1, len(files)), n_empty))
    print()
    print("  v7 预标类别分布（需你复核修正）:")
    for k, v in cls_cnt.items():
        if v:
            print("    %-18s %3d  (%s)" % (k, v, ZH[k]))
    print()
    print("  文件:")
    print("    %s" % (out / "classes.txt"))
    print("    %s" % (out / "复核说明.txt"))
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
