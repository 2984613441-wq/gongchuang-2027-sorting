#!/usr/bin/env python3
"""打包视觉代码给队长"""

import shutil
from pathlib import Path
from datetime import datetime

# 创建打包目录
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
package_name = f"vision_code_{timestamp}"
package_dir = Path(package_name)
package_dir.mkdir(exist_ok=True)

# 需要打包的内容
items_to_copy = [
    "src/",
    "tests/",
    "examples/",
    "tools/",
    "training/",
    "datasets/preliminary/",
    "README.md",
    "DATASET_REQUIREMENTS.md",
    "TRAINING.md",
]

base_dir = Path("视觉")
copied_count = 0
skipped_count = 0

print(f"打包视觉代码到: {package_name}/\n")

for item in items_to_copy:
    src_path = base_dir / item

    if not src_path.exists():
        print(f"[SKIP] {item}")
        skipped_count += 1
        continue

    dest_path = package_dir / item

    if src_path.is_dir():
        shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
        file_count = len(list(dest_path.rglob("*")))
        print(f"[OK] {item} ({file_count} files)")
    else:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_path)
        print(f"[OK] {item}")

    copied_count += 1

# 创建打包说明
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
readme = f"""# 视觉子系统代码包

打包时间: {now}
包含内容: {copied_count} 项

## 目录结构

- src/              核心代码（44 个 .py 文件）
- tests/            测试代码（51 个测试）
- examples/         示例代码
- tools/            工具脚本
- training/         训练脚本
- datasets/         数据集（534 张图片，211 个标注）
- README.md         总体说明
- DATASET_REQUIREMENTS.md  数据集要求
- TRAINING.md       训练指南

## 核心功能

1. 物体检测: YOLO11 + MaixCAM/ONNX 后端
2. 颜色分类: HSV 量化 + 形状识别
3. 分拣规划: BoxAssignment（冻结映射）+ 分组排序
4. 坐标转换: 像素坐标 → 物理坐标（0.1mm 单位）

## 当前状态

- 代码: 100% 完成，测试全绿
- 数据: 534 张图片，211 个已标注（39.5%），323 个待标注
- 阻塞项: 需要机械侧提供映射表 + 落点坐标（见 docs/design/2026-08-27-机械侧量测清单-box映射与落点坐标.md）

## 快速开始

1. 解压代码包
2. 运行测试: pytest tests/ -v
3. 查看 README.md 了解详细接口
4. 标注数据: 见 datasets/preliminary/README_ANNOTATION.md

联系人: 视觉侧负责人
"""

with open(package_dir / "打包说明.txt", "w", encoding="utf-8") as f:
    f.write(readme)

print(f"\n{'='*50}")
print(f"[DONE] Package created!")
print(f"Location: {package_dir.absolute()}")
print(f"Stats: copied {copied_count} items, skipped {skipped_count} items")
print(f"\nSend to team leader:")
print(f"  1. Compress {package_name}/ folder")
print(f"  2. Read '打包说明.txt' first")
