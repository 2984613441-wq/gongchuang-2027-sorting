"""Optional Ultralytics adapter for PC or Raspberry Pi deployments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import BackendError, DependencyUnavailableError, ModelUnavailableError
from ..types import BackendOutput, BoundingBox, ImageLike, RawDetection


class UltralyticsBackend:
    name = "ultralytics"

    def __init__(
        self,
        model_path: str | Path,
        *,
        device: str = "cpu",
        input_size: tuple[int, int] = (640, 640),
    ) -> None:
        self._model_path = Path(model_path).expanduser().resolve()
        self._device = device
        self._input_size = input_size
        self._model: Any | None = None
        if not self._model_path.is_file():
            raise ModelUnavailableError(f"model file does not exist: {self._model_path}")

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise DependencyUnavailableError(
                "UltralyticsBackend requires the optional 'ultralytics' package; "
                "install it only in the selected deployment environment"
            ) from exc
        try:
            self._model = YOLO(str(self._model_path))
        except Exception as exc:  # third-party loader boundary
            raise ModelUnavailableError(f"failed to load model {self._model_path}: {exc}") from exc
        return self._model

    def infer(self, image: ImageLike) -> BackendOutput:
        model = self._load_model()
        try:
            results = model.predict(
                source=image,
                device=self._device,
                imgsz=self._input_size,
                verbose=False,
            )
            if len(results) != 1:
                raise BackendError(f"expected one image result, got {len(results)}")
            result = results[0]
            height, width = (int(value) for value in result.orig_shape)
            detections: list[RawDetection] = []
            for box in result.boxes:
                xyxy = box.xyxy[0].tolist()
                detections.append(
                    RawDetection(
                        class_id=int(box.cls[0].item()),
                        confidence=float(box.conf[0].item()),
                        bbox=BoundingBox(*(float(value) for value in xyxy)),
                    )
                )
            return BackendOutput(width, height, tuple(detections))
        except (BackendError, ModelUnavailableError, DependencyUnavailableError):
            raise
        except Exception as exc:  # third-party runtime boundary
            raise BackendError(f"Ultralytics inference failed: {exc}") from exc
