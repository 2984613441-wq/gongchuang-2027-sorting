"""Host-side tests for framebuffer packing（rpi/display_hdmi.py 的 fb 部分）。

不需要 /dev/fb0：这里验的是"按真实 bpp 打包"这一段本身 ——
16bpp 走 RGB565 小端、24/32bpp 走 fbdev 的 B,G,R[,X] 内存序、行填充、
以及读不到 bpp 时 fail-closed（绝不猜成 32）。

参考实现与实机验证记录：工具/pi_blit_png.py（同打包方式，16bpp 实机出图成功）。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from electrical_control.rpi import display_hdmi
from electrical_control.rpi.display_hdmi import (
    FramebufferFormat,
    FramebufferFormatError,
    FramebufferFrameOutput,
    encode_frame,
    read_framebuffer_format,
)

try:
    from PIL import Image
except ImportError:  # 模块本身无 Pillow 也应能 import（懒加载）
    Image = None


def rgb565_le(red: int, green: int, blue: int) -> bytes:
    value = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
    return bytes((value & 0xFF, value >> 8))


@unittest.skipIf(Image is None, "Pillow not installed")
class EncodeFrameTests(unittest.TestCase):
    def test_rgb565_little_endian_colors(self) -> None:
        """16bpp 的字节序判据：红=0xF800 → 字节 00 F8（小端）。"""

        fmt = FramebufferFormat(bpp=16, virtual_width=1, virtual_height=1)
        for color, want in (
            ((255, 0, 0), b"\x00\xf8"),      # 红 0xF800
            ((0, 255, 0), b"\xe0\x07"),      # 绿 0x07E0
            ((0, 0, 255), b"\x1f\x00"),      # 蓝 0x001F
            ((255, 255, 255), b"\xff\xff"),  # 白 0xFFFF
            ((0, 0, 0), b"\x00\x00"),        # 黑 0x0000
        ):
            with self.subTest(color=color):
                got = encode_frame(Image.new("RGB", (1, 1), color), fmt)
                self.assertEqual(2, len(got))
                self.assertEqual(want, got)
                self.assertEqual(rgb565_le(*color), got)

    def test_1024x600_frame_sizes_per_bpp(self) -> None:
        frame = Image.new("RGB", (1024, 600), (10, 20, 30))
        at16 = encode_frame(
            frame, FramebufferFormat(16, 1024, 600)
        )
        at32 = encode_frame(
            frame, FramebufferFormat(32, 1024, 600)
        )
        self.assertEqual(1228800, len(at16))  # 1024*600*2：实机 16bpp 一帧的字节数
        # 32bpp 是 4 字节/像素（RGBX），不是 3：写 3 字节/像素会让整幅斜切
        self.assertEqual(2457600, len(at32))

    def test_24bpp_is_bgr_in_memory(self) -> None:
        got = encode_frame(
            Image.new("RGB", (1, 1), (255, 0, 0)),
            FramebufferFormat(24, 1, 1),
        )
        self.assertEqual(b"\x00\x00\xff", got)

    def test_32bpp_is_bgrx_in_memory(self) -> None:
        got = encode_frame(
            Image.new("RGB", (1, 1), (0, 0, 255)),
            FramebufferFormat(32, 1, 1),
        )
        self.assertEqual(b"\xff\x00\x00\x00", got)

    def test_line_length_padding(self) -> None:
        frame = Image.new("RGB", (4, 2), (0, 0, 0))
        compact = encode_frame(frame, FramebufferFormat(16, 4, 2, line_length=8))
        padded = encode_frame(frame, FramebufferFormat(16, 4, 2, line_length=12))
        self.assertEqual(compact, padded[:8] + padded[12:20])  # 每行后多 4 字节
        self.assertEqual(16, len(compact))
        self.assertEqual(24, len(padded))
        self.assertEqual(b"\x00" * 4, padded[8:12])

    def test_frame_larger_than_fb_is_rejected(self) -> None:
        with self.assertRaises(FramebufferFormatError):
            encode_frame(
                Image.new("RGB", (1024, 600), (0, 0, 0)),
                FramebufferFormat(16, 800, 480),
            )

    def test_smaller_frame_is_allowed_with_warning(self) -> None:
        """fb 比帧大不是花屏，是"只画左上角"：允许，但要有告警。"""

        with self.assertLogs("electrical_control.rpi.display_hdmi", level="WARNING"):
            data = encode_frame(
                Image.new("RGB", (4, 2), (0, 0, 0)),
                FramebufferFormat(16, 8, 4),
            )
        self.assertEqual(4 * 2 * 2, len(data))

    def test_stride_smaller_than_row_is_rejected(self) -> None:
        with self.assertRaises(FramebufferFormatError):
            encode_frame(
                Image.new("RGB", (4, 1), (0, 0, 0)),
                FramebufferFormat(16, 4, 1, line_length=4),
            )

    def test_unsupported_bpp_is_rejected(self) -> None:
        with self.assertRaises(FramebufferFormatError):
            encode_frame(
                Image.new("RGB", (1, 1), (0, 0, 0)),
                FramebufferFormat(8, 1, 1),
            )


class ReadFramebufferFormatTests(unittest.TestCase):
    """在没有 fb 的机器上只能验 fail-closed 这一半（真数值要上树莓派读）。"""

    def test_missing_sysfs_nodes_fail_closed_not_32bpp(self) -> None:
        with self.assertRaises(FramebufferFormatError) as caught:
            read_framebuffer_format("/dev/fb-does-not-exist")
        message = str(caught.exception)
        self.assertIn("bits_per_pixel", message)
        self.assertIn("拒绝猜 bpp", message)


@unittest.skipIf(Image is None, "Pillow not installed")
class FrameOutputCallbackTests(unittest.TestCase):
    def test_callback_writes_exactly_encode_frame_bytes(self) -> None:
        """用临时文件当设备，验证回调写下去的字节与 encode_frame 完全一致。"""

        frame = Image.new("RGB", (4, 2), (255, 0, 0))
        fmt = FramebufferFormat(16, 4, 2)
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "fb0")
            output = FramebufferFrameOutput.__new__(FramebufferFrameOutput)
            output.device = target
            output.format = fmt
            output(frame)
            with open(target, "rb") as handle:
                written = handle.read()
        self.assertEqual(encode_frame(frame, fmt), written)
        self.assertEqual(16, len(written))

    def test_pi_like_16bpp_fb_end_to_end(self) -> None:
        """照实机那台 Pi 的 sysfs 值（16bpp / 1024,600 / line_length 读不到）跑完整条路径：
        构造 → 读格式 → 校验尺寸 → 打包 → 写设备，落盘字节数必须是 1,228,800。
        按 32bpp 写 1,843,200 就是实机踩到的 [Errno 28]。"""

        nodes = {
            "/sys/class/graphics/fb0/bits_per_pixel": "16",
            "/sys/class/graphics/fb0/virtual_size": "1024,600",
        }
        with mock.patch.object(
            display_hdmi, "_read_sysfs", lambda path: nodes.get(path)
        ):
            with tempfile.TemporaryDirectory() as directory:
                target = os.path.join(directory, "fb0")
                output = FramebufferFrameOutput(target, size=(1024, 600))
                output(Image.new("RGB", (1024, 600), (14, 22, 40)))
                written = os.path.getsize(target)

        self.assertEqual(16, output.format.bpp)
        self.assertIsNone(output.format.line_length)  # 实机就是这个节点读不到
        self.assertEqual(1228800, written)


if __name__ == "__main__":
    unittest.main()
