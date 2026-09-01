"""Stable internal data objects. These are not the frozen binary wire format."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import Any

from .errors import InvalidDetectionError, InvalidInputError


class ResultStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"


@dataclass(frozen=True)
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float

    def validate(self, image_width: int, image_height: int) -> None:
        values = (self.x1, self.y1, self.x2, self.y2)
        if not all(isinstance(value, (int, float)) and isfinite(value) for value in values):
            raise InvalidDetectionError("bounding box values must be finite numbers")
        if not (0 <= self.x1 < self.x2 <= image_width):
            raise InvalidDetectionError(
                f"bounding box x range [{self.x1}, {self.x2}] is outside image width {image_width}"
            )
        if not (0 <= self.y1 < self.y2 <= image_height):
            raise InvalidDetectionError(
                f"bounding box y range [{self.y1}, {self.y2}] is outside image height {image_height}"
            )

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    @property
    def area(self) -> float:
        return (self.x2 - self.x1) * (self.y2 - self.y1)


@dataclass(frozen=True)
class RawDetection:
    class_id: int
    confidence: float
    bbox: BoundingBox

    def validate(self, image_width: int, image_height: int) -> None:
        if not isinstance(self.class_id, int) or self.class_id < 0:
            raise InvalidDetectionError("class_id must be a non-negative integer")
        if not isinstance(self.confidence, (int, float)) or not isfinite(self.confidence):
            raise InvalidDetectionError("confidence must be a finite number")
        if not 0.0 <= self.confidence <= 1.0:
            raise InvalidDetectionError("confidence must be within [0, 1]")
        self.bbox.validate(image_width, image_height)


@dataclass(frozen=True)
class BackendOutput:
    image_width: int
    image_height: int
    detections: tuple[RawDetection, ...]

    def validate_dimensions(self) -> None:
        if not isinstance(self.image_width, int) or self.image_width <= 0:
            raise InvalidInputError("backend image_width must be a positive integer")
        if not isinstance(self.image_height, int) or self.image_height <= 0:
            raise InvalidInputError("backend image_height must be a positive integer")


@dataclass(frozen=True)
class FakeImage:
    key: str
    width: int
    height: int
    corrupted: bool = False


@dataclass(frozen=True)
class Coordinate:
    x: float
    y: float
    frame: str
    unit: str
    calibrated: bool
    calibration_id: str | None = None


@dataclass(frozen=True)
class DetectionResult:
    target_seq: int
    class_id: int
    class_name: str
    confidence: float
    bbox: BoundingBox
    center_pixel: tuple[float, float]
    coordinate: Coordinate

    @property
    def motion_ready(self) -> bool:
        return self.coordinate.calibrated


@dataclass(frozen=True)
class InferenceIssue:
    code: str
    message: str


@dataclass(frozen=True)
class BatchResult:
    task_id: int
    status: ResultStatus
    backend: str
    image_width: int | None = None
    image_height: int | None = None
    detections: tuple[DetectionResult, ...] = field(default_factory=tuple)
    issues: tuple[InferenceIssue, ...] = field(default_factory=tuple)
    schema_version: str = "vision-diagnostic-v0.1"

    @property
    def motion_ready(self) -> bool:
        return (
            self.status is ResultStatus.OK
            and bool(self.detections)
            and all(detection.motion_ready for detection in self.detections)
        )


@dataclass(frozen=True)
class ReacquireResult:
    task_id: int
    target_seq: int
    status: ResultStatus
    backend: str
    detection: DetectionResult | None = None
    issues: tuple[InferenceIssue, ...] = field(default_factory=tuple)
    schema_version: str = "vision-diagnostic-v0.1"

    @property
    def motion_ready(self) -> bool:
        return (
            self.status is ResultStatus.OK
            and self.detection is not None
            and self.detection.motion_ready
        )


ImageLike = Any
