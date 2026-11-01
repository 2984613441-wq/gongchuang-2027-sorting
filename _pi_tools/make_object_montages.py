#!/usr/bin/env python3
"""把每个检出物件裁出来拼成大网格 —— 让人工判形效率提升 10 倍。

## 为什么这么做

522 帧里 337 帧有真物件，共 552 个。但其中 **192 帧只有 1 个物件**，
为了判一个形状去看整幅 1280×720 图太浪费。

改成：每个物件裁成 130×130 小图，48 个拼一张 8×6 网格 ⇒ 552 个只要 12 张。

## 与整幅拼版的配合

整幅拼版（`make_tilt30_sheets.py`）用于**核对框位置是否准确**；
本脚本生成的裁片网格用于**快速判形状**。两者结合：
  1. 先看裁片网格判形状（快）
  2. 抽几张整幅图核对框位置

## 输出

    _new_capture_tilt30/_crops/montage_XXX.jpg   8×6 裁片网格
    _new_capture_tilt30/_crops/index.json        每个格子的 (帧名, 框id, 颜色, 像素框)

## 用法

    python _pi_tools/make_object_montages.py
    python _pi_tools/make_object_montages.py --cell 130 --cols 8 --rows 6
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent

# ⚠️ 2026-10-28：原来硬编码 BASE = _new_capture_tilt30，
#   导致新一批数据（_new_capture_20261028）无法独立处理。
#   现在由 --base 参数覆盖；默认仍是昨晚那批，保持向后兼容。
BASE = ROOT / "_new_capture_tilt30"
ALL_DIR = BASE / "all"
SHEETS = BASE / "_sheets"
OUT = BASE / "_crops"


def _set_base(p: Path) -> None:
    """切换数据根目录（同时更新派生的三个路径）。"""
    global BASE, ALL_DIR, SHEETS, OUT
    BASE = p
    ALL_DIR = BASE / "all"
    SHEETS = BASE / "_sheets"
    OUT = BASE / "_crops"

PAD_FRAC = 0.08          # 裁片四周留白比例
CELL = 130               # 每格边长（像素）

# 🔴 手/背景过滤：靠「鲜艳度占比」
#
# 2026-10-27 实测：montage_004 里约 **50% 的裁片是手**。
#   · 手：淡粉/白，饱和度低（S 通常 30~100），V 高
#   · 物件：高饱和彩色塑料（S 通常 >120）
#   ⇒ 统计框内「S>VIVID_S 且 V>60」的像素占比，
#     低于 MIN_VIVID_FRAC 的判为手/背景，直接丢弃，不进网格。
VIVID_S = 115            # 饱和度下限
VIVID_V = 55             # 亮度下限（排除暗部噪声）
MIN_VIVID_FRAC = 0.45    # 框内鲜艳像素占比低于此值 ⇒ 丢弃

# 🔴 窄条过滤（滤掉电线/木桌边）
#
# 2026-10-27 实测对比（montage_002 里 17 个假框 vs 13 个真件）：
#   假框（黄色/棕色电线竖条）: 宽高比 0.22~0.60（中位 0.44），宽 44~95
#   真件                     : 宽高比 0.91~2.60（中位 1.36），宽 102~174
#   ⇒ 完全可分，无重叠。取 0.70 作阈值。
MIN_ASPECT = 0.70        # w/h 低于此值 ⇒ 判为电线/边缘，丢弃


def vivid_frac(crop: np.ndarray) -> float:
    """框内「鲜艳彩色」像素占比。手/白托盘/背景都很低。"""
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    vivid = (s > VIVID_S) & (v > VIVID_V)
    return float(vivid.mean())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", type=int, default=CELL)
    ap.add_argument("--cols", type=int, default=8)
    ap.add_argument("--rows", type=int, default=6)
    ap.add_argument("--base", default=None,
                    help="数据根目录（相对仓库根或绝对路径）；默认 _new_capture_tilt30")
    args = ap.parse_args(argv)

    if args.base:
        p = Path(args.base)
        _set_base(p if p.is_absolute() else ROOT / p)
        print("数据根目录: %s" % BASE)

    bf = SHEETS / "boxes_all.json"
    if not bf.is_file():
        print("❌ 缺 %s（先跑 make_tilt30_sheets.py）" % bf)
        return 1
    boxes_all = json.loads(bf.read_text(encoding="utf-8"))

    items = []          # (frame_name, box, crop_img)
    n_hand = 0
    n_strip = 0
    for fname in sorted(boxes_all):
        info = boxes_all[fname]
        img = cv2.imdecode(np.fromfile(str(ALL_DIR / fname), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            continue
        H, W = img.shape[:2]
        for b in info["boxes"]:
            x, y, w, h = b["x"], b["y"], b["w"], b["h"]
            # ── 窄条过滤（电线/木桌边）──
            if h > 0 and (w / h) < MIN_ASPECT:
                n_strip += 1
                continue
            px = int(w * PAD_FRAC)
            py = int(h * PAD_FRAC)
            x1 = max(0, x - px); y1 = max(0, y - py)
            x2 = min(W, x + w + px); y2 = min(H, y + h + py)
            if x2 - x1 < 12 or y2 - y1 < 12:
                continue
            crop = img[y1:y2, x1:x2]
            # ── 手/背景过滤 ──
            vf = vivid_frac(crop)
            if vf < MIN_VIVID_FRAC:
                n_hand += 1
                continue
            b = dict(b)
            b["vivid"] = round(vf, 3)
            items.append((fname, b, crop))

    print("=" * 74)
    print("  生成物件裁片网格")
    print("=" * 74)
    print("  帧数 %d   候选框 %d" % (len({i[0] for i in items}), len(items)))
    print("  🔴 鲜艳度过滤丢弃（手/背景）: %d 个（阈值 %.2f）"
          % (n_hand, MIN_VIVID_FRAC))
    print("  🔴 窄条过滤丢弃（电线/边缘）: %d 个（宽高比 < %.2f）"
          % (n_strip, MIN_ASPECT))
    print("  ✅ 保留物件: %d 个" % len(items))
    print("  网格 %d×%d = %d 个/张  每格 %dpx"
          % (args.cols, args.rows, args.cols * args.rows, args.cell))
    print()

    if not items:
        print("❌ 没有裁片")
        return 1

    if OUT.is_dir():
        import shutil
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    per_sheet = args.cols * args.rows
    index = []
    n_sheet = 0
    for si in range(0, len(items), per_sheet):
        batch = items[si:si + per_sheet]
        cell = args.cell
        grid = np.full((args.rows * cell, args.cols * cell, 3), 32, np.uint8)
        for k, (fname, b, crop) in enumerate(batch):
            r, c = divmod(k, args.cols)
            # 等比缩放进 cell，保持不拉伸
            ch, cw = crop.shape[:2]
            scale = min((cell - 4) / cw, (cell - 4) / ch)
            nw, nh = max(1, int(cw * scale)), max(1, int(ch * scale))
            rs = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
            yo = r * cell + (cell - nh) // 2
            xo = c * cell + (cell - nw) // 2
            grid[yo:yo + nh, xo:xo + nw] = rs
            # 格子编号（大号，便于我读）
            gid = si + k
            tag = "%02d" % gid if gid < 100 else str(gid)
            cv2.putText(grid, tag, (c * cell + 3, r * cell + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
            cv2.putText(grid, tag, (c * cell + 3, r * cell + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            # 颜色小标记
            cv2.circle(grid, (c * cell + cell - 14, r * cell + 14), 7,
                       {"red": (0, 0, 255), "yellow": (0, 200, 255),
                        "green": (0, 220, 0), "blue": (255, 120, 0),
                        }.get(b["color"], (200, 200, 200)), -1)
            cv2.rectangle(grid, (c * cell, r * cell),
                          (c * cell + cell - 1, r * cell + cell - 1),
                          (70, 70, 70), 1)
            index.append({
                "gid": gid,
                "sheet": si // per_sheet,
                "row": r, "col": c,
                "frame": fname,
                "box_id": b["id"],
                "color": b["color"],
                "x": b["x"], "y": b["y"], "w": b["w"], "h": b["h"],
                "area_pct": b.get("area_pct"),
            })
        p = OUT / ("montage_%03d.jpg" % (si // per_sheet))
        ok, buf = cv2.imencode(".jpg", grid,
                               [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        if ok:
            buf.tofile(str(p))
            print("  %-18s 物件 %d~%d" % (p.name, si, si + len(batch) - 1))
            n_sheet += 1

    (OUT / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")

    print()
    print("=" * 74)
    print("  ✅ 生成 %d 张裁片网格，%d 个物件" % (n_sheet, len(items)))
    print("     目录: %s" % OUT)
    print("     索引: %s" % (OUT / "index.json"))
    print()
    print("  ⇒ 我逐张看网格判形状（每个裁片只判 6 类之一）")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
