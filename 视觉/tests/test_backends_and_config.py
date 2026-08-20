from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from sorting_vision.backends import MaixCamKmodelBackend, OnnxRuntimeBackend, UltralyticsBackend
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
