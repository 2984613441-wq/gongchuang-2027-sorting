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
                BatchTargets(7, (VisionTarget(1, 2, 0),)),
                BatchTargets(7, (VisionTarget(2, 3, 0),)),
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
                VisionTarget(1, 2, 0),
                VisionTarget(2, 5, 0),
            ),
        )

        queue = build_item_task_queue(batch, image_id_for_class=lambda class_id: class_id)

        self.assertEqual((1, 2, 2), (queue[0].target_seq, queue[0].class_id, queue[0].image_id))
        self.assertEqual((2, 5, 5), (queue[1].target_seq, queue[1].class_id, queue[1].image_id))

    def test_queue_items_remain_logical_until_wire_boundary(self) -> None:
        batch = BatchTargets(7, (VisionTarget(1, 2, 0),))
        queue = build_item_task_queue(batch, image_id_for_class=lambda class_id: 3)

        with self.assertRaises(PayloadError):
            encode_item_task_payload(queue[0])

    def test_image_id_mapping_is_required_and_not_guessed(self) -> None:
        batch = BatchTargets(7, (VisionTarget(1, 2, 0),))

        with self.assertRaises(TypeError):
            build_item_task_queue(batch, image_id_for_class=None)

    def test_drop_point_resolution_fills_coordinates_and_angle(self) -> None:
        batch = BatchTargets(
            7,
            (
                VisionTarget(1, 2, 0, box_id=3),
                VisionTarget(2, 5, 0, box_id=1),
            ),
        )
        drop = {3: (1200, -800), 1: (-500, 400)}

        queue = build_item_task_queue(
            batch,
            image_id_for_class=lambda class_id: class_id,  # 冻结不变式: image_id == class_id
            drop_point_for_box=lambda box_id: drop[box_id],
            # P3: 抓取点（像素→mm 换算后的结果）必须单独注入；这里按 target_seq 给点。
            grasp_point_for_target=lambda target: (100 * target.target_seq, -50),
        )

        self.assertEqual(
            (1200, -800, 0xFF),
            (queue[0].x_position, queue[0].y_position, queue[0].grip_angle),
        )
        self.assertEqual(
            (-500, 400, 0xFF),
            (queue[1].x_position, queue[1].y_position, queue[1].grip_angle),
        )
        self.assertEqual(
            (100, -50),
            (queue[0].pick_x_position, queue[0].pick_y_position),
        )
        self.assertEqual(
            (200, -50),
            (queue[1].pick_x_position, queue[1].pick_y_position),
        )
        # 只有落料表 + 抓取点都注入后，载荷才可序列化（12 字节）。
        self.assertEqual(12, len(encode_item_task_payload(queue[0])))

    def test_without_grasp_calibration_payload_is_not_serializable(self) -> None:
        """P3 只提供通道，不提供数据源：没有像素→mm 换算就没有抓取点，
        载荷必须停在不可序列化状态，绝不用 (0,0) 顶上（E-18）。"""
        batch = BatchTargets(7, (VisionTarget(1, 2, 0, box_id=3),))

        queue = build_item_task_queue(
            batch,
            image_id_for_class=lambda class_id: class_id,
            drop_point_for_box=lambda box_id: (1200, -800),
        )

        self.assertIsNone(queue[0].pick_x_position)
        self.assertIsNone(queue[0].pick_y_position)
        with self.assertRaises(PayloadError):
            encode_item_task_payload(queue[0])

    def test_unresolvable_grasp_point_drops_the_item(self) -> None:
        """换算不出抓取点的件：拒识该件（跳过），绝不猜一个点。"""
        batch = BatchTargets(
            7,
            (
                VisionTarget(1, 2, 0, box_id=3),
                VisionTarget(2, 5, 0, box_id=1),
            ),
        )

        queue = build_item_task_queue(
            batch,
            image_id_for_class=lambda class_id: class_id,
            drop_point_for_box=lambda box_id: (1200, -800),
            grasp_point_for_target=lambda target: None if target.target_seq == 1 else (10, 20),
        )

        self.assertEqual(1, len(queue))
        self.assertEqual(2, queue[0].target_seq)

    def test_drop_point_resolution_requires_box_id(self) -> None:
        batch = BatchTargets(7, (VisionTarget(1, 2, 0),))

        with self.assertRaises(TypeError):
            build_item_task_queue(
                batch,
                image_id_for_class=lambda class_id: 3,
                drop_point_for_box=lambda box_id: (0, 0),
            )


if __name__ == "__main__":
    unittest.main()
