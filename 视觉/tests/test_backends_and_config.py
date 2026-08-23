from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from sorting_vision.backends import (
    MaixCamKmodelBackend,
    MaixPyYoloBackend,
    OnnxRuntimeBackend,
    UltralyticsBackend,
)
from sorting_vision.backends.maixcam import objects_to_backend_output
from sorting_vision.config import InferenceConfig
from sorting_vision.errors import (
    ConfigurationError,
    DependencyUnavailableError,
    ModelUnavailableError,
)


class ConfigurationAndBackendTests(unittest.TestCase):
    def test_configuration_rejects_missing_class_map_and_bad_thresholds(self) -> None:
        with self.assertRaises(ConfigurationError):
            InferenceConfig()
        with self.assertRaises(ConfigurationError):
            InferenceConfig(class_names={0: "ok"}, confidence_threshold=1.1)
        with self.assertRaises(ConfigurationError):
            InferenceConfig(class_names={0: "ok"}, input_size=(0, 640))

    def test_real_backends_reject_missing_model_files_clearly(self) -> None:
        missing = Path(tempfile.gettempdir()) / "sorting-vision-model-does-not-exist.bin"
        with self.assertRaisesRegex(ModelUnavailableError, "does not exist"):
            UltralyticsBackend(missing)
        with self.assertRaisesRegex(ModelUnavailableError, "does not exist"):
            MaixCamKmodelBackend(missing)
        with self.assertRaisesRegex(ModelUnavailableError, "does not exist"):
            OnnxRuntimeBackend(missing)

    def test_maixcam_boundary_requires_explicit_runtime_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "test.kmodel"
            model.write_bytes(b"test-only")
            backend = MaixCamKmodelBackend(model)
            with self.assertRaisesRegex(DependencyUnavailableError, "runner"):
                backend.infer(object())

    def test_maixpy_objects_decode_to_backend_output(self) -> None:
        objects = [
            SimpleNamespace(class_id=0, score=0.9, x=10.0, y=20.0, w=30.0, h=40.0),
            SimpleNamespace(class_id=1, score=0.5, x=100.0, y=200.0, w=50.0, h=60.0),
        ]
        output = objects_to_backend_output(objects, 640, 480)
        self.assertEqual((640, 480), (output.image_width, output.image_height))
        self.assertEqual(2, len(output.detections))
        first = output.detections[0]
        self.assertEqual(0, first.class_id)
        self.assertAlmostEqual(0.9, first.confidence)
        self.assertEqual(
            (10.0, 20.0, 40.0, 60.0),
            (first.bbox.x1, first.bbox.y1, first.bbox.x2, first.bbox.y2),
        )

    def test_maixpy_backend_rejects_unknown_family(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "test.mud"
            model.write_bytes(b"test-only")
            with self.assertRaises(ConfigurationError):
                MaixPyYoloBackend(model, family="unknown")

    def test_maixpy_backend_infer_with_injected_detector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "test.mud"
            model.write_bytes(b"test-only")
            detector = SimpleNamespace(
                detect=lambda img: [
                    SimpleNamespace(class_id=0, score=0.8, x=1.0, y=2.0, w=3.0, h=4.0)
                ]
            )
            image = SimpleNamespace(width=320, height=240)
            backend = MaixPyYoloBackend(model, detector=detector)
            output = backend.infer(image)
            self.assertEqual((320, 240), (output.image_width, output.image_height))
            self.assertEqual(1, len(output.detections))

    def test_maixpy_backend_missing_maixpy_dependency_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "test.mud"
            model.write_bytes(b"test-only")
            backend = MaixPyYoloBackend(model)
            with patch.dict(sys.modules, {"maix": None}):
                with self.assertRaisesRegex(DependencyUnavailableError, "MaixPy"):
                    backend.infer(object())

    def test_onnx_boundary_requires_model_specific_preprocess_and_decoder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "test.onnx"
            model.write_bytes(b"test-only")
            backend = OnnxRuntimeBackend(model)
            with self.assertRaisesRegex(DependencyUnavailableError, "preprocessing"):
                backend.infer(object())

    def test_ultralytics_missing_optional_dependency_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "test.pt"
            model.write_bytes(b"test-only")
            backend = UltralyticsBackend(model)
            with patch.dict(sys.modules, {"ultralytics": None}):
                with self.assertRaisesRegex(DependencyUnavailableError, "optional 'ultralytics'"):
                    backend.infer(object())


if __name__ == "__main__":
    unittest.main()
