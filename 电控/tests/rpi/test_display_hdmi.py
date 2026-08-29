"""Unit tests for the real HDMI display renderer (rpi/display_hdmi.py).

Host tests only: Pillow composes frames, an injected FrameOutput captures
them, and PendingRender.complete() yields the RenderReceipt the DISPLAY_ACK
loop needs -- no hardware is touched.
"""

from __future__ import annotations

import os
import unittest
from typing import get_type_hints

from electrical_control.protocol import DisplayContent, ItemTaskPayload
from electrical_control.rpi import ItemTaskContext, PendingRender, RenderReceipt
from electrical_control.rpi.display import DisplayViewModel
from electrical_control.rpi.display_hdmi import (
    FrameOutput,
    HdmiDisplayRenderer,
    ImageLoadError,
    ImageLoader,
)

try:
    from PIL import Image
except ImportError:  # 模块本身无 Pillow 也应能 import（懒加载）
    Image = None


def make_task(
    *, target_seq: int = 1, class_id: int = 2, image_id: int = 3
) -> ItemTaskContext:
    return ItemTaskContext(
        round_id="round-new",
        task_id=7,
        frame_seq=target_seq,
        payload=ItemTaskPayload(target_seq, class_id, image_id, 0, 0, 0),
    )


def make_view(
    *,
    target_seq: int = 1,
    name: str = "锂离子电池",
    image_id: int = 3,
    success_count: int = 5,
    result_code: int = 0,
) -> DisplayViewModel:
    return DisplayViewModel(target_seq, name, image_id, success_count, result_code)


class FrameCapture:
    """FrameOutput 替身：记录收到的合成帧。"""

    def __init__(self) -> None:
        self.frames: list[Image.Image] = []

    def __call__(self, frame: Image.Image) -> None:
        self.frames.append(frame)


@unittest.skipIf(Image is None, "Pillow not installed")
class HdmiDisplayRendererTests(unittest.TestCase):
    RED = (200, 30, 30)
    BG = (14, 22, 40)

    def make_renderer(
        self, loader: ImageLoader, capture: FrameOutput, **kwargs: object
    ) -> HdmiDisplayRenderer:
        return HdmiDisplayRenderer(
            image_loader=loader, frame_output=capture, task=make_task(), **kwargs
        )

    def test_present_renders_1024x600_rgb_frame_and_outputs(self) -> None:
        capture = FrameCapture()
        pending = self.make_renderer(
            lambda image_id: Image.new("RGB", (100, 60), self.RED), capture
        ).present(make_view())

        self.assertEqual(1, len(capture.frames))
        frame = capture.frames[0]
        self.assertEqual((1024, 600), frame.size)
        self.assertEqual("RGB", frame.mode)
        self.assertIsInstance(pending, PendingRender)
        self.assertIsNone(pending.receipt)

    def test_receipt_matches_rebuilt_display_content_crc32(self) -> None:
        capture = FrameCapture()
        task = make_task(target_seq=1, class_id=2, image_id=3)
        renderer = HdmiDisplayRenderer(
            image_loader=lambda image_id: Image.new("RGB", (4, 4), self.RED),
            frame_output=capture,
            task=task,
        )
        view = make_view(
            target_seq=1, name="锂离子电池", image_id=3, success_count=5, result_code=0
        )

        receipt = renderer.present(view).complete()

        self.assertIsInstance(receipt, RenderReceipt)
        self.assertEqual("round-new", receipt.round_id)
        self.assertEqual(7, receipt.task_id)
        self.assertEqual(1, receipt.target_seq)
        expected = DisplayContent(1, 2, 3, 5, 0)
        self.assertEqual(expected.crc32, receipt.content_crc32)

    def test_class_id_comes_from_task_payload_not_view(self) -> None:
        task = make_task(target_seq=1, class_id=9, image_id=3)
        view = make_view(target_seq=1, name="电池", image_id=3, success_count=5, result_code=0)

        receipt = HdmiDisplayRenderer(
            image_loader=lambda image_id: Image.new("RGB", (4, 4), self.RED),
            frame_output=FrameCapture(),
            task=task,
        ).present(view).complete()

        self.assertEqual(DisplayContent(1, 9, 3, 5, 0).crc32, receipt.content_crc32)

    def test_image_loader_failure_is_fail_closed(self) -> None:
        def broken(image_id: int) -> None:
            raise RuntimeError("disk read failed")

        capture = FrameCapture()
        with self.assertRaises(ImageLoadError) as caught:
            self.make_renderer(broken, capture).present(make_view(image_id=3))

        self.assertIsInstance(caught.exception, ValueError)
        self.assertIn("image_id=3", str(caught.exception))
        self.assertIn("disk read failed", str(caught.exception))
        self.assertEqual([], capture.frames)  # 不产生半成品渲染

    def test_loader_returning_non_image_is_fail_closed(self) -> None:
        capture = FrameCapture()
        with self.assertRaises(ImageLoadError):
            self.make_renderer(lambda image_id: None, capture).present(make_view())
        self.assertEqual([], capture.frames)

    def test_wide_image_is_fitted_inside_image_box(self) -> None:
        capture = FrameCapture()
        self.make_renderer(
            lambda image_id: Image.new("RGB", (2000, 500), self.RED), capture
        ).present(make_view())
        frame = capture.frames[0]

        # 左栏图片区 (48,150)-(548,560)；2000x500 按宽缩放 -> 500x125 居中
        self.assertEqual(self.RED, frame.getpixel((298, 355)))  # 图片区内
        self.assertEqual(self.BG, frame.getpixel((10, 355)))    # 图片区左侧外
        self.assertEqual(self.BG, frame.getpixel((560, 355)))   # 图片区右侧外
        self.assertEqual(self.BG, frame.getpixel((298, 140)))   # 图片区上方（头部文字之下）
        self.assertEqual(self.BG, frame.getpixel((298, 575)))   # 图片区下方

    def test_tall_image_is_fitted_inside_image_box(self) -> None:
        capture = FrameCapture()
        self.make_renderer(
            lambda image_id: Image.new("RGB", (100, 800), self.RED), capture
        ).present(make_view())
        frame = capture.frames[0]

        # 100x800 按高缩放 -> 51x410 垂直占满、水平居中
        self.assertEqual(self.RED, frame.getpixel((298, 300)))  # 图片区内
        self.assertEqual(self.BG, frame.getpixel((100, 300)))   # 图片左侧留白
        self.assertEqual(self.BG, frame.getpixel((500, 300)))   # 图片右侧留白

    def test_rgba_image_is_flattened_to_rgb(self) -> None:
        capture = FrameCapture()
        rgba = Image.new("RGBA", (100, 60), (200, 30, 30, 255))
        self.make_renderer(lambda image_id: rgba, capture).present(make_view())
        frame = capture.frames[0]

        self.assertEqual("RGB", frame.mode)
        self.assertEqual(self.RED, frame.getpixel((298, 355)))

    def test_failure_result_code_still_renders(self) -> None:
        capture = FrameCapture()
        self.make_renderer(
            lambda image_id: Image.new("RGB", (4, 4), self.RED), capture
        ).present(make_view(result_code=1))
        self.assertEqual((1024, 600), capture.frames[0].size)

    def test_width_height_are_injected_not_hardcoded(self) -> None:
        capture = FrameCapture()
        renderer = HdmiDisplayRenderer(
            width=640,
            height=480,
            image_loader=lambda image_id: Image.new("RGB", (50, 50), self.RED),
            frame_output=capture,
            task=make_task(),
        )
        renderer.present(make_view())
        self.assertEqual((640, 480), capture.frames[0].size)

    def test_invalid_size_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            HdmiDisplayRenderer(
                width=0,
                image_loader=lambda image_id: Image.new("RGB", (4, 4), self.RED),
                frame_output=FrameCapture(),
                task=make_task(),
            )

    @unittest.skipUnless(
        os.path.exists(r"C:\Windows\Fonts\arial.ttf"), "arial.ttf not present"
    )
    def test_font_path_ttf_is_used_without_error(self) -> None:
        capture = FrameCapture()
        renderer = HdmiDisplayRenderer(
            image_loader=lambda image_id: Image.new("RGB", (50, 50), self.RED),
            frame_output=capture,
            task=make_task(),
            font_path=r"C:\Windows\Fonts\arial.ttf",
        )
        renderer.present(make_view())
        self.assertEqual((1024, 600), capture.frames[0].size)

    def test_double_complete_is_rejected(self) -> None:
        capture = FrameCapture()
        pending = self.make_renderer(
            lambda image_id: Image.new("RGB", (4, 4), self.RED), capture
        ).present(make_view())
        pending.complete()

        with self.assertRaises(RuntimeError):
            pending.complete()

    def test_present_signature_matches_display_renderer_protocol(self) -> None:
        hints = get_type_hints(HdmiDisplayRenderer.present)
        self.assertEqual(
            {"view": DisplayViewModel, "return": PendingRender}, hints
        )


if __name__ == "__main__":
    unittest.main()
