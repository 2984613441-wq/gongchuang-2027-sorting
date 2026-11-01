#!/usr/bin/env python3
"""生成「带大号编号框」的 2×2 拼版 —— 供 AI 逐批目视判定每个编号的形状。

## 分工（关键）

· **坐标**：HSV 在托盘 ROI 内定位色块，像素级精确 —— 只用来"找块在哪"
· **形状 class**：AI 看图判定编号对应什么形状 —— 这才是 YOLO 标签内容

## 为什么拼 2×2 半尺寸

全尺寸逐帧看要 112 回合；半尺寸 2×2 一回合看 4 帧。
数字放大到能读清，配合"框的位置关系"足以判定形状（形状不需要精确坐标）。

## 输出

```
_label_ws_6c/_sheets/num_XXX.jpg    ← 2×2 拼版，每格带编号框
_label_ws_6c/_sheets/num_boxes.json ← 每帧的框像素坐标（供写标签用）
```
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
WS = ROOT / "_label_ws_6c"
SHEETS = WS / "_sheets"
IMG = WS / "images"

# 托盘内层（measure_tray_bbox 实测）：只在这里找块，避开木桌/线缆/水瓶
TX1, TY1, TX2, TY2 = 385, 34, 1005, 685

# 分色窗口（放宽饱和，收紧亮度）
HSV = {
    "red":    [((160, 70, 40), (179, 255, 255)), ((0, 70, 40), (12, 255, 255))],
    "yellow": [((16, 80, 50), (32, 255, 255))],
    "green":  [((52, 70, 35), (92, 255, 255))],
    "blue":   [((95, 80, 35), (132, 255, 255))],
}
ORDER = ["red", "yellow", "green", "blue"]
DRAW = {"red": (0, 0, 255), "yellow": (0, 215, 255),
        "green": (0, 220, 0), "blue": (255, 120, 0)}


def detect(img: np.ndarray) -> list[dict]:
    h, w = img.shape[:2]
    roi_area = (TX2 - TX1) * (TY2 - TY1)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    res = []
    for color, ranges in HSV.items():
        m = None
        for lo, hi in ranges:
            mm = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
            m = mm if m is None else cv2.bitwise_or(m, mm)
        # 只在托盘 ROI 内
        m[:TY1, :] = 0
        m[TY2:, :] = 0
        m[:, :TX1] = 0
        m[:, TX2:] = 0
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k, 3)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k, 2)
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cs:
            a = cv2.contourArea(c)
            if a < roi_area * 0.006 or a > roi_area * 0.30:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            if bw < 40 or bh < 40:
                continue
            res.append({"color": color, "x": int(x), "y": int(y),
                        "w": int(bw), "h": int(bh)})
    res.sort(key=lambda r: (ORDER.index(r["color"]), r["y"], r["x"]))
    for i, r in enumerate(res, 1):
        r["id"] = i
    return res


def tile(fn: str, boxes: list[dict], scale: float = 0.5) -> np.ndarray | None:
    p = IMG / fn
    if not p.is_file():
        return None
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    vis = img.copy()
    # 托盘边界（青色）
    cv2.rectangle(vis, (TX1, TY1), (TX2, TY2), (255, 255, 0), 2)
    for b in boxes:
        col = DRAW[b["color"]]
        cv2.rectangle(vis, (b["x"], b["y"]),
                      (b["x"] + b["w"], b["y"] + b["h"]), col, 4)
        # 大号编号：白底黑字 + 黑边，任何背景都能读
        txt = str(b["id"])
        ox, oy = b["x"] + 6, b["y"] + 46
        cv2.putText(vis, txt, (ox, oy), cv2.FONT_HERSHEY_SIMPLEX, 1.6,
                    (0, 0, 0), 7)
        cv2.putText(vis, txt, (ox, oy), cv2.FONT_HERSHEY_SIMPLEX, 1.6,
                    (255, 255, 255), 3)
    vis = cv2.resize(vis, (int(w * scale), int(h * scale)),
                     interpolation=cv2.INTER_AREA)
    nw = int(w * scale)
    cv2.rectangle(vis, (0, 0), (nw, 26), (0, 0, 0), -1)
    cv2.putText(vis, "%s  n=%d" % (fn, len(boxes)), (5, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
    return vis


def main(argv: list[str] | None = None) -> int:
    groups_file = SHEETS / "dup_groups.json"
    if not groups_file.is_file():
        print("❌ 缺 %s" % groups_file)
        return 1
    groups = json.loads(groups_file.read_text(encoding="utf-8"))
    reps = [g[0] for g in groups]

    done_file = SHEETS / "my_shapes.json"
    done = set()
    if done_file.is_file():
        done = set(json.loads(done_file.read_text(encoding="utf-8")).keys())
    # 自动筛掉的帧不需要再看
    auto_file = SHEETS / "auto_skip.json"
    if auto_file.is_file():
        auto = set(json.loads(auto_file.read_text(encoding="utf-8")).keys())
        print("  auto_skip 跳过 %d 帧" % len(auto - done))
        done |= auto
    todo = [r for r in reps if r not in done]

    print("代表 %d，已判/已跳过 %d，待判 %d" % (len(reps), len(done), len(todo)))

    all_boxes: dict[str, dict] = {}
    # 兼容旧文件名
    old_boxes = SHEETS / "boxes_all.json"
    if old_boxes.is_file():
        try:
            all_boxes.update(json.loads(old_boxes.read_text(encoding="utf-8")))
        except Exception:
            pass

    n_sheet = 0
    for bi in range(0, len(todo), 4):
        batch = todo[bi:bi + 4]
        tiles = []
        for fn in batch:
            p = IMG / fn
            img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                               cv2.IMREAD_COLOR)
            if img is None:
                continue
            bs = detect(img)
            all_boxes[fn] = {"W": img.shape[1], "H": img.shape[0],
                             "boxes": bs}
            t = tile(fn, bs)
            if t is not None:
                tiles.append(t)
        while len(tiles) < 4:
            tiles.append(np.zeros((360, 640, 3), np.uint8))
        sheet = np.vstack([np.hstack(tiles[0:2]), np.hstack(tiles[2:4])])
        p = SHEETS / ("num_%03d.jpg" % bi)
        ok, buf = cv2.imencode(".jpg", sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 93])
        if ok:
            buf.tofile(str(p))
            print("  %-14s <- %s" % (p.name, ", ".join(batch)))
            n_sheet += 1

    (SHEETS / "boxes_all.json").write_text(
        json.dumps(all_boxes, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print("已生成 %d 张拼版，%d 帧的框坐标已存 boxes_all.json"
          % (n_sheet, len(all_boxes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
