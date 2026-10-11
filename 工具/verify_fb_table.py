#!/usr/bin/env python3
"""对「树莓派 /dev/fb0 回读帧」做结构校验（不看屏也能判定屏上画了什么）。

不是渲染一遍再自比 —— 输入是**真机 framebuffer 的回读 dump**，走完了
「PIL 合成 → encode_frame RGB565 → 写 /dev/fb0 → 回读 → 手工解 565」整条真路径。
所以它能发现：字节序写反、行填充错位、缩略图贴错行、表格挤出行外。

用法：py -3 工具/verify_fb_table.py 工具/_fb0_table.png
"""

from __future__ import annotations

import os
import sys

from PIL import Image, ImageOps

ROW_TOP, ROW_H, THUMB = 92, 82, 64
THUMB_X = (180 + 420 - THUMB) // 2
BG = (14, 22, 40)


def through_rgb565(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """把颜色过一遍 RGB565 编码→解码，得到「回读帧里应该看到的那个值」。

    ⚠️ **不要拿原始底色直接比回读帧**：16bpp 是 5/6/5 位，写下去就已经被量化了。
    底色 (14,22,40) 写进 fb 再读回来是 (8,20,41)，每通道差 6 —— 那是这个格式的
    分辨率上限，不是错位。（本校验的第一版正是这样误报的。）
    """
    r, g, b = rgb
    value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return (((value >> 11) & 0x1F) * 255 // 31,
            ((value >> 5) & 0x3F) * 255 // 63,
            (value & 0x1F) * 255 // 31)


BG565 = through_rgb565(BG)
IMAGES = {1: "image1.jpeg", 2: "image6.jpeg", 3: "image2.jpeg",
          4: "image3.jpeg", 5: "image4.jpeg", 6: "image5.jpeg"}
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "object_images")


def rms(a: Image.Image, b: Image.Image) -> float:
    pa, pb = a.convert("RGB").tobytes(), b.convert("RGB").tobytes()
    return (sum((pa[i] - pb[i]) ** 2 for i in range(len(pa))) / len(pa)) ** 0.5


def expected_thumb(seq: int) -> Image.Image:
    res = getattr(Image, "Resampling", Image)
    with Image.open(os.path.join(ROOT, IMAGES[seq])) as handle:
        return ImageOps.fit(handle.convert("RGB"), (THUMB, THUMB), res.LANCZOS)


def main(path: str) -> int:
    frame = Image.open(path).convert("RGB")
    print(f"帧：{path}  {frame.size}  {frame.mode}")
    failures: list[str] = []

    if frame.size != (1024, 600):
        failures.append(f"帧尺寸 {frame.size} != (1024, 600)")
    for corner in ((1010, 590), (10, 590), (10, 6), (1010, 6)):
        if frame.getpixel(corner) != BG565:
            failures.append(
                f"角点 {corner} = {frame.getpixel(corner)} != {BG565}（期望底色过 RGB565）"
                "（整幅可能斜切/错位）"
            )
    print(f"  四角底色 = {BG565}（= 底色{BG} 过 RGB565）：OK" if not failures else "")

    # 1) 每一行的缩略图必须**最像自己那一行的图**
    thumbs = {}
    for seq in IMAGES:
        y = ROW_TOP + (seq - 1) * ROW_H + (ROW_H - THUMB) // 2
        crop = frame.crop((THUMB_X, y, THUMB_X + THUMB, y + THUMB))
        thumbs[seq] = crop
        scores = {other: rms(crop, expected_thumb(other)) for other in IMAGES}
        best = min(scores, key=scores.get)
        flag = "OK " if best == seq else "BAD"
        print(f"  行{seq}: 最像行 {best}  (RMS={scores[seq]:5.2f}, 次小={sorted(scores.values())[1]:5.2f})  {flag}")
        if best != seq:
            failures.append(f"行 {seq} 的缩略图最像行 {best}（放错图了）")
        if scores[seq] > 40:
            failures.append(f"行 {seq} 的 RMS={scores[seq]:.1f} 偏大（图可能没贴上/贴歪）")

    # 2) 六行都要有实际绘制内容（防「合成成功但整幅是底色」）
    for seq in IMAGES:
        y = ROW_TOP + (seq - 1) * ROW_H
        for name, box in (("序号列", (32, y + 6, 180, y + 76)),
                          ("个数列", (420, y + 6, 992, y + 76))):
            data = frame.crop(box).tobytes()
            drawn = sum(1 for i in range(0, len(data), 3) if data[i:i + 3] != bytes(BG565))
            if drawn == 0:
                failures.append(f"第 {seq} 行 {name} 是空的")
    print("  六行 × (序号列, 个数列) 均非空：OK" if not failures else "")

    # 3) 表头与标题：顶部必须有强调色（标题+表头分隔线）与灰色表头文字
    top = frame.crop((0, 0, 1024, 92))
    accent = sum(1 for i in range(0, len(top.tobytes()), 3)
                 if abs(top.tobytes()[i] - 88) < 40 and top.tobytes()[i + 2] > 150)
    print(f"  顶部强调色像素 {accent}（标题 + 表头分隔线）")
    if accent < 500:
        failures.append(f"顶部强调色像素只有 {accent}，标题/表头可能没画上")

    # 4) 演示计数 1=2 3=1 5=3，其余 0 —— 计数为 0 与不为 0 的格子必须不同
    def cell(seq):
        y = ROW_TOP + (seq - 1) * ROW_H
        return frame.crop((420, y + 6, 992, y + 76)).tobytes()

    if cell(1) == cell(2):
        failures.append("行1(计数2) 与 行2(计数0) 的个数格完全相同 —— 计数没进画面")
    else:
        print("  计数格 行1(2) != 行2(0)：OK")

    print()
    if failures:
        print("❌ 校验失败：")
        for item in failures:
            print("   ·", item)
        return 1
    print("✅ 全部通过：真机回读帧里，六行序号/图片/计数都在位，且每行贴的是自己那张图。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "工具/_fb0_table.png"))
