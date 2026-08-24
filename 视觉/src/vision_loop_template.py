"""
vision_loop_template.py
=======================

Adapted reference skeleton for the smart-sorting vision loop.

Source material: MaixHub main.py (MaixPy v0.6.0, K210) - value kept:
  1. capture -> infer -> parse -> lightweight output loop
  2. configurable labels (no hard-coded class table)
  3. mirror/flip switches for camera mounting orientation
  4. per-frame timing
  5. explicit resource release on exit

Not carried over: K210 kpu API, classification-only argmax,
hard-coded UART pins/baud, QVGA-only sizing, frozen wire format.

This file is a TEMPLATE and is superseded by ``sorting_vision`` for the
single-target loop. The confirmed target is MaixCAM with MaixPy 4.12.5
(camera GC4653); the K210 kpu API here is obsolete. See
``sorting_vision.backends.MaixPyYoloBackend`` for the concrete runtime adapter.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

# ---------------------------------------------------------------------------
# 1. Configuration: everything the loop needs is explicit.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VisionLoopConfig:
    model_path: str
    labels: tuple[str, ...] = (
        "hexagonal_prism",
        "pentagonal_prism",
        "triangular_prism",
        "square_pyramid",
        "cylinder",
        "cube",
        "cuboid",
    )
    input_width: int = 640
    input_height: int = 640
    confidence: float = 0.35
    hmirror: bool = False
    vflip: bool = False
    rotation: int = 0
    source: str = "camera"          # "camera" | "image" | "video"
    camera_index: int = 0
    # Diagnostic only. This is NOT the frozen binary wire codec.
    output_line: bool = True
    max_frames: Optional[int] = None

    def validate(self) -> None:
        if not self.model_path.strip():
            raise ValueError("model_path must be non-empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        if self.input_width <= 0 or self.input_height <= 0:
            raise ValueError("input size must be positive")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("labels must be unique")


# ---------------------------------------------------------------------------
# 2. Backend protocol: capture + infer are injected, so the same loop can run
#    on a host, Raspberry Pi, or MaixCAM without changing the orchestration.
# ---------------------------------------------------------------------------

class VisionBackend(Protocol):
    name: str

    def capture(self): ...              # returns one raw frame (image-like)

    def infer(self, frame): ...         # returns backend output object

    def release(self) -> None: ...      # cleanup on exit


@dataclass(frozen=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)


# ---------------------------------------------------------------------------
# 3. Lightweight diagnostic output (NOT the frozen wire protocol).
#    Keeps the source main.py idea: send a short text summary, not the image.
# ---------------------------------------------------------------------------

def format_diagnostic_line(
    frame_id: int,
    detection: Optional[Detection],
    elapsed_ms: float,
) -> str:
    if detection is None:
        return f"{frame_id}:none:{elapsed_ms:.1f}ms\n"
    cx, cy = detection.center
    return (
        f"{frame_id}:{detection.class_name}:"
        f"{detection.confidence:.2f}:{cx:.1f},{cy:.1f}:{elapsed_ms:.1f}ms\n"
    )


# ---------------------------------------------------------------------------
# 4. The reusable loop.
# ---------------------------------------------------------------------------

def run_vision_loop(
    config: VisionLoopConfig,
    backend: VisionBackend,
    on_result: Callable[[int, Optional[Detection], float], None],
) -> None:
    config.validate()
    frame_id = 0
    try:
        while True:
            if config.max_frames is not None and frame_id >= config.max_frames:
                break
            frame = backend.capture()
            if frame is None:
                break
            started = time.perf_counter()
            output = backend.infer(frame)
            detection = _pick_best(output, config)  # host-side helper below
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            frame_id += 1
            on_result(frame_id, detection, elapsed_ms)
    finally:
        backend.release()


# Placeholder post-processing. Real pipeline uses configurable confidence
# filter + NMS from the project's sorting_vision core.
def _pick_best(output, config: VisionLoopConfig) -> Optional[Detection]:
    items = getattr(output, "detections", None) or []
    best = None
    for item in items:
        if item.confidence < config.confidence:
            continue
        if best is None or item.confidence > best.confidence:
            best = item
    return best


# ---------------------------------------------------------------------------
# 5. Raspberry Pi adapter sketch (OpenCV + any inference engine).
#    Runtime must exist on the device; import is intentionally lazy.
# ---------------------------------------------------------------------------

class OpenCvCameraBackend:
    """Generic camera backend for a host or Raspberry Pi (needs opencv-python)."""

    name = "opencv-camera"

    def __init__(self, camera_index: int = 0, width: int = 640, height: int = 480):
        import cv2  # noqa: F401  (imported only when this backend is chosen)
        self._cv2 = cv2
        self._cap = cv2.VideoCapture(camera_index)
        if not self._cap.isOpened():
            raise RuntimeError(f"cannot open camera index {camera_index}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    def capture(self):
        ok, frame = self._cap.read()
        if not ok:
            return None
        return frame

    def infer(self, frame):
        # TODO: plug in ONNX / Ultralytics / NCNN runner here.
        raise NotImplementedError("attach a real inference runner")

    def release(self) -> None:
        self._cap.release()


# ---------------------------------------------------------------------------
# 6. MaixCAM adapter sketch.
#    The MaixCAM API differs from the K210 kpu API. This placeholder is obsolete:
#    use ``sorting_vision.backends.MaixPyYoloBackend`` (MaixPy v4.12.5).
# ---------------------------------------------------------------------------

class MaixCamBackend:
    """Placeholder: superseded by sorting_vision.backends.MaixPyYoloBackend."""

    name = "maixcam"

    def __init__(self, config: VisionLoopConfig):
        raise NotImplementedError(
            "use sorting_vision.backends.MaixPyYoloBackend (MaixPy v4.12.5)"
        )

    def capture(self):
        raise NotImplementedError

    def infer(self, frame):
        raise NotImplementedError

    def release(self) -> None:
        pass


# ---------------------------------------------------------------------------
# 7. Quick host smoke test (no model, no camera).
# ---------------------------------------------------------------------------

class FakeBackend:
    name = "fake"

    def __init__(self) -> None:
        self.frames = 3
        self._count = 0

    def capture(self):
        if self._count >= self.frames:
            return None
        self._count += 1
        return object()

    def infer(self, frame):
        return _FakeOutput()

    def release(self) -> None:
        pass


class _FakeOutput:
    detections = ()


if __name__ == "__main__":
    cfg = VisionLoopConfig(model_path="fake.pt", max_frames=3)
    run_vision_loop(cfg, FakeBackend(), on_result=lambda fid, det, ms: print(
        format_diagnostic_line(fid, det, ms).rstrip()
    ))
