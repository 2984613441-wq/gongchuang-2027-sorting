# -*- coding: utf-8 -*-
"""把 7 类数据集重映射成 5 类（对齐省赛表1）。

## 为什么

省赛表1（`docs/references/赛题原文-提取文本/2026补充说明-原文.txt` L28~38）
只有 **6 种货物名称**：

    正方体、长方体、圆柱、五棱柱、圆锥、正四面体

而现有 `_dataset_yolo` 是 **7 类**，其中两个是表1 **没有**的：

| 旧 id | 旧类名 | 表1 | 处理 |
|---|---|---|---|
| 0 | cube | ✅ | → 0 cube |
| 1 | cuboid | ✅ | → 1 cuboid |
| 2 | cylinder | ✅ | → 2 cylinder |
| **3** | **hexagonal_prism 六棱柱** | ❌ | **丢弃** |
| 4 | pentagonal_prism | ✅ | → 3 pentagonal_prism |
| **5** | **triangular_prism 三棱柱** | ❌ | **丢弃** |
| 6 | square_pyramid | ✅ **= 正四面体** | → 4 tetrahedron |

## 圆锥（cone）

表1 有，但**我们零数据**。用户 2026-10-25 裁决：**圆锥后面再说**，
本次只出 5 类模型。等采到圆锥数据后，把 CONE 接到 id5 重训即可。

## 用法

    python _pi_tools/remap_to_5class.py            # 干跑，只统计不写
    python _pi_tools/remap_to_5class.py --apply    # 真写

输出目录：`_dataset_yolo_5c/`（与原目录并列，不动原数据）

## 安全

· **只读原数据集**，绝不修改 `_dataset_yolo` 里的任何文件
· 输出到新目录，失败也不影响原数据
· 每张图对应一个 .txt，丢弃的框直接不写（不写空文件会让该图变成"负样本"，
  所以**图也一起跳过**——避免"图里有物体但标签为空"污染训练）
"""
from __future__ import annotations

import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "_dataset_yolo"
DST = ROOT / "_dataset_yolo_5c"

# 旧 id -> 新 id；不在表里的 = 丢弃
REMAP = {
    0: 0,   # cube            正方体
    1: 1,   # cuboid          长方体
    2: 2,   # cylinder        圆柱
    4: 3,   # pentagonal_prism 五棱柱
    6: 4,   # square_pyramid -> tetrahedron 正四面体
}
DROP = {3, 5}   # hexagonal_prism 六棱柱 / triangular_prism 三棱柱（表1 没有）

NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism", "tetrahedron"]
ZH = {
    "cube": "正方体", "cuboid": "长方体", "cylinder": "圆柱",
    "pentagonal_prism": "五棱柱", "tetrahedron": "正四面体",
    "cone": "圆锥",     # 预留，暂无数据
}

APPLY = "--apply" in sys.argv


def main() -> int:
    if not SRC.exists():
        print("❌ 源数据集不存在: %s" % SRC)
        return 1

    print("=" * 74)
    print("7 类 → 5 类 重映射")
    print("  源: %s" % SRC)
    print("  目标: %s" % DST)
    print("  模式: %s" % ("** 真写 **" if APPLY else "干跑（不写文件）"))
    print("=" * 74)

    stats = {s: {"imgs": 0, "kept_txt": 0, "skip_img": 0,
                 "boxes_in": 0, "boxes_out": 0, "dropped": 0}
             for s in ("train", "val")}
    new_cnt = Counter()
    old_cnt = Counter()

    for split in ("train", "val"):
        img_dir = SRC / "images" / split
        lbl_dir = SRC / "labels" / split
        if not img_dir.exists():
            print("  ⚠️ 缺目录: %s" % img_dir)
            continue

        out_img = DST / "images" / split
        out_lbl = DST / "labels" / split
        if APPLY:
            out_img.mkdir(parents=True, exist_ok=True)
            out_lbl.mkdir(parents=True, exist_ok=True)

        for img in sorted(img_dir.iterdir()):
            if not img.is_file():
                continue
            stats[split]["imgs"] += 1
            lbl = lbl_dir / (img.stem + ".txt")
            if not lbl.exists():
                stats[split]["skip_img"] += 1
                continue

            out_lines = []
            for line in lbl.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                old_id = int(parts[0])
                old_cnt[old_id] += 1
                stats[split]["boxes_in"] += 1
                if old_id in DROP:
                    stats[split]["dropped"] += 1
                    continue
                if old_id not in REMAP:
                    stats[split]["dropped"] += 1
                    continue
                new_id = REMAP[old_id]
                out_lines.append(" ".join([str(new_id)] + parts[1:]))
                new_cnt[new_id] += 1
                stats[split]["boxes_out"] += 1

            # 全部框都被丢掉 ⇒ 这张图等于没有目标。不复制，
            # 否则会变成「图里有物体但标签空」的负样本，污染训练。
            if not out_lines:
                stats[split]["skip_img"] += 1
                continue

            stats[split]["kept_txt"] += 1
            if APPLY:
                shutil.copy2(img, out_img / img.name)
                (out_lbl / (img.stem + ".txt")).write_text(
                    "\n".join(out_lines) + "\n", encoding="utf-8")

    # ── 报告 ────────────────────────────────────────────────────────────
    print("\n=== 旧类分布 ===")
    OLD_NAMES = ["cube", "cuboid", "cylinder", "hexagonal_prism",
                 "pentagonal_prism", "triangular_prism", "square_pyramid"]
    for i, n in enumerate(OLD_NAMES):
        c = old_cnt.get(i, 0)
        mark = "❌ 丢弃" if i in DROP else "✅ → id%d" % REMAP[i]
        print("  id%-2d %-18s %5d 框   %s" % (i, n, c, mark))

    print("\n=== 新类分布（5 类）===")
    for i, n in enumerate(NAMES):
        print("  id%-2d %-18s %s   %5d 框" % (i, n, ZH[n], new_cnt.get(i, 0)))
    print("  ---- cone 圆锥            暂缺               0 框（后面再补）")

    print("\n=== 图片统计 ===")
    for split in ("train", "val"):
        s = stats[split]
        print("  %-5s 原图 %4d  保留 %4d  跳过 %3d（无标签/框被全丢）"
              % (split, s["imgs"], s["kept_txt"], s["skip_img"]))
        print("        框: 进 %5d  出 %5d  丢 %4d"
              % (s["boxes_in"], s["boxes_out"], s["dropped"]))

    if APPLY:
        yaml = DST / "data.yaml"
        lines = [
            "# 5 类 YOLO 数据集（对齐省赛表1；圆锥暂缺，后面补）",
            "# 由 _pi_tools/remap_to_5class.py 从 _dataset_yolo（7类）生成",
            "# 丢弃: hexagonal_prism(六棱柱) / triangular_prism(三棱柱) —— 表1 无",
            "path: %s" % DST.as_posix(),
            "train: images/train",
            "val: images/val",
            "",
            "nc: 5",
            "names:",
        ]
        for i, n in enumerate(NAMES):
            lines.append("  %d: %s" % (i, n))
        lines.append("")
        yaml.write_text("\n".join(lines), encoding="utf-8")
        print("\n✅ 已写入: %s" % yaml)
        print("✅ 数据集: %s" % DST)
    else:
        print("\n（干跑结束。加 --apply 才真正写文件）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
