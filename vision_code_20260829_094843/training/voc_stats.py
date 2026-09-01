from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
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


def annotation_dir(source_root: Path) -> Path:
    xml_root = source_root / "xml"
    if xml_root.is_dir():
        return xml_root
    annotations_root = source_root / "annotations"
    if annotations_root.is_dir():
        return annotations_root
    raise DatasetError("missing xml/ or annotations/ directory")


def stats(source_root: Path, expected_classes: tuple[str, ...]) -> dict[str, object]:
    images_root = source_root / "images"
    if not images_root.is_dir():
        raise DatasetError(f"missing images directory: {images_root}")
    xml_root = annotation_dir(source_root)

    images = {
        path.stem: path
        for path in images_root.iterdir()
        if path.suffix.lower() in IMAGE_SUFFIXES
    }
    xml_paths = sorted(xml_root.glob("*.xml"))
    box_counts: Counter[str] = Counter()
    image_counts: Counter[str] = Counter()
    unknown_classes: Counter[str] = Counter()
    missing_xml: list[str] = []
    missing_image: list[str] = []
    expected_set = set(expected_classes)

    for xml_path in xml_paths:
        stem = xml_path.stem
        if stem not in images:
            missing_image.append(stem)
            continue
        root = ElementTree.parse(xml_path).getroot()
        present: set[str] = set()
        for obj in root.findall("object"):
            name = (obj.findtext("name") or "").strip()
            if not name:
                continue
            box_counts[name] += 1
            present.add(name)
            if name not in expected_set:
                unknown_classes[name] += 1
        for name in present:
            image_counts[name] += 1

    for stem in images:
        if not (xml_root / f"{stem}.xml").is_file():
            missing_xml.append(stem)

    return {
        "images": len(images),
        "xml_files": len(xml_paths),
        "box_counts": dict(sorted(box_counts.items())),
        "image_counts": dict(sorted(image_counts.items())),
        "unknown_classes": dict(sorted(unknown_classes.items())),
        "missing_xml": sorted(missing_xml),
        "missing_image": sorted(missing_image),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Print class/image counts for a Pascal VOC dataset.")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--classes",
        default=",".join(DEFAULT_CLASSES),
        help="comma-separated expected class names",
    )
    args = parser.parse_args()
    expected_classes = tuple(name.strip() for name in args.classes.split(",") if name.strip())
    result = stats(args.source_root, expected_classes)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["missing_xml"] or result["missing_image"]:
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DatasetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
