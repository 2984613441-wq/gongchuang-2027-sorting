from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from sorting_vision.backends import FakeBackend
from sorting_vision.benchmark import benchmark_pipeline
from sorting_vision.config import InferenceConfig
from sorting_vision.coordinates import AffineCoordinateTransform
from sorting_vision.export import to_diagnostic_json
from sorting_vision.pipeline import VisionPipeline
from sorting_vision.types import (
    BackendOutput,
    BoundingBox,
    FakeImage,
    RawDetection,
    ResultStatus,
)


def raw(class_id: int, confidence: float, bbox: tuple[float, float, float, float]) -> RawDetection:
    return RawDetection(class_id, confidence, BoundingBox(*bbox))


class VisionPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = InferenceConfig(class_names={0: "class_a", 1: "class_b"})

    def pipeline_for(self, key: str, detections: tuple[RawDetection, ...], **kwargs) -> VisionPipeline:
        output = BackendOutput(100, 80, detections)
        return VisionPipeline(
            kwargs.pop("config", self.config),
            FakeBackend({key: output}),
            kwargs.pop("transform", None),
        )

    def test_batch_success_is_diagnostic_only_without_calibration(self) -> None:
        pipeline = self.pipeline_for(
            "normal",
            (
                raw(0, 0.91, (10, 10, 30, 30)),
                raw(1, 0.82, (60, 20, 90, 50)),
            ),
        )
        result = pipeline.infer_batch(7, FakeImage("normal", 100, 80))
        self.assertEqual(ResultStatus.OK, result.status)
        self.assertEqual([1, 2], [item.target_seq for item in result.detections])
        self.assertEqual(["class_a", "class_b"], [item.class_name for item in result.detections])
        self.assertFalse(result.motion_ready)
        self.assertEqual("image_pixel", result.detections[0].coordinate.frame)

        payload = json.loads(to_diagnostic_json(result))
        self.assertEqual("vision-diagnostic-v0.1", payload["schema_version"])
        self.assertEqual(2, payload["target_count"])
        self.assertEqual([91.0, 82.0], payload["confidence_percent"])
        self.assertFalse(payload["motion_ready"])
        self.assertFalse(payload["wire_codec_frozen"])
        self.assertTrue(payload["diagnostic_only"])

    def test_explicit_calibration_can_mark_result_motion_ready(self) -> None:
        transform = AffineCoordinateTransform(
            matrix=((0.5, 0.0, 1.0), (0.0, 0.25, 2.0)),
            x_bounds=(0.0, 100.0),
            y_bounds=(0.0, 100.0),
            frame="test_machine_frame",
            unit="test_unit",
            calibration_id="test-calibration-only",
        )
        pipeline = self.pipeline_for(
            "calibrated", (raw(0, 0.9, (10, 10, 30, 30)),), transform=transform
        )
        result = pipeline.infer_batch(8, FakeImage("calibrated", 100, 80))
        self.assertTrue(result.motion_ready)
        self.assertEqual((11.0, 7.0), (result.detections[0].coordinate.x, result.detections[0].coordinate.y))

    def test_low_confidence_becomes_explicit_empty_failure(self) -> None:
        pipeline = self.pipeline_for("low", (raw(0, 0.49, (10, 10, 20, 20)),))
        result = pipeline.infer_batch(1, FakeImage("low", 100, 80))
        self.assertEqual(ResultStatus.FAILED, result.status)
        self.assertEqual("EMPTY_DETECTION", result.issues[0].code)
        self.assertEqual((), result.detections)
        self.assertFalse(result.motion_ready)

    def test_empty_detection_fails_closed(self) -> None:
        pipeline = self.pipeline_for("empty", ())
        result = pipeline.infer_batch(1, FakeImage("empty", 100, 80))
        self.assertEqual("EMPTY_DETECTION", result.issues[0].code)
        self.assertFalse(result.motion_ready)

    def test_unknown_class_fails_closed(self) -> None:
        pipeline = self.pipeline_for("unknown", (raw(9, 0.9, (10, 10, 20, 20)),))
        result = pipeline.infer_batch(1, FakeImage("unknown", 100, 80))
        self.assertEqual("UNKNOWN_CLASS", result.issues[0].code)
        self.assertEqual((), result.detections)

    def test_invalid_confidence_fails_closed(self) -> None:
        pipeline = self.pipeline_for("confidence", (raw(0, 1.01, (10, 10, 20, 20)),))
        result = pipeline.infer_batch(1, FakeImage("confidence", 100, 80))
        self.assertEqual("INVALID_DETECTION", result.issues[0].code)

    def test_out_of_image_bbox_fails_closed(self) -> None:
        pipeline = self.pipeline_for("bbox", (raw(0, 0.9, (90, 10, 110, 20)),))
        result = pipeline.infer_batch(1, FakeImage("bbox", 100, 80))
        self.assertEqual("INVALID_DETECTION", result.issues[0].code)

    def test_duplicate_target_fails_closed(self) -> None:
        pipeline = self.pipeline_for(
            "duplicate",
            (
                raw(0, 0.95, (10, 10, 40, 40)),
                raw(0, 0.90, (11, 11, 39, 39)),
            ),
        )
        result = pipeline.infer_batch(1, FakeImage("duplicate", 100, 80))
        self.assertEqual("DUPLICATE_DETECTION", result.issues[0].code)
        self.assertEqual((), result.detections)

    def test_nms_can_be_enabled_as_explicit_non_safety_diagnostic_mode(self) -> None:
        config = InferenceConfig(
            class_names={0: "class_a"},
            reject_duplicates=False,
        )
        pipeline = self.pipeline_for(
            "nms",
            (
                raw(0, 0.95, (10, 10, 40, 40)),
                raw(0, 0.90, (11, 11, 39, 39)),
            ),
            config=config,
        )
        result = pipeline.infer_batch(1, FakeImage("nms", 100, 80))
        self.assertEqual(ResultStatus.OK, result.status)
        self.assertEqual(1, len(result.detections))

    def test_transformed_coordinate_out_of_bounds_fails_closed(self) -> None:
        transform = AffineCoordinateTransform(
            matrix=((10.0, 0.0, 0.0), (0.0, 10.0, 0.0)),
            x_bounds=(0.0, 100.0),
            y_bounds=(0.0, 100.0),
            frame="test",
            unit="test",
            calibration_id="test",
        )
        pipeline = self.pipeline_for(
            "coord", (raw(0, 0.9, (10, 10, 30, 30)),), transform=transform
        )
        result = pipeline.infer_batch(1, FakeImage("coord", 100, 80))
        self.assertEqual("COORDINATE_OUT_OF_BOUNDS", result.issues[0].code)
        self.assertEqual((), result.detections)

    def test_corrupted_input_fails_closed(self) -> None:
        pipeline = self.pipeline_for("corrupt", (raw(0, 0.9, (10, 10, 20, 20)),))
        result = pipeline.infer_batch(1, FakeImage("corrupt", 100, 80, corrupted=True))
        self.assertEqual("INVALID_INPUT", result.issues[0].code)

    def test_invalid_task_id_fails_closed(self) -> None:
        pipeline = self.pipeline_for("normal", (raw(0, 0.9, (10, 10, 20, 20)),))
        result = pipeline.infer_batch(70000, FakeImage("normal", 100, 80))
        self.assertEqual("INVALID_INPUT", result.issues[0].code)

    def test_single_target_reacquire_requires_exactly_one_candidate(self) -> None:
        success = self.pipeline_for("one", (raw(0, 0.9, (10, 10, 20, 20)),)).reacquire(
            1, 3, 0, FakeImage("one", 100, 80)
        )
        self.assertEqual(ResultStatus.OK, success.status)
        self.assertEqual(3, success.detection.target_seq)

        ambiguous_pipeline = self.pipeline_for(
            "many",
            (
                raw(0, 0.9, (10, 10, 20, 20)),
                raw(0, 0.8, (50, 10, 60, 20)),
            ),
        )
        ambiguous = ambiguous_pipeline.reacquire(1, 3, 0, FakeImage("many", 100, 80))
        self.assertEqual(ResultStatus.FAILED, ambiguous.status)
        self.assertEqual("AMBIGUOUS_REACQUIRE", ambiguous.issues[0].code)
        self.assertFalse(ambiguous.motion_ready)

        unknown = ambiguous_pipeline.reacquire(1, 3, 99, FakeImage("many", 100, 80))
        self.assertEqual(ResultStatus.FAILED, unknown.status)
        self.assertEqual("UNKNOWN_CLASS", unknown.issues[0].code)

    def test_benchmark_record_has_comparison_fields_without_fabricated_accuracy(self) -> None:
        pipeline = self.pipeline_for("bench", (raw(0, 0.9, (10, 10, 20, 20)),))
        record = benchmark_pipeline(
            pipeline,
            [FakeImage("bench", 100, 80), FakeImage("bench", 100, 80)],
            target="host-fake",
            model_format="fake",
            model_version="v0",
            validation_set_id="test-only",
        )
        self.assertEqual(2, record.successful_samples)
        self.assertGreaterEqual(record.mean_latency_ms, 0)
        self.assertIsNone(record.accuracy_metric_value)
        self.assertIsNone(record.peak_temperature_c)


if __name__ == "__main__":
    unittest.main()
