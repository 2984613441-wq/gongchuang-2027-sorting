#!/usr/bin/env python3
"""准备 labelImg 标注工作区。

## 重要：标「原始 1280×720 帧」，不是裁剪版

比赛时模型跑在 MaixCAM 输出的**完整 1280×720** 帧上，
所以训练数据必须是完整帧（否则训练/推理不一致）。

筛选脚本 v3 产出的 `_clean3/` 是**裁剪到托盘**的版本，
只用于目视检查。本脚本把 `_clean3` 里的**文件名**拿到原始目录取图。

## 产出

```
_label_workspace/
  images/                  ← 待标注的完整帧
  predefined_classes.txt   ← 6 类（顺序必须与 _dataset_yolo_6c/data.yaml 一致）
  打开标注工具.bat          ← 双击启动 labelImg
  标注说明.txt              ← 给操作者的说明
```
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 干净帧目录（裁剪版，只用来拿文件名）
CLEAN_DIR = ROOT / "_new_capture" / "whitetray_1793028347" / "_clean3"
# 原始完整帧目录
ORIG_DIR = ROOT / "_new_capture" / "whitetray_1793028347"
# 输出工作区
WS = ROOT / "_label_workspace"

# 6 类：顺序必须与 _dataset_yolo_6c/data.yaml 完全一致
CLASSES = [
    "cube",              # 0 正方体
    "cuboid",            # 1 长方体
    "cylinder",          # 2 圆柱
    "pentagonal_prism",  # 3 五棱柱
    "cone",              # 4 圆锥
    "tetrahedron",       # 5 正四面体
]

CLASSES_ZH = ["正方体", "长方体", "圆柱", "五棱柱", "圆锥", "正四面体"]

PY = (r"C:\Users\29845\.dsh\dsh-runtimes\dsh-primary-runtime"
      r"\dependencies\python\python.exe")


def main() -> int:
    if not CLEAN_DIR.is_dir():
        print("❌ 干净帧目录不存在: %s" % CLEAN_DIR)
        return 1
    if not ORIG_DIR.is_dir():
        print("❌ 原始帧目录不存在: %s" % ORIG_DIR)
        return 1

    img_dir = WS / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    clean_names = sorted(p.name for p in CLEAN_DIR.glob("*.jpg"))
    print("  干净帧: %d 张" % len(clean_names))

    n_copied = 0
    missing = []
    for name in clean_names:
        src = ORIG_DIR / name
        if not src.is_file():
            missing.append(name)
            continue
        dst = img_dir / name
        if not dst.is_file():
            shutil.copy2(src, dst)
        n_copied += 1

    print("  ✅ 已复制 %d 张完整帧到 %s" % (n_copied, img_dir))
    if missing:
        print("  ⚠️ 原始目录缺 %d 张: %s" % (len(missing), missing[:5]))

    # predefined_classes.txt
    cls_file = WS / "predefined_classes.txt"
    cls_file.write_text("\n".join(CLASSES) + "\n", encoding="utf-8")
    print("  ✅ 已写类别文件: %s" % cls_file)

    # 标注说明
    readme = WS / "标注说明.txt"
    lines = [
        "=" * 66,
        "  labelImg 标注说明",
        "=" * 66,
        "",
        "## 启动",
        "  双击本目录下的「打开标注工具.bat」",
        "",
        "## 关键设置（第一次一定要设，设完会记住）",
        "  左侧工具栏点【PascalVOC】按钮 → 切换到【YOLO】",
        "  ⚠️ 不切成 YOLO 会存成 XML，后面用不了！",
        "",
        "## 类别顺序（必须记住，标错整个数据集就废了）",
    ]
    for i, (en, zh) in enumerate(zip(CLASSES, CLASSES_ZH)):
        lines.append("  %d = %-18s %s" % (i, en, zh))
    lines += [
        "",
        "## 操作",
        "  1. 按 W 开始画框，鼠标拖出物料的矩形框",
        "  2. 弹窗里选类别（或标完后按 0~5 快捷键改）",
        "  3. 按 D 下一张 / 按 A 上一张",
        "  4. 每张标完会自动保存 .txt（YOLO 格式）",
        "",
        "## 快捷键",
        "  W          画框",
        "  Ctrl+S     保存（一般自动保存）",
        "  D / A      下一张 / 上一张",
        "  0~5        把选中的框改成对应类别",
        "  Del        删除选中的框",
        "  Ctrl+Z     撤销",
        "",
        "## 标注要求",
        "  · 每个物料画一个紧贴外轮廓的矩形框（含可见的侧面）",
        "  · 同一种物料在不同位置都要标",
        "  · 被遮挡的也要标（按可见部分画）",
        "  · 画面外的物料不标",
        "",
        "## 两种最容易错的地方",
        "  · 圆柱 vs 圆锥：俯视都是圆。看侧面——",
        "      圆柱：侧壁竖直、顶面是平的椭圆",
        "      圆锥：有尖顶、锥面有明暗渐变",
        "  · 正方体 vs 长方体：看长宽比，接近正方形的算正方体",
        "",
        "=" * 66,
    ]
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("  ✅ 已写说明: %s" % readme)

    # 启动 bat
    # ⚠️ bat 里有 %~dp0，不能用 % 格式化（会报 unsupported format character）。
    #    用占位符替换。
    bat = WS / "打开标注工具.bat"
    bat_lines = [
        "@echo off",
        "chcp 65001 >nul",
        'set "PYTHONIOENCODING=utf-8"',
        'cd /d "%~dp0"',
        "echo 启动 labelImg ...",
        "echo.",
        "echo 类别顺序: 0=cube 1=cuboid 2=cylinder 3=pentagonal_prism "
        "4=cone 5=tetrahedron",
        "echo.",
        "echo 第一次务必: 左侧 PascalVOC 按钮 -^> 切成 YOLO",
        "echo.",
        # ⚠️ 引号内不能有多余空格（`"python.exe "` 会变成无效命令）
        '"@@PY@@" -m labelImg "%~dp0images" "%~dp0predefined_classes.txt" '
        '"%~dp0images"',
        "pause",
    ]
    bat_content = "\r\n".join(bat_lines).replace("@@PY@@", PY) + "\r\n"
    bat.write_text(bat_content, encoding="utf-8")
    print("  ✅ 已写启动脚本: %s" % bat)
    print()
    print("=" * 66)
    print("  完成！现在双击「%s」即可" % bat.name)
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
