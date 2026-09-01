"""Host-only example; it does not access a camera or produce a wire frame."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from sorting_vision.backends import FakeBackend
from sorting_vision.config import InferenceConfig
from sorting_vision.export import to_diagnostic_json
from sorting_vision.pipeline import VisionPipeline
from sorting_vision.types import BackendOutput, BoundingBox, FakeImage, RawDetection


def main() -> None:
    config = InferenceConfig(class_names={0: "example_class"})
    backend = FakeBackend(
        {
            "example": BackendOutput(
                image_width=640,
                image_height=480,
                detections=(RawDetection(0, 0.92, BoundingBox(10, 20, 110, 120)),),
            )
        }
    )
    result = VisionPipeline(config, backend).infer_batch(1, FakeImage("example", 640, 480))
    print(to_diagnostic_json(result))


if __name__ == "__main__":
    main()
