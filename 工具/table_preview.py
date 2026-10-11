#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主机侧：生成「R-D03 逐件累加表格」效果图（PNG），供人眼确认后再上机。

用法（在仓库根目录）：
    set PYTHONPATH=电控\\src
    py -3 工具\\table_preview.py
输出：docs\交付\2026-09-22\表格效果预览.png
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "电控" / "src"))

from PIL import Image  # noqa: E402
from electrical_control.rpi.display_table import compose_table_frame  # noqa: E402

IMG_DIRS = [
    ROOT / "电控" / "deploy" / "cargo_images",
    ROOT / "电控" / "deploy" / "images",
    ROOT / "视觉" / "cargo_images",
]
EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

# 与 runs 里一致的六类（按 names.json）
NAMES = {1: "青色正方体", 2: "绿色正方体", 3: "红色三棱柱",
         4: "蓝色三棱柱", 5: "黑色圆柱", 6: "橙色圆柱"}


def loader(image_id: int) -> Image.Image:
    for d in IMG_DIRS:
        for e in EXTS:
            p = d / f"{image_id}{e}"
            if p.exists():
                return Image.open(p)
    raise FileNotFoundError(f"找不到货物图片 {image_id}（试过 {[str(d) for d in IMG_DIRS]}）")


def main() -> int:
    # 造 7 件（故意超过 max_rows=6 ⇒ 验证"只留最近 6 行"）
    seq_material = [1, 2, 3, 5, 6, 2, 4]
    rows = [(i + 1, NAMES[m], m, i + 1) for i, m in enumerate(seq_material)]

    frame = compose_table_frame(rows, image_loader=loader, max_rows=6)
    out = ROOT / "docs" / "交付" / "2026-09-22" / "表格效果预览.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.save(out)
    print(f"OK 已生成：{out}")
    print(f"   尺寸 {frame.size}；输入 7 行 ⇒ 只显示最近 6 行；最后一行（第 7 件）高亮")
    return 0


if __name__ == "__main__":
    sys.exit(main())
