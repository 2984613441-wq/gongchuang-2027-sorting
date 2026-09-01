"""Optional ONNX Runtime boundary without assuming a YOLO tensor layout."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Sequence

from ..errors import BackendError, DependencyUnavailableError, ModelUnavailableError
from ..types import BackendOutput, ImageLike


OnnxInputBuilder = Callable[[ImageLike], Mapping[str, object]]
OnnxOutputDecoder = Callable[[Sequence[object]], BackendOutput]


class OnnxRuntimeBackend:
    name = "onnxruntime"

    def __init__(
        self,
        model_path: str | Path,
        *,
        input_builder: OnnxInputBuilder | None = None,
        output_decoder: OnnxOutputDecoder | None = None,
        providers: tuple[str, ...] | None = None,
    ) -> None:
        self._model_path = Path(model_path).expanduser().resolve()
        self._input_builder = input_builder
        self._output_decoder = output_decoder
        self._providers = providers
        self._session = None
        if not self._model_path.is_file():
            raise ModelUnavailableError(f"ONNX model file does not exist: {self._model_path}")

    def _load_session(self):
        if self._session is not None:
            return self._session
        try:
            import onnxruntime
        except ImportError as exc:
            raise DependencyUnavailableError(
                "OnnxRuntimeBackend requires the optional 'onnxruntime' package in the selected environment"
            ) from exc
        try:
            kwargs = {"providers": list(self._providers)} if self._providers else {}
            self._session = onnxruntime.InferenceSession(str(self._model_path), **kwargs)
        except Exception as exc:
            raise ModelUnavailableError(f"failed to load ONNX model {self._model_path}: {exc}") from exc
        return self._session

    def infer(self, image: ImageLike) -> BackendOutput:
        if self._input_builder is None or self._output_decoder is None:
            raise DependencyUnavailableError(
                "ONNX inference needs explicit preprocessing and output decoder adapters for the exported model"
            )
        try:
            session = self._load_session()
            output = self._output_decoder(session.run(None, dict(self._input_builder(image))))
        except (DependencyUnavailableError, ModelUnavailableError):
            raise
        except Exception as exc:
            raise BackendError(f"ONNX Runtime inference failed: {exc}") from exc
        if not isinstance(output, BackendOutput):
            raise BackendError("ONNX output decoder must return BackendOutput")
        return output
