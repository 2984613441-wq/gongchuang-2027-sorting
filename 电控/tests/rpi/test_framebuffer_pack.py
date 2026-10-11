"""Host-side tests for framebuffer packing（rpi/display_hdmi.py 的 fb 部分）。

不需要 /dev/fb0：这里验的是"按真实 bpp 打包"这一段本身 ——
16bpp 走 RGB565 小端、24/32bpp 走 fbdev 的 B,G,R[,X] 内存序、行填充、
以及读不到 bpp 时 fail-closed（绝不猜成 32）。

参考实现与实机验证记录：工具/pi_blit_png.py（同打包方式，16bpp 实机出图成功）。
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from unittest import mock

import numpy as np

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


@unittest.skipIf(Image is None, "Pillow not installed")
class PatternCorpusParityTests(unittest.TestCase):
    """图样帧 golden 对拍 —— **验收语料 2026-09-21 换过了**，别退回纯色帧。

    为什么换
    --------
    原语料 `Image.new("RGB",(1024,600),(10,20,30))` 是**纯色帧**，对**位置类**
    错误是**盲的**：行序颠倒、整幅沿 Y 挪一行、x/y 互换，纯色帧的输出全都一样。
    `np.arange(1024*600*3, dtype=np.uint8).reshape(...)` **也不行**：一行 =
    1024*3 = 3072 B，而 `3072 % 256 == 0` ⇒ 600 行里只有 **1** 种不同的行，
    对行序错误照样是盲的（这些是实测结论，矩阵见 `电控/tools/fb_encode_parity.py`）。

    这里改用**逐像素唯一**的图样帧（(y,x) -> RGB 是单射），并把 6 组
    `bpp x (stride==row / stride>row)` 的输出字节 sha256 **冻成 golden**。
    golden 由**补丁前的逐像素实现**算得 —— 旧行为就是基准，改 golden 等于改基准。
    """

    # 6 组 (bpp, line_length) -> 期望字节 sha256（1024x600 逐像素唯一图样帧）
    GOLDEN = {
        (16, None): "d862790fe24b70320f1729d76267d5c2ec2a2c1ceb723554132b62eae34827fe",
        (16, 2100): "87c7e150710eae7b7da862f93fe78d5e0402a8a29fac2d819345f3c424559dd1",
        (24, None): "21d59e0b1f7b2efbe14d8a193f1519e4c2f64c4995620b2fb8f5d9e43fe89f4e",
        (24, 3136): "b1a65b7d4d042029a3d415985229176c4834cfe29f5a1ea405ea4b1b3ee9d95a",
        (32, None): "40d20f9280405d9bdb9bca9b3acf4165f272feb2a7d48f14fa176b713d4afae3",
        (32, 4160): "b2b61a5d7664eaef3ae737f3c09a375720d6c4fcb61d0fbb0f91017e782a755f",
    }

    WIDTH, HEIGHT = 1024, 600

    @staticmethod
    def pattern() -> np.ndarray:
        """逐像素唯一的确定性图样帧：像素序号按位切进 R/G/B。"""

        index = (
            np.arange(PatternCorpusParityTests.HEIGHT, dtype=np.int64)[:, None]
            * PatternCorpusParityTests.WIDTH
            + np.arange(PatternCorpusParityTests.WIDTH, dtype=np.int64)[None, :]
        )
        return np.stack(
            [(index >> 12) & 0xFF, (index >> 6) & 0xFF, index & 0xFF], axis=-1
        ).astype(np.uint8)

    def test_corpus_is_position_sensitive(self) -> None:
        """语料自身必须先证明"不瞎"：没有重复行、没有重复列、像素互不相同。"""

        pattern = self.pattern()
        rows = len({row.tobytes() for row in pattern})
        cols = len({col.tobytes() for col in pattern.transpose(1, 0, 2)})
        pixels = len({pixel.tobytes() for pixel in pattern.reshape(-1, 3)})
        self.assertEqual(self.HEIGHT, rows, "图样帧有重复行 ⇒ 对行序错误是盲的")
        self.assertEqual(self.WIDTH, cols, "图样帧有重复列 ⇒ 对列错位是盲的")
        self.assertEqual(self.WIDTH * self.HEIGHT, pixels, "图样帧有重复像素")

    def test_row_flip_changes_bytes(self) -> None:
        """位置类改动的自检：行序颠倒必须改变字节（纯色/arange 语料抓不住）。"""

        pattern = self.pattern()
        fmt = FramebufferFormat(16, self.WIDTH, self.HEIGHT)
        same = encode_frame(Image.fromarray(pattern, "RGB"), fmt)
        flipped = encode_frame(Image.fromarray(pattern[::-1], "RGB"), fmt)
        self.assertNotEqual(same, flipped)

    def test_pattern_frame_bytes_match_golden(self) -> None:
        """6 组 bpp x stride 的字节 sha256 必须逐组等于基准。"""

        frame = Image.fromarray(self.pattern(), "RGB")
        for (bpp, line_length), want in self.GOLDEN.items():
            with self.subTest(bpp=bpp, line_length=line_length):
                fmt = FramebufferFormat(
                    bpp, self.WIDTH, self.HEIGHT, line_length=line_length
                )
                got = encode_frame(frame, fmt)
                self.assertEqual(
                    want,
                    hashlib.sha256(got).hexdigest(),
                    f"{bpp}bpp line_length={line_length} 的字节与补丁前不一致",
                )


if __name__ == "__main__":
    unittest.main()
