#!/usr/bin/env python3
"""比对「训练用的白托盘图」与「现在现场抓的图」—— 判断相机是否被挪动过。

## 为什么做这个

如果训练图和现场图的托盘位置/大小明显不同，说明相机被挪过，
那远端低置信度就不只是遮挡问题，还有「域不匹配」问题 ⇒ 必须补拍重训。

## 方法

在两幅图里都找「白色托盘区域」（白度高、饱和度低的连通域），比较：
  · 托盘的包围盒（x1,y1,x2,y2）
  · 占画面宽高比例
  · 顶端是否贴到 y=0（远端是否被切）
  · 托盘面积占比

## 用法

    python _pi_tools/compare_view.py _pi_tools/grab1.jpg
    python _pi_tools/compare_view.py _pi_tools/grab1.jpg --refs 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
# 🔴 2026-10-29 修：原来指向 `_label_review_all/images`（旧标注工作区，构图与 v11 训练**不是同一批**），
#    导致"训练图参照"算出 50.8% 宽、却拿训练帧一跑就报"必须重训"（自相矛盾）。
#    改用**真正的 v11 训练集**做参照。
TRAIN_IMG = ROOT / "_dataset_yolo_6c_v11" / "images" / "train"

WHITE_V_MIN = 170        # 白托盘亮度下限
WHITE_S_MAX = 55         # 白托盘饱和度上限


def white_bbox(img: np.ndarray):
    """返回白色托盘区域的包围盒与统计（用最大连通域）。"""
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array((0, 0, WHITE_V_MIN), np.uint8),
                       np.array((179, WHITE_S_MAX, 255), np.uint8))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, 2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, 1)
    cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    area = cv2.contourArea(c)
    if area < W * H * 0.02:
        return None
    x, y, w, h = cv2.boundingRect(c)
    return {
        "x1": x, "y1": y, "x2": x + w, "y2": y + h,
        "w": w, "h": h,
        "w_frac": w / W, "h_frac": h / H,
        "area_frac": area / (W * H),
        "touch_top": y <= 3,
        "touch_bottom": (y + h) >= H - 3,
        "touch_left": x <= 3,
        "touch_right": (x + w) >= W - 3,
    }


def fmt(b) -> str:
    if b is None:
        return "  未找到白色托盘区域"
    flags = []
    if b["touch_top"]:
        flags.append("顶边被切")
    if b["touch_bottom"]:
        flags.append("底边被切")
    if b["touch_left"]:
        flags.append("左边被切")
    if b["touch_right"]:
        flags.append("右边被切")
    fl = ("  ⚠️ " + " / ".join(flags)) if flags else "  ✅ 四边都在画面内"
    return (
        "  包围盒 (%d,%d) - (%d,%d)   宽 %d  高 %d\n"
        "  占画面  宽 %.1f%%  高 %.1f%%   面积 %.1f%%\n%s"
        % (b["x1"], b["y1"], b["x2"], b["y2"], b["w"], b["h"],
           b["w_frac"] * 100, b["h_frac"] * 100, b["area_frac"] * 100, fl)
    )


def load(p: Path):
    if not p.is_file():
        return None
    return cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("now", help="现场抓的图")
    ap.add_argument("--refs", type=int, default=4,
                    help="取几张训练图做参照（默认 4）")
    args = ap.parse_args(argv)

    now_p = Path(args.now)
    now = load(now_p)
    if now is None:
        print("读不到: %s" % now_p)
        return 1
    H, W = now.shape[:2]

    print("=" * 78)
    print("  托盘取景比对：训练图 vs 现场")
    print("=" * 78)
    print()
    print("【现场】%s  (%dx%d)" % (now_p.name, W, H))
    b_now = white_bbox(now)
    print(fmt(b_now))
    print()

    # 参照：从 v11 训练集**均匀抽样**（全量 265 张，只取 --refs 张）
    _all = sorted(TRAIN_IMG.glob("*.jpg"))
    if not _all:
        print("❌ 找不到 v11 训练图（%s）" % TRAIN_IMG)
        return 1
    _step = max(1, len(_all) // max(1, args.refs))
    refs = _all[::_step][:args.refs]

    stats = []
    print("【训练图】共 %d 张参照" % len(refs))
    for p in refs:
        img = load(p)
        if img is None:
            continue
        b = white_bbox(img)
        stats.append((p.name, b))
        print()
        print("  %s" % p.name)
        print(fmt(b))
    print()

    # ── 汇总结论 ────────────────────────────────────────────────
    print("=" * 78)
    print("  结论")
    print("=" * 78)
    valid = [(n, b) for n, b in stats if b is not None]
    if b_now is None or not valid:
        print("  ⚠️ 至少一侧找不到托盘，无法比对")
        return 0

    ref_w = np.mean([b["w_frac"] for _, b in valid])
    ref_h = np.mean([b["h_frac"] for _, b in valid])
    ref_area = np.mean([b["area_frac"] for _, b in valid])
    ref_top_cut = any(b["touch_top"] for _, b in valid)

    print("  %-16s %-14s %-14s %s" % ("指标", "训练图(均)", "现场", "差异"))
    print("  " + "-" * 62)
    print("  %-16s %-14s %-14s %s"
          % ("占画面宽",
             "%.1f%%" % (ref_w * 100), "%.1f%%" % (b_now["w_frac"] * 100),
             "%+.1f%%" % ((b_now["w_frac"] - ref_w) * 100)))
    print("  %-16s %-14s %-14s %s"
          % ("占画面高",
             "%.1f%%" % (ref_h * 100), "%.1f%%" % (b_now["h_frac"] * 100),
             "%+.1f%%" % ((b_now["h_frac"] - ref_h) * 100)))
    print("  %-16s %-14s %-14s %s"
          % ("面积占比",
             "%.1f%%" % (ref_area * 100), "%.1f%%" % (b_now["area_frac"] * 100),
             "%+.1f%%" % ((b_now["area_frac"] - ref_area) * 100)))
    print("  %-16s %-14s %-14s" % ("远端是否被切",
                                   "是" if ref_top_cut else "否",
                                   "是" if b_now["touch_top"] else "否"))
    print()

    # 🔴 2026-10-29 判据**已弃用**：本脚本的白块阈值(V>170,S<55)与新验收工具
    #    `cam_verdict.py`(V>100,S<60) 口径不同 —— 同一张训练帧，本脚本量出占高 51%，
    #    而 cam_verdict 量出 100%，两份判据会给出相反结论（"两个真相"）。
    #    ⇒ **唯一权威判据 = `_pi_tools/cam_verdict.py`**；本脚本只保留"看 bbox 数值"的用途。
    print("  ⇒ ⚠️ 本脚本判据已弃用（白块阈值与 cam_verdict.py 不一致）")
    print("     请用唯一权威判据：")
    print("       python _pi_tools/cam_verdict.py <现场帧>.jpg")
    print("     合格区间：托盘占宽 78~87%、占高 ≥90%、网格主方向 |角| ≤5°")
    if b_now["touch_top"] and not ref_top_cut:
        print("  （参考）训练时远端没被切，现在被切了 ⇒ 取景变了")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
