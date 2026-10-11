from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from typing import get_type_hints

from electrical_control.protocol import DisplayContent, ItemTaskPayload
from electrical_control.rpi import ItemTaskContext, PendingRender, RenderReceipt
from electrical_control.rpi.display import (
    DisplayRenderer,
    DisplayViewModel,
    FakeDisplayRenderer,
    build_display_view,
)


def context(target_seq: int = 1) -> ItemTaskContext:
    """ItemTaskContext("round-new", 7, 1, ItemTaskPayload(1, 2, 3, 0, 0, 0, None, None)) at seq 1."""
    return ItemTaskContext(
        round_id="round-new",
        task_id=7,
        frame_seq=target_seq,
        payload=ItemTaskPayload(target_seq, 2, 3, 0, 0, 0, None, None),
    )


class BuildDisplayViewTests(unittest.TestCase):
    def test_known_vector_resolves_name_and_passthroughs_fields(self) -> None:
        view = build_display_view(DisplayContent(1, 2, 3, 4, 0), {2: "锂离子电池"})

        self.assertEqual(DisplayViewModel(1, "锂离子电池", 3, 4, 0), view)
        self.assertEqual(1, view.target_seq)
        self.assertEqual("锂离子电池", view.name)
        self.assertEqual(3, view.image_id)
        self.assertEqual(4, view.success_count)
        self.assertEqual(0, view.result_code)

    def test_image_id_defaults_to_content_when_no_mapping(self) -> None:
        view = build_display_view(DisplayContent(1, 2, 3, 4, 0), {2: "x"}, image_ids=None)
        self.assertEqual(3, view.image_id)

    def test_image_ids_overrides_displayed_image(self) -> None:
        view = build_display_view(
            DisplayContent(1, 2, 3, 4, 0), {2: "x"}, image_ids={2: 99}
        )
        self.assertEqual(99, view.image_id)

    def test_missing_class_id_in_names_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as caught:
            build_display_view(DisplayContent(1, 2, 3, 4, 0), {1: "x"})
        self.assertIn("不在本地名称映射", str(caught.exception))
        self.assertIn("2", str(caught.exception))

    def test_missing_class_id_in_image_ids_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            build_display_view(DisplayContent(1, 2, 3, 4, 0), {2: "x"}, image_ids={1: 9})

    def test_view_model_is_frozen_and_hashable(self) -> None:
        view = build_display_view(DisplayContent(1, 2, 3, 4, 0), {2: "x"})

        with self.assertRaises(FrozenInstanceError):
            view.name = "other"

        self.assertEqual(hash(view), hash(DisplayViewModel(1, "x", 3, 4, 0)))


class FakeDisplayRendererTests(unittest.TestCase):
    def test_present_returns_pending_render_for_constructed_task(self) -> None:
        pending = FakeDisplayRenderer(context(1)).present(
            build_display_view(DisplayContent(1, 2, 3, 4, 0), {2: "x"})
        )

        self.assertIsInstance(pending, PendingRender)
        self.assertIsNone(pending.receipt)

    def test_complete_receipt_matches_original_content(self) -> None:
        content = DisplayContent(1, 2, 3, 4, 0)
        view = build_display_view(content, {2: "锂离子电池"})

        receipt = FakeDisplayRenderer(context(1)).present(view).complete()

        self.assertIsInstance(receipt, RenderReceipt)
        self.assertEqual("round-new", receipt.round_id)
        self.assertEqual(7, receipt.task_id)
        self.assertEqual(1, receipt.target_seq)
        self.assertEqual(content.crc32, receipt.content_crc32)

    def test_class_id_comes_from_task_payload_not_view(self) -> None:
        task = ItemTaskContext("round-new", 7, 1, ItemTaskPayload(1, 9, 3, 0, 0, 0, None, None))
        view = DisplayViewModel(1, "电池", 3, 4, 0)

        receipt = FakeDisplayRenderer(task).present(view).complete()

        self.assertEqual(DisplayContent(1, 9, 3, 4, 0).crc32, receipt.content_crc32)

    def test_double_complete_is_rejected(self) -> None:
        pending = FakeDisplayRenderer(context(1)).present(
            build_display_view(DisplayContent(1, 2, 3, 4, 0), {2: "x"})
        )
        pending.complete()

        with self.assertRaises(RuntimeError):
            pending.complete()


class DisplayRendererProtocolTests(unittest.TestCase):
    def test_present_signature_matches_contract(self) -> None:
        hints = get_type_hints(DisplayRenderer.present)
        self.assertEqual(
            {"view": DisplayViewModel, "return": PendingRender},
            hints,
        )


if __name__ == "__main__":
    unittest.main()
