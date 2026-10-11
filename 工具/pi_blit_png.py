#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把已渲染好的 PNG 逐张贴到 /dev/fb0（树莓派侧，不含任何字体依赖）。

为什么存在：pi_screen_probe.py 在树莓派上【必须】找到中文字体才会出图（fail-closed），
而 Raspberry Pi OS Lite 常常没装 CJK 字库。这条保底通道把渲染搬到开发机，
树莓派只负责"解码 PNG → 按 fb 的真实像素格式打包 → 写 /dev/fb0"。

⚠️ 2026-09-17 实机教训（这段别删）：
   本机 fb 是 bits_per_pixel=16（RGB565），不是 32。
   第一版按 1024x600x3=1,843,200 字节直写 → [Errno 28] No space left on device
   （16bpp 一帧只要 1,228,800 字节，多写 614,400 字节直接越界）。
   所以本脚本【必须先读】/sys/class/graphics/fb0/bits_per_pixel，按真实 bpp 打包。
   连带发现：项目里的 display_hdmi.py / run_chain.py --frame-output fb0 都按 RGB888(32bpp)
   写，在 16bpp 的 fb 上会花屏 —— 要么给 config.txt 加 framebuffer_depth=32 并重启，
   要么让它们也按 bpp 打包。

用法（树莓派上）：
    python3 pi_blit_png.py                        # /tmp/frame_*.png -> /dev/fb0
    python3 pi_blit_png.py /dev/fb0 '/tmp/*.png'
    python3 pi_blit_png.py --info                 # 只打印 fb 参数，不写
    python3 pi_blit_png.py --list                 # 只列会贴哪些文件，不写
    python3 pi_blit_png.py --bpp 32               # 手动指定 bpp（读不到 sysfs 时）
    python3 pi_blit_png.py --selftest             # 不碰 fb，验 RGB565 打包
"""
from __future__ import annotations

import glob
import os
import sys
import time


def reconfigure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def read_sysfs(path: str) -> str | None:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except Exception:  # noqa: BLE001
        return None


def fb_info(fb: str) -> dict:
    """读 fb 的真实参数。sysfs 节点按设备名（fb0）挂，不看传入路径。"""
    name = os.path.basename(fb.rstrip("/")) or "fb0"
    base = "/sys/class/graphics/%s" % name
    info: dict = {"bpp": None, "vx": None, "vy": None, "line_length": None}
    bpp = read_sysfs(base + "/bits_per_pixel")
    if (bpp or "").isdigit():
        info["bpp"] = int(bpp)
    vs = read_sysfs(base + "/virtual_size")
    if vs and "," in vs:
        try:
            x, y = vs.split(",")[:2]
            info["vx"], info["vy"] = int(x), int(y)
        except ValueError:
            pass
    # 2026-09-18 树莓派实机修复：sysfs 里行长度这个属性叫 `stride`，
    # 不叫 `line_length`（实测 /sys/class/graphics/fb0/stride = 2048）。
    # 只读 line_length 会永远拿到 None → 有行填充的 fb 会写错。两个都试。
    ll = read_sysfs(base + "/line_length") or read_sysfs(base + "/stride")
    if (ll or "").isdigit():
        info["line_length"] = int(ll)
    return info


def encode_frame(im, bpp: int) -> bytes:
    """把 PIL 图像按 fb 的 bpp 打包成可直接写的字节。

    ⚠️ 2026-09-17 修正：原来 bpp=32 时直接返回 RGB888（3 字节/像素）是【错的】。
       fbdev 里 32bpp = 4 字节/像素（XRGB8888），一帧 1024x600 = 2,457,600 字节；
       写 1,843,200 字节只会填满 3/4 且像素错位。
       24/32bpp 的内存序都是 B,G,R[,X]（red 在 bit16 / green 在 bit8 / blue 在 bit0）。
       对照：电控/src/electrical_control/rpi/display_hdmi.py 的 _BYTES_PER_PIXEL
       = {16: 2, 24: 3, 32: 4}，与本实现一致。
       （实机树莓派是 16bpp，所以这条路径没被踩到，但必须写对。）
    """
    im = im.convert("RGB")
    raw = im.tobytes()
    n = len(raw) // 3
    if bpp == 16:
        # RGB565 小端。614k 次纯 Python 循环约 1 秒，够用。
        out = bytearray(n * 2)
        j = 0
        for i in range(0, len(raw), 3):
            v = ((raw[i] & 0xF8) << 8) | ((raw[i + 1] & 0xFC) << 3) | (raw[i + 2] >> 3)
            out[j] = v & 0xFF
            out[j + 1] = v >> 8
            j += 2
        return bytes(out)
    if bpp == 24:
        out = bytearray(n * 3)
        out[0::3] = raw[2::3]   # B
        out[1::3] = raw[1::3]   # G
        out[2::3] = raw[0::3]   # R
        return bytes(out)
    if bpp == 32:
        out = bytearray(n * 4)  # 第 4 字节保持 0（X）
        out[0::4] = raw[2::3]   # B
        out[1::4] = raw[1::3]   # G
        out[2::4] = raw[0::3]   # R
        return bytes(out)
    raise ValueError("暂不支持的 bits_per_pixel=%r（只支持 16/24/32）" % bpp)


def apply_stride(data: bytes, width: int, bpp: int, line_length: int | None) -> bytes:
    """fb 行有填充时（line_length > width*bpp/8）补零。"""
    row = width * (bpp // 8)
    if not line_length or line_length == row:
        return data
    if line_length < row:
        raise ValueError("line_length=%d 小于一行应有的 %d 字节" % (line_length, row))
    pad = b"\x00" * (line_length - row)
    return b"".join(data[i:i + row] + pad for i in range(0, len(data), row))


def selftest() -> int:
    from PIL import Image
    ok = True

    def chk(name, cond):
        nonlocal ok
        print("  [%s] %s" % ("OK" if cond else "FAIL", name))
        ok = ok and cond

    # 纯红 -> RGB565 = 0xF800；纯绿 -> 0x07E0；纯蓝 -> 0x001F
    for name, rgb, want in (("red", (255, 0, 0), 0xF800),
                            ("green", (0, 255, 0), 0x07E0),
                            ("blue", (0, 0, 255), 0x001F),
                            ("white", (255, 255, 255), 0xFFFF),
                            ("black", (0, 0, 0), 0x0000)):
        im = Image.new("RGB", (1, 1), rgb)
        b = encode_frame(im, 16)
        got = b[0] | (b[1] << 8)
        chk("%s -> 0x%04X" % (name, want), got == want and len(b) == 2)

    im = Image.new("RGB", (1024, 600), (10, 20, 30))
    chk("1024x600@16bpp = 1228800 字节", len(encode_frame(im, 16)) == 1228800)
    chk("1024x600@24bpp = 1843200 字节", len(encode_frame(im, 24)) == 1843200)
    chk("1024x600@32bpp = 2457600 字节", len(encode_frame(im, 32)) == 2457600)

    # 24/32bpp 必须是 B,G,R[,X]（fbdev truecolor 内存序），不是 RGB
    red = Image.new("RGB", (1, 1), (255, 0, 0))
    chk("24bpp 红 -> B,G,R = 00 00 FF", encode_frame(red, 24) == bytes((0, 0, 255)))
    chk("32bpp 红 -> B,G,R,X = 00 00 FF 00", encode_frame(red, 32) == bytes((0, 0, 255, 0)))
    blue = Image.new("RGB", (1, 1), (0, 0, 255))
    chk("24bpp 蓝 -> B,G,R = FF 00 00", encode_frame(blue, 24) == bytes((255, 0, 0)))
    chk("32bpp 蓝 -> B,G,R,X = FF 00 00 00", encode_frame(blue, 32) == bytes((255, 0, 0, 0)))

    # line_length 填充
    d = encode_frame(Image.new("RGB", (4, 2), (0, 0, 0)), 16)
    chk("无填充时原样返回", apply_stride(d, 4, 16, 8) == d)
    padded = apply_stride(d, 4, 16, 12)
    chk("line_length=12 时每行补 4 字节", len(padded) == 24)

    print("\n自检：%s" % ("全部通过" if ok else "有失败项"))
    return 0 if ok else 1


def main() -> int:
    reconfigure_stdout()
    args = sys.argv[1:]

    if "--selftest" in args:
        return selftest()

    if "--list" in args:
        args.remove("--list")
        pattern = args[1] if len(args) > 1 else (args[0] if args else "/tmp/frame_*.png")
        files = sorted(glob.glob(pattern))
        print("匹配 %d 个文件：" % len(files))
        for p in files:
            print("  " + p)
        return 0 if files else 2

    # 先摘掉所有 --flag（含带值的 --bpp N），再做位置参数解析；
    # 否则 `--info` 会被当成设备路径（2026-09-17 实机踩到）。
    positional: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--bpp", "--auto"):
            i += 2
            continue
        if a.startswith("--"):
            i += 1
            continue
        positional.append(a)
        i += 1

    fb = positional[0] if positional else "/dev/fb0"
    pattern = positional[1] if len(positional) > 1 else "/tmp/frame_*.png"
    force_bpp = None
    auto_s: float | None = None
    if "--auto" in args:
        j = args.index("--auto")
        try:
            auto_s = float(args[j + 1])
        except (IndexError, ValueError):
            print("--auto 后面要跟秒数，例如 --auto 3")
            return 2
    if "--bpp" in args:
        i = args.index("--bpp")
        try:
            force_bpp = int(args[i + 1])
        except (IndexError, ValueError):
            print("--bpp 后面要跟一个整数")
            return 2

    info = fb_info(fb)
    bpp = force_bpp or info.get("bpp")
    print("framebuffer : %s" % fb)
    print("bpp         : %s%s" % (info.get("bpp"),
                                  "   (--bpp 覆盖为 %d)" % force_bpp if force_bpp else ""))
    print("virtual_size: %sx%s" % (info.get("vx"), info.get("vy")))
    print("line_length : %s" % info.get("line_length"))

    if "--info" in args:
        return 0

    if not bpp:
        print("读不到 bits_per_pixel。用 --bpp 手动指定（16 或 32）。")
        return 2
    if bpp == 16:
        vx, vy = info.get("vx") or 0, info.get("vy") or 0
        print("            ^ 16bpp=RGB565；一帧 %dx%d 只要 %d 字节（不是 x3）" % (vx, vy, vx * vy * 2))
        print("              项目里 display_hdmi.py 按 RGB888 写，在 16bpp 上必然花屏。")

    try:
        from PIL import Image
    except ImportError:
        print("缺 Pillow。装：sudo apt install python3-pil")
        return 2

    files = sorted(glob.glob(pattern))
    if not files:
        print("没有匹配到 PNG：%s" % pattern)
        return 2

    for p in files:
        try:
            im = Image.open(p).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            print("  跳过 %s：%s" % (p, exc))
            continue
        try:
            data = encode_frame(im, bpp)
            data = apply_stride(data, im.size[0], bpp, info.get("line_length"))
        except Exception as exc:  # noqa: BLE001
            print("  跳过 %s：%s" % (p, exc))
            continue
        try:
            with open(fb, "wb") as fh:
                fh.write(data)
        except Exception as exc:  # noqa: BLE001
            print("  写 %s 失败：%s" % (fb, exc))
            if getattr(exc, "errno", None) == 28:
                print("  Errno 28 = 写超了 fb 容量：bpp 判断错了，或 virtual_size 与实际不符")
            print("  权限不足加 sudo；被占用先关桌面（sudo systemctl stop lightdm）")
            return 2
        if auto_s:
            print("  已上屏 %s (%dx%d -> %d 字节 @%dbpp)，停留 %.1fs 后自动下一张"
                  % (p, im.size[0], im.size[1], len(data), bpp, auto_s))
            time.sleep(auto_s)
        else:
            print("  已上屏 %s (%dx%d -> %d 字节 @%dbpp) —— 看完按回车看下一张"
                  % (p, im.size[0], im.size[1], len(data), bpp))
            if not sys.stdin.isatty():
                # 2026-09-18 实机踩到：非交互 SSH 下 input() 永远等不到回车，
                # 整个命令挂死（实测卡满 120s 超时）。没有 TTY 就不等待，贴完收工。
                print("    (stdin 不是终端，跳过等待；要停留请看 --auto)")
                break
            try:
                input()
            except EOFError:
                break

    print("\n全部贴完。若画面全黑/花屏/尺寸不对 -> 查 bpp 与 virtual_size，不是字体问题。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
