from __future__ import annotations

import unittest

from electrical_control.protocol import PayloadError, encode_item_task_payload
from electrical_control.rpi import (
    BatchTargets,
    FakeVisionSource,
    VisionTarget,
    build_item_task_queue,
)


class FakeVisionSourceTests(unittest.TestCase):
    def test_fake_source_is_deterministic_and_gate_controlled(self) -> None:
        source = FakeVisionSource(
            [
                BatchTargets(7, (VisionTarget(1, 2),)),
                BatchTargets(7, (VisionTarget(2, 3),)),
            ]
        )

        self.assertIsNone(source.next_if_permitted())
        source.set_permitted(True)
        self.assertEqual(1, source.next_if_permitted().targets[0].target_seq)
        self.assertEqual(2, source.next_if_permitted().targets[0].target_seq)
        self.assertIsNone(source.next_if_permitted())


class BuildItemTaskQueueTests(unittest.TestCase):
    def test_batch_becomes_queue_with_injected_image_ids(self) -> None:
        batch = BatchTargets(
            7,
            (
                VisionTarget(1, 2),
                VisionTarget(2, 5),
            ),
        )

        queue = build_item_task_queue(batch, image_id_for_class=lambda class_id: class_id + 100)

        self.assertEqual((1, 2, 102), (queue[0].target_seq, queue[0].class_id, queue[0].image_id))
        self.assertEqual((2, 5, 105), (queue[1].target_seq, queue[1].class_id, queue[1].image_id))

    def test_queue_items_remain_logical_until_wire_boundary(self) -> None:
        batch = BatchTargets(7, (VisionTarget(1, 2),))
        queue = build_item_task_queue(batch, image_id_for_class=lambda class_id: 3)

        with self.assertRaises(PayloadError):
            encode_item_task_payload(queue[0])

    def test_image_id_mapping_is_required_and_not_guessed(self) -> None:
        batch = BatchTargets(7, (VisionTarget(1, 2),))

        with self.assertRaises(TypeError):
            build_item_task_queue(batch, image_id_for_class=None)


if __name__ == "__main__":
    unittest.main()
