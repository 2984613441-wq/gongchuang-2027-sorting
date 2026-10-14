"""Depth fusion for resolving shape ambiguities using ToF sensor data.

This module provides depth-based disambiguation for shapes that have identical
or similar top-view projections. Three ambiguity groups are addressed:

1. Cylinder vs Sphere (both circular top-view)
2. Triangular prism vs Regular tetrahedron (both triangular top-view)
3. Cube vs Square pyramid (both square top-view)

The disambiguation uses height thresholds derived from standard geometric
proportions and requires a calibrated ToF sensor returning object height in mm.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# Height ratio thresholds (height / base_width) for disambiguation
# Initial values based on standard geometry; require on-site calibration
CYLINDER_HEIGHT_RATIO = 1.2  # Cylinders typically taller than spheres
SPHERE_HEIGHT_RATIO = 0.8    # Sphere height ≈ diameter

TRIANGULAR_PRISM_RATIO = 0.8  # Prism height > tetrahedron height
TETRAHEDRON_RATIO = 0.6       # Tetrahedron height ≈ 0.58 * edge_length

CUBE_RATIO = 0.1              # Cube height ≈ width (±10% tolerance)
PYRAMID_RATIO = 0.6           # Pyramid height ≈ 0.5-0.7 * base_width


@dataclass(frozen=True)
class DepthReading:
    """ToF sensor depth reading for one detected object."""
    height_mm: float  # Object height in millimeters (0.1mm resolution)
    confidence: float  # Sensor confidence [0, 1]


AmbiguousShape = Literal[
    "cylinder_or_sphere",
    "triangular_prism_or_tetrahedron",
    "cube_or_pyramid",
]

DisambiguatedShape = Literal[
    "cylinder", "sphere",
    "triangular_prism", "regular_tetrahedron",
    "cube", "square_pyramid",
]


def depth_disambiguate(
    yolo_shape: str,
    bbox_width_px: float,
    depth_reading: DepthReading,
    px_to_mm: float = 1.0,
) -> DisambiguatedShape | str:
    """Disambiguate YOLO shape using ToF depth measurement.

    Args:
        yolo_shape: Shape label from YOLO class_id (e.g., "cylinder", "cube").
        bbox_width_px: Bounding box width in pixels.
        depth_reading: ToF sensor height measurement.
        px_to_mm: Pixel-to-millimeter conversion factor (calibrated).

    Returns:
        Disambiguated shape label, or original yolo_shape if no ambiguity.

    Examples:
        >>> depth = DepthReading(height_mm=45.0, confidence=0.95)
        >>> depth_disambiguate("cylinder", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        'sphere'  # 45mm height < 50mm width * 0.8

        >>> depth = DepthReading(height_mm=65.0, confidence=0.95)
        >>> depth_disambiguate("cylinder", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        'cylinder'  # 65mm height > 50mm width * 1.2
    """
    # Low confidence → fall back to YOLO
    if depth_reading.confidence < 0.7:
        return yolo_shape

    # Convert bbox width to mm
    base_width_mm = bbox_width_px * px_to_mm
    if base_width_mm <= 0:
        return yolo_shape

    # Compute height ratio
    height_ratio = depth_reading.height_mm / base_width_mm

    # Disambiguate based on shape and height ratio
    if yolo_shape == "cylinder":
        # Group 1: Cylinder vs Sphere
        if height_ratio >= CYLINDER_HEIGHT_RATIO:
            return "cylinder"
        elif height_ratio <= SPHERE_HEIGHT_RATIO:
            return "sphere"
        else:
            # Ambiguous range: default to YOLO prediction
            return "cylinder"

    elif yolo_shape == "triangular_prism":
        # Group 2: Triangular prism vs Regular tetrahedron
        if height_ratio >= TRIANGULAR_PRISM_RATIO:
            return "triangular_prism"
        elif height_ratio <= TETRAHEDRON_RATIO:
            return "regular_tetrahedron"
        else:
            return "triangular_prism"

    elif yolo_shape == "cube":
        # Group 3: Cube vs Square pyramid
        if 1.0 - CUBE_RATIO <= height_ratio <= 1.0 + CUBE_RATIO:
            return "cube"  # Height ≈ width (within tolerance)
        elif height_ratio <= PYRAMID_RATIO:
            return "square_pyramid"
        else:
            return "cube"

    # No ambiguity for other shapes
    return yolo_shape


def get_ambiguity_group(shape: str) -> AmbiguousShape | None:
    """Return the ambiguity group for a shape, or None if unambiguous.

    Args:
        shape: Shape label from YOLO.

    Returns:
        Ambiguity group identifier, or None if shape has no depth ambiguity.
    """
    if shape in ("cylinder", "sphere"):
        return "cylinder_or_sphere"
    elif shape in ("triangular_prism", "regular_tetrahedron"):
        return "triangular_prism_or_tetrahedron"
    elif shape in ("cube", "square_pyramid"):
        return "cube_or_pyramid"
    else:
        return None


def requires_depth_disambiguation(shape: str) -> bool:
    """Check if a shape requires ToF depth to resolve ambiguity.

    Args:
        shape: Shape label from YOLO.

    Returns:
        True if shape is part of an ambiguous group.
    """
    return get_ambiguity_group(shape) is not None
