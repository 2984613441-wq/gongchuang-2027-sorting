#!/usr/bin/env python3
"""Copy images and labels from capture/ to 视觉/datasets/preliminary/"""

import shutil
from pathlib import Path

# Paths
capture_dir = Path("capture")
images_dir = Path("视觉/datasets/preliminary/images")
labels_dir = Path("视觉/datasets/preliminary/labels")

# Ensure target dirs exist
images_dir.mkdir(parents=True, exist_ok=True)
labels_dir.mkdir(parents=True, exist_ok=True)

# Copy images and labels
img_count = 0
label_count = 0

for session_dir in sorted(capture_dir.glob("session_*")):
    session_name = session_dir.name  # e.g. session_1787757527
    for jpg_file in sorted(session_dir.glob("*.jpg")):
        # Rename: img_00000.jpg -> session_1787757527_img_00000.jpg
        new_name = f"{session_name}_{jpg_file.name}"
        shutil.copy2(jpg_file, images_dir / new_name)
        img_count += 1

        # Copy corresponding label if exists
        txt_file = jpg_file.with_suffix(".txt")
        if txt_file.exists() and txt_file.stat().st_size > 0:
            shutil.copy2(txt_file, labels_dir / new_name.replace(".jpg", ".txt"))
            label_count += 1

print(f"复制完成:")
print(f"  图片: {img_count}")
print(f"  标注: {label_count}")
print(f"  未标注: {img_count - label_count}")
