#!/usr/bin/env python3
"""Analyze training dataset image poses"""
import os
import random
from pathlib import Path
from PIL import Image

# Config
DATASET_ROOT = Path(r"D:\AAAdesktop1\shijue\yolo_dataset")
TRAIN_IMG_DIR = DATASET_ROOT / "images" / "train"
SAMPLE_SIZE = 30

def analyze_images():
    """Analyze images and generate pose assessment report"""

    # Collect all training images
    image_files = list(TRAIN_IMG_DIR.glob("*.jpg")) + list(TRAIN_IMG_DIR.glob("*.png"))

    if not image_files:
        print(f"ERROR: No images found in {TRAIN_IMG_DIR}")
        return

    print(f"Total training images: {len(image_files)}")

    # Random sampling
    sample_files = random.sample(image_files, min(SAMPLE_SIZE, len(image_files)))

    # Create output directory
    output_dir = Path(__file__).parent / "pose_analysis_samples"
    output_dir.mkdir(exist_ok=True)

    print(f"\nAnalyzing {len(sample_files)} sample images...")

    # Analyze each image
    poses = []
    for i, img_path in enumerate(sample_files):
        try:
            img = Image.open(img_path)
            w, h = img.size

            # Save thumbnail for manual inspection
            thumb_path = output_dir / f"sample_{i:02d}_{img_path.name}"
            img.thumbnail((400, 400))
            img.save(thumb_path)

            poses.append({
                'file': img_path.name,
                'size': (w, h),
                'thumb': thumb_path
            })

        except Exception as e:
            print(f"WARNING: Failed to process {img_path.name}: {e}")

    # Generate report
    report_path = output_dir / "pose_analysis_report.txt"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(f"Training Dataset Pose Analysis Report\n")
        f.write(f"=" * 60 + "\n\n")
        f.write(f"Dataset root: {DATASET_ROOT}\n")
        f.write(f"Total training images: {len(image_files)}\n")
        f.write(f"Sample size: {len(poses)}\n\n")
        f.write(f"Sample file list:\n")
        f.write(f"-" * 60 + "\n")

        for i, pose_info in enumerate(poses):
            f.write(f"{i+1:2d}. {pose_info['file']}\n")
            f.write(f"    Size: {pose_info['size'][0]}x{pose_info['size'][1]}\n")
            f.write(f"    Thumbnail: {pose_info['thumb']}\n\n")

        f.write(f"\n" + "=" * 60 + "\n")
        f.write(f"MANUAL INSPECTION REQUIRED:\n")
        f.write(f"Please open {output_dir} and check thumbnails to determine:\n")
        f.write(f"1. Are objects ONLY in 'face-up' poses?\n")
        f.write(f"2. Are there side views, tilted, or randomly placed poses?\n")
        f.write(f"3. Are objects touching or occluding each other?\n")

    print(f"\nAnalysis complete!")
    print(f"Thumbnails saved to: {output_dir}")
    print(f"Report saved to: {report_path}")
    print(f"\nPlease manually inspect thumbnails to assess object pose distribution.")

if __name__ == "__main__":
    analyze_images()
