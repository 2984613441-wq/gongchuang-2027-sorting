"""Contract for the optional "info" attribute (final-round only).

The preliminary round only requires ``(color, shape)``. The printed text, QR
code, and simulated stain/defect graphic are unknown and are therefore left as
an explicit slot here instead of being implemented.

Integration points for the real adapters (add later, after their dependencies
are confirmed on the target device):

- OCR on Raspberry Pi, RapidOCR::

      from rapidocr import RapidOCR
      engine = RapidOCR()
      result = engine(roi)          # str / ndarray / bytes / Path
      text = " ".join(result.txts)  # result.boxes / result.scores also exist

- OCR on Raspberry Pi, OnnxOCR::

      import cv2
      from onnxocr.onnx_paddleocr import ONNXPaddleOcr
      engine = ONNXPaddleOcr(use_angle_cls=False, use_gpu=False)
      result = engine.ocr(cv2.imread(path))  # returns detection + text boxes

- QR decode: use ``zxing-cpp`` (C++ core with Python bindings) or
  ``pyzbar``/``zbar``. Do not hand-port Reed-Solomon from the PHP/JS/ObjC
  ports; the decode pipeline (finder patterns -> perspective correction ->
  sampling -> Reed-Solomon) is already maintained in those mature cores.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .types import ImageLike


@dataclass(frozen=True)
class InfoResult:
    qr_text: str | None = None
    ocr_text: str | None = None
    graphic_id: int | None = None

    def key(self) -> tuple[str | None, str | None, int | None]:
        """Stable tuple used to group items by identical info."""

        return (self.qr_text, self.ocr_text, self.graphic_id)


@dataclass(frozen=True)
class InfoDecodeConfig:
    enable_qr: bool = False
    enable_ocr: bool = False
    enable_graphic: bool = False


class InfoDecoder(Protocol):
    @property
    def name(self) -> str: ...

    def decode(self, roi: ImageLike) -> InfoResult: ...


class FakeInfoDecoder:
    """Deterministic host-side decoder; returns no info by default."""

    name = "fake-info"

    def __init__(self, config: InfoDecodeConfig | None = None) -> None:
        self._config = config or InfoDecodeConfig()

    def decode(self, roi: ImageLike) -> InfoResult:
        return InfoResult()
