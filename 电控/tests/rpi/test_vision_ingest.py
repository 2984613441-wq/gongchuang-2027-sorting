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

    def test_drop_point_resolution_fills_coordinates_and_angle(self) -> None:
        batch = BatchTargets(
            7,
            (
                VisionTarget(1, 2, box_id=3),
                VisionTarget(2, 5, box_id=1),
            ),
        )
        drop = {3: (1200, -800), 1: (-500, 400)}

        queue = build_item_task_queue(
            batch,
            image_id_for_class=lambda class_id: class_id + 100,
            drop_point_for_box=lambda box_id: drop[box_id],
        )

        self.assertEqual(
            (1200, -800, 0xFF),
            (queue[0].x_position, queue[0].y_position, queue[0].grip_angle),
        )
        self.assertEqual(
            (-500, 400, 0xFF),
            (queue[1].x_position, queue[1].y_position, queue[1].grip_angle),
        )
        # Resolved payloads become serializable at the wire boundary.
        self.assertEqual(8, len(encode_item_task_payload(queue[0])))

    def test_drop_point_resolution_requires_box_id(self) -> None:
        batch = BatchTargets(7, (VisionTarget(1, 2),))

        with self.assertRaises(TypeError):
            build_item_task_queue(
                batch,
                image_id_for_class=lambda class_id: 3,
                drop_point_for_box=lambda box_id: (0, 0),
            )


if __name__ == "__main__":
    unittest.main()
