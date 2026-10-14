"""Platform-neutral inference core for the smart sorting vision subsystem."""

from .color_quant import color_name, dominant_color, mmcq, rgb_to_hsl
from .config import InferenceConfig
from .coordinates import AffineCoordinateTransform, PixelCenterTransform
from .drop_table import DropPoint, DropTable, DropTableError, ITEM_TASK_COORD_LIMIT
from .errors import AmbiguousTargetError
from .info_decode import (
    FakeInfoDecoder,
    InfoDecodeConfig,
    InfoDecoder,
    InfoResult,
)
from .pipeline import VisionPipeline
from .shape_features import (
    CLASSIFIABLE_SHAPES,
    SHAPE_LABELS,
    UNKNOWN_SHAPE,
    ContourFeatures,
    classify_shape_from_features,
    extract_and_classify_roi,
    extract_contour_features,
)
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
    BoxAssignment,
    PlacedItem,
    SortPlan,
    TooManyGroupsError,
    UnknownColorError,
    UnknownGroupError,
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
    "BoxAssignment",
    "CLASSIFIABLE_SHAPES",
    "ContourFeatures",
    "DetectionResult",
    "DropPoint",
    "DropTable",
    "DropTableError",
    "DEFAULT_COLOR_VOCABULARY",
    "FakeImage",
    "FakeInfoDecoder",
    "InfoDecodeConfig",
    "InfoDecoder",
    "InfoResult",
    "ITEM_TASK_COORD_LIMIT",
    "SHAPE_LABELS",
    "SingleTargetLoopConfig",
    "SingleTargetResult",
    "SortPlan",
    "TooManyGroupsError",
    "UNKNOWN_SHAPE",
    "UnknownColorError",
    "UnknownGroupError",
    "PlacedItem",
    "build_sort_plan",
    "classify_and_plan",
    "classify_shape_from_features",
    "color_name",
    "color_name_to_id",
    "dominant_color",
    "extract_and_classify_roi",
    "extract_contour_features",
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
