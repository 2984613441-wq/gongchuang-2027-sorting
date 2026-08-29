"""Coordinate conversion interfaces. No project-specific calibration is hard-coded."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from .errors import ConfigurationError, CoordinateOutOfBoundsError
from .types import BoundingBox, Coordinate


class CoordinateTransform(Protocol):
    def transform(self, bbox: BoundingBox) -> Coordinate: ...


class PixelCenterTransform:
    """Diagnostic-only transform. Pixel centers are never motion ready."""

    def transform(self, bbox: BoundingBox) -> Coordinate:
        x, y = bbox.center
        return Coordinate(x=x, y=y, frame="image_pixel", unit="pixel", calibrated=False)


@dataclass(frozen=True)
class AffineCoordinateTransform:
    """Explicitly injected 2x3 affine transform with verified output limits."""

    matrix: tuple[tuple[float, float, float], tuple[float, float, float]]
    x_bounds: tuple[float, float]
    y_bounds: tuple[float, float]
    frame: str
    unit: str
    calibration_id: str

    def __post_init__(self) -> None:
        if not (
            isinstance(self.matrix, (tuple, list))
            and len(self.matrix) == 2
            and all(
                isinstance(row, (tuple, list)) and len(row) == 3
                for row in self.matrix
            )
        ):
            raise ConfigurationError("affine matrix must have shape 2x3")
        flattened = tuple(value for row in self.matrix for value in row)
        if not all(isinstance(value, (int, float)) and isfinite(value) for value in flattened):
            raise ConfigurationError("affine matrix values must be finite")
        for name, bounds in (("x_bounds", self.x_bounds), ("y_bounds", self.y_bounds)):
            if not (
                isinstance(bounds, (tuple, list))
                and len(bounds) == 2
                and all(
                    isinstance(value, (int, float)) and isfinite(value)
                    for value in bounds
                )
            ):
                raise ConfigurationError(f"{name} must contain two finite numbers")
        if not self.x_bounds[0] < self.x_bounds[1] or not self.y_bounds[0] < self.y_bounds[1]:
            raise ConfigurationError("coordinate output bounds must be strictly increasing")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.frame, self.unit, self.calibration_id)
        ):
            raise ConfigurationError("frame, unit, and calibration_id must be explicit")

    def transform(self, bbox: BoundingBox) -> Coordinate:
        pixel_x, pixel_y = bbox.center
        x = self.matrix[0][0] * pixel_x + self.matrix[0][1] * pixel_y + self.matrix[0][2]
        y = self.matrix[1][0] * pixel_x + self.matrix[1][1] * pixel_y + self.matrix[1][2]
        if not self.x_bounds[0] <= x <= self.x_bounds[1]:
            raise CoordinateOutOfBoundsError(
                f"transformed x={x} is outside configured bounds {self.x_bounds}"
            )
        if not self.y_bounds[0] <= y <= self.y_bounds[1]:
            raise CoordinateOutOfBoundsError(
                f"transformed y={y} is outside configured bounds {self.y_bounds}"
            )
        return Coordinate(
            x=x,
            y=y,
            frame=self.frame,
            unit=self.unit,
            calibrated=True,
            calibration_id=self.calibration_id,
        )
