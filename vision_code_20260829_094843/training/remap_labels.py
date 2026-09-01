#!/usr/bin/env python3
"""把 LabelImg 标的类别编号，重映射回正确的 0-6 顺序。

背景：用户的 LabelImg 精简版没读到 classes.txt，类别编号按"第一次输入
类别名的顺序"定的。真实下拉顺序（从上到下）为：
    六棱柱, 三棱柱, 五棱柱, 圆柱, 四棱锥, 长方体, cube
对应旧编号 0..6。而模型要求的正确顺序是：
    0=cube, 1=cuboid, 2=cylinder, 3=hexagonal_prism,
    4=pentagonal_prism, 5=square_pyramid, 6=triangular_prism
所以需要把旧编号按 REMAP 重映射。

同时把"没用到的空照片"（.txt 为 0 字节）连同图片移到 _unused/ 子目录，
避免它们混进训练集。可回退：文件只是移动，没删除。
"""

from __future__ import annotations

from pathlib import Path

# 旧 LabelImg 编号 -> 正确编号
REMAP = {0: 3, 1: 6, 2: 4, 3: 2, 4: 5, 5: 1, 6: 0}

# 正确的类别名（顺序 0-6），用于验证时打印
CLASSES = (
    "cube", "cuboid", "cylinder", "hexagonal_prism",
    "pentagonal_prism", "square_pyramid", "triangular_prism",
)


def main() -> int:
    base = Path(r"C:\Users\29845\Desktop\工创赛\workspace_label")
    unused = base / "_unused"
    unused.mkdir(exist_ok=True)

    n_remapped = 0
    n_moved = 0

    for txt in sorted(base.glob("img_*.txt")):
        jpg = txt.with_suffix(".jpg")
        if txt.stat().st_size == 0:
            # 空标签 -> 没用到的照片，移走（图片一起移）
            txt.rename(unused / txt.name)
            if jpg.exists():
                jpg.rename(unused / jpg.name)
            n_moved += 1
            continue

        lines = txt.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines:
            parts = line.split()
            if not parts:
                continue
            old = int(parts[0])
            new = REMAP.get(old, old)
            out.append(" ".join([str(new)] + parts[1:]))
        txt.write_text("\n".join(out) + "\n", encoding="utf-8")
        n_remapped += 1

    # 验证：统计重映射后的各类别框数
    counts = {i: 0 for i in range(7)}
    total_boxes = 0
    for txt in sorted(base.glob("img_*.txt")):
        for line in txt.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if not parts:
                continue
            counts[int(parts[0])] += 1
            total_boxes += 1

    print(f"remapped  : {n_remapped} 个标签文件")
    print(f"moved     : {n_moved} 张空照片 -> {unused.name}/")
    print(f"total box : {total_boxes}")
    print("--- 重映射后各类别框数 ---")
    for i in range(7):
        print(f"  {i} {CLASSES[i]:<18} {counts[i]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
