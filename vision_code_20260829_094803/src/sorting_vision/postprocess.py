"""Detection validation, confidence filtering, and class-aware NMS."""

from __future__ import annotations

from .config import InferenceConfig
from .errors import DuplicateDetectionError, EmptyDetectionError, UnknownClassError
from .types import BackendOutput, BoundingBox, RawDetection


def intersection_over_union(left: BoundingBox, right: BoundingBox) -> float:
    intersection_width = max(0.0, min(left.x2, right.x2) - max(left.x1, right.x1))
    intersection_height = max(0.0, min(left.y2, right.y2) - max(left.y1, right.y1))
    intersection = intersection_width * intersection_height
    union = left.area + right.area - intersection
    return intersection / union if union > 0 else 0.0


def non_max_suppression(
    detections: tuple[RawDetection, ...], iou_threshold: float
) -> tuple[tuple[RawDetection, ...], tuple[RawDetection, ...]]:
    kept: list[RawDetection] = []
    suppressed: list[RawDetection] = []
    for candidate in sorted(detections, key=lambda item: item.confidence, reverse=True):
        if any(
            candidate.class_id == selected.class_id
            and intersection_over_union(candidate.bbox, selected.bbox) > iou_threshold
            for selected in kept
        ):
            suppressed.append(candidate)
        else:
            kept.append(candidate)
    return tuple(kept), tuple(suppressed)


def postprocess(output: BackendOutput, config: InferenceConfig) -> tuple[RawDetection, ...]:
    output.validate_dimensions()
    validated: list[RawDetection] = []
    for detection in output.detections:
        detection.validate(output.image_width, output.image_height)
        if detection.class_id not in config.class_names:
            raise UnknownClassError(
                f"class_id {detection.class_id} is absent from configured dataset classes"
            )
        if detection.confidence >= config.confidence_threshold:
            validated.append(detection)
    if not validated:
        raise EmptyDetectionError("no detections remain after validation and confidence filtering")
    kept, suppressed = non_max_suppression(tuple(validated), config.nms_iou_threshold)
    if suppressed and config.reject_duplicates:
        raise DuplicateDetectionError(
            f"class-aware NMS found {len(suppressed)} overlapping duplicate detection(s)"
        )
    if len(kept) > config.max_detections:
        raise DuplicateDetectionError(
            f"detection count {len(kept)} exceeds configured maximum {config.max_detections}"
        )
    return kept
