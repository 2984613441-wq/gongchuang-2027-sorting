from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPLITS = ("train", "val", "test")
DEFAULT_CLASSES = (
    "cube",
    "cuboid",
    "cylinder",
    "hexagonal_prism",
    "pentagonal_prism",
    "square_pyramid",
    "triangular_prism",
)


class DatasetError(ValueError):
    pass


def read_image_size(image_path: Path) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise DatasetError(
            "Pillow is required to inspect images. Install Pillow in the local training environment."
        ) from exc
    try:
        with Image.open(image_path) as image:
            width, height = image.size
            image.verify()
            return int(width), int(height)
    except Exception as exc:
        raise DatasetError(f"unreadable image: {image_path}") from exc


def parse_voc_boxes(
    xml_path: Path, fallback_size: tuple[int, int] | None
) -> tuple[int, int, list[tuple[str, float, float, float, float]]]:
    root = ElementTree.parse(xml_path).getroot()

    size = root.find("size")
    if size is not None:
        width_text = size.findtext("width")
        height_text = size.findtext("height")
        if width_text is not None and height_text is not None:
            try:
                width = int(float(width_text))
                height = int(float(height_text))
            except ValueError as exc:
                raise DatasetError(f"invalid VOC size in {xml_path.name}") from exc
        else:
            width, height = fallback_size if fallback_size else (0, 0)
    else:
        width, height = fallback_size if fallback_size else (0, 0)

    if width <= 0 or height <= 0:
        raise DatasetError(f"cannot determine image size for {xml_path.name}")

    boxes: list[tuple[str, float, float, float, float]] = []
    for obj in root.findall("object"):
        name = (obj.findtext("name") or "").strip()
        if not name:
            raise DatasetError(f"{xml_path.name}: object without a class name")
        bndbox = obj.find("bndbox")
        if bndbox is None:
            raise DatasetError(f"{xml_path.name}: object without bndbox")
        try:
            xmin = float(bndbox.findtext("xmin"))
            ymin = float(bndbox.findtext("ymin"))
            xmax = float(bndbox.findtext("xmax"))
            ymax = float(bndbox.findtext("ymax"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise DatasetError(f"{xml_path.name}: invalid bndbox") from exc
        boxes.append((name, xmin, ymin, xmax, ymax))

    return width, height, boxes


def to_yolo_box(
    box: tuple[str, float, float, float, float],
    width: int,
    height: int,
) -> tuple[str, float, float, float, float]:
    _, xmin, ymin, xmax, ymax = box
    if not (0 <= xmin < xmax <= width and 0 <= ymin < ymax <= height):
        raise DatasetError(
            f"box {box[0]} outside image bounds: ({xmin},{ymin},{xmax},{ymax}) vs {width}x{height}"
        )
    box_width = xmax - xmin
    box_height = ymax - ymin
    x_center = (xmin + xmax) / 2.0 / width
    y_center = (ymin + ymax) / 2.0 / height
    norm_width = box_width / width
    norm_height = box_height / height
    if not (0.0 < norm_width <= 1.0 and 0.0 < norm_height <= 1.0):
        raise DatasetError(f"invalid normalized box size for {box[0]}")
    return (box[0], x_center, y_center, norm_width, norm_height)


def build_entries(source_root: Path, class_to_id: dict[str, int]) -> list[dict[str, object]]:
    images_root = source_root / "images"
    if not images_root.is_dir():
        raise DatasetError(f"missing images directory: {images_root}")
    xml_root = source_root / "xml"
    if not xml_root.is_dir():
        xml_root = source_root / "annotations"
    if not xml_root.is_dir():
        raise DatasetError(
            f"missing annotation directory; expected {source_root / 'xml'} or "
            f"{source_root / 'annotations'}"
        )

    entries: list[dict[str, object]] = []
    image_stems: set[str] = set()
    for image_path in sorted(images_root.iterdir()):
        if image_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        stem = image_path.stem
        if stem in image_stems:
            raise DatasetError(f"duplicate image stem: {stem}")
        image_stems.add(stem)

        xml_path = xml_root / f"{stem}.xml"
        if not xml_path.is_file():
            raise DatasetError(f"image has no matching XML: {image_path.name}")

        width, height = read_image_size(image_path)
        xml_width, xml_height, voc_boxes = parse_voc_boxes(xml_path, (width, height))
        yolo_boxes = [to_yolo_box(box, xml_width, xml_height) for box in voc_boxes]

        labeled_classes: set[int] = set()
        for name, x_center, y_center, norm_width, norm_height in yolo_boxes:
            class_id = class_to_id.get(name)
            if class_id is None:
                raise DatasetError(f"{xml_path.name}: unknown class {name!r}")
            labeled_classes.add(class_id)

        entries.append(
            {
                "stem": stem,
                "image_path": image_path,
                "xml_path": xml_path,
                "boxes": yolo_boxes,
                "classes": sorted(labeled_classes),
            }
        )

    if not entries:
        raise DatasetError("no image/XML pairs found")
    return entries


def stratified_split(
    entries: list[dict[str, object]],
    val_ratio: float,
    test_ratio: float,
    seed: int,
) -> dict[str, list[dict[str, object]]]:
    rng = random.Random(seed)
    by_primary_class: dict[int, list[dict[str, object]]] = defaultdict(list)
    for entry in entries:
        primary_class = int(entry["classes"][0])
        by_primary_class[primary_class].append(entry)

    split_entries: dict[str, list[dict[str, object]]] = {split: [] for split in SPLITS}
    for class_id in sorted(by_primary_class):
        group = by_primary_class[class_id]
        rng.shuffle(group)
        count = len(group)
        if count < 3:
            raise DatasetError(
                f"class {class_id} has only {count} images; at least 3 are required for train/val/test"
            )
        test_count = max(1, min(count - 2, round(count * test_ratio)))
        val_count = max(1, min(count - test_count - 1, round(count * val_ratio)))
        split_entries["test"].extend(group[:test_count])
        split_entries["val"].extend(group[test_count : test_count + val_count])
        split_entries["train"].extend(group[test_count + val_count :])

    for split in SPLITS:
        if not split_entries[split]:
            raise DatasetError(f"empty split: {split}")
        present_classes: set[int] = set()
        for entry in split_entries[split]:
            present_classes.update(int(class_id) for class_id in entry["classes"])
        if len(present_classes) != len(by_primary_class):
            raise DatasetError(
                f"{split} split does not contain every class; "
                "increase per-class images or use one-object-per-image annotations"
            )
    return split_entries


def write_label(path: Path, boxes: list[tuple[str, float, float, float, float]], class_to_id: dict[str, int]) -> None:
    lines = []
    for name, x_center, y_center, norm_width, norm_height in boxes:
        lines.append(
            f"{class_to_id[name]} {x_center:.6f} {y_center:.6f} {norm_width:.6f} {norm_height:.6f}"
        )
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def prepare(
    source_root: Path,
    output_root: Path,
    classes: list[str],
    val_ratio: float,
    test_ratio: float,
    seed: int,
) -> dict[str, object]:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        raise DatasetError(f"output already exists; refusing to overwrite: {output_root}")
    if not 0.0 < val_ratio + test_ratio < 1.0:
        raise DatasetError("val_ratio + test_ratio must be between 0 and 1")

    class_to_id = {name: index for index, name in enumerate(classes)}
    entries = build_entries(source_root, class_to_id)
    split_entries = stratified_split(entries, val_ratio, test_ratio, seed)

    for split in SPLITS:
        (output_root / "images" / split).mkdir(parents=True, exist_ok=False)
        (output_root / "labels" / split).mkdir(parents=True, exist_ok=False)

    split_images: Counter[str] = Counter()
    split_class_counts: dict[str, Counter[int]] = {split: Counter() for split in SPLITS}
    for split, split_group in split_entries.items():
        for entry in split_group:
            image_path = Path(entry["image_path"])
            label_dest = output_root / "labels" / split / f"{entry['stem']}.txt"
            shutil.copy2(image_path, output_root / "images" / split / image_path.name)
            write_label(label_dest, entry["boxes"], class_to_id)
            split_images[split] += 1
            for class_id in entry["classes"]:
                split_class_counts[split][int(class_id)] += 1

    yaml_root = output_root.as_posix()
    yaml_lines = [
        f"path: {json.dumps(yaml_root, ensure_ascii=False)}",
        "train: images/train",
        "val: images/val",
        "test: images/test",
        "names:",
    ]
    yaml_lines.extend(f"  {index}: {json.dumps(name, ensure_ascii=False)}" for index, name in enumerate(classes))
    (output_root / "data.yaml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")
    (output_root / "classes.txt").write_text("\n".join(classes) + "\n", encoding="utf-8")

    stats = {
        split: {
            "images": split_images[split],
            "classes": {
                str(class_id): split_class_counts[split][class_id] for class_id in range(len(classes))
            },
        }
        for split in SPLITS
    }
    manifest = {
        "schema_version": "voc-to-yolo-dataset-v1",
        "source_root": str(source_root),
        "output_root": str(output_root),
        "classes": classes,
        "split_stats": stats,
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert Pascal VOC images+xml into a YOLO train/val/test dataset."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--classes",
        default=",".join(DEFAULT_CLASSES),
        help="comma-separated class names in YOLO id order",
    )
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--test-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    classes = [name.strip() for name in args.classes.split(",") if name.strip()]
    if len(classes) != len(set(classes)):
        raise DatasetError("class names must be unique and non-empty")

    manifest = prepare(
        args.source_root,
        args.output_root,
        classes,
        args.val_ratio,
        args.test_ratio,
        args.seed,
    )
    print(json.dumps(manifest["split_stats"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DatasetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
