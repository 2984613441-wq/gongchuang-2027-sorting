"""Platform-neutral inference core for the smart sorting vision subsystem."""

from .color_quant import color_name, dominant_color, mmcq, rgb_to_hsl
from .config import InferenceConfig
from .coordinates import AffineCoordinateTransform, PixelCenterTransform
from .errors import AmbiguousTargetError
from .info_decode import (
    FakeInfoDecoder,
    InfoDecodeConfig,
    InfoDecoder,
    InfoResult,
)
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
from .sort_plan import (
    DEFAULT_COLOR_VOCABULARY,
    PlacedItem,
    SortPlan,
    TooManyGroupsError,
    UnknownColorError,
    build_sort_plan,
    classify_and_plan,
    color_name_to_id,
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
    "DEFAULT_COLOR_VOCABULARY",
    "FakeImage",
    "FakeInfoDecoder",
    "InfoDecodeConfig",
    "InfoDecoder",
    "InfoResult",
    "SingleTargetLoopConfig",
    "SingleTargetResult",
    "SortPlan",
    "TooManyGroupsError",
    "UnknownColorError",
    "PlacedItem",
    "build_sort_plan",
    "classify_and_plan",
    "color_name",
    "color_name_to_id",
    "dominant_color",
    "format_diagnostic_text",
    "InferenceConfig",
    "mmcq",
    "PixelCenterTransform",
    "process_single_target_frame",
    "RawDetection",
    "ReacquireResult",
    "render_diagnostic",
    "ResultStatus",
    "rgb_to_hsl",
    "run_vision_loop",
    "to_single_target_json",
    "VisionPipeline",
]
