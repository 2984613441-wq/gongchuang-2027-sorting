from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from sorting_vision.backends import FakeBackend
from sorting_vision.coordinates import AffineCoordinateTransform
from sorting_vision.errors import ConfigurationError
from sorting_vision.single_target import (
    SingleTargetLoopConfig,
    SingleTargetResult,
    format_diagnostic_text,
    process_single_target_frame,
    render_diagnostic,
    run_vision_loop,
    to_single_target_json,
)
from sorting_vision.types import (
    BackendOutput,
    BoundingBox,
    Coordinate,
    DetectionResult,
    FakeImage,
    InferenceIssue,
    RawDetection,
    ResultStatus,
)


def raw(class_id: int, confidence: float, bbox: tuple[float, float, float, float]) -> RawDetection:
    return RawDetection(class_id, confidence, BoundingBox(*bbox))


def success_output() -> BackendOutput:
    return BackendOutput(100, 80, (raw(0, 0.90, (10, 10, 30, 30)),))


class LoopFakeBackend(FakeBackend):
    name = "loop-fake"

    def __init__(self, outputs, frames: int) -> None:
        super().__init__(outputs)
        self._frames = [FakeImage("single", 100, 80) for _ in range(frames)]
        self.released = False

    def capture(self):
        return self._frames.pop(0) if self._frames else None

    def release(self) -> None:
        self.released = True


class SequenceLoopBackend:
    name = "loop-fake"

    def __init__(self, outputs: list[BackendOutput]) -> None:
        self._outputs = list(outputs)
        self.released = False

    def capture(self):
        return object() if self._outputs else None

    def infer(self, image):
        return self._outputs.pop(0)

    def release(self) -> None:
        self.released = True


class SingleTargetTests(unittest.TestCase):
    def assert_failed(self, result: SingleTargetResult, code: str) -> None:
        self.assertIs(ResultStatus.FAILED, result.status)
        self.assertIsNone(result.detection)
        self.assertFalse(result.motion_ready)
        self.assertEqual(code, result.issues[0].code)

    def test_single_target_success_without_calibration_is_not_motion_ready(self) -> None:
        config = SingleTargetLoopConfig(model_path="fake.pt", labels=("block",))
        backend = FakeBackend({"single": success_output()})
        result = process_single_target_frame(
            config, backend, FakeImage("single", 100, 80), frame_id=5
        )

        self.assertIs(ResultStatus.OK, result.status)
        self.assertEqual(5, result.frame_id)
        self.assertEqual("fake", result.backend)
        self.assertEqual("block", result.detection.class_name)
        self.assertEqual((20.0, 20.0), result.detection.center_pixel)
        self.assertFalse(result.detection.motion_ready)
        self.assertFalse(result.motion_ready)
        self.assertEqual((), result.issues)
        self.assertGreaterEqual(result.elapsed_ms, 0.0)

    def test_low_confidence_fails_closed_as_empty_detection(self) -> None:
        config = SingleTargetLoopConfig(model_path="fake.pt", labels=("block",))
        backend = FakeBackend(
            {"single": BackendOutput(100, 80, (raw(0, 0.20, (10, 10, 30, 30)),))}
        )
        result = process_single_target_frame(config, backend, FakeImage("single", 100, 80))
        self.assert_failed(result, "EMPTY_DETECTION")

    def test_unknown_class_fails_closed(self) -> None:
        config = SingleTargetLoopConfig(model_path="fake.pt", labels=("block",))
        backend = FakeBackend(
            {"single": BackendOutput(100, 80, (raw(7, 0.90, (10, 10, 30, 30)),))}
        )
        result = process_single_target_frame(config, backend, FakeImage("single", 100, 80))
        self.assert_failed(result, "UNKNOWN_CLASS")

    def test_out_of_image_bbox_fails_closed(self) -> None:
        config = SingleTargetLoopConfig(model_path="fake.pt", labels=("block",))
        backend = FakeBackend(
            {"single": BackendOutput(100, 80, (raw(0, 0.90, (95, 10, 110, 20)),))}
        )
        result = process_single_target_frame(config, backend, FakeImage("single", 100, 80))
        self.assert_failed(result, "INVALID_DETECTION")

    def test_overlapping_duplicate_boxes_fail_closed(self) -> None:
        config = SingleTargetLoopConfig(model_path="fake.pt", labels=("block",))
        backend = FakeBackend(
            {
                "single": BackendOutput(
                    100,
                    80,
                    (
                        raw(0, 0.95, (10, 10, 40, 40)),
                        raw(0, 0.90, (11, 11, 39, 39)),
                    ),
                )
            }
        )
        result = process_single_target_frame(config, backend, FakeImage("single", 100, 80))
        self.assert_failed(result, "DUPLICATE_DETECTION")

    def test_two_non_overlapping_targets_fail_closed_as_ambiguous(self) -> None:
        config = SingleTargetLoopConfig(model_path="fake.pt", labels=("block",))
        backend = FakeBackend(
            {
                "single": BackendOutput(
                    100,
                    80,
                    (
                        raw(0, 0.90, (10, 10, 30, 30)),
                        raw(0, 0.80, (60, 10, 80, 30)),
                    ),
                )
            }
        )
        result = process_single_target_frame(config, backend, FakeImage("single", 100, 80))
        self.assert_failed(result, "AMBIGUOUS_TARGET")

    def test_missing_labels_fail_closed_when_detection_appears(self) -> None:
        config = SingleTargetLoopConfig(model_path="fake.pt")
        backend = FakeBackend({"single": success_output()})
        result = process_single_target_frame(config, backend, FakeImage("single", 100, 80))
        self.assert_failed(result, "UNKNOWN_CLASS")

    def test_corrupted_input_fails_closed(self) -> None:
        config = SingleTargetLoopConfig(model_path="fake.pt", labels=("block",))
        backend = FakeBackend({"single": success_output()})
        result = process_single_target_frame(
            config, backend, FakeImage("single", 100, 80, corrupted=True)
        )
        self.assert_failed(result, "INVALID_INPUT")

    def test_unexpected_backend_exception_fails_closed(self) -> None:
        class ExplodingBackend:
            name = "exploding"

            def infer(self, image):
                raise RuntimeError("boom")

        config = SingleTargetLoopConfig(model_path="fake.pt", labels=("block",))
        result = process_single_target_frame(config, ExplodingBackend(), FakeImage("single", 100, 80))
        self.assert_failed(result, "UNEXPECTED_BACKEND_FAILURE")

    def test_core_unknown_exception_maps_to_internal_core_error(self) -> None:
        config = SingleTargetLoopConfig(model_path="fake.pt", labels=("block",))
        backend = FakeBackend({"single": success_output()})

        with patch(
            "sorting_vision.single_target.postprocess",
            side_effect=RuntimeError("core boom"),
        ):
            result = process_single_target_frame(
                config, backend, FakeImage("single", 100, 80)
            )

        self.assert_failed(result, "INTERNAL_CORE_ERROR")

    def test_loop_passes_coordinate_transform_through(self) -> None:
        config = SingleTargetLoopConfig(
            model_path="fake.pt", labels=("block",), max_frames=1
        )
        backend = LoopFakeBackend({"single": success_output()}, frames=1)
        transform = AffineCoordinateTransform(
            matrix=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            x_bounds=(0.0, 100.0),
            y_bounds=(0.0, 100.0),
            frame="workspace_mm",
            unit="mm",
            calibration_id="cal-001",
        )
        results: list[SingleTargetResult] = []

        run_vision_loop(
            config,
            backend,
            results.append,
            coordinate_transform=transform,
        )

        self.assertEqual(1, len(results))
        result = results[0]
        self.assertIs(ResultStatus.OK, result.status)
        self.assertTrue(result.detection.motion_ready)
        self.assertTrue(result.motion_ready)
        self.assertEqual("workspace_mm", result.detection.coordinate.frame)
        self.assertEqual("cal-001", result.detection.coordinate.calibration_id)

    def test_loop_emits_after_consecutive_same_class_frames(self) -> None:
        config = SingleTargetLoopConfig(
            model_path="fake.pt",
            labels=("block",),
            max_frames=3,
            min_confirm_frames=3,
        )
        backend = LoopFakeBackend({"single": success_output()}, frames=3)
        results: list[SingleTargetResult] = []

        run_vision_loop(config, backend, results.append)

        self.assertEqual([3], [result.frame_id for result in results])

    def test_loop_confirmation_resets_when_class_changes(self) -> None:
        config = SingleTargetLoopConfig(
            model_path="fake.pt",
            labels=("block_a", "block_b"),
            max_frames=4,
            min_confirm_frames=2,
        )
        backend = SequenceLoopBackend(
            [
                BackendOutput(100, 80, (raw(0, 0.9, (10, 10, 30, 30)),)),
                BackendOutput(100, 80, (raw(1, 0.9, (10, 10, 30, 30)),)),
                BackendOutput(100, 80, (raw(0, 0.9, (10, 10, 30, 30)),)),
                BackendOutput(100, 80, (raw(0, 0.9, (10, 10, 30, 30)),)),
            ]
        )
        results: list[SingleTargetResult] = []

        run_vision_loop(config, backend, results.append)

        self.assertEqual([4], [result.frame_id for result in results])

    def test_loop_keeps_emitting_after_confirmation(self) -> None:
        config = SingleTargetLoopConfig(
            model_path="fake.pt",
            labels=("block",),
            max_frames=4,
            min_confirm_frames=2,
        )
        backend = LoopFakeBackend({"single": success_output()}, frames=4)
        results: list[SingleTargetResult] = []

        run_vision_loop(config, backend, results.append)

        self.assertEqual([2, 3, 4], [result.frame_id for result in results])

    def test_loop_failure_frame_resets_confirmation_and_is_emitted(self) -> None:
        config = SingleTargetLoopConfig(
            model_path="fake.pt",
            labels=("block",),
            max_frames=5,
            min_confirm_frames=3,
        )
        backend = SequenceLoopBackend(
            [
                BackendOutput(100, 80, (raw(0, 0.9, (10, 10, 30, 30)),)),
                BackendOutput(100, 80, ()),
                BackendOutput(100, 80, (raw(0, 0.9, (10, 10, 30, 30)),)),
                BackendOutput(100, 80, (raw(0, 0.9, (10, 10, 30, 30)),)),
                BackendOutput(100, 80, (raw(0, 0.9, (10, 10, 30, 30)),)),
            ]
        )
        results: list[SingleTargetResult] = []

        run_vision_loop(config, backend, results.append)

        self.assertEqual([2, 5], [result.frame_id for result in results])

    def test_loop_honors_max_frames_and_releases_backend(self) -> None:
        config = SingleTargetLoopConfig(
            model_path="fake.pt", labels=("block",), max_frames=3
        )
        backend = LoopFakeBackend({"single": success_output()}, frames=4)
        results: list[SingleTargetResult] = []

        run_vision_loop(config, backend, results.append)

        self.assertEqual(3, len(results))
        self.assertEqual([1, 2, 3], [result.frame_id for result in results])
        self.assertTrue(all(result.status is ResultStatus.OK for result in results))
        self.assertTrue(backend.released)

    def test_text_and_json_diagnostics_have_required_fields(self) -> None:
        detection = DetectionResult(
            target_seq=1,
            class_id=0,
            class_name="block",
            confidence=0.90,
            bbox=BoundingBox(10, 10, 30, 30),
            center_pixel=(20.0, 20.0),
            coordinate=Coordinate(x=20.0, y=20.0, frame="image_pixel", unit="pixel", calibrated=False),
        )
        result = SingleTargetResult(
            frame_id=3,
            status=ResultStatus.OK,
            backend="fake",
            detection=detection,
            elapsed_ms=12.5,
        )

        self.assertEqual("3:block:0.90:20.0,20.0:12.5ms\n", format_diagnostic_text(result))
        payload = json.loads(to_single_target_json(result))
        self.assertEqual(3, payload["frame_id"])
        self.assertIs(True, payload["diagnostic_only"])
        self.assertIs(False, payload["wire_codec_frozen"])
        self.assertIs(False, payload["motion_ready"])
        self.assertEqual(90.0, payload["confidence_percent"])

        text_config = SingleTargetLoopConfig(model_path="fake.pt", output_format="text")
        self.assertEqual(
            "3:block:0.90:20.0,20.0:12.5ms\n", render_diagnostic(text_config, result)
        )
        json_config = SingleTargetLoopConfig(model_path="fake.pt", output_format="json")
        self.assertIn('"diagnostic_only": true', render_diagnostic(json_config, result))

    def test_failed_text_diagnostic_includes_error_code(self) -> None:
        result = SingleTargetResult(
            frame_id=3,
            status=ResultStatus.FAILED,
            backend="fake",
            issues=(
                InferenceIssue(
                    "AMBIGUOUS_TARGET",
                    "expected exactly one target, found 2",
                ),
            ),
            elapsed_ms=12.5,
        )

        self.assertEqual(
            "3:none:AMBIGUOUS_TARGET:12.5ms\n", format_diagnostic_text(result)
        )

    def test_config_validate_rejects_unknown_output_format(self) -> None:
        config = SingleTargetLoopConfig(model_path="fake.pt", output_format="xml")
        with self.assertRaises(ConfigurationError):
            config.validate()


if __name__ == "__main__":
    unittest.main()
