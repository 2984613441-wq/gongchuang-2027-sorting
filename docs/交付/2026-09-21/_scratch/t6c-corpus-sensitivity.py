"""临时证据脚本（T6c，非交付物）：验收语料灵敏度矩阵 + 提速实测。

问题：现有验收用纯色帧 `Image.new("RGB",(1024,600),(10,20,30))`，对**位置类**
错误是盲的。这里造 6 种**典型写错法**，用三种候选语料分别去对拍，看谁抓得住：

  A 纯色帧            —— 现有测试用的
  B np.arange(...).reshape(...)  —— 原方案建议的
  C 逐像素唯一图样帧   —— 本补丁实际采用的

判据：变体输出 != 旧实现输出 ⇒ "抓住"；否则 "漏掉"（对拍会假通过）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

_ROOT = Path(__file__).resolve().parents[4]  # 工创赛/
sys.path.insert(0, str(_ROOT / "电控" / "src"))
sys.path.insert(0, str(_ROOT / "电控" / "tools"))

from fb_encode_parity import PATTERN as CORPUS_C, legacy_encode_frame  # noqa: E402
from electrical_control.rpi.display_hdmi import (  # noqa: E402
    FramebufferFormat,
    encode_frame,
)

W, H = 1024, 600
CORPUS_A = np.full((H, W, 3), (10, 20, 30), dtype=np.uint8)
CORPUS_B = np.arange(W * H * 3, dtype=np.uint8).reshape(H, W, 3)


# --------------------------------------------------------------------------
# 6 种典型"写错法"。每个都返回"错误的字节"，用来检验语料抓不抓得住。
# --------------------------------------------------------------------------
def bug_uint8_shift(frame, fmt):
    """颜色类：16bpp 忘了 astype(uint16) ⇒ uint8 左移回绕，红色全变 0。"""

    rgb = np.asarray(frame.convert("RGB"), dtype=np.uint8)
    v = ((rgb[:, :, 0] & 0xF8) << 8) | ((rgb[:, :, 1] & 0xFC) << 3) | (rgb[:, :, 2] >> 3)
    return _pack(v, fmt, 2)


def bug_channel_order(frame, fmt):
    """颜色类：24/32bpp 写成 R,G,B（fbdev 要的是 B,G,R）。"""

    rgb = np.asarray(frame.convert("RGB"), dtype=np.uint8)
    px = fmt.bytes_per_pixel
    row = W * px
    out = np.zeros((rgb.shape[0], row), dtype=np.uint8)
    out[:, 0::px] = rgb[:, :, 0]
    out[:, 1::px] = rgb[:, :, 1]
    out[:, 2::px] = rgb[:, :, 2]
    return _pad(out.tobytes(), row, fmt)


def bug_row_flip(frame, fmt):
    """位置类：行序颠倒。"""

    return _encode(np.asarray(frame.convert("RGB"), dtype=np.uint8)[::-1], fmt)


def bug_row_shift(frame, fmt):
    """位置类：整幅沿 Y 挪一行（wrap）。"""

    rgb = np.asarray(frame.convert("RGB"), dtype=np.uint8)
    return _encode(np.roll(rgb, 1, axis=0), fmt)


def bug_col_shift(frame, fmt):
    """位置类：每行沿 X 挪一像素（wrap）。"""

    rgb = np.asarray(frame.convert("RGB"), dtype=np.uint8)
    return _encode(np.roll(rgb, 1, axis=1), fmt)


def bug_pad_once(frame, fmt):
    """布局类：行填充一次补到末尾（第 2 行起整幅斜切）。"""

    row, stride = W * fmt.bytes_per_pixel, (fmt.line_length or W * fmt.bytes_per_pixel)
    if stride == row:
        return None  # 该配置没有行填充，这个 bug 不存在
    data = encode_frame(frame, fmt)
    body = b"".join(data[at : at + stride][:row] for at in range(0, len(data), stride))
    return body + b"\x00" * (stride - row)


VARIANTS = (
    ("颜色类：uint8移位回绕", bug_uint8_shift, (16,)),
    ("颜色类：通道序写成RGB", bug_channel_order, (24, 32)),
    ("位置类：行序颠倒", bug_row_flip, (16, 24, 32)),
    ("位置类：整幅Y挪一行", bug_row_shift, (16, 24, 32)),
    ("位置类：行内X挪一像素", bug_col_shift, (16, 24, 32)),
    ("布局类：行填充补到末尾", bug_pad_once, (16, 24, 32)),
)

CORPORA = (("A 纯色", CORPUS_A), ("B arange", CORPUS_B), ("C 逐像素唯一", CORPUS_C))
CONFIGS = (
    ("16bpp stride==row", FramebufferFormat(16, W, H)),
    ("16bpp stride>row", FramebufferFormat(16, W, H, line_length=2100)),
    ("32bpp stride==row", FramebufferFormat(32, W, H)),
    ("32bpp stride>row", FramebufferFormat(32, W, H, line_length=4160)),
)


def _encode(rgb, fmt):
    """正确的 numpy 编码（用来表达"只有那一个地方写错了"）。"""

    if fmt.bpp == 16:
        r = rgb[:, :, 0].astype(np.uint16)
        g = rgb[:, :, 1].astype(np.uint16)
        b = rgb[:, :, 2].astype(np.uint16)
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        return _pack(v, fmt, 2)
    px = fmt.bytes_per_pixel
    row = W * px
    out = np.zeros((rgb.shape[0], row), dtype=np.uint8)
    out[:, 0::px] = rgb[:, :, 2]
    out[:, 1::px] = rgb[:, :, 1]
    out[:, 2::px] = rgb[:, :, 0]
    return _pad(out.tobytes(), row, fmt)


def _pack(value, fmt, px):
    return _pad(value.astype("<u2").tobytes(), W * px, fmt)


def _pad(data, row, fmt):
    stride = fmt.line_length or row
    if stride == row:
        return data
    pad = b"\x00" * (stride - row)
    return b"".join(data[at : at + row] + pad for at in range(0, len(data), row))


def main() -> int:
    print("=== 语料灵敏度矩阵（抓住 = 该语料能发现这种写错法）===")
    for cfg_name, fmt in CONFIGS:
        bases = {
            label: legacy_encode_frame(Image.fromarray(arr, "RGB"), fmt)
            for label, arr in CORPORA
        }
        print(f"\n--- {cfg_name} ---")
        print(f"{'写错法':<24}" + "".join(f"{label:<14}" for label, _ in CORPORA))
        for name, fn, bpps in VARIANTS:
            cells = []
            for label, arr in CORPORA:
                if fmt.bpp not in bpps:
                    cells.append("n/a")
                    continue
                got = fn(Image.fromarray(arr, "RGB"), fmt)
                if got is None:
                    cells.append("n/a")
                else:
                    cells.append("抓住" if got != bases[label] else "**漏掉**")
            print(f"{name:<24}" + "".join(f"{c:<14}" for c in cells))

    print("\n=== 语料自身：不同行/列/像素的种数（越少越盲）===")
    for label, arr in CORPORA:
        rows = len({r.tobytes() for r in arr})
        cols = len({c.tobytes() for c in arr.transpose(1, 0, 2)})
        print(f"  {label:<14} 行 {rows}/{H}   列 {cols}/{W}")

    print("\n=== 提速实测（1024x600@16bpp，同机同帧，各 3 次取最好）===")
    fmt16 = FramebufferFormat(16, W, H)
    frame = Image.fromarray(CORPUS_C, "RGB")
    times = {}
    for label, fn in (("旧逐像素循环", legacy_encode_frame), ("numpy 向量化", encode_frame)):
        times[label] = min(_timeit(fn, frame, fmt16) for _ in range(3))
        print(f"  {label:<14} {times[label] * 1000:6.1f} ms")
    print(f"  省下 {times['旧逐像素循环'] - times['numpy 向量化']:.3f} s / 帧"
          "（本机 4 核 x86；树莓派上原循环更慢，见交付说明）")
    return 0


def _timeit(fn, frame, fmt) -> float:
    t = time.perf_counter()
    fn(frame, fmt)
    return time.perf_counter() - t


if __name__ == "__main__":
    raise SystemExit(main())
