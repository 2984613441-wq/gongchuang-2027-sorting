#!/usr/bin/env python3
"""把 my_shapes.json（编号→类别）与 boxes_all.json（编号→像素框）合并，
写成 YOLO 标签。同时把 COPY/SKIP/DELETE 一并处理。

## 为什么需要

· `make_numbered_sheets.py` 用 HSV 只做**定位**，产出 `boxes_all.json`（像素框，编号索引）
· 我（AI）看图判定每个编号的**形状**，写进 `my_shapes.json`
· 本脚本把两者合并 → YOLO 标签（class = 形状，与颜色无关）

## my_shapes.json 三种值

```json
{"img_00055.jpg": {"1": 3, "2": 4},      // 编号→class_id
 "img_00023.jpg": "COPY:img_00022.jpg",  // 同布局，复制标签
 "img_00118.jpg": "SKIP"}                // 不标不删
```

## 用法

```bash
python _pi_tools/merge_shapes_to_yolo.py --dry-run
python _pi_tools/merge_shapes_to_yolo.py
```
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WS = ROOT / "_label_ws_6c"
SHEETS = WS / "_sheets"
LBL = WS / "labels"

CLASS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism",
               "cone", "tetrahedron"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    bf = SHEETS / "boxes_all.json"
    full = SHEETS / "my_shapes_full.json"
    sf = full if full.is_file() else SHEETS / "my_shapes.json"
    if not bf.is_file():
        print("❌ 缺 %s" % bf)
        return 1
    if not sf.is_file():
        print("❌ 缺 %s" % sf)
        return 1

    boxes_all = json.loads(bf.read_text(encoding="utf-8"))
    shapes = json.loads(sf.read_text(encoding="utf-8"))

    LBL.mkdir(parents=True, exist_ok=True)

    resolved: dict[str, list] = {}      # fname -> [[cid,cx,cy,nw,nh],...]
    cls_cnt = Counter()
    problems = []
    n_skip = 0

    def build(fname: str) -> list | None:
        info = boxes_all.get(fname)
        if info is None:
            problems.append("%s: 没有检测结果" % fname)
            return None
        W, H = info["W"], info["H"]
        by_id = {str(b["id"]): b for b in info["boxes"]}
        assign = shapes[fname]
        out = []
        for bid, cid in assign.items():
            b = by_id.get(str(bid))
            if b is None:
                problems.append("%s: 没有框 %s" % (fname, bid))
                continue
            if not (0 <= int(cid) < 6):
                problems.append("%s: class_id %s 越界" % (fname, cid))
                continue
            cx = (b["x"] + b["w"] / 2.0) / W
            cy = (b["y"] + b["h"] / 2.0) / H
            nw = b["w"] / float(W)
            nh = b["h"] / float(H)
            out.append((int(cid), cx, cy, nw, nh))
        return out

    def from_label_file(ref: str) -> list | None:
        """从已存在的 .txt 标签文件读回（COPY 的兜底来源）。

        这样即使参考帧是在 my_boxes_manual.json（像素格式）里定义的、
        只要它的 .txt 已生成过，就能被 COPY 引用。
        """
        p = LBL / (Path(ref).stem + ".txt")
        if not p.is_file():
            return None
        out = []
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            parts = ln.split()
            if len(parts) != 5:
                continue
            try:
                out.append((int(float(parts[0])),
                            float(parts[1]), float(parts[2]),
                            float(parts[3]), float(parts[4])))
            except ValueError:
                continue
        return out or None

    for fname in sorted(shapes):
        val = shapes[fname]
        if val == "SKIP":
            n_skip += 1
            continue
        if isinstance(val, str) and val.startswith("COPY:"):
            ref = val[5:]
            if ref in resolved:
                lines = resolved[ref]
            else:
                lines = None
                if isinstance(shapes.get(ref), dict):
                    lines = build(ref)
                if lines is None:
                    lines = from_label_file(ref)
                if lines is None:
                    problems.append("%s: COPY 参考 %s 解析不出" % (fname, ref))
                    continue
                resolved[ref] = lines
            resolved[fname] = lines
        elif isinstance(val, dict):
            lines = build(fname)
            if lines is None:
                continue
            resolved[fname] = lines
        else:
            problems.append("%s: 值类型不支持" % fname)
            continue

        if not resolved[fname]:
            problems.append("%s: 最终无框" % fname)
            continue

        txt = "\n".join("%d %.6f %.6f %.6f %.6f" % t for t in resolved[fname])
        if not args.dry_run:
            (LBL / (Path(fname).stem + ".txt")).write_text(txt + "\n",
                                                           encoding="utf-8")
        for cid, *_ in resolved[fname]:
            cls_cnt[cid] += 1

    print("=" * 74)
    print("  合并编号→YOLO 标签%s" % ("（DRY-RUN）" if args.dry_run else ""))
    print("=" * 74)
    print("  判定条目 : %d" % len(shapes))
    print("  写出标签 : %d 帧" % len(resolved))
    print("  跳过     : %d 帧" % n_skip)
    print()
    print("  各类实例数:")
    tot = 0
    for cid, nm in enumerate(CLASS_NAMES):
        n = cls_cnt.get(cid, 0)
        tot += n
        print("    %d %-18s %4d" % (cid, nm, n))
    print("    %-20s %4d" % ("合计", tot))
    print()
    if problems:
        print("  ⚠️ 问题（前 10）:")
        for p in problems[:10]:
            print("    %s" % p)
        print()
    allf = {p.name for p in (WS / "images").glob("img_*.jpg")}
    left = sorted(allf - set(shapes))
    print("  进度: %d / %d 已判，剩 %d 帧" % (len(set(shapes) & allf),
                                             len(allf), len(left)))
    print("  标签目录: %s" % LBL)
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
