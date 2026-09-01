"""Batch inference and single-target reacquisition orchestration."""

from __future__ import annotations

from .backends.base import InferenceBackend
from .config import InferenceConfig
from .coordinates import CoordinateTransform, PixelCenterTransform
from .errors import AmbiguousReacquireError, VisionError
from .postprocess import postprocess
from .types import (
    BatchResult,
    DetectionResult,
    ImageLike,
    InferenceIssue,
    ReacquireResult,
    ResultStatus,
)


def _validate_task_id(task_id: int) -> None:
    if not isinstance(task_id, int) or not 0 <= task_id <= 65535:
        from .errors import InvalidInputError

        raise InvalidInputError("task_id must be an integer within [0, 65535]")


class VisionPipeline:
    def __init__(
        self,
        config: InferenceConfig,
        backend: InferenceBackend,
        coordinate_transform: CoordinateTransform | None = None,
    ) -> None:
        self.config = config
        self.backend = backend
        self.coordinate_transform = coordinate_transform or PixelCenterTransform()

    def infer_batch(self, task_id: int, image: ImageLike) -> BatchResult:
        try:
            _validate_task_id(task_id)
            backend_output = self.backend.infer(image)
            raw_detections = postprocess(backend_output, self.config)
            detections: list[DetectionResult] = []
            for target_seq, raw in enumerate(raw_detections, start=1):
                coordinate = self.coordinate_transform.transform(raw.bbox)
                detections.append(
                    DetectionResult(
                        target_seq=target_seq,
                        class_id=raw.class_id,
                        class_name=self.config.class_names[raw.class_id],
                        confidence=float(raw.confidence),
                        bbox=raw.bbox,
                        center_pixel=raw.bbox.center,
                        coordinate=coordinate,
                    )
                )
            return BatchResult(
                task_id=task_id,
                status=ResultStatus.OK,
                backend=self.backend.name,
                image_width=backend_output.image_width,
                image_height=backend_output.image_height,
                detections=tuple(detections),
            )
        except VisionError as exc:
            return BatchResult(
                task_id=task_id if isinstance(task_id, int) else -1,
                status=ResultStatus.FAILED,
                backend=self.backend.name,
                issues=(InferenceIssue(exc.code, str(exc)),),
            )
        except Exception as exc:  # fail closed at untrusted backend boundary
            return BatchResult(
                task_id=task_id if isinstance(task_id, int) else -1,
                status=ResultStatus.FAILED,
                backend=self.backend.name,
                issues=(InferenceIssue("UNEXPECTED_BACKEND_FAILURE", str(exc)),),
            )

    def reacquire(
        self,
        task_id: int,
        target_seq: int,
        expected_class_id: int,
        image: ImageLike,
    ) -> ReacquireResult:
        try:
            if not isinstance(target_seq, int) or not 1 <= target_seq <= 255:
                from .errors import InvalidInputError

                raise InvalidInputError("target_seq must be an integer within [1, 255]")
            if expected_class_id not in self.config.class_names:
                from .errors import UnknownClassError

                raise UnknownClassError(
                    f"expected class_id {expected_class_id} is absent from configured dataset classes"
                )
            batch = self.infer_batch(task_id, image)
            if batch.status is ResultStatus.FAILED:
                return ReacquireResult(
                    task_id=task_id,
                    target_seq=target_seq,
                    status=ResultStatus.FAILED,
                    backend=self.backend.name,
                    issues=batch.issues,
                )
            matches = [item for item in batch.detections if item.class_id == expected_class_id]
            if len(matches) != 1:
                raise AmbiguousReacquireError(
                    f"expected exactly one class_id {expected_class_id} candidate, found {len(matches)}"
                )
            match = matches[0]
            detection = DetectionResult(
                target_seq=target_seq,
                class_id=match.class_id,
                class_name=match.class_name,
                confidence=match.confidence,
                bbox=match.bbox,
                center_pixel=match.center_pixel,
                coordinate=match.coordinate,
            )
            return ReacquireResult(
                task_id=task_id,
                target_seq=target_seq,
                status=ResultStatus.OK,
                backend=self.backend.name,
                detection=detection,
            )
        except VisionError as exc:
            return ReacquireResult(
                task_id=task_id if isinstance(task_id, int) else -1,
                target_seq=target_seq if isinstance(target_seq, int) else -1,
                status=ResultStatus.FAILED,
                backend=self.backend.name,
                issues=(InferenceIssue(exc.code, str(exc)),),
            )
