"""Geometric shape classification from an item's 2D contour (OpenCV fallback).

Why this module exists
----------------------
``sort_plan`` takes the item's shape from the detector's ``class_id``. This
module is the complementary, model-free path: it derives the shape from the
geometry of a colour-segmented blob, so it can still produce an answer when no
model is loaded (the MaixCAM chain), when a class is under-trained, or when a
second opinion on a detector's ``class_id`` is wanted.

Provenance
----------
The feature set and the decision rules are ported from the archived MaixCAM
script ``archive/_B档金贵-20261002/视觉V6-03_历史版本与验证/stage1_contour_v3.py``
(function ``shape_from_contour``, lines 45-83).

What that provenance does and does not buy:

* The archived check next to it, ``stage1_contour_checks/results.json``, records
  ``"host_opencv": "5.0.0"`` and says of itself at line 253: "Existing
  screenshots contain overlays. This is not raw-camera or on-device
  verification." So these thresholds come from a **host-side** check on
  screenshots, not from on-device acceptance. Do not read the port as hardware
  validation.
* ``stage1_v3_color_first_checks.json`` belongs to the *colour-first* variant;
  its cases are labelled "same contour, mapped shape", so it never exercises
  ``shape_from_contour`` and says nothing about the rules below.

Note that the file the original task brief pointed at,
``视觉V6-01_当前运行_V6/stage1_color_v6_stable.py``, does **not** contain a shape
classifier: its docstring states "不测量轮廓形状", and it derives shape from the
``COLOR_TO_MATERIAL`` colour lookup (line 111). Its contour code is an area and
bounding-box *filter*, not a classifier. The rules below therefore come from
``stage1_contour_v3.py``, not from that file.

Scope limit - read before trusting an answer
--------------------------------------------
The archived rule set was developed for a scene holding only the three shapes
whose flat face points up (``cube``, ``cylinder``, ``triangular_prism``) on a
white tray with separated items under a fixed top-down camera. It does **not**
attempt the other four vocabulary classes (``cuboid``, ``hexagonal_prism``,
``pentagonal_prism``, ``square_pyramid``): inventing thresholds for those without
calibration data would be worse than returning ``unknown``.

A return of ``unknown`` is therefore always safe. A return of ``cube``,
``cylinder`` or ``triangular_prism`` is **not** a guarantee that the item is one
of those three, because the rules only ever see a 2D silhouette. Measured
against opencv-python-headless 5.0.0.93 on smooth synthetic polygons, a regular
**hexagon** and a regular **octagon** are both returned as ``cylinder``
(hexagon: circularity 0.824, min-area-rect ratio 0.875, ellipse-area ratio
0.962). ``hexagonal_prism`` is a real member of the seven-class vocabulary, so
that is a confident wrong answer - and it is inherited verbatim from the archive,
which never saw a hexagon.

Consequence: this module must not silently drive the box decision. It is
deliberately not wired into ``sort_plan``; see ``视觉/README.md``.

This is a hypothesis generator, not a calibrated measurement. Every threshold
here is empirical and needs on-site revalidation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

try:  # OpenCV and numpy are optional: the pure rule layer must import without them.
    import cv2
    import numpy as np

    CV2_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised on hosts without OpenCV
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    CV2_AVAILABLE = False

from .constants import MIN_CONTOUR_AREA_PX
from .errors import DependencyUnavailableError, InvalidInputError

# --- vocabulary -------------------------------------------------------------

UNKNOWN_SHAPE = "unknown"

#: The seven shape classes the trained detector is documented to emit.
SHAPE_LABELS: tuple[str, ...] = (
    "cube",
    "cuboid",
    "cylinder",
    "hexagonal_prism",
    "pentagonal_prism",
    "square_pyramid",
    "triangular_prism",
)

#: The subset this geometric classifier can actually decide (see module docstring).
CLASSIFIABLE_SHAPES: tuple[str, ...] = ("cube", "cylinder", "triangular_prism")

# --- rule thresholds --------------------------------------------------------
# All values are ported verbatim from stage1_contour_v3.py::shape_from_contour.
# They are empirical and scenario-specific (white tray, fixed top-down camera,
# separated items) and must be revalidated on site.

SOLIDITY_MIN = 0.90
"""Below this, the blob is too concave/ragged to name; return ``unknown``."""

POLYGON_EPSILON_FRACTION = 0.025
"""approxPolyDP epsilon for the main polygon, as a fraction of perimeter."""

TRIANGLE_EPSILON_FRACTION = 0.035
"""Looser epsilon used only for the triangle hypothesis. Item sides and
chamfers add a small extra vertex to a triangle, so the strict polygon is
allowed to over-segment before the triangle test is applied."""

TRIANGLE_RECT_RATIO_MIN = 0.50
"""Minimum min-area-rect aspect ratio accepted as a triangle."""

TRIANGLE_AREA_COVERAGE_MIN = 0.78
"""The fitted triangle must cover this fraction of the real contour area,
otherwise an arbitrary polygon would be accepted as a triangle."""

CUBE_RECT_RATIO_MIN = 0.74
CUBE_RECT_EXTENT_MIN = 0.84
CUBE_CORNER_COSINE_MAX = 0.35
"""A square has four right angles -> |cos| near 0. A skewed quad exceeds this."""

CIRCLE_CIRCULARITY_MIN = 0.80
CIRCLE_RECT_RATIO_MIN = 0.68
CIRCLE_ELLIPSE_AREA_RATIO_MIN = 0.90
CIRCLE_ELLIPSE_AREA_RATIO_MAX = 1.08
"""A circle must roughly match its fitted ellipse.

Do NOT rely on this band to exclude other round-ish polygons: measured, a
regular hexagon lands at 0.962 and a regular octagon at 0.994 - both inside the
band - so both are returned as ``cylinder``. See the module docstring."""

QUAD_CORNER_COUNT = 4
TRIANGLE_CORNER_COUNT = 3
MIN_ELLIPSE_FIT_POINTS = 5
"""cv2.fitEllipse needs at least this many points."""


@dataclass(frozen=True)
class ContourFeatures:
    """Geometric descriptors measured from a single contour.

    Instances can be built by hand: ``classify_shape_from_features`` never
    touches OpenCV, so the rule layer is testable on hosts without it.
    """

    area: float
    perimeter: float
    hull_area: float
    contour_point_count: int
    polygon_corner_count: int
    polygon_convex: bool
    triangle_corner_count: int
    triangle_convex: bool
    triangle_area_coverage: float
    min_area_rect_ratio: float
    min_area_rect_extent: float
    max_corner_cosine: float
    ellipse_area_ratio: float
    bbox_aspect_ratio: float
    bbox_extent: float

    @property
    def solidity(self) -> float:
        """Contour area over convex-hull area."""
        return self.area / self.hull_area if self.hull_area > 0 else 0.0

    @property
    def circularity(self) -> float:
        """``4*pi*area / perimeter^2``; 1.0 for a perfect circle."""
        if self.perimeter <= 0:
            return 0.0
        return (4.0 * math.pi * self.area) / (self.perimeter * self.perimeter)


def _max_corner_cosine(polygon) -> float:
    """Largest |cos| between adjacent edges of a 4-gon; 1.0 when undefined."""

    points = polygon.reshape(-1, 2).astype(float)
    if len(points) != QUAD_CORNER_COUNT:
        return 1.0
    worst = 0.0
    for index in range(QUAD_CORNER_COUNT):
        incoming = points[(index - 1) % QUAD_CORNER_COUNT] - points[index]
        outgoing = points[(index + 1) % QUAD_CORNER_COUNT] - points[index]
        norm = float(np.linalg.norm(incoming) * np.linalg.norm(outgoing))
        cosine = abs(float(np.dot(incoming, outgoing))) / norm if norm else 1.0
        worst = max(worst, cosine)
    return worst


def _ellipse_area_ratio(contour, area: float) -> float:
    """``area / fitted_ellipse_area``; 0.0 when it cannot be computed.

    A failed fit returns 0.0, which is outside the accepted band, so the caller
    falls through to ``unknown``. The degradation is deliberately toward the safe
    answer rather than toward a guessed class.
    """

    if area <= 0 or len(contour) < MIN_ELLIPSE_FIT_POINTS:
        return 0.0
    try:
        (_, _), (ellipse_width, ellipse_height), _ = cv2.fitEllipse(contour)
    except cv2.error:  # pragma: no cover - degenerate contour
        return 0.0
    ellipse_area = math.pi * ellipse_width * ellipse_height / 4.0
    return area / ellipse_area if ellipse_area > 0 else 0.0


def extract_contour_features(contour) -> ContourFeatures:
    """Measure ``ContourFeatures`` from an OpenCV contour.

    Args:
        contour: an ``(N, 1, 2)`` or ``(N, 2)`` OpenCV contour. Any numeric dtype
            and memory layout is accepted; the array is normalised internally.

    Raises:
        DependencyUnavailableError: OpenCV/numpy is not importable.
        InvalidInputError: the contour is not a non-empty 2-D point array of a
            concrete numeric dtype.
    """

    if not CV2_AVAILABLE:
        raise DependencyUnavailableError(
            "OpenCV (cv2) and numpy are required for contour feature extraction"
        )
    if not isinstance(contour, np.ndarray):
        raise InvalidInputError("contour must be a numpy array")
    if contour.size == 0:
        raise InvalidInputError("contour is empty")
    if contour.ndim not in (2, 3) or contour.shape[-1] != 2:
        raise InvalidInputError("contour must have shape (N, 1, 2) or (N, 2)")

    # OpenCV's geometry functions accept only CV_32F/CV_32S point arrays:
    # float64, uint8, uint16, bool, object and non-contiguous views all raise
    # cv2.error. Normalise to a contiguous float32 array instead of letting that
    # escape, so the documented error contract above actually holds. float32
    # (rather than int32) is used so fractional coordinates are not truncated.
    try:
        contour = np.ascontiguousarray(contour, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise InvalidInputError(f"contour must have a numeric dtype: {exc}") from exc

    area = float(cv2.contourArea(contour))
    perimeter = float(cv2.arcLength(contour, closed=True))
    hull_area = float(cv2.contourArea(cv2.convexHull(contour)))

    polygon = cv2.approxPolyDP(contour, POLYGON_EPSILON_FRACTION * perimeter, True)
    triangle = cv2.approxPolyDP(contour, TRIANGLE_EPSILON_FRACTION * perimeter, True)

    (_, _), (rect_width, rect_height), _ = cv2.minAreaRect(contour)
    rect_long = max(rect_width, rect_height)
    rect_short = min(rect_width, rect_height)
    rect_ratio = rect_short / rect_long if rect_long > 0 else 0.0
    rect_extent = area / (rect_width * rect_height) if rect_width * rect_height > 0 else 0.0

    triangle_area = float(cv2.contourArea(triangle)) if len(triangle) else 0.0
    triangle_coverage = triangle_area / area if area > 0 else 0.0

    circularity = (
        (4.0 * math.pi * area) / (perimeter * perimeter) if perimeter > 0 else 0.0
    )
    # Mirror the archive's laziness: it fitted the ellipse only inside the round
    # branch, after these cheap preconditions. Fitting for every contour would
    # cost a fit per contour for no classification benefit.
    circle_preconditions_met = (
        len(polygon) >= MIN_ELLIPSE_FIT_POINTS
        and circularity >= CIRCLE_CIRCULARITY_MIN
        and rect_ratio >= CIRCLE_RECT_RATIO_MIN
        and len(contour) >= MIN_ELLIPSE_FIT_POINTS
    )

    x, y, box_width, box_height = cv2.boundingRect(contour)

    return ContourFeatures(
        area=area,
        perimeter=perimeter,
        hull_area=hull_area,
        contour_point_count=len(contour),
        polygon_corner_count=len(polygon),
        polygon_convex=bool(cv2.isContourConvex(polygon)),
        triangle_corner_count=len(triangle),
        triangle_convex=bool(cv2.isContourConvex(triangle)),
        triangle_area_coverage=triangle_coverage,
        min_area_rect_ratio=rect_ratio,
        min_area_rect_extent=rect_extent,
        max_corner_cosine=_max_corner_cosine(polygon)
        if len(polygon) == QUAD_CORNER_COUNT
        else 1.0,
        ellipse_area_ratio=_ellipse_area_ratio(contour, area)
        if circle_preconditions_met
        else 0.0,
        bbox_aspect_ratio=box_width / box_height if box_height > 0 else 0.0,
        bbox_extent=area / (box_width * box_height) if box_width * box_height > 0 else 0.0,
    )


def classify_shape_from_features(features: ContourFeatures) -> str:
    """Name the shape, or return ``UNKNOWN_SHAPE``.

    Rule order is the archived order and matters: the triangle branch is tried
    before the quad branch because a looser polygon fit is required for it, and
    the round branch last because it accepts the most polygons.

    ``bbox_*`` fields are recorded for diagnostics only and never decide a
    class: a bounding box cannot separate a cube seen from the top from one seen
    at an angle, whereas the min-area rectangle and the corner angles can.
    """

    if features.solidity < SOLIDITY_MIN:
        return UNKNOWN_SHAPE

    if (
        features.triangle_corner_count == TRIANGLE_CORNER_COUNT
        and features.triangle_convex
        and features.min_area_rect_ratio >= TRIANGLE_RECT_RATIO_MIN
        and features.triangle_area_coverage >= TRIANGLE_AREA_COVERAGE_MIN
    ):
        return "triangular_prism"

    if (
        features.polygon_corner_count == QUAD_CORNER_COUNT
        and features.polygon_convex
        and features.min_area_rect_ratio >= CUBE_RECT_RATIO_MIN
        and features.min_area_rect_extent >= CUBE_RECT_EXTENT_MIN
        and features.max_corner_cosine <= CUBE_CORNER_COSINE_MAX
    ):
        return "cube"

    if (
        features.polygon_corner_count >= MIN_ELLIPSE_FIT_POINTS
        and features.circularity >= CIRCLE_CIRCULARITY_MIN
        and features.min_area_rect_ratio >= CIRCLE_RECT_RATIO_MIN
        and features.contour_point_count >= MIN_ELLIPSE_FIT_POINTS
        and CIRCLE_ELLIPSE_AREA_RATIO_MIN
        <= features.ellipse_area_ratio
        <= CIRCLE_ELLIPSE_AREA_RATIO_MAX
    ):
        return "cylinder"

    return UNKNOWN_SHAPE


def _merge_hsv_mask(hsv, ranges: Sequence[Sequence[Sequence[int]]]):
    """Boolean-OR one or more ``(lower, upper)`` HSV ranges into a mask.

    Raises:
        InvalidInputError: a bound is not three integers within 0..255. OpenCV's
            ``inRange`` would otherwise raise a bare ``OverflowError`` (or accept
            a silently truncated value) for out-of-range bounds.
    """

    mask = None
    for lower, upper in ranges:
        for bound in (lower, upper):
            if len(bound) != 3 or any(
                not isinstance(component, int) or isinstance(component, bool)
                for component in bound
            ):
                raise InvalidInputError("HSV bounds must be three integers")
            if any(component < 0 or component > 255 for component in bound):
                raise InvalidInputError("HSV bounds must be within 0..255")
        part = cv2.inRange(
            hsv,
            np.array(lower, dtype=np.uint8),
            np.array(upper, dtype=np.uint8),
        )
        mask = part if mask is None else cv2.bitwise_or(mask, part)
    return mask


def extract_and_classify_roi(
    roi_bgr,
    color_mask_lower: Sequence[int],
    color_mask_upper: Sequence[int],
    *,
    extra_ranges: Sequence[Sequence[Sequence[int]]] = (),
    min_area: float = MIN_CONTOUR_AREA_PX,
) -> str | None:
    """Colour-segment an item crop, take the largest blob, and name its shape.

    Only ``stage1_contour_v3.py::shape_from_contour``'s rules were ported. The
    gates that script applied *around* that function were deliberately **not**
    reimplemented, because they assume a full 320x320 frame rather than a tight
    crop:

    * its frame-contact veto (``clipped`` -> ``unknown``) would reject nearly
      every real crop, since a detector's bounding box is meant to touch the item;
    * its relative area gate (``0.0015 .. 0.22`` of the frame) has no fixed pixel
      equivalent for an arbitrary crop - it is 153.6 px only at 320x320;
    * its morphological open/close was tuned for a full-frame mask.

    Callers must therefore pass an adequately padded crop and treat the result
    as one hypothesis among several, not as a verdict.

    Args:
        roi_bgr: BGR crop of one item.
        color_mask_lower: ``[H, S, V]`` lower bound of the colour window.
        color_mask_upper: ``[H, S, V]`` upper bound of the colour window.
        extra_ranges: further ``(lower, upper)`` pairs OR-ed into the mask. A
            hue that wraps around 0/179 (red) needs two ranges.
        min_area: blobs smaller than this are treated as noise.

    Returns:
        A shape label, or ``None`` when there is no blob big enough to judge.

    Raises:
        DependencyUnavailableError: OpenCV/numpy is not importable.
        InvalidInputError: the crop is not a non-empty 3-channel image array, or
            an HSV bound is malformed.
    """

    if not CV2_AVAILABLE:
        raise DependencyUnavailableError(
            "OpenCV (cv2) and numpy are required for contour-based shape features"
        )
    if not isinstance(roi_bgr, np.ndarray):
        raise InvalidInputError("roi_bgr must be a numpy array")
    if roi_bgr.ndim != 3 or roi_bgr.shape[2] != 3:
        raise InvalidInputError("roi_bgr must be an HxWx3 BGR image")
    if roi_bgr.shape[0] == 0 or roi_bgr.shape[1] == 0:
        # cv2.cvtColor raises on an empty image; reject it as bad input instead.
        raise InvalidInputError("roi_bgr must not be empty")

    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    ranges = [(color_mask_lower, color_mask_upper), *extra_ranges]
    mask = _merge_hsv_mask(hsv, ranges)

    contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea)
    if float(cv2.contourArea(largest)) < min_area:
        return None

    return classify_shape_from_features(extract_contour_features(largest))


def rgba_roi_to_bgr_array(
    pixels: Sequence[int],
    image_width: int,
    image_height: int,
    bbox,
):
    """Convert a flat RGBA buffer crop into an ``HxWx3`` BGR numpy array.

    This is the adapter ``sort_plan.classify_and_plan`` would need, because it
    receives a flat RGBA byte sequence rather than an image array. It is not yet
    wired into that function on purpose: see the module docstring and
    ``CHANGELOG_20261011.md`` - changing the box decision path needs its own
    review.

    Raises:
        DependencyUnavailableError: numpy is not importable.
        InvalidInputError: ``pixels`` is not a sized sequence of 0..255 values,
            the buffer length does not match the image, ``bbox`` lacks numeric
            bounds, or the box is not a non-empty box inside the image.
    """

    try:
        import numpy as _np
    except ImportError as exc:  # pragma: no cover
        raise DependencyUnavailableError("numpy is required to slice an RGBA buffer") from exc

    for name, value in (("image_width", image_width), ("image_height", image_height)):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise InvalidInputError(f"{name} must be a positive integer")

    if not hasattr(pixels, "__len__"):
        raise InvalidInputError("pixels must be a sized sequence of RGBA values")
    if len(pixels) != image_width * image_height * 4:
        raise InvalidInputError(
            "RGBA buffer length must be image_width * image_height * 4"
        )

    bounds = []
    for name in ("x1", "y1", "x2", "y2"):
        value = getattr(bbox, name, None)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise InvalidInputError(f"bbox.{name} must be a number")
        bounds.append(int(value))
    x1, y1, x2, y2 = bounds
    if not (0 <= x1 < x2 <= image_width) or not (0 <= y1 < y2 <= image_height):
        raise InvalidInputError("bbox must be a non-empty box inside the image")

    try:
        frame = _np.asarray(pixels, dtype=_np.uint8).reshape(
            image_height, image_width, 4
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvalidInputError(f"pixels must be 0..255 RGBA values: {exc}") from exc
    rgba = frame[y1:y2, x1:x2]
    return _np.ascontiguousarray(rgba[:, :, [2, 1, 0]])
