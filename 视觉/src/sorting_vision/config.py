"""Validated configuration for inference. No mechanical calibration is embedded."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .constants import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_INPUT_HEIGHT,
    DEFAULT_INPUT_WIDTH,
    DEFAULT_MAX_DETECTIONS_BATCH,
    DEFAULT_NMS_IOU_THRESHOLD,
)
from .errors import ConfigurationError


@dataclass(frozen=True)
class InferenceConfig:
    backend: str = "fake"
    model_path: Path | None = None
    class_names: Mapping[int, str] = field(default_factory=dict)
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    nms_iou_threshold: float = DEFAULT_NMS_IOU_THRESHOLD
    input_size: tuple[int, int] = (DEFAULT_INPUT_WIDTH, DEFAULT_INPUT_HEIGHT)
    device: str = "cpu"
    max_detections: int = DEFAULT_MAX_DETECTIONS_BATCH
    reject_duplicates: bool = True

    def __post_init__(self) -> None:
        if not self.backend.strip():
            raise ConfigurationError("backend must be a non-empty name")
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ConfigurationError("confidence_threshold must be within [0, 1]")
        if not 0.0 <= self.nms_iou_threshold <= 1.0:
            raise ConfigurationError("nms_iou_threshold must be within [0, 1]")
        if len(self.input_size) != 2 or any(
            not isinstance(value, int) or value <= 0 for value in self.input_size
        ):
            raise ConfigurationError("input_size must contain two positive integers")
        if not self.device.strip():
            raise ConfigurationError("device must be a non-empty value")
        if not isinstance(self.max_detections, int) or self.max_detections <= 0:
            raise ConfigurationError("max_detections must be a positive integer")
        if not self.class_names:
            raise ConfigurationError("class_names must be supplied from the dataset metadata")
        for class_id, class_name in self.class_names.items():
            if not isinstance(class_id, int) or class_id < 0:
                raise ConfigurationError("class IDs must be non-negative integers")
            if not isinstance(class_name, str) or not class_name.strip():
                raise ConfigurationError("class names must be non-empty strings")

    @property
    def normalized_model_path(self) -> Path | None:
        return self.model_path.expanduser().resolve() if self.model_path else None
