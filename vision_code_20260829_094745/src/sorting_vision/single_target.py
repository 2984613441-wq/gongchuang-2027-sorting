"""Single-target inference loop for the smart sorting vision subsystem.

This module adapts the desktop vision-loop skeleton to the V0.1 core's
fail-closed contracts. It deliberately replaces the template's silent
"pick the highest score" behavior with strict exactly-one-target checks.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, replace
from math import isfinite
from typing import Any, Callable, Protocol

from .config import InferenceConfig
from .coordinates import CoordinateTransform, PixelCenterTransform
from .errors import (
    AmbiguousTargetError,
    ConfigurationError,
    EmptyDetectionError,
    InvalidInputError,
    UnknownClassError,
    VisionError,
)
from .export import normalize_value
from .postprocess import postprocess
from .types import (
    BackendOutput,
    DetectionResult,
    ImageLike,
    InferenceIssue,
    ResultStatus,
)


class LoopBackend(Protocol):
    """Backend contract for the capture/infer/release loop."""

    name: str

    def capture(self) -> ImageLike | None: ...

    def infer(self, image: ImageLike) -> BackendOutput: ...

    def release(self) -> None: ...


@dataclass(frozen=True)
class SingleTargetLoopConfig:
    model_path: str
    labels: tuple[str, ...] = ()
    confidence: float = 0.35
    input_width: int = 448
    input_height: int = 448
    hmirror: bool = False
    vflip: bool = False
    rotation: int = 0
    source: str = "camera"
    camera_index: int = 0
    output_format: str = "text"
    max_frames: int | None = None
    min_confirm_frames: int = 1

    def validate(self) -> None:
        if not isinstance(self.model_path, str) or not self.model_path.strip():
            raise ConfigurationError("model_path must be a non-empty string")
        if (
            not isinstance(self.confidence, (int, float))
            or not isfinite(self.confidence)
            or not 0.0 <= self.confidence <= 1.0
        ):
            raise ConfigurationError("confidence must be a finite number within [0, 1]")
        if not isinstance(self.input_width, int) or self.input_width <= 0:
            raise ConfigurationError("input_width must be a positive integer")
        if not isinstance(self.input_height, int) or self.input_height <= 0:
            raise ConfigurationError("input_height must be a positive integer")
        if not isinstance(self.labels, tuple) or any(
            not isinstance(label, str) or not label.strip() for label in self.labels
        ):
            raise ConfigurationError("labels must be a tuple of non-empty strings")
        if len(set(self.labels)) != len(self.labels):
            raise ConfigurationError("labels must be unique")
        if not isinstance(self.hmirror, bool) or not isinstance(self.vflip, bool):
            raise ConfigurationError("hmirror and vflip must be boolean values")
        if self.rotation not in (0, 90, 180, 270):
            raise ConfigurationError("rotation must be one of 0, 90, 180, or 270")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ConfigurationError("source must be a non-empty string")
        if not isinstance(self.camera_index, int) or self.camera_index < 0:
            raise ConfigurationError("camera_index must be a non-negative integer")
        if self.output_format not in ("text", "json"):
            raise ConfigurationError("output_format must be 'text' or 'json'")
        if self.max_frames is not None and (
            not isinstance(self.max_frames, int) or self.max_frames < 0
        ):
            raise ConfigurationError("max_frames must be a non-negative integer or None")
        if not isinstance(self.min_confirm_frames, int) or self.min_confirm_frames <= 0:
            raise ConfigurationError("min_confirm_frames must be a positive integer")


@dataclass(frozen=True)
class SingleTargetResult:
    frame_id: int
    status: ResultStatus
    backend: str
    detection: DetectionResult | None = None
    issues: tuple[InferenceIssue, ...] = ()
    elapsed_ms: float = 0.0
    schema_version: str = "vision-diagnostic-v0.1"

    @property
    def motion_ready(self) -> bool:
        return (
            self.status is ResultStatus.OK
            and self.detection is not None
            and self.detection.motion_ready
        )


def _backend_name(backend: Any) -> str:
    name = getattr(backend, "name", None)
    return name if isinstance(name, str) and name else "unknown"


# Must exceed the single-target count; otherwise a multi-target frame is
# clamped to DUPLICATE_DETECTION before AMBIGUOUS_TARGET can be raised.
MAX_DETECTIONS = 100


def _inference_config(config: SingleTargetLoopConfig) -> InferenceConfig:
    return InferenceConfig(
        backend="single-target",
        model_path=config.model_path,
        class_names={index: name for index, name in enumerate(config.labels)},
        confidence_threshold=config.confidence,
        input_size=(config.input_width, config.input_height),
        max_detections=MAX_DETECTIONS,
        reject_duplicates=True,
    )


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _failed_result(
    config: SingleTargetLoopConfig,
    backend: Any,
    frame_id: int,
    elapsed_ms: float,
    exc: Exception,
    *,
    code: str | None = None,
) -> SingleTargetResult:
    if code is None:
        code = exc.code if isinstance(exc, VisionError) else "UNEXPECTED_BACKEND_FAILURE"
    return SingleTargetResult(
        frame_id=frame_id,
        status=ResultStatus.FAILED,
        backend=_backend_name(backend),
        issues=(InferenceIssue(code, str(exc)),),
        elapsed_ms=elapsed_ms,
    )


def process_single_target_frame(
    config: SingleTargetLoopConfig,
    backend: Any,
    image: ImageLike,
    coordinate_transform: CoordinateTransform | None = None,
    frame_id: int = 0,
) -> SingleTargetResult:
    """Process one frame and return a fail-closed result.

    ``frame_id`` defaults to 0; ``run_vision_loop`` passes 1-based frame ids.
    """
    started = time.perf_counter()
    try:
        config.validate()
        try:
            output = backend.infer(image)
        except VisionError as exc:
            return _failed_result(config, backend, frame_id, _elapsed_ms(started), exc)
        except Exception as exc:
            return _failed_result(config, backend, frame_id, _elapsed_ms(started), exc)

        if not isinstance(output, BackendOutput):
            raise InvalidInputError("backend.infer must return BackendOutput")
        output.validate_dimensions()

        if not config.labels:
            for detection in output.detections:
                detection.validate(output.image_width, output.image_height)
            if output.detections:
                raise UnknownClassError(
                    "labels are not configured; no detected class can be validated"
                )
            raise EmptyDetectionError(
                "no detections remain and labels are not configured"
            )

        raw_detections = postprocess(output, _inference_config(config))
        if len(raw_detections) != 1:
            raise AmbiguousTargetError(
                f"expected exactly one target, found {len(raw_detections)}"
            )

        raw = raw_detections[0]
        coordinate = (coordinate_transform or PixelCenterTransform()).transform(raw.bbox)
        detection = DetectionResult(
            target_seq=1,
            class_id=raw.class_id,
            class_name=config.labels[raw.class_id],
            confidence=float(raw.confidence),
            bbox=raw.bbox,
            center_pixel=raw.bbox.center,
            coordinate=coordinate,
        )
        return SingleTargetResult(
            frame_id=frame_id,
            status=ResultStatus.OK,
            backend=_backend_name(backend),
            detection=detection,
            elapsed_ms=_elapsed_ms(started),
        )
    except VisionError as exc:
        return _failed_result(config, backend, frame_id, _elapsed_ms(started), exc)
    except Exception as exc:  # core failure, not a backend failure
        return _failed_result(
            config,
            backend,
            frame_id,
            _elapsed_ms(started),
            exc,
            code="INTERNAL_CORE_ERROR",
        )


def run_vision_loop(
    config: SingleTargetLoopConfig,
    backend: LoopBackend,
    on_result: Callable[[SingleTargetResult], None],
    coordinate_transform: CoordinateTransform | None = None,
) -> None:
    """Run the loop until capture is exhausted or max_frames is reached.

    Frame ids passed to ``process_single_target_frame`` are 1-based. When
    ``min_confirm_frames`` exceeds 1, OK results are suppressed until N
    consecutive frames report the same class_id; after that, every subsequent
    same-class frame is emitted until a failure or class change resets it.
    """
    config.validate()
    frame_id = 0
    last_class_id: int | None = None
    confirm_streak = 0
    try:
        while True:
            if config.max_frames is not None and frame_id >= config.max_frames:
                break
            frame = backend.capture()
            if frame is None:
                break
            frame_id += 1
            started = time.perf_counter()
            result = process_single_target_frame(
                config,
                backend,
                frame,
                coordinate_transform=coordinate_transform,
                frame_id=frame_id,
            )
            result = replace(result, elapsed_ms=_elapsed_ms(started))
            if result.status is ResultStatus.OK and result.detection is not None:
                class_id = result.detection.class_id
                if class_id == last_class_id:
                    confirm_streak += 1
                else:
                    last_class_id = class_id
                    confirm_streak = 1
                emit = confirm_streak >= config.min_confirm_frames
            else:
                last_class_id = None
                confirm_streak = 0
                emit = True
            if emit:
                on_result(result)
    finally:
        release = getattr(backend, "release", None)
        if callable(release):
            release()


def format_diagnostic_text(result: SingleTargetResult) -> str:
    if result.detection is None:
        error_code = result.issues[0].code if result.issues else "NO_ERROR_CODE"
        return f"{result.frame_id}:none:{error_code}:{result.elapsed_ms:.1f}ms\n"
    detection = result.detection
    center_x, center_y = detection.center_pixel
    return (
        f"{result.frame_id}:{detection.class_name}:"
        f"{detection.confidence:.2f}:{center_x:.1f},{center_y:.1f}:"
        f"{result.elapsed_ms:.1f}ms\n"
    )


def render_diagnostic(
    config: SingleTargetLoopConfig, result: SingleTargetResult
) -> str:
    config.validate()
    if config.output_format == "json":
        return to_single_target_json(result)
    return format_diagnostic_text(result)


def to_single_target_dict(result: SingleTargetResult) -> dict[str, Any]:
    payload = normalize_value(asdict(result))
    payload["diagnostic_only"] = True
    payload["wire_codec_frozen"] = False
    payload["motion_ready"] = result.motion_ready
    if result.detection is not None:
        payload["confidence_percent"] = round(result.detection.confidence * 100.0, 3)
    return payload


def to_single_target_json(result: SingleTargetResult, *, indent: int = 2) -> str:
    return json.dumps(
        to_single_target_dict(result), ensure_ascii=False, indent=indent, sort_keys=True
    )
