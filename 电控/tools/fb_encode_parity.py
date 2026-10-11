#!/usr/bin/env python3
"""encode_frame 新旧实现**逐字节对拍**（T6c 验收脚本，只读、不落盘）。

为什么要有它
------------
`rpi/display_hdmi.py:encode_frame` 要从"逐像素 Python 循环"（1024x600@16bpp
= 614,400 次迭代，实机约 0.3–0.6 s）改成 numpy 向量化。这条路径写错就是
**花屏/斜切/颜色错**，所以判据不是"看起来对"，而是**字节完全相同**。

本脚本把补丁前那份循环实现**原样内置**为基准（`legacy_encode_frame`），
与模块里的 `encode_frame` 对同一帧逐字节比较。跑法（**任何一台装了
numpy + Pillow 的机器都行；不写任何文件**）：

    python 电控/tools/fb_encode_parity.py
    # 树莓派：python3 /home/pi/电控/tools/fb_encode_parity.py

语料为什么不是纯色帧、也不是 `np.arange(...).reshape(...)`
----------------------------------------------------------
纯色帧（`Image.new("RGB",(1024,600),(10,20,30))`）对**位置类**错误是**盲的**
—— 行序交换、x/y 互换、整行错位、整幅平移，纯色帧的输出全都一样。

⚠️ 但 `np.arange(1024*600*3, dtype=np.uint8).reshape(600,1024,3)` **同样不行**：
一行 = 1024*3 = 3072 B，而 `3072 % 256 == 0` ⇒ 该语料**每一行字节完全相同**
（本机实测：600 行里只有 **1** 种不同的行）。行序颠倒、整幅平移照样对拍通过
—— 它只是换了一种盲法。

这里用**逐像素唯一**的确定性图样帧：(y,x) -> RGB 是单射，本机实测
614400/614400 个像素、600/600 行、1024/1024 列**互不相同**。
任何一个像素搬到别处，字节都会变。脚本每次启动把这三项打印出来，
语料日后被人改瞎了一眼就能看见。

覆盖 6 组：16/24/32bpp x (stride==row / stride>row)。
"""

from __future__ import annotations

import hashlib
import inspect
import sys
from pathlib import Path

import numpy as np
from PIL import Image

_EC = Path(__file__).resolve().parents[1]  # 电控/
if str(_EC / "src") not in sys.path:
    sys.path.insert(0, str(_EC / "src"))

from electrical_control.rpi.display_hdmi import (  # noqa: E402
    FramebufferFormat,
    FramebufferFormatError,
    encode_frame,
    validate_frame_size,
)

# 实机分辨率（树莓派那台就是 1024x600 @16bpp）
WIDTH, HEIGHT = 1024, 600

# 确定性图样帧：把像素序号按位切进 R/G/B ⇒ (y,x) -> RGB 是**单射**。
# 位分配：B = i & 0xFF、G = (i>>6) & 0xFF、R = (i>>12) & 0xFF；
# G+B 覆盖 i 的低 14 位、R 覆盖 12..19 位，故整个序号可还原（要求 W*H <= 2**20）。
_PIXEL_INDEX = (
    np.arange(HEIGHT, dtype=np.int64)[:, None] * WIDTH
    + np.arange(WIDTH, dtype=np.int64)[None, :]
)
PATTERN = np.stack(
    [
        (_PIXEL_INDEX >> 12) & 0xFF,
        (_PIXEL_INDEX >> 6) & 0xFF,
        _PIXEL_INDEX & 0xFF,
    ],
    axis=-1,
).astype(np.uint8)

# (bpp, line_length)：None = sysfs 读不到 line_length（= 实机现状，stride == row）
CASES: tuple[tuple[int, int | None], ...] = (
    (16, None),   # stride = 2048 = row
    (16, 2100),   # stride > row（行填充 52 B）
    (24, None),   # stride = 3072 = row
    (24, 3136),   # stride > row（行填充 64 B）
    (32, None),   # stride = 4096 = row
    (32, 4160),   # stride > row（行填充 64 B）
)


def legacy_encode_frame(frame: "Image.Image", fmt: FramebufferFormat) -> bytes:
    """补丁前 `display_hdmi.py` 的逐像素实现（原样抄录，作为对拍基准）。

    改这段没有意义 —— 它是"旧行为"的定义；改了就不再是对拍。
    """

    px = fmt.bytes_per_pixel
    width, height = frame.size
    validate_frame_size(width, height, fmt)

    row = width * px
    stride = fmt.line_length or row
    if stride < row:
        raise FramebufferFormatError(
            f"line_length/stride={stride} 小于一行应有的 {row} 字节"
            f"（{width}px @{fmt.bpp}bpp）"
        )

    rgb = frame.convert("RGB").tobytes()
    out = bytearray(width * height * px)
    index = 0
    if fmt.bpp == 16:
        for offset in range(0, len(rgb), 3):
            value = (
                ((rgb[offset] & 0xF8) << 8)
                | ((rgb[offset + 1] & 0xFC) << 3)
                | (rgb[offset + 2] >> 3)
            )
            out[index] = value & 0xFF  # 小端：低字节先写
            out[index + 1] = value >> 8
            index += 2
    else:  # 24/32bpp：B,G,R[,X]
        for offset in range(0, len(rgb), 3):
            out[index] = rgb[offset + 2]
            out[index + 1] = rgb[offset + 1]
            out[index + 2] = rgb[offset]
            index += px  # 32bpp 的第 4 字节保持 0（屏不用）

    data = bytes(out)
    if stride == row:
        return data
    pad = b"\x00" * (stride - row)
    return b"".join(
        data[at : at + row] + pad for at in range(0, len(data), row)
    )


def _implemented_with_numpy() -> bool:
    """模块里的 encode_frame 是不是 numpy 版（补丁到底应用了没有）。

    补丁**没应用**时本脚本照样"全过"（旧 vs 旧当然相同）—— 那是**假通过**，
    所以先把这件事打印出来，别把假通过当验收。
    """

    try:
        return "np.asarray" in inspect.getsource(encode_frame)
    except OSError:  # 打包成 zip 跑时拿不到源码
        return False


def _corpus_check() -> str:
    """把语料的"位置灵敏度"打出来：重复行/重复列/重复像素 = 对位置类错误失明。"""

    rows = len({row.tobytes() for row in PATTERN})
    cols = len({col.tobytes() for col in PATTERN.transpose(1, 0, 2)})
    pixels = len({pixel.tobytes() for pixel in PATTERN.reshape(-1, 3)})
    return (f"不同行 {rows}/{HEIGHT}、不同列 {cols}/{WIDTH}、"
            f"不同像素 {pixels}/{WIDTH * HEIGHT}")


def _first_diff(a: bytes, b: bytes, stride: int) -> str:
    """第一处不同的字节偏移 + 它落在第几行（定位"斜切/错位"最快的一眼）。"""

    for at, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return (f"第 {at} 字节 old={x:#04x} new={y:#04x}"
                    f"（第 {at // stride} 行第 {at % stride} 列）")
    return f"前缀相同但长度不同 old={len(a)} new={len(b)}"


def main() -> int:
    frame = Image.fromarray(PATTERN, "RGB")
    numpy_version = _implemented_with_numpy()
    print("encode_frame 新旧逐字节对拍（T6c）")
    print(
        f"被测实现 = {'numpy 向量化' if numpy_version else '旧逐像素循环'}"
        + ("  ← 补丁尚未应用，本次对拍恒真，不算验收" if not numpy_version else "")
    )
    print(f"语料 = 逐像素唯一图样帧 {WIDTH}x{HEIGHT}（{_corpus_check()}）")

    failed = 0
    for nth, (bpp, line_length) in enumerate(CASES, start=1):
        px = bpp // 8
        row = WIDTH * px
        stride = line_length or row
        fmt = FramebufferFormat(bpp, WIDTH, HEIGHT, line_length=line_length)
        old = legacy_encode_frame(frame, fmt)
        new = encode_frame(frame, fmt)
        same = old == new
        failed += 0 if same else 1
        tag = "OK " if same else "差异"
        where = "==row" if stride == row else f">{row}(+{stride - row})"
        print(
            f"[{tag}] {nth}/6  {bpp}bpp stride={stride}{where} "
            f"bytes={len(new)} sha256={hashlib.sha256(new).hexdigest()[:16]}"
        )
        if not same:
            print(f"       {_first_diff(old, new, stride)}")

    print(f"[{'PASS' if not failed else 'FAIL'}] {6 - failed}/6 组逐字节相同")
    if not numpy_version:
        print("提示：先应用补丁 docs/交付/2026-09-21/补丁-T6c-屏幕帧numpy化-2026-09-21.patch")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
