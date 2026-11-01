#!/usr/bin/env python3
"""用现有 5 类模型给新采集的帧预标注，并输出可视化诊断。

目的：
  1. 看现有模型在「白托盘 + 顶视」上的表现（域偏移有多大）
  2. 生成草稿标签供人工修正
  3. 把可视化图存下来，方便肉眼判断哪些需要改

⚠️ 已知局限：
  · 模型没见过**圆锥** ⇒ 圆锥会被误判成 cylinder 或漏检
  · 训练集是「木桌 + 3/4 侧视」，现场是「白托盘 + 顶视」⇒ 域偏移
  · 输出的标签**必须人工复核**

用法：
  python _pi_tools/prelabel_new.py --src _new_capture/whitetray_1793028347/_clean3
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 5 类模型的类别顺序
MODEL_5C_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism", "tetrahedron"]
# 6 类数据集顺序
DATASET_6C_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism",
                    "cone", "tetrahedron"]
# 5 类 id → 6 类 id（tetrahedron 4→5）
ID_MAP = {0: 0, 1: 1, 2: 2, 3: 3, 4: 5}

DEFAULT_WEIGHT = ROOT / "_runs" / "yolo11n_5c_448" / "weights" / "best.pt"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="5 类模型预标注 + 诊断")
    ap.add_argument("--src", required=True)
    ap.add_argument("--weight", default=str(DEFAULT_WEIGHT))
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=448)
    ap.add_argument("--write-labels", action="store_true",
                    help="真的写 .txt（默认只出可视化 + 统计）")
    ap.add_argument("--vis-dir", default=None,
                    help="可视化输出目录（默认 <src>/_prelabel_vis）")
    args = ap.parse_args(argv)

    src = Path(args.src)
    frames = sorted(src.glob("*.jpg"))
    if not frames:
        print("❌ 没有 .jpg")
        return 1

    weight = Path(args.weight)
    if not weight.is_file():
        print("❌ 权重不存在: %s" % weight)
        return 1

    vis_dir = Path(args.vis_dir) if args.vis_dir else src / "_prelabel_vis"
    vis_dir.mkdir(parents=True, exist_ok=True)

    try:
        import cv2
        import numpy as np
        from ultralytics import YOLO
    except Exception as exc:
        print("❌ 依赖缺失: %s" % exc)
        return 1

    print("=" * 72)
    print("  5 类模型预标注（域偏移诊断）")
    print("=" * 72)
    print("  源目录 : %s" % src)
    print("  帧数   : %d" % len(frames))
    print("  权重   : %s" % weight)
    print("  置信度 : %.2f" % args.conf)
    print("  写标签 : %s" % ("是" if args.write_labels else "否（只诊断）"))
    print()

    model = YOLO(str(weight))
    print("  ✅ 模型已加载")
    print()

    cls_counter = Counter()
    conf_by_cls = {}
    n_per_frame = []
    n_written = 0

    for i, p in enumerate(frames, 1):
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            continue
        H, W = img.shape[:2]

        r = model.predict(source=img, imgsz=args.imgsz, conf=args.conf,
                          verbose=False, device="0")[0]

        lines = []
        vis = img.copy()
        k = 0
        boxes = getattr(r, "boxes", None)
        if boxes is not None:
            for b in boxes:
                old_id = int(b.cls.item())
                conf = float(b.conf.item())
                new_id = ID_MAP.get(old_id)
                if new_id is None:
                    continue
                x, y, w2, h2 = [float(v) for v in b.xywh[0].tolist()]
                xywhn = b.xywhn[0].tolist()
                lines.append("%d %.6f %.6f %.6f %.6f"
                             % (new_id, xywhn[0], xywhn[1], xywhn[2], xywhn[3]))
                cls_counter[new_id] += 1
                conf_by_cls.setdefault(new_id, []).append(conf)

                # 画框
                x1 = int(x - w2 / 2); y1 = int(y - h2 / 2)
                x2 = int(x + w2 / 2); y2 = int(y + h2 / 2)
                cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
                label = "%s %.2f" % (DATASET_6C_NAMES[new_id], conf)
                cv2.putText(vis, label, (x1, max(14, y1 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                k += 1

        n_per_frame.append(k)

        if args.write_labels:
            txt = p.with_suffix(".txt")
            txt.write_text("\n".join(lines) + ("\n" if lines else ""),
                           encoding="utf-8")
            n_written += 1

        # 可视化图（缩放到便于查看的尺寸）
        out_vis = vis_dir / p.name
        cv2.imencode(".jpg", vis, [int(cv2.IMWRITE_JPEG_QUALITY), 90])[1].tofile(
            str(out_vis))

        if i % 10 == 0 or i == len(frames):
            print("  [%d/%d] 已处理" % (i, len(frames)))

    # ── 汇总 ────────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("  诊断结果")
    print("=" * 72)
    print("  处理帧数 : %d" % len(n_per_frame))
    if n_per_frame:
        print("  每帧检出 : 平均 %.1f 个，最少 %d，最多 %d"
              % (sum(n_per_frame) / len(n_per_frame),
                 min(n_per_frame), max(n_per_frame)))
        n_zero = sum(1 for n in n_per_frame if n == 0)
        print("  完全没检出 : %d 帧 (%.0f%%)"
              % (n_zero, 100.0 * n_zero / len(n_per_frame)))
    print()
    print("  各类检出数 + 平均置信度:")
    total = 0
    for cid, name in enumerate(DATASET_6C_NAMES):
        n = cls_counter.get(cid, 0)
        total += n
        if n:
            avg = sum(conf_by_cls[cid]) / len(conf_by_cls[cid])
            print("    %d %-18s %4d 个  conf=%.3f" % (cid, name, n, avg))
        else:
            mark = "  ← 模型没见过（正常）" if name == "cone" else "  ← 检不出！"
            print("    %d %-18s %4d 个%s" % (cid, name, 0, mark))
    print("    %-20s %4d 个" % ("合计", total))
    print()
    print("  可视化图: %s" % vis_dir)
    if args.write_labels:
        print("  ✅ 已写 %d 个 .txt（**必须人工复核**）" % n_written)
    print()
    print("  怎么看诊断:")
    print("    · 每帧平均检出 4~5 个 ≈ 正常（托盘上 5 件）")
    print("    · 完全没检出的帧多 ⇒ 域偏移严重，需要补数据")
    print("    · cone 检出 0 个 ⇒ 正常（模型没见过），但会被误标成 cylinder")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
