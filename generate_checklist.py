#!/usr/bin/env python3
"""Generate annotation review checklist"""

from pathlib import Path

images_dir = Path("视觉/datasets/preliminary/images")
labels_dir = Path("视觉/datasets/preliminary/labels")

images = {f.stem for f in images_dir.glob("*.jpg")}
labels = {f.stem for f in labels_dir.glob("*.txt")}

annotated = sorted(images & labels)
unannotated = sorted(images - labels)

print(f"总计: {len(images)} 张图片")
print(f"已标注: {len(annotated)} 张 ({len(annotated)/len(images)*100:.1f}%)")
print(f"未标注: {len(unannotated)} 张 ({len(unannotated)/len(images)*100:.1f}%)")
print()

# Save unannotated list
output_file = Path("视觉/datasets/preliminary/unannotated.txt")
with output_file.open("w", encoding="utf-8") as f:
    f.write(f"# 未标注图片清单 ({len(unannotated)}/{ len(images)})\n")
    f.write(f"# 复核时请在 PyCharm 中打开此文件，逐个检查下列图片\n\n")
    for name in unannotated:
        f.write(f"images/{name}.jpg\n")

print(f"未标注清单已保存至: {output_file}")
print()
print("下一步:")
print("1. 在 PyCharm 中安装 YOLO 标注插件（推荐: LabelImg 或 YOLO-Annotator）")
print("2. 打开 视觉/datasets/preliminary/ 文件夹")
print("3. 配置类别文件: class.txt")
print("4. 按照 unannotated.txt 清单逐个标注")
