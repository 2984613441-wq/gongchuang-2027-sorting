from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPLITS = ("train", "val", "test")


class DatasetError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def group_for(stem: str) -> str:
    if stem.startswith("photo_"):
        return "photos"
    if "_t" not in stem:
        raise DatasetError(f"cannot determine source group from filename: {stem}")
    return stem.split("_t", 1)[0]


def read_classes(path: Path) -> list[str]:
    classes = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if not classes or len(classes) != len(set(classes)):
        raise DatasetError("classes.txt must contain unique, non-empty class names")
    return classes


def validate_label(path: Path, class_count: int) -> Counter[int]:
    counts: Counter[int] = Counter()
    seen: set[tuple[int, float, float, float, float]] = set()
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not any(line.strip() for line in lines):
        raise DatasetError(f"empty label file is not allowed for this dataset: {path.name}")

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5:
            raise DatasetError(f"{path.name}:{line_number}: expected 5 fields, got {len(parts)}")
        try:
            class_id = int(parts[0])
            x_center, y_center, width, height = (float(value) for value in parts[1:])
        except ValueError as exc:
            raise DatasetError(f"{path.name}:{line_number}: non-numeric YOLO field") from exc

        if class_id < 0 or class_id >= class_count:
            raise DatasetError(f"{path.name}:{line_number}: unknown class id {class_id}")
        values = (x_center, y_center, width, height)
        if not all(math.isfinite(value) for value in values):
            raise DatasetError(f"{path.name}:{line_number}: non-finite coordinate")
        if not (0.0 <= x_center <= 1.0 and 0.0 <= y_center <= 1.0):
            raise DatasetError(f"{path.name}:{line_number}: center outside [0, 1]")
        if not (0.0 < width <= 1.0 and 0.0 < height <= 1.0):
            raise DatasetError(f"{path.name}:{line_number}: width/height outside (0, 1]")

        tolerance = 1e-6
        if (
            x_center - width / 2 < -tolerance
            or x_center + width / 2 > 1.0 + tolerance
            or y_center - height / 2 < -tolerance
            or y_center + height / 2 > 1.0 + tolerance
        ):
            raise DatasetError(f"{path.name}:{line_number}: box extends outside the image")

        record = (class_id, x_center, y_center, width, height)
        if record in seen:
            raise DatasetError(f"{path.name}:{line_number}: exact duplicate box")
        seen.add(record)
        counts[class_id] += 1
    return counts


def verify_image(path: Path) -> None:
    try:
        with Image.open(path) as image:
            image.verify()
    except Exception as exc:
        raise DatasetError(f"unreadable image: {path}") from exc


def load_plan(path: Path) -> tuple[list[str], dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    classes = payload.get("classes")
    split_groups = payload.get("split_groups")
    if not isinstance(classes, list) or not all(isinstance(item, str) and item for item in classes):
        raise DatasetError("split plan must define a non-empty classes list")
    if not isinstance(split_groups, dict) or set(split_groups) != set(SPLITS):
        raise DatasetError("split plan must define train, val and test groups")

    assignment: dict[str, str] = {}
    for split in SPLITS:
        groups = split_groups[split]
        if not isinstance(groups, list) or not groups:
            raise DatasetError(f"split plan {split} group list must be non-empty")
        for group in groups:
            if group in assignment:
                raise DatasetError(f"source group assigned more than once: {group}")
            assignment[group] = split
    return classes, assignment


def prepare(source_root: Path, output_root: Path, plan_path: Path) -> dict[str, object]:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    images_root = source_root / "frames_raw"
    labels_root = source_root / "labels_raw"
    if output_root.exists():
        raise DatasetError(f"output already exists; refusing to overwrite: {output_root}")
    if not images_root.is_dir() or not labels_root.is_dir():
        raise DatasetError("source root must contain frames_raw and labels_raw directories")

    planned_classes, assignment = load_plan(plan_path)
    actual_classes = read_classes(labels_root / "classes.txt")
    if actual_classes != planned_classes:
        raise DatasetError(f"class order mismatch: expected {planned_classes}, got {actual_classes}")

    images_by_stem: dict[str, Path] = {}
    for image_path in images_root.iterdir():
        if image_path.is_file() and image_path.suffix.lower() in IMAGE_SUFFIXES:
            if image_path.stem in images_by_stem:
                raise DatasetError(f"duplicate image stem: {image_path.stem}")
            images_by_stem[image_path.stem] = image_path

    label_paths = sorted(path for path in labels_root.glob("*.txt") if path.name != "classes.txt")
    if not label_paths:
        raise DatasetError("no label files found")

    entries: list[dict[str, object]] = []
    group_splits: dict[str, set[str]] = defaultdict(set)
    image_hash_splits: dict[str, set[str]] = defaultdict(set)
    split_images: Counter[str] = Counter()
    split_class_counts: dict[str, Counter[int]] = {split: Counter() for split in SPLITS}

    for label_path in label_paths:
        image_path = images_by_stem.get(label_path.stem)
        if image_path is None:
            raise DatasetError(f"label has no matching image: {label_path.name}")
        group = group_for(label_path.stem)
        split = assignment.get(group)
        if split is None:
            raise DatasetError(f"source group is missing from split plan: {group}")
        verify_image(image_path)
        class_counts = validate_label(label_path, len(actual_classes))
        image_hash = sha256(image_path)
        label_hash = sha256(label_path)
        group_splits[group].add(split)
        image_hash_splits[image_hash].add(split)
        split_images[split] += 1
        split_class_counts[split].update(class_counts)
        entries.append(
            {
                "stem": label_path.stem,
                "group": group,
                "split": split,
                "image_source": str(image_path),
                "label_source": str(label_path),
                "image_sha256": image_hash,
                "label_sha256": label_hash,
                "class_counts": {str(key): value for key, value in sorted(class_counts.items())},
            }
        )

    missing_planned_groups = sorted(set(assignment) - set(group_splits))
    if missing_planned_groups:
        raise DatasetError(f"planned groups have no labeled samples: {missing_planned_groups}")
    leaking_groups = {group: splits for group, splits in group_splits.items() if len(splits) != 1}
    if leaking_groups:
        raise DatasetError(f"source group leakage detected: {leaking_groups}")
    leaking_hashes = {digest: splits for digest, splits in image_hash_splits.items() if len(splits) > 1}
    if leaking_hashes:
        raise DatasetError(f"exact duplicate images cross splits: {list(leaking_hashes)[:3]}")
    for split in SPLITS:
        if split_images[split] == 0:
            raise DatasetError(f"empty split: {split}")
        if set(split_class_counts[split]) != set(range(len(actual_classes))):
            raise DatasetError(f"split {split} does not contain every class")

    for split in SPLITS:
        (output_root / "images" / split).mkdir(parents=True, exist_ok=False)
        (output_root / "labels" / split).mkdir(parents=True, exist_ok=False)

    for entry in entries:
        image_source = Path(str(entry["image_source"]))
        label_source = Path(str(entry["label_source"]))
        split = str(entry["split"])
        image_dest = output_root / "images" / split / image_source.name
        label_dest = output_root / "labels" / split / label_source.name
        shutil.copy2(image_source, image_dest)
        shutil.copy2(label_source, label_dest)
        if sha256(image_dest) != entry["image_sha256"] or sha256(label_dest) != entry["label_sha256"]:
            raise DatasetError(f"copy verification failed: {entry['stem']}")

    yaml_path = output_root / "data.yaml"
    yaml_root = output_root.as_posix()
    yaml_lines = [
        f"path: {json.dumps(yaml_root, ensure_ascii=False)}",
        "train: images/train",
        "val: images/val",
        "test: images/test",
        "names:",
    ]
    yaml_lines.extend(f"  {index}: {json.dumps(name, ensure_ascii=False)}" for index, name in enumerate(actual_classes))
    yaml_path.write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")

    stats = {
        split: {
            "images": split_images[split],
            "classes": {
                str(class_id): split_class_counts[split][class_id] for class_id in range(len(actual_classes))
            },
        }
        for split in SPLITS
    }
    manifest = {
        "schema_version": "block-dataset-manifest-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "output_root": str(output_root),
        "classes": actual_classes,
        "split_stats": stats,
        "entries": entries,
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and split the two-class block YOLO dataset.")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--split-plan", type=Path, required=True)
    args = parser.parse_args()
    manifest = prepare(args.source_root, args.output_root, args.split_plan)
    print(json.dumps(manifest["split_stats"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
