#!/usr/bin/env python3
"""把 /dev/fb0 的当前内容读回来存成 PNG，用于「屏上到底画了什么」的可复核证据。

按 fb 的**真实**几何读（sysfs 的 bits_per_pixel / virtual_size / stride），
16bpp 按 RGB565 小端手工解码 —— 不依赖 PIL 的 rawmode 命名（'BGR;16' 到底是
565 还是 555 各版本说法不一，猜错了颜色就全错，等于没有证据）。

用法：python3 pi_fb_dump.py /home/pi/_stage/fb0_dump.png
"""

import os
import sys

from PIL import Image

FB = "/dev/fb0"
SYS = "/sys/class/graphics/fb0"


def read_int(name, default=None):
    try:
        with open(os.path.join(SYS, name)) as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return default


def main(out_path):
    bpp = read_int("bits_per_pixel")
    virtual = read_int("virtual_size")  # 读不到就下面兜底
    stride = read_int("stride") or read_int("line_length")
    width, height = 1024, 600
    try:
        with open(os.path.join(SYS, "virtual_size")) as handle:
            w, h = handle.read().strip().split(",")
            width, height = int(w), int(h)
    except (OSError, ValueError):
        pass
    if virtual is None and (width, height) == (1024, 600):
        pass
    if stride is None:
        stride = width * (bpp // 8)

    print(f"{FB}: {width}x{height} @{bpp}bpp stride={stride}（读自 sysfs）")
    if bpp != 16:
        print(f"本脚本只实现了 16bpp 解码，实际 {bpp}bpp —— 拒绝按猜的格式解")
        return 2

    with open(FB, "rb") as handle:
        raw = handle.read(height * stride)
    print(f"读回 {len(raw)} 字节（期望 {height * stride}）")
    if len(raw) < height * stride:
        print("读回的字节数不足一帧，拒绝出图")
        return 3

    out = bytearray(width * height * 3)
    for y in range(height):
        base = y * stride
        o = y * width * 3
        for x in range(width):
            at = base + x * 2
            value = raw[at] | (raw[at + 1] << 8)  # 小端：低字节先
            i = o + x * 3
            out[i] = ((value >> 11) & 0x1F) * 255 // 31      # R
            out[i + 1] = ((value >> 5) & 0x3F) * 255 // 63   # G
            out[i + 2] = (value & 0x1F) * 255 // 31          # B

    Image.frombytes("RGB", (width, height), bytes(out)).save(out_path)
    print(f"已写出 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/fb0_dump.png"))
