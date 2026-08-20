"""MaixCAM/kmodel adaptation boundary without assuming a vendor runtime API."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..errors import BackendError, DependencyUnavailableError, ModelUnavailableError
from ..types import BackendOutput, ImageLike


MaixRunner = Callable[[Path, ImageLike], object]
MaixDecoder = Callable[[object], BackendOutput]


class MaixCamKmodelBackend:
    """Adapter that receives vendor-specific runner and decoder functions.

    V0.1 intentionally does not guess MaixPy APIs or kmodel tensor layouts.
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
