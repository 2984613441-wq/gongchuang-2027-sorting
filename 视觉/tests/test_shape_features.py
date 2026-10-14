"""Tests for the contour shape-feature fallback.

Split in two on purpose:

* The rule layer (``classify_shape_from_features``) is pure arithmetic over a
  ``ContourFeatures`` value, so these tests build features by hand and run even
  where OpenCV is absent. They are the real verification of the ported
  thresholds.
* The measurement layer (``extract_contour_features`` /
  ``extract_and_classify_roi``) needs OpenCV and is skipped when it is absent.
  A skip here is an honest gap, not a pass.
"""

from __future__ import annotations

import math
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import sorting_vision.shape_features as shape_features
from sorting_vision.errors import DependencyUnavailableError, InvalidInputError
from sorting_vision.shape_features import (
    CLASSIFIABLE_SHAPES,
    CV2_AVAILABLE,
    SHAPE_LABELS,
    UNKNOWN_SHAPE,
    ContourFeatures,
    classify_shape_from_features,
    extract_and_classify_roi,
    extract_contour_features,
    rgba_roi_to_bgr_array,
)

try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]
    NUMPY_AVAILABLE = False


def features(**overrides) -> ContourFeatures:
    """A square-ish, perfectly solid baseline; override to probe one rule."""

    base = ContourFeatures(
        area=10000.0,
        perimeter=400.0,
        hull_area=10000.0,
        contour_point_count=40,
        polygon_corner_count=4,
        polygon_convex=True,
        triangle_corner_count=8,
        triangle_convex=False,
        triangle_area_coverage=0.95,
        min_area_rect_ratio=1.0,
        min_area_rect_extent=0.98,
        max_corner_cosine=0.02,
        ellipse_area_ratio=0.80,
        bbox_aspect_ratio=1.0,
        bbox_extent=0.98,
    )
    return replace(base, **overrides)


class VocabularyTests(unittest.TestCase):
    def test_shape_labels_are_the_seven_detector_classes(self) -> None:
        self.assertEqual(7, len(SHAPE_LABELS))
        self.assertEqual(
            {
                "cube",
                "cuboid",
                "cylinder",
                "hexagonal_prism",
                "pentagonal_prism",
                "square_pyramid",
                "triangular_prism",
            },
            set(SHAPE_LABELS),
        )

    def test_classifiable_subset_is_inside_the_vocabulary(self) -> None:
        self.assertTrue(set(CLASSIFIABLE_SHAPES).issubset(set(SHAPE_LABELS)))
        self.assertEqual({"cube", "cylinder", "triangular_prism"}, set(CLASSIFIABLE_SHAPES))

    def test_unknown_is_not_a_vocabulary_class(self) -> None:
        self.assertNotIn(UNKNOWN_SHAPE, SHAPE_LABELS)


class DerivedFeatureTests(unittest.TestCase):
    def test_solidity_is_area_over_hull_area(self) -> None:
        self.assertAlmostEqual(0.5, features(area=50.0, hull_area=100.0).solidity)

    def test_solidity_is_zero_without_a_hull(self) -> None:
        self.assertEqual(0.0, features(area=50.0, hull_area=0.0).solidity)

    def test_circularity_is_one_for_a_circle(self) -> None:
        # r = 10 -> area = pi*100, perimeter = 2*pi*10
        area = math.pi * 100.0
        perimeter = 2.0 * math.pi * 10.0
        self.assertAlmostEqual(1.0, features(area=area, perimeter=perimeter).circularity)

    def test_circularity_is_zero_without_a_perimeter(self) -> None:
        self.assertEqual(0.0, features(perimeter=0.0).circularity)


class ClassifyShapeRuleTests(unittest.TestCase):
    def test_square_like_features_are_a_cube(self) -> None:
        self.assertEqual("cube", classify_shape_from_features(features()))

    def test_low_solidity_is_unknown_even_when_the_shape_looks_square(self) -> None:
        # Guards the global concave/ragged gate that runs before every rule.
        self.assertEqual(
            UNKNOWN_SHAPE,
            classify_shape_from_features(features(area=10000.0, hull_area=12000.0)),
        )
        self.assertEqual(
            UNKNOWN_SHAPE,
            classify_shape_from_features(features(area=100.0, hull_area=200.0)),
        )

    def test_skewed_quad_is_not_a_cube(self) -> None:
        self.assertEqual(
            UNKNOWN_SHAPE, classify_shape_from_features(features(max_corner_cosine=0.50))
        )
        self.assertEqual(
            UNKNOWN_SHAPE, classify_shape_from_features(features(max_corner_cosine=0.90))
        )

    def test_thin_quad_is_not_a_cube(self) -> None:
        self.assertEqual(
            UNKNOWN_SHAPE, classify_shape_from_features(features(min_area_rect_extent=0.50))
        )

    def test_three_corner_hypothesis_is_a_triangular_prism(self) -> None:
        self.assertEqual(
            "triangular_prism",
            classify_shape_from_features(
                features(
                    area=10000.0,
                    hull_area=10500.0,
                    triangle_corner_count=3,
                    triangle_convex=True,
                    triangle_area_coverage=0.90,
                    min_area_rect_ratio=0.60,
                )
            ),
        )
        # The archived helper also fires for an exact 3-gon with full coverage.
        self.assertEqual(
            "triangular_prism",
            classify_shape_from_features(
                features(
                    triangle_corner_count=3,
                    triangle_convex=True,
                    triangle_area_coverage=1.0,
                    min_area_rect_ratio=1.0,
                )
            ),
        )

    def test_triangle_needs_to_cover_the_real_contour(self) -> None:
        # Without the coverage gate, any polygon could be accepted as a triangle.
        self.assertEqual(
            UNKNOWN_SHAPE,
            classify_shape_from_features(
                features(
                    triangle_corner_count=3,
                    triangle_convex=True,
                    triangle_area_coverage=0.50,
                    min_area_rect_ratio=0.60,
                )
            ),
        )

    def test_non_convex_triangle_fit_is_rejected(self) -> None:
        self.assertEqual(
            UNKNOWN_SHAPE,
            classify_shape_from_features(
                features(
                    triangle_corner_count=3,
                    triangle_convex=False,
                    triangle_area_coverage=0.90,
                    min_area_rect_ratio=0.60,
                )
            ),
        )

    def test_round_polygon_with_matching_ellipse_is_a_cylinder(self) -> None:
        self.assertEqual(
            "cylinder",
            classify_shape_from_features(
                features(
                    perimeter=360.0,
                    polygon_corner_count=8,
                    min_area_rect_ratio=0.95,
                    ellipse_area_ratio=0.98,
                )
            ),
        )
        self.assertEqual(
            "cylinder",
            classify_shape_from_features(
                features(
                    area=100.0,
                    perimeter=36.0,
                    hull_area=100.0,
                    contour_point_count=12,
                    polygon_corner_count=8,
                    triangle_corner_count=4,
                    ellipse_area_ratio=1.0,
                )
            ),
        )

    def test_round_blob_that_does_not_match_its_ellipse_is_unknown(self) -> None:
        # This is the archived behaviour that rejects a hexagon's silhouette.
        self.assertEqual(
            UNKNOWN_SHAPE,
            classify_shape_from_features(
                features(perimeter=360.0, polygon_corner_count=8, ellipse_area_ratio=0.85)
            ),
        )

    def test_too_few_circularity_points_is_unknown(self) -> None:
        self.assertEqual(
            UNKNOWN_SHAPE,
            classify_shape_from_features(
                features(perimeter=360.0, polygon_corner_count=8, contour_point_count=4)
            ),
        )

    def test_triangle_rule_is_evaluated_before_the_round_rule(self) -> None:
        # Rule order is part of the ported behaviour, not an implementation detail.
        self.assertEqual(
            "triangular_prism",
            classify_shape_from_features(
                features(
                    perimeter=360.0,
                    triangle_corner_count=3,
                    triangle_convex=True,
                    triangle_area_coverage=0.90,
                    min_area_rect_ratio=0.80,
                    polygon_corner_count=8,
                    ellipse_area_ratio=0.98,
                )
            ),
        )

    def test_bounding_box_fields_never_decide_a_class(self) -> None:
        # The original brief's rules keyed off the bounding box; this port
        # deliberately does not, because a bbox cannot separate a top-facing
        # square from a tilted one.
        wide = classify_shape_from_features(features(bbox_aspect_ratio=3.0, bbox_extent=0.40))
        square = classify_shape_from_features(features(bbox_aspect_ratio=1.0, bbox_extent=0.98))
        self.assertEqual("cube", wide)
        self.assertEqual(wide, square)

    def test_never_returns_a_class_outside_the_supported_vocabulary(self) -> None:
        # The four classes this geometric method cannot decide must come back
        # as unknown rather than being guessed.
        undecidable = {"cuboid", "hexagonal_prism", "pentagonal_prism", "square_pyramid"}
        probes = (
            features(),
            features(perimeter=360.0, polygon_corner_count=8, ellipse_area_ratio=0.98),
            features(triangle_corner_count=3, triangle_convex=True, min_area_rect_ratio=0.60),
            features(polygon_corner_count=6, min_area_rect_ratio=0.90, ellipse_area_ratio=0.99),
            features(polygon_corner_count=5, min_area_rect_ratio=0.95, ellipse_area_ratio=0.97),
        )
        for probe in probes:
            with self.subTest(probe=probe):
                answer = classify_shape_from_features(probe)
                self.assertNotIn(answer, undecidable)
                self.assertIn(answer, (*CLASSIFIABLE_SHAPES, UNKNOWN_SHAPE))


class ThresholdBoundaryTests(unittest.TestCase):
    """Sit exactly ON each ported threshold.

    These exist because the rest of the file is boundary-blind: every other
    fixture sits comfortably inside or outside a rule, so flipping any `>=` to
    `>` would leave all of them green. Each assertion below pairs the exact
    boundary (must be accepted) with the value one step outside (must not be),
    which fails if the comparison direction or inclusivity changes.

    Every boundary here is an exact decimal that is float-reproducible:
    90/100 == 0.90, 74/100 == 0.74, and the circularity fixture is constructed
    so that 4*pi*area/perimeter**2 == 0.80 exactly.
    """

    CIRCLE_PERIMETER = 100.0
    # area chosen so the computed circularity lands exactly on the threshold
    CIRCLE_AREA = shape_features.CIRCLE_CIRCULARITY_MIN * CIRCLE_PERIMETER**2 / (4.0 * math.pi)

    def circle_features(self, **overrides) -> ContourFeatures:
        base = dict(
            area=self.CIRCLE_AREA,
            perimeter=self.CIRCLE_PERIMETER,
            hull_area=self.CIRCLE_AREA,
            polygon_corner_count=8,
            triangle_corner_count=8,
            min_area_rect_ratio=1.0,
            ellipse_area_ratio=1.0,
        )
        base.update(overrides)
        return features(**base)

    def test_solidity_gate_boundary(self) -> None:
        self.assertEqual("cube", classify_shape_from_features(
            features(area=90.0, hull_area=100.0)
        ))
        self.assertEqual(UNKNOWN_SHAPE, classify_shape_from_features(
            features(area=89.9, hull_area=100.0)
        ))

    def test_triangle_coverage_boundary(self) -> None:
        inside = dict(
            triangle_corner_count=3, triangle_convex=True, min_area_rect_ratio=0.60
        )
        self.assertEqual("triangular_prism", classify_shape_from_features(
            features(triangle_area_coverage=0.78, **inside)
        ))
        self.assertEqual(UNKNOWN_SHAPE, classify_shape_from_features(
            features(triangle_area_coverage=0.7799, **inside)
        ))

    def test_triangle_min_area_rect_ratio_boundary(self) -> None:
        inside = dict(triangle_corner_count=3, triangle_convex=True, triangle_area_coverage=0.90)
        self.assertEqual("triangular_prism", classify_shape_from_features(
            features(min_area_rect_ratio=0.50, **inside)
        ))
        self.assertEqual(UNKNOWN_SHAPE, classify_shape_from_features(
            features(min_area_rect_ratio=0.4999, **inside)
        ))

    def test_cube_min_area_rect_ratio_boundary(self) -> None:
        self.assertEqual("cube", classify_shape_from_features(
            features(min_area_rect_ratio=0.74)
        ))
        self.assertEqual(UNKNOWN_SHAPE, classify_shape_from_features(
            features(min_area_rect_ratio=0.7399)
        ))

    def test_cube_min_area_rect_extent_boundary(self) -> None:
        self.assertEqual("cube", classify_shape_from_features(
            features(min_area_rect_extent=0.84)
        ))
        self.assertEqual(UNKNOWN_SHAPE, classify_shape_from_features(
            features(min_area_rect_extent=0.8399)
        ))

    def test_cube_corner_cosine_boundary(self) -> None:
        self.assertEqual("cube", classify_shape_from_features(
            features(max_corner_cosine=0.35)
        ))
        self.assertEqual(UNKNOWN_SHAPE, classify_shape_from_features(
            features(max_corner_cosine=0.3501)
        ))

    def test_circle_circularity_boundary(self) -> None:
        # The fixture's circularity is exactly 0.80, so a strict '>' would fail here.
        self.assertAlmostEqual(
            shape_features.CIRCLE_CIRCULARITY_MIN, self.circle_features().circularity
        )
        self.assertEqual("cylinder", classify_shape_from_features(self.circle_features()))
        self.assertEqual(UNKNOWN_SHAPE, classify_shape_from_features(
            self.circle_features(
                area=0.7999 * self.CIRCLE_PERIMETER**2 / (4.0 * math.pi)
            )
        ))

    def test_circle_min_area_rect_ratio_boundary(self) -> None:
        self.assertEqual("cylinder", classify_shape_from_features(
            self.circle_features(min_area_rect_ratio=0.68)
        ))
        self.assertEqual(UNKNOWN_SHAPE, classify_shape_from_features(
            self.circle_features(min_area_rect_ratio=0.6799)
        ))

    def test_ellipse_area_ratio_band_boundaries(self) -> None:
        for inside in (0.90, 1.08):
            with self.subTest(bound=inside):
                self.assertEqual("cylinder", classify_shape_from_features(
                    self.circle_features(ellipse_area_ratio=inside)
                ))
        for outside in (0.8999, 1.0801):
            with self.subTest(bound=outside):
                self.assertEqual(UNKNOWN_SHAPE, classify_shape_from_features(
                    self.circle_features(ellipse_area_ratio=outside)
                ))


class MissingDependencyTests(unittest.TestCase):
    """The fallback must fail loudly when OpenCV is absent, not silently."""

    def test_extract_features_requires_opencv(self) -> None:
        with patch("sorting_vision.shape_features.CV2_AVAILABLE", False):
            with self.assertRaises(DependencyUnavailableError):
                extract_contour_features(None)

    def test_classify_roi_requires_opencv(self) -> None:
        with patch("sorting_vision.shape_features.CV2_AVAILABLE", False):
            with self.assertRaises(DependencyUnavailableError):
                extract_and_classify_roi(None, (0, 0, 0), (179, 255, 255))

    def test_rule_layer_does_not_need_opencv(self) -> None:
        # The whole point of splitting the module: thresholds stay testable
        # on a host with no OpenCV.
        with patch("sorting_vision.shape_features.CV2_AVAILABLE", False):
            self.assertEqual("cube", classify_shape_from_features(features()))


@unittest.skipUnless(NUMPY_AVAILABLE, "numpy not installed")
class RgbaAdapterTests(unittest.TestCase):
    """The bridge ``sort_plan`` would need; verified without OpenCV."""

    def _buffer(self) -> list[int]:
        # 3x2 RGBA, R channel encodes the column so a channel swap is observable.
        pixels: list[int] = []
        for _row in range(2):
            for col in range(3):
                pixels += [10 * (col + 1), 100, 200, 255]
        return pixels

    def test_crop_is_returned_as_bgr(self) -> None:
        from sorting_vision.types import BoundingBox

        array = rgba_roi_to_bgr_array(self._buffer(), 3, 2, BoundingBox(0, 0, 3, 2))
        self.assertEqual((2, 3, 3), array.shape)
        # RGBA (10, 100, 200) -> BGR (200, 100, 10)
        self.assertEqual([200, 100, 10], array[0, 0].tolist())
        self.assertEqual([200, 100, 20], array[0, 1].tolist())

    def test_sub_box_is_cropped(self) -> None:
        from sorting_vision.types import BoundingBox

        array = rgba_roi_to_bgr_array(self._buffer(), 3, 2, BoundingBox(2, 1, 3, 2))
        self.assertEqual((1, 1, 3), array.shape)
        self.assertEqual([200, 100, 30], array[0, 0].tolist())

    def test_wrong_buffer_length_is_rejected(self) -> None:
        from sorting_vision.types import BoundingBox

        with self.assertRaises(InvalidInputError):
            rgba_roi_to_bgr_array([0, 0, 0, 255], 3, 2, BoundingBox(0, 0, 3, 2))

    def test_out_of_image_box_is_rejected(self) -> None:
        from sorting_vision.types import BoundingBox

        with self.assertRaises(InvalidInputError):
            rgba_roi_to_bgr_array(self._buffer(), 3, 2, BoundingBox(0, 0, 4, 2))

    def test_missing_or_malformed_bbox_is_rejected(self) -> None:
        # A tuple, None, or a bbox with non-numeric bounds must not leak
        # AttributeError / TypeError out of a public helper.
        for bad in (None, (0, 0, 3, 2), object()):
            with self.subTest(bbox=bad):
                with self.assertRaises(InvalidInputError):
                    rgba_roi_to_bgr_array(self._buffer(), 3, 2, bad)

        class BadBox:
            x1, y1, x2, y2 = "0", 0, 3, 2

        with self.assertRaises(InvalidInputError):
            rgba_roi_to_bgr_array(self._buffer(), 3, 2, BadBox())

    def test_unsized_pixels_is_rejected(self) -> None:
        from sorting_vision.types import BoundingBox

        with self.assertRaises(InvalidInputError):
            rgba_roi_to_bgr_array(12345, 3, 2, BoundingBox(0, 0, 3, 2))

    def test_boolean_image_size_is_rejected(self) -> None:
        from sorting_vision.types import BoundingBox

        # bool is an int subclass; True must not be accepted as "1".
        with self.assertRaises(InvalidInputError):
            rgba_roi_to_bgr_array(self._buffer(), True, 2, BoundingBox(0, 0, 3, 2))

    def test_out_of_byte_range_pixels_are_rejected(self) -> None:
        from sorting_vision.types import BoundingBox

        bad = list(self._buffer())
        bad[0] = 999
        with self.assertRaises(InvalidInputError):
            rgba_roi_to_bgr_array(bad, 3, 2, BoundingBox(0, 0, 3, 2))


@unittest.skipUnless(CV2_AVAILABLE and NUMPY_AVAILABLE, "OpenCV not installed")
class ContourMeasurementTests(unittest.TestCase):
    """Measurement layer. Skipped on hosts without OpenCV."""

    def square_contour(self):
        return np.array([[[10, 10]], [[60, 10]], [[60, 60]], [[10, 60]]], dtype=np.int32)

    def test_axis_aligned_square_measures_as_a_cube(self) -> None:
        self.assertEqual(
            "cube",
            classify_shape_from_features(extract_contour_features(self.square_contour())),
        )

    def test_rotated_square_measures_as_a_cube(self) -> None:
        diamond = np.array([[[50, 10]], [[90, 50]], [[50, 90]], [[10, 50]]], dtype=np.int32)
        self.assertEqual(
            "cube", classify_shape_from_features(extract_contour_features(diamond))
        )

    def test_empty_contour_is_rejected(self) -> None:
        with self.assertRaises(InvalidInputError):
            extract_contour_features(np.empty((0, 1, 2), dtype=np.int32))

    def test_non_array_contour_is_rejected(self) -> None:
        with self.assertRaises(InvalidInputError):
            extract_contour_features([[0, 0], [1, 1]])

    def test_degenerate_contours_return_unknown_instead_of_raising(self) -> None:
        # Verified against cv2 5.0: minAreaRect/convexHull/approxPolyDP all
        # tolerate these, so no cv2.error may escape this module.
        cases = {
            "one_point": np.array([[[5, 5]]], dtype=np.int32),
            "two_points": np.array([[[5, 5]], [[9, 9]]], dtype=np.int32),
            "collinear_three": np.array([[[5, 5]], [[6, 6]], [[7, 7]]], dtype=np.int32),
            "collinear_four": np.array([[[0, 0]], [[1, 1]], [[2, 2]], [[3, 3]]], dtype=np.int32),
        }
        for name, contour in cases.items():
            with self.subTest(name=name):
                self.assertEqual(
                    UNKNOWN_SHAPE,
                    classify_shape_from_features(extract_contour_features(contour)),
                )

    def test_triangle_contour_is_classified_as_a_triangular_prism(self) -> None:
        triangle = np.array([[[10, 10]], [[90, 10]], [[50, 80]]], dtype=np.int32)
        self.assertEqual(
            "triangular_prism",
            classify_shape_from_features(extract_contour_features(triangle)),
        )

    def test_flat_point_pairs_and_float_contours_are_accepted(self) -> None:
        flat = np.array([[10, 10], [60, 10], [60, 60], [10, 60]], dtype=np.int32)
        floats = np.array(
            [[[10.0, 10.0]], [[60.0, 10.0]], [[60.0, 60.0]], [[10.0, 60.0]]], dtype=np.float32
        )
        self.assertEqual("cube", classify_shape_from_features(extract_contour_features(flat)))
        self.assertEqual("cube", classify_shape_from_features(extract_contour_features(floats)))

    def test_wrong_point_layout_is_rejected(self) -> None:
        for bad in (np.zeros((4,), dtype=np.int32), np.zeros((4, 3), dtype=np.int32)):
            with self.subTest(shape=bad.shape):
                with self.assertRaises(InvalidInputError):
                    extract_contour_features(bad)

    def test_every_numeric_dtype_and_layout_is_accepted(self) -> None:
        # Regression guard: raw cv2.contourArea raises cv2.error for float64,
        # uint8, int16, uint16, bool and non-contiguous views. The module must
        # normalise them, not let a cv2.error escape its documented contract.
        points = [[10, 10], [60, 10], [60, 60], [10, 60]]
        for dtype in (np.int32, np.int64, np.float32, np.float64, np.uint8, np.int16, np.uint16):
            with self.subTest(dtype=np.dtype(dtype).name):
                contour = np.array([[p] for p in points], dtype=dtype)
                self.assertEqual(
                    "cube",
                    classify_shape_from_features(extract_contour_features(contour)),
                )
        with self.subTest(dtype="bool"):
            bools = np.array([[p] for p in points], dtype=bool)
            # a bool contour is degenerate as geometry, but must not raise
            self.assertEqual(
                UNKNOWN_SHAPE,
                classify_shape_from_features(extract_contour_features(bools)),
            )
        with self.subTest(layout="non_contiguous"):
            # Two columns of the same points: a (N, 2) view whose stride is wider
            # than its row, i.e. not C-contiguous.
            wide = np.zeros((4, 4), dtype=np.int32)
            wide[:, 0:2] = points
            view = wide[:, 0:2]
            self.assertFalse(view.flags["C_CONTIGUOUS"])
            self.assertEqual(
                "cube", classify_shape_from_features(extract_contour_features(view))
            )

    def test_non_numeric_dtype_is_rejected_cleanly(self) -> None:
        # Must be InvalidInputError, not a bare TypeError from the coercion.
        with self.assertRaises(InvalidInputError):
            extract_contour_features(np.array([["a", "b"]], dtype=object))

    def test_smooth_hexagon_is_currently_named_cylinder(self) -> None:
        """Documented limitation, not desired behaviour.

        A regular hexagon is `hexagonal_prism` in the seven-class vocabulary, but
        the ported rules return `cylinder` for it (measured: circularity 0.824,
        min-area-rect ratio 0.875, ellipse-area ratio 0.962). This test pins that
        known-wrong answer so the limitation is visible in code and cannot change
        silently. It must be replaced when real on-site data lets the rules be
        extended - never used to justify feeding this into the box decision.

        The hexagon is rasterised and re-extracted so the contour carries the
        boundary jitter a real camera blob has; a bare 6-vertex array is too
        jagged and lands on `unknown` instead.
        """

        import cv2

        canvas = np.zeros((120, 120), dtype=np.uint8)
        hexagon = np.array(
            [
                [int(round(60 + 40 * math.cos(a))), int(round(60 + 40 * math.sin(a)))]
                for a in (2 * math.pi * i / 6 for i in range(6))
            ],
            dtype=np.int32,
        )
        cv2.fillPoly(canvas, [hexagon], 255)
        contours = cv2.findContours(canvas, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]
        largest = max(contours, key=cv2.contourArea)

        measured = extract_contour_features(largest)
        self.assertEqual(6, measured.polygon_corner_count)
        self.assertEqual("cylinder", classify_shape_from_features(measured))

    def green_square_image(self, size: int = 100, box: int = 60):
        image = np.zeros((size, size, 3), dtype=np.uint8)
        offset = (size - box) // 2
        image[offset : offset + box, offset : offset + box] = (0, 255, 0)
        return image

    def test_green_square_roi_is_classified_as_a_cube(self) -> None:
        self.assertEqual(
            "cube",
            extract_and_classify_roi(self.green_square_image(), (36, 95, 35), (84, 255, 255)),
        )

    def test_red_square_on_a_white_tray_is_classified_as_a_cube(self) -> None:
        import cv2

        image = np.full((80, 80, 3), 255, dtype=np.uint8)
        # White has S=0, so the saturation floor alone excludes the tray.
        self.assertIsNone(extract_and_classify_roi(image, (0, 100, 80), (10, 255, 255)))
        cv2.rectangle(image, (15, 15), (65, 65), (0, 0, 255), -1)
        self.assertEqual(
            "cube", extract_and_classify_roi(image, (0, 100, 80), (10, 255, 255))
        )

    def test_tiny_blob_is_below_the_area_gate(self) -> None:
        self.assertIsNone(
            extract_and_classify_roi(
                self.green_square_image(box=5), (36, 95, 35), (84, 255, 255)
            )
        )

    def test_colour_window_that_matches_nothing_returns_none(self) -> None:
        # Blue window against a green square.
        self.assertIsNone(
            extract_and_classify_roi(
                self.green_square_image(), (105, 95, 30), (137, 255, 255)
            )
        )

    def test_non_image_roi_is_rejected(self) -> None:
        with self.assertRaises(InvalidInputError):
            extract_and_classify_roi(
                np.zeros((10, 10), dtype=np.uint8), (0, 0, 0), (179, 255, 255)
            )

    def test_empty_roi_is_rejected(self) -> None:
        # cv2.cvtColor raises on an empty image; it must surface as bad input.
        with self.assertRaises(InvalidInputError):
            extract_and_classify_roi(
                np.zeros((0, 0, 3), dtype=np.uint8), (0, 0, 0), (179, 255, 255)
            )

    def test_malformed_hsv_bounds_are_rejected(self) -> None:
        image = self.green_square_image()
        cases = {
            "too_short": ((36, 95), (84, 255, 255)),
            "out_of_range": ((36, 95, 35), (84, 255, 300)),
            "negative": ((-1, 95, 35), (84, 255, 255)),
            "non_integer": ((36.5, 95, 35), (84, 255, 255)),
        }
        for name, (lower, upper) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(InvalidInputError):
                    extract_and_classify_roi(image, lower, upper)

    def test_bad_extra_range_is_rejected(self) -> None:
        with self.assertRaises(InvalidInputError):
            extract_and_classify_roi(
                self.green_square_image(), (36, 95, 35), (84, 255, 255),
                extra_ranges=[((173, 95, 35), (179, 255, 999))],
            )


if __name__ == "__main__":
    unittest.main()
