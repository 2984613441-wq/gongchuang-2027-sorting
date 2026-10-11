#!/usr/bin/env python3
"""
数据集归并、去重、划分脚本
用于整合多个数据源，生成训练/验证/测试集
"""
import hashlib
import shutil
from pathlib import Path
from collections import defaultdict
import random
import json
import yaml
from typing import Dict, List, Tuple, Set

# 配置
DATA_SOURCES = [
    Path(r"D:\AAAdesktop1\shijue\yolo_dataset"),
    Path(r"C:\Users\29845\Desktop\工创赛\视觉\datasets\preliminary"),
    Path(r"C:\Users\29845\Desktop\工创赛\workspace_label"),
]

OUTPUT_ROOT = Path(r"D:\AAAdesktop1\shijue\merged_dataset_v1")
SEED = 42
TRAIN_RATIO = 0.70
VAL_RATIO = 0.15
TEST_RATIO = 0.15

CLASS_NAMES = [
    "cube", "cuboid", "cylinder", "hexagonal_prism",
    "pentagonal_prism", "square_pyramid", "triangular_prism"
]

def compute_hash(image_path: Path) -> str:
    """计算图片的 SHA256 哈希"""
    sha256 = hashlib.sha256()
    with open(image_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()

def find_label(image_path: Path) -> Path:
    """查找对应的标注文件"""
    label_path = image_path.parent.parent / "labels" / image_path.parent.name / f"{image_path.stem}.txt"
    if label_path.exists():
        return label_path

    # 备选：labels 在同级目录
    label_path = image_path.parent.parent / "labels" / f"{image_path.stem}.txt"
    if label_path.exists():
        return label_path

    return None

def validate_label(label_path: Path) -> Tuple[bool, str]:
    """验证标注文件格式"""
    try:
        with open(label_path, 'r') as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            parts = line.strip().split()
            if len(parts) != 5:
                return False, f"Line {i+1}: expected 5 fields, got {len(parts)}"

            class_id = int(parts[0])
            if not (0 <= class_id <= 6):
                return False, f"Line {i+1}: class_id {class_id} out of range [0, 6]"

            for j, coord in enumerate(parts[1:]):
                val = float(coord)
                if not (0.0 <= val <= 1.0):
                    return False, f"Line {i+1}: coordinate {j} = {val} out of range [0, 1]"

        return True, "OK"

    except Exception as e:
        return False, str(e)

def detect_adjacent_frames(image_files: List[Path]) -> List[Tuple[Path, Path]]:
    """检测相邻帧（可能的数据泄漏）"""
    # 提取文件名中的序号
    def extract_number(path: Path) -> int:
        import re
        match = re.search(r'_(\d+)\.(jpg|jpeg|png)$', path.name.lower())
        if match:
            return int(match.group(1))
        return -1

    adjacent_pairs = []
    sorted_files = sorted(image_files, key=lambda p: (p.parent, extract_number(p)))

    for i in range(len(sorted_files) - 1):
        curr = sorted_files[i]
        next_file = sorted_files[i + 1]

        if curr.parent != next_file.parent:
            continue

        curr_num = extract_number(curr)
        next_num = extract_number(next_file)

        if curr_num > 0 and next_num > 0 and abs(next_num - curr_num) == 1:
            adjacent_pairs.append((curr, next_file))

    return adjacent_pairs

def collect_and_deduplicate() -> Dict[str, Tuple[Path, Path]]:
    """收集所有图片并去重"""
    print("Collecting images from all sources...")

    hash_to_files = defaultdict(list)

    for source_root in DATA_SOURCES:
        if not source_root.exists():
            print(f"WARNING: Source not found: {source_root}")
            continue

        # 查找所有图片
        for ext in ['*.jpg', '*.jpeg', '*.png', '*.JPG', '*.JPEG', '*.PNG']:
            for img_path in source_root.rglob(ext):
                # 跳过特定目录
                if any(skip in img_path.parts for skip in ['_unused', '_review', 'archive']):
                    continue

                img_hash = compute_hash(img_path)
                hash_to_files[img_hash].append(img_path)

    print(f"Total unique images: {len(hash_to_files)}")

    # 去重：优先保留有标注的版本
    unique_files = {}
    duplicates = []

    for img_hash, files in hash_to_files.items():
        if len(files) > 1:
            duplicates.append(files)

        # 优先选择有标注的文件
        best_file = None
        for f in files:
            label = find_label(f)
            if label and label.exists():
                best_file = f
                break

        if not best_file:
            best_file = files[0]

        label = find_label(best_file)
        unique_files[img_hash] = (best_file, label)

    print(f"Duplicates found: {len(duplicates)} groups")
    print(f"Final unique images: {len(unique_files)}")

    return unique_files

def stratified_split(files_by_class: Dict[int, List[str]],
                     train_ratio: float, val_ratio: float, test_ratio: float,
                     seed: int) -> Dict[str, List[str]]:
    """按类别分层抽样"""
    random.seed(seed)

    train_files = []
    val_files = []
    test_files = []

    for class_id, files in files_by_class.items():
        random.shuffle(files)
        n = len(files)

        n_train = int(n * train_ratio)
        n_val = int(n * val_ratio)

        train_files.extend(files[:n_train])
        val_files.extend(files[n_train:n_train+n_val])
        test_files.extend(files[n_train+n_val:])

    return {
        'train': train_files,
        'val': val_files,
        'test': test_files
    }

def main():
    """主流程"""
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    review_dir = OUTPUT_ROOT / "_review"
    review_dir.mkdir(exist_ok=True)

    # 1. 收集并去重
    unique_files = collect_and_deduplicate()

    # 2. 验证标注
    print("\nValidating labels...")
    valid_files = {}
    invalid_files = []

    for img_hash, (img_path, label_path) in unique_files.items():
        if label_path is None or not label_path.exists():
            print(f"WARNING: No label for {img_path.name}")
            invalid_files.append((img_path, "No label"))
            continue

        is_valid, msg = validate_label(label_path)
        if not is_valid:
            print(f"ERROR: {img_path.name}: {msg}")
            invalid_files.append((img_path, msg))
            continue

        valid_files[img_hash] = (img_path, label_path)

    print(f"Valid images: {len(valid_files)}")
    print(f"Invalid images: {len(invalid_files)}")

    # 3. 检查数据泄漏
    print("\nChecking for data leakage (adjacent frames)...")
    all_images = [img for img, _ in valid_files.values()]
    adjacent_pairs = detect_adjacent_frames(all_images)

    if adjacent_pairs:
        print(f"WARNING: Found {len(adjacent_pairs)} adjacent frame pairs")
        with open(OUTPUT_ROOT / "adjacent_frames.txt", 'w') as f:
            for pair in adjacent_pairs:
                f.write(f"{pair[0].name} <-> {pair[1].name}\n")

    # 4. 按类别统计
    files_by_class = defaultdict(list)
    for img_hash, (img_path, label_path) in valid_files.items():
        with open(label_path, 'r') as f:
            for line in f:
                class_id = int(line.split()[0])
                files_by_class[class_id].append(img_hash)
                break  # 只取第一个目标的类别作为该图片的主类别

    print("\nClass distribution:")
    for class_id, files in sorted(files_by_class.items()):
        print(f"  {class_id} ({CLASS_NAMES[class_id]}): {len(files)} images")

    # 5. 分层划分
    print("\nSplitting dataset...")
    splits = stratified_split(files_by_class, TRAIN_RATIO, VAL_RATIO, TEST_RATIO, SEED)

    # 6. 复制文件到输出目录
    print("\nCopying files...")
    for split_name, hashes in splits.items():
        img_dir = OUTPUT_ROOT / "images" / split_name
        label_dir = OUTPUT_ROOT / "labels" / split_name
        img_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)

        for img_hash in hashes:
            img_path, label_path = valid_files[img_hash]

            # 复制图片
            dst_img = img_dir / img_path.name
            shutil.copy2(img_path, dst_img)

            # 复制标注
            dst_label = label_dir / f"{img_path.stem}.txt"
            shutil.copy2(label_path, dst_label)

        print(f"  {split_name}: {len(hashes)} images")

    # 7. 生成 data.yaml
    data_yaml = {
        'path': str(OUTPUT_ROOT),
        'train': 'images/train',
        'val': 'images/val',
        'test': 'images/test',
        'nc': 7,
        'names': CLASS_NAMES
    }

    with open(OUTPUT_ROOT / "data.yaml", 'w') as f:
        yaml.dump(data_yaml, f)

    # 8. 生成 manifest.json
    manifest = {
        'total_images': len(unique_files),
        'valid_images': len(valid_files),
        'invalid_images': len(invalid_files),
        'adjacent_pairs': len(adjacent_pairs),
        'splits': {k: len(v) for k, v in splits.items()},
        'class_distribution': {CLASS_NAMES[k]: len(v) for k, v in files_by_class.items()}
    }

    with open(OUTPUT_ROOT / "manifest.json", 'w') as f:
        json.dump(manifest, f, indent=2)

    print(f"\nDataset merged successfully!")
    print(f"Output: {OUTPUT_ROOT}")
    print(f"Manifest: {OUTPUT_ROOT / 'manifest.json'}")

if __name__ == "__main__":
    main()
