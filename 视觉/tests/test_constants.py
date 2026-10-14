"""Guard tests for ``sorting_vision.constants`` and its consumers.

These assert that each module's default equals the shared constant, so the
"single source of truth" claim cannot silently rot into two divergent values.

Scope limit: these compare *values*, so they catch drift but NOT re-inlining.
Replacing ``confidence_threshold = DEFAULT_CONFIDENCE_THRESHOLD`` with a literal
``0.50`` in ``config.py`` keeps every test here green (and an identity check
would not help either - ``1450`` is an interned small int). Verifying that a
module actually *reads* the constant would need a source/AST scan, which this
suite deliberately does not do.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from sorting_vision import constants
from sorting_vision.backends import FakeBackend
from sorting_vision.config import InferenceConfig
from sorting_vision.drop_table import ITEM_TASK_COORD_LIMIT
from sorting_vision.pipeline import VisionPipeline
from sorting_vision.single_target import MAX_DETECTIONS, SingleTargetLoopConfig
from sorting_vision.types import BackendOutput, BoundingBox, FakeImage, RawDetection, ResultStatus


class ConstantsAreTheOnlySourceTests(unittest.TestCase):
    def test_batch_config_defaults_come_from_constants(self) -> None:
        config = InferenceConfig(class_names={0: "class_a"})
        self.assertEqual(constants.DEFAULT_CONFIDENCE_THRESHOLD, config.confidence_threshold)
        self.assertEqual(constants.DEFAULT_NMS_IOU_THRESHOLD, config.nms_iou_threshold)
        self.assertEqual(
            (constants.DEFAULT_INPUT_WIDTH, constants.DEFAULT_INPUT_HEIGHT), config.input_size
        )
        self.assertEqual(constants.DEFAULT_MAX_DETECTIONS_BATCH, config.max_detections)

    def test_single_target_defaults_come_from_constants(self) -> None:
        config = SingleTargetLoopConfig(model_path="fake.pt")
        self.assertEqual(constants.DEFAULT_CONFIDENCE_THRESHOLD, config.confidence)
        self.assertEqual(constants.DEFAULT_INPUT_WIDTH, config.input_width)
        self.assertEqual(constants.DEFAULT_INPUT_HEIGHT, config.input_height)

    def test_single_target_and_batch_confidence_defaults_agree(self) -> None:
        # Regression guard: these two drifted apart once (0.35 vs 0.50).
        batch = InferenceConfig(class_names={0: "class_a"})
        loop = SingleTargetLoopConfig(model_path="fake.pt")
        self.assertEqual(batch.confidence_threshold, loop.confidence)
        self.assertEqual(0.50, loop.confidence)

    def test_max_detections_alias_matches_the_constant(self) -> None:
        self.assertEqual(constants.MAX_DETECTIONS_SINGLE_TARGET, MAX_DETECTIONS)
        # Must stay above 1 so DUPLICATE_DETECTION is reachable before
        # AMBIGUOUS_TARGET; see the constants docstring.
        self.assertGreater(constants.MAX_DETECTIONS_SINGLE_TARGET, 1)

    def test_drop_table_reuses_the_protocol_coordinate_bound(self) -> None:
        self.assertEqual(constants.COORDINATE_BOUND_MM10, ITEM_TASK_COORD_LIMIT)
        self.assertEqual(1450, ITEM_TASK_COORD_LIMIT)

    def test_protocol_values_match_the_frozen_contract(self) -> None:
        # interface-contract.md V0.9: task_id uint16, target_seq uint8,
        # |X|,|Y| <= 1450 in 0.1 mm.
        self.assertEqual(65535, constants.MAX_TASK_ID)
        self.assertEqual(255, constants.MAX_TARGET_SEQ)
        self.assertEqual(1450, constants.COORDINATE_BOUND_MM10)

    def test_min_contour_area_is_positive(self) -> None:
        self.assertGreater(constants.MIN_CONTOUR_AREA_PX, 0)


class PipelineUsesTheConstantsTests(unittest.TestCase):
    """The literals are gone, so the boundaries must still be the same ones."""

    def setUp(self) -> None:
        self.config = InferenceConfig(class_names={0: "class_a"})
        backend = FakeBackend({"frame": BackendOutput(100, 80, (RawDetection(
            0, 0.90, BoundingBox(10, 10, 30, 30)
        ),))})
        self.pipeline = VisionPipeline(self.config, backend)

    def test_task_id_upper_bound_is_accepted(self) -> None:
        result = self.pipeline.infer_batch(constants.MAX_TASK_ID, FakeImage("frame", 100, 80))
        self.assertIs(ResultStatus.OK, result.status)

    def test_task_id_above_the_bound_fails_closed(self) -> None:
        result = self.pipeline.infer_batch(constants.MAX_TASK_ID + 1, FakeImage("frame", 100, 80))
        self.assertIs(ResultStatus.FAILED, result.status)
        self.assertEqual("INVALID_INPUT", result.issues[0].code)

    def test_task_id_non_integer_fails_closed_and_echoes_minus_one(self) -> None:
        result = self.pipeline.infer_batch("7", FakeImage("frame", 100, 80))
        self.assertIs(ResultStatus.FAILED, result.status)
        self.assertEqual(-1, result.task_id)

    def test_target_seq_boundaries_fail_closed(self) -> None:
        for target_seq in (0, constants.MAX_TARGET_SEQ + 1):
            with self.subTest(target_seq=target_seq):
                result = self.pipeline.reacquire(
                    constants.MAX_TASK_ID, target_seq, 0, FakeImage("frame", 100, 80)
                )
                self.assertIs(ResultStatus.FAILED, result.status)
                self.assertEqual("INVALID_INPUT", result.issues[0].code)

    def test_target_seq_upper_bound_is_accepted(self) -> None:
        result = self.pipeline.reacquire(
            constants.MAX_TASK_ID, constants.MAX_TARGET_SEQ, 0, FakeImage("frame", 100, 80)
        )
        self.assertIs(ResultStatus.OK, result.status)


if __name__ == "__main__":
    unittest.main()
