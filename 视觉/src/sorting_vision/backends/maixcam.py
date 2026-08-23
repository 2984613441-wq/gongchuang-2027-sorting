"""MaixCAM backends.

Confirmed target hardware (user provided, 2026-08-23):
- MaixCAM (SG2002 series), hostname ``maxicam-544c.local``
- MaixPy 4.12.5 (v4, not the older K210 / MaixPy v0.6 kpu API)
- camera GC4653, no IMU

The concrete ``MaixPyYoloBackend`` below targets that runtime. The exact model
family and input size are not frozen until MaixHub exports a model, so they are
constructor arguments instead of hidden defaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from ..errors import (
    BackendError,
    ConfigurationError,
    DependencyUnavailableError,
    ModelUnavailableError,
)
from ..types import BackendOutput, BoundingBox, ImageLike, RawDetection


MaixRunner = Callable[[Path, ImageLike], object]
MaixDecoder = Callable[[object], BackendOutput]


class MaixCamKmodelBackend:
    """Adapter that receives vendor-specific runner and decoder functions.

    This stays a pure injection boundary and does not guess MaixPy APIs or kmodel
    tensor layouts. Prefer ``MaixPyYoloBackend`` for the concrete MaixCAM runtime.
    """

    name = "maixcam-kmodel"

    def __init__(
        self,
        model_path: str | Path,
        *,
        runner: MaixRunner | None = None,
        decoder: MaixDecoder | None = None,
    ) -> None:
        self._model_path = Path(model_path).expanduser().resolve()
        self._runner = runner
        self._decoder = decoder
        if not self._model_path.is_file():
            raise ModelUnavailableError(f"kmodel file does not exist: {self._model_path}")

    def infer(self, image: ImageLike) -> BackendOutput:
        if self._runner is None or self._decoder is None:
            raise DependencyUnavailableError(
                "MaixCAM inference needs explicit vendor runner and tensor decoder adapters; "
                "their APIs are not frozen in V0.1"
            )
        try:
            output = self._decoder(self._runner(self._model_path, image))
        except Exception as exc:
            raise BackendError(f"MaixCAM/kmodel inference failed: {exc}") from exc
        if not isinstance(output, BackendOutput):
            raise BackendError("MaixCAM decoder must return BackendOutput")
        return output


def objects_to_backend_output(
    objects: Iterable[Any], image_width: int, image_height: int
) -> BackendOutput:
    """Convert MaixPy ``nn.Object`` detections into ``BackendOutput``.

    MaixPy reports boxes as top-left ``x``/``y`` plus ``w``/``h``; this maps them
    to our ``x1``/``y1``/``x2``/``y2`` contract. Pure logic, host-testable.
    """

    detections = tuple(
        RawDetection(
            class_id=int(obj.class_id),
            confidence=float(obj.score),
            bbox=BoundingBox(
                float(obj.x),
                float(obj.y),
                float(obj.x + obj.w),
                float(obj.y + obj.h),
            ),
        )
        for obj in objects
    )
    return BackendOutput(int(image_width), int(image_height), detections)


class MaixPyYoloBackend:
    """Concrete MaixPy v4 YOLO backend for MaixCAM.

    Uses ``from maix import nn`` and a family-specific detector
    (``YOLOv5``/``YOLOv8``/``YOLO11``). The detector is imported lazily so host
    tests do not require MaixPy. ``detector`` is injectable for host tests.
    """

    name = "maixcam-maixpy-yolo"

    _FAMILY_CLASSES = {
        "yolov5": "YOLOv5",
        "yolov8": "YOLOv8",
        "yolo11": "YOLO11",
    }

    def __init__(
        self,
        model_path: str | Path,
        *,
        family: str = "yolo11",
        dual_buff: bool = True,
        fallback_size: tuple[int, int] = (640, 640),
        detector: Any | None = None,
    ) -> None:
        self._model_path = Path(model_path).expanduser().resolve()
        self._family = family
        self._dual_buff = dual_buff
        self._fallback_size = fallback_size
        self._detector = detector
        if family not in self._FAMILY_CLASSES:
            raise ConfigurationError(
                f"unsupported MaixPy YOLO family {family!r}; "
                f"choose one of {sorted(self._FAMILY_CLASSES)}"
            )
        if not self._model_path.is_file():
            raise ModelUnavailableError(f"model file does not exist: {self._model_path}")

    def _load_detector(self) -> Any:
        if self._detector is not None:
            return self._detector
        try:
            from maix import nn
        except ImportError as exc:
            raise DependencyUnavailableError(
                "MaixPy 'maix' is required for MaixPyYoloBackend"
            ) from exc
        detector_cls = getattr(nn, self._FAMILY_CLASSES[self._family], None)
        if detector_cls is None:
            raise DependencyUnavailableError(
                f"MaixPy has no {self._FAMILY_CLASSES[self._family]} detector"
            )
        try:
            self._detector = detector_cls(
                model=str(self._model_path), dual_buff=self._dual_buff
            )
        except Exception as exc:
            raise ModelUnavailableError(
                f"failed to load model {self._model_path}: {exc}"
            ) from exc
        return self._detector

    def infer(self, image: ImageLike) -> BackendOutput:
        detector = self._load_detector()
        try:
            objects = detector.detect(image)
        except Exception as exc:
            raise BackendError(f"MaixCAM inference failed: {exc}") from exc
        width = getattr(image, "width", self._fallback_size[0])
        height = getattr(image, "height", self._fallback_size[1])
        return objects_to_backend_output(objects, int(width), int(height))
