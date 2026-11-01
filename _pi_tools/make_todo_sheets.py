#!/usr/bin/env python3
"""生成「待判」图像拼版，供 AI 逐批目视判定形状。

每张拼版 2×2 = 4 张原图，每格 640×360（原图 1280×720 的一半），
画 100px 灰色网格 + 200px 黄色坐标标注，便于估框。
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


def tile(fn: str, scale: float = 0.5) -> np.ndarray | None:
    p = IMG / fn
    if not p.is_file():
        return None
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    vis = img.copy()
    for x in range(100, w, 100):
        cv2.line(vis, (x, 0), (x, h), (90, 90, 90), 1)
    for y in range(100, h, 100):
        cv2.line(vis, (0, y), (w, y), (90, 90, 90), 1)
    for x in range(200, w, 200):
        cv2.putText(vis, str(x), (x + 2, 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 255, 255), 1)
    for y in range(200, h, 200):
        cv2.putText(vis, str(y), (3, y - 4), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 255, 255), 1)
    vis = cv2.resize(vis, (int(w * scale), int(h * scale)),
                     interpolation=cv2.INTER_AREA)
    nw = int(w * scale)
    cv2.rectangle(vis, (0, 0), (nw, 24), (0, 0, 0), -1)
    cv2.putText(vis, fn, (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (0, 255, 255), 2)
    return vis


def main(argv: list[str] | None = None) -> int:
    groups_file = SHEETS / "dup_groups.json"
    manual_file = SHEETS / "my_boxes_manual.json"

    if not groups_file.is_file():
        print("❌ 缺 %s" % groups_file)
        return 1
    groups = json.loads(groups_file.read_text(encoding="utf-8"))
    reps = [g[0] for g in groups]

    done = set()
    if manual_file.is_file():
        done = set(json.loads(manual_file.read_text(encoding="utf-8")).keys())
    todo = [r for r in reps if r not in done]

    print("唯一代表 %d，已判 %d，待判 %d" % (len(reps), len(done), len(todo)))
    if not todo:
        print("✅ 全部判完")
        return 0

    n_batch = 0
    for bi in range(0, len(todo), 4):
        batch = todo[bi:bi + 4]
        tiles = [t for t in (tile(f) for f in batch) if t is not None]
        while len(tiles) < 4:
            tiles.append(np.zeros((360, 640, 3), np.uint8))
        sheet = np.vstack([np.hstack(tiles[0:2]), np.hstack(tiles[2:4])])
        p = SHEETS / ("todo_%03d.jpg" % bi)
        ok, buf = cv2.imencode(".jpg", sheet,
                               [int(cv2.IMWRITE_JPEG_QUALITY), 93])
        if ok:
            buf.tofile(str(p))
            print("  %-14s <- %s" % (p.name, ", ".join(batch)))
            n_batch += 1

    print()
    print("已生成 %d 张拼版（每张 4 帧）" % n_batch)
    print("拼版目录: %s" % SHEETS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
