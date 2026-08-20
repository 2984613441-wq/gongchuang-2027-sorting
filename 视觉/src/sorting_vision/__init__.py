"""Platform-neutral inference core for the smart sorting vision subsystem."""

from .config import InferenceConfig
from .coordinates import AffineCoordinateTransform, PixelCenterTransform
from .errors import AmbiguousTargetError
from .pipeline import VisionPipeline
from .single_target import (
    SingleTargetLoopConfig,
    SingleTargetResult,
    format_diagnostic_text,
    process_single_target_frame,
    render_diagnostic,
    run_vision_loop,
    to_single_target_json,
)
from .types import (
    BatchResult,
    BoundingBox,
    DetectionResult,
    FakeImage,
    RawDetection,
    ReacquireResult,
    ResultStatus,
)

__all__ = [
    "AffineCoordinateTransform",
    "AmbiguousTargetError",
    "BatchResult",
    "BoundingBox",
    "DetectionResult",
    "FakeImage",
    "SingleTargetLoopConfig",
    "SingleTargetResult",
    "format_diagnostic_text",
    "InferenceConfig",
    "PixelCenterTransform",
    "process_single_target_frame",
    "RawDetection",
    "ReacquireResult",
    "render_diagnostic",
    "ResultStatus",
    "run_vision_loop",
    "to_single_target_json",
    "VisionPipeline",
]
