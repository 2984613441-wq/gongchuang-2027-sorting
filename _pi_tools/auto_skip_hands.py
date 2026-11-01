#!/usr/bin/env python3
"""自动筛掉「有手 / 摆件进行中」的帧 —— 大幅减少需要人眼判定的帧数。

## 判据（都来自实测）

**手在 HSV 里会被红/黄窗口检出，形成「巨型框」：**
  · 实测有手帧里，框宽常 > 0.35×W 或 框高 > 0.60×H
  · 而真实物件的框：宽 < 0.30×W、高 < 0.45×H（1280×720 上约 380×320）

**再叠一个数量判据：**
  · 真实摆放通常 3~7 个物件
  · 若检出 > 9 个，多半是手 + 噪声

## 输出

`_sheets/auto_skip.json` —— 被自动跳过的帧清单（含原因）
供 `expand_dups.py` / `merge_shapes_to_yolo.py` 直接按 SKIP 处理。

## 用法

```bash
python _pi_tools/auto_skip_hands.py
```
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WS = ROOT / "_label_ws_6c"
SHEETS = WS / "_sheets"

# 巨型框判据（相对图像尺寸）
# 实测：真实物件宽 0.10~0.16W；手被 HSV 当红块检出时 0.20~0.35W
# => 0.19W 能干净分开
MAX_BOX_W_FRAC = 0.19
MAX_BOX_H_FRAC = 0.35
# 数量判据
MAX_OBJECTS = 9


def main(argv: list[str] | None = None) -> int:
    bf = SHEETS / "boxes_all.json"
    if not bf.is_file():
        print("❌ 缺 %s" % bf)
        return 1
    boxes_all = json.loads(bf.read_text(encoding="utf-8"))

    skip: dict[str, str] = {}
    ok: dict[str, int] = {}
    reasons = Counter()

    for fname, info in sorted(boxes_all.items()):
        W, H = info["W"], info["H"]
        boxes = info["boxes"]
        n = len(boxes)
        why = None

        if n == 0:
            why = "empty_tray_or_no_detection"
        elif n > MAX_OBJECTS:
            why = "too_many_objects(%d)" % n
        else:
            for b in boxes:
                if b["w"] > W * MAX_BOX_W_FRAC or b["h"] > H * MAX_BOX_H_FRAC:
                    why = "giant_box(%dx%d)" % (b["w"], b["h"])
                    break

        if why:
            skip[fname] = why
            reasons[why.split("(")[0]] += 1
        else:
            ok[fname] = n

    print("=" * 74)
    print("  自动筛选（有手 / 摆件中 / 空托盘）")
    print("=" * 74)
    print("  总帧数     : %d" % len(boxes_all))
    print("  自动跳过   : %d 帧" % len(skip))
    print("  需要人眼判 : %d 帧" % len(ok))
    print()
    print("  跳过原因分布:")
    for k, v in reasons.most_common():
        print("    %-28s %4d" % (k, v))
    print()
    print("  物件数分布（留下的）:")
    cnt = Counter(ok.values())
    for k in sorted(cnt):
        print("    %d 个物件: %4d 帧" % (k, cnt[k]))

    of = SHEETS / "auto_skip.json"
    of.write_text(json.dumps(skip, ensure_ascii=False, indent=1),
                  encoding="utf-8")
    print()
    print("  ✅ 已写 %s" % of)
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
