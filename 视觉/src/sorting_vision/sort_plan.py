"""Group detections by (color, shape) and assign items to storage boxes.

This is the pure-logic core of the preliminary-round chain:

    detect -> crop ROI -> shape (from detection) + color (from pixels)
           -> group by (color_id, shape_id) -> map groups to boxes

It does not encode wire frames, emit motion commands, or require a camera. The
color vocabulary is a starter table; it must be frozen only after on-site
white-balance and lighting calibration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .color_quant import color_name, dominant_color
from .errors import EmptyDetectionError, InvalidDetectionError, InvalidInputError
from .types import BoundingBox, RawDetection


DEFAULT_COLOR_VOCABULARY = (
    "red",
    "orange",
    "yellow",
    "green",
    "cyan",
    "blue",
    "purple",
    "pink",
    "black",
    "white",
    "gray",
)


class TooManyGroupsError(Exception):
    code = "TOO_MANY_GROUPS"


class UnknownColorError(Exception):
    code = "UNKNOWN_COLOR"


@dataclass(frozen=True)
class PlacedItem:
    shape_id: int
    color_id: int
    color_name: str
    confidence: float
    bbox: BoundingBox
    box_id: int


@dataclass(frozen=True)
class SortPlan:
    items: tuple[PlacedItem, ...]
    group_count: int
    box_count: int

    @property
    def valid(self) -> bool:
        return bool(self.items) and 1 <= self.group_count <= self.box_count


def color_name_to_id(name: str, vocabulary: Sequence[str] = DEFAULT_COLOR_VOCABULARY) -> int:
    try:
        return list(vocabulary).index(name)
    except ValueError:
        raise UnknownColorError(f"color {name!r} is not in the configured vocabulary") from None


def crop_rgba(
    pixels: Sequence[int],
    image_width: int,
    image_height: int,
    bbox: BoundingBox,
) -> list[int]:
    """Return the flat RGBA bytes inside ``bbox``."""

    if not isinstance(image_width, int) or image_width <= 0:
        raise InvalidInputError("image_width must be a positive integer")
    if not isinstance(image_height, int) or image_height <= 0:
        raise InvalidInputError("image_height must be a positive integer")
    bbox.validate(image_width, image_height)

    x1, y1 = int(bbox.x1), int(bbox.y1)
    x2, y2 = int(bbox.x2), int(bbox.y2)
    out: list[int] = []
    for y in range(y1, y2):
        row_start = y * image_width * 4
        for x in range(x1, x2):
            offset = row_start + x * 4
            out.extend(pixels[offset : offset + 4])
    return out


def classify_roi_color(pixels: Sequence[int]) -> str:
    return color_name(dominant_color(pixels))


def build_sort_plan(
    detections: Sequence[RawDetection],
    color_labels: Sequence[str],
    box_count: int = 6,
    vocabulary: Sequence[str] = DEFAULT_COLOR_VOCABULARY,
) -> SortPlan:
    """Group detections by ``(color_id, shape_id)`` and assign box ids.

    Box ids are assigned in ``(color_id, shape_id)`` lexicographic order, so a
    given key always maps to the same box and distinct keys map to distinct
    boxes. More distinct keys than ``box_count`` fails closed.
    """

    if not detections:
        raise EmptyDetectionError("no detections to sort")
    if len(detections) != len(color_labels):
        raise ValueError("detections and color labels must have the same length")
    if not isinstance(box_count, int) or box_count < 1:
        raise ValueError("box_count must be a positive integer")

    keys: list[tuple[int, int]] = []
    for detection, label in zip(detections, color_labels):
        keys.append((color_name_to_id(label, vocabulary), detection.class_id))

    unique = sorted(set(keys))
    if len(unique) > box_count:
        raise TooManyGroupsError(
            f"{len(unique)} distinct (color, shape) groups exceed {box_count} boxes"
        )

    box_of = {key: index + 1 for index, key in enumerate(unique)}
    items = tuple(
        PlacedItem(
            shape_id=detection.class_id,
            color_id=keys[i][0],
            color_name=color_labels[i],
            confidence=detection.confidence,
            bbox=detection.bbox,
            box_id=box_of[keys[i]],
        )
        for i, detection in enumerate(detections)
    )
    return SortPlan(items=items, group_count=len(unique), box_count=box_count)


def classify_and_plan(
    pixels: Sequence[int],
    image_width: int,
    image_height: int,
    detections: Sequence[RawDetection],
    box_count: int = 6,
    vocabulary: Sequence[str] = DEFAULT_COLOR_VOCABULARY,
) -> SortPlan:
    """Full chain: crop each ROI, name its dominant color, then plan boxes."""

    labels = [
        classify_roi_color(crop_rgba(pixels, image_width, image_height, detection.bbox))
        for detection in detections
    ]
    return build_sort_plan(detections, labels, box_count, vocabulary)
