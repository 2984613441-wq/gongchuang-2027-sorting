from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from sorting_vision.errors import EmptyDetectionError, InvalidDetectionError, InvalidInputError
from sorting_vision.sort_plan import (
    BoxAssignment,
    TooManyGroupsError,
    UnknownColorError,
    UnknownGroupError,
    build_sort_plan,
    classify_and_plan,
    crop_rgba,
)
from sorting_vision.types import BoundingBox, RawDetection


def det(shape_id: int, bbox: tuple[float, float, float, float], conf: float = 0.9) -> RawDetection:
    return RawDetection(shape_id, conf, BoundingBox(*bbox))


class SortPlanTests(unittest.TestCase):
    def test_grouping_assigns_boxes_by_color_then_shape(self) -> None:
        plan = build_sort_plan(
            (
                det(0, (10, 10, 20, 20)),  # blue cube
                det(0, (30, 10, 40, 20)),  # red cube
                det(1, (10, 30, 20, 40)),  # blue cuboid
            ),
            ("blue", "red", "blue"),
            box_count=6,
        )
        self.assertTrue(plan.valid)
        self.assertEqual(3, plan.group_count)
        self.assertEqual([2, 1, 3], [item.box_id for item in plan.items])

    def test_same_key_maps_to_same_box(self) -> None:
        plan = build_sort_plan(
            (
                det(2, (10, 10, 20, 20)),
                det(2, (40, 10, 50, 20)),
            ),
            ("green", "green"),
            box_count=6,
        )
        self.assertEqual(1, plan.group_count)
        self.assertEqual([1, 1], [item.box_id for item in plan.items])

    def test_too_many_groups_fails_closed(self) -> None:
        detections = tuple(det(i, (i * 10, 0, i * 10 + 5, 5)) for i in range(7))
        labels = ("red", "orange", "yellow", "green", "cyan", "blue", "purple")
        with self.assertRaises(TooManyGroupsError):
            build_sort_plan(detections, labels, box_count=6)

    def test_frozen_box_assignment_overrides_lexicographic(self) -> None:
        assignment = BoxAssignment({(0, 0): 3, (0, 1): 5})  # (color_id, shape_id) -> box_id
        plan = build_sort_plan(
            (det(0, (10, 10, 20, 20)), det(1, (30, 10, 40, 20))),
            ("red", "red"),
            box_count=6,
            box_assignment=assignment,
        )
        self.assertEqual([3, 5], [item.box_id for item in plan.items])

    def test_frozen_box_assignment_fails_closed_on_unknown_group(self) -> None:
        assignment = BoxAssignment({(0, 0): 1})
        with self.assertRaises(UnknownGroupError):
            build_sort_plan(
                (det(0, (0, 0, 5, 5)), det(1, (5, 0, 10, 5))),
                ("red", "red"),
                box_count=6,
                box_assignment=assignment,
            )

    def test_unknown_color_fails_closed(self) -> None:
        with self.assertRaises(UnknownColorError):
            build_sort_plan((det(0, (0, 0, 5, 5)),), ("mauve",), box_count=6)

    def test_empty_detections_fail_closed(self) -> None:
        with self.assertRaises(EmptyDetectionError):
            build_sort_plan((), (), box_count=6)

    def test_length_mismatch_fails(self) -> None:
        with self.assertRaises(ValueError):
            build_sort_plan((det(0, (0, 0, 5, 5)),), (), box_count=6)

    def test_classify_and_plan_crops_and_names_colors(self) -> None:
        width, height = 6, 4
        pixels: list[int] = []
        for _ in range(width * height):
            pixels += [205, 25, 25, 255]
        # Make the right half green.
        for y in range(height):
            for x in range(3, width):
                offset = (y * width + x) * 4
                pixels[offset : offset + 4] = [25, 175, 60, 255]

        plan = classify_and_plan(
            pixels,
            width,
            height,
            (
                det(0, (0, 0, 3, 4)),
                det(1, (3, 0, 6, 4)),
            ),
            box_count=6,
        )
        self.assertTrue(plan.valid)
        self.assertEqual(["red", "green"], [item.color_name for item in plan.items])
        self.assertEqual([1, 2], [item.box_id for item in plan.items])

    def test_crop_rgba_rejects_out_of_image_bbox(self) -> None:
        with self.assertRaises(InvalidDetectionError):
            crop_rgba([0] * 24, 3, 2, BoundingBox(0, 0, 5, 2))

    def test_crop_rgba_rejects_truncated_image_buffer(self) -> None:
        with self.assertRaises(InvalidInputError):
            crop_rgba([0] * 23, 3, 2, BoundingBox(0, 0, 3, 2))


if __name__ == "__main__":
    unittest.main()
